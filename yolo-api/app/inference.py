"""
inference.py
────────────
Thread-safe, async-safe YOLOv8 inference engine.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The ML Async Blind Spot Problem
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FastAPI runs on a single-threaded asyncio event loop. PyTorch /
ultralytics model inference is CPU-bound (or GPU-bound) and is
*NOT* coroutine-friendly:

  • Calling model.predict() directly inside `async def` blocks
    the entire event loop → all concurrent requests stall until
    inference finishes (the "async blind spot").

  • Sharing a mutable model object across concurrent coroutines
    can corrupt internal state (race condition).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Solution
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Model singleton  – loaded ONCE at startup; all requests share
                      the same in-memory model.

2. threading.Lock   – a per-process mutex ensures only ONE inference
                      runs at a time on the model, preventing
                      concurrent writes to shared GPU/CPU state.

3. ThreadPoolExecutor – asyncio.get_event_loop().run_in_executor()
                      offloads the blocking call to a worker thread,
                      freeing the event loop to accept new HTTP
                      connections while inference is running.

4. Bounded pool     – MAX_WORKERS=1 matches single-GPU / CPU-only
                      deployments. Increase for multi-GPU setups.

5. Warm-up pass     – a dummy forward pass at startup pre-JIT-compiles
                      CUDA kernels so the first real request isn't slow.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from ultralytics import YOLO

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration (override via environment variables where possible)
# ──────────────────────────────────────────────────────────────────────────────

MODEL_PATH: Path = Path(__file__).parent.parent / "models" / "best.pt"

#: Workers = 1 → safe for single-GPU or CPU-only hosts.
#: Raise to N only on multi-GPU servers with proper model sharding.
MAX_WORKERS: int = 1

#: Detections below this confidence are discarded.
CONFIDENCE_THRESHOLD: float = 0.35

# ──────────────────────────────────────────────────────────────────────────────
# Label normalisation map
# Maps raw YOLO class names → canonical display labels.
#
# Why this is needed:
#   The model may have been trained with different class name schemes:
#     - 1-class model  → only "pakcoy" (cannot distinguish healthy/diseased)
#     - 2-class model  → "pakcoy_sehat" / "pakcoy_tidak_sehat"  (correct)
#   This map normalises both variants to the canonical 2-class scheme.
#   If the model outputs a 1-class "pakcoy" label, it is forwarded as-is
#   so the UI can still display it; the disease card will show "Tidak Diketahui".
# ──────────────────────────────────────────────────────────────────────────────
LABEL_MAP: dict[str, str] = {
    # ── 2-class expected labels (pass-through) ────────────────────────────────
    "pakcoy_sehat":         "pakcoy_sehat",
    "pakcoy_tidak_sehat":   "pakcoy_tidak_sehat",
    # ── Common 1-class / typo variants ───────────────────────────────────────
    "pakcoy":               "pakcoy",          # 1-class model – unknown condition
    "pakcoy sehat":         "pakcoy_sehat",
    "pakcoy tidak sehat":   "pakcoy_tidak_sehat",
    "healthy":              "pakcoy_sehat",
    "unhealthy":            "pakcoy_tidak_sehat",
    "sakit":                "pakcoy_tidak_sehat",
    "sehat":                "pakcoy_sehat",
}

# ──────────────────────────────────────────────────────────────────────────────
# Module-level singletons (process-local)
# ──────────────────────────────────────────────────────────────────────────────

_model: Optional[YOLO] = None
_model_lock: threading.Lock = threading.Lock()
_executor: Optional[ThreadPoolExecutor] = None

# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle helpers (called by FastAPI lifespan handlers)
# ──────────────────────────────────────────────────────────────────────────────

def load_model() -> None:
    """
    Load YOLOv8 model into memory exactly once at application startup.
    Subsequent calls are no-ops (double-checked locking pattern).
    """
    global _model, _executor

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model weights not found at: {MODEL_PATH}\n"
            "Place best.pt inside the models/ directory before starting the server."
        )

    logger.info("Loading YOLOv8 model from %s …", MODEL_PATH)

    with _model_lock:
        if _model is None:
            _model = YOLO(str(MODEL_PATH))

            # Warm-up: pre-allocate CUDA kernels / JIT-compile the graph.
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            _model.predict(dummy, conf=CONFIDENCE_THRESHOLD, verbose=False)
            logger.info("Model loaded and warm-up complete.")

    _executor = ThreadPoolExecutor(
        max_workers=MAX_WORKERS,
        thread_name_prefix="yolo-worker",
    )
    logger.info("Inference ThreadPoolExecutor started (max_workers=%d).", MAX_WORKERS)


def unload_model() -> None:
    """Gracefully drain the thread pool on application shutdown."""
    global _executor
    if _executor is not None:
        logger.info("Shutting down ThreadPoolExecutor …")
        _executor.shutdown(wait=True)
        _executor = None
        logger.info("ThreadPoolExecutor shut down cleanly.")


# ──────────────────────────────────────────────────────────────────────────────
# Public async API
# ──────────────────────────────────────────────────────────────────────────────

async def run_inference(image_buffer: io.BytesIO) -> list[dict]:
    """
    Schedule YOLOv8 inference asynchronously.

    Offloads the blocking call to the bounded ThreadPoolExecutor so the
    asyncio event loop stays free to serve new HTTP requests concurrently.

    Returns a list of detection dicts::

        [{"label": "Sehat", "confidence": 0.912}, …]
    """
    if _model is None or _executor is None:
        raise RuntimeError(
            "Model is not loaded. Ensure load_model() ran during startup."
        )

    loop = asyncio.get_event_loop()
    detections: list[dict] = await loop.run_in_executor(
        _executor,
        _blocking_inference,
        image_buffer,
    )
    return detections


# ──────────────────────────────────────────────────────────────────────────────
# Blocking worker (runs inside the ThreadPoolExecutor thread, NOT the event loop)
# ──────────────────────────────────────────────────────────────────────────────

def _blocking_inference(image_buffer: io.BytesIO) -> list[dict]:
    """
    Synchronous YOLO forward pass — protected by threading.Lock.

    The lock serialises GPU/CPU access, preventing race conditions when
    multiple HTTP requests land close together and both reach this function
    before the first one finishes.
    """
    with _model_lock:
        img_np = np.array(Image.open(image_buffer).convert("RGB"))

        results = _model.predict(  # type: ignore[union-attr]
            source=img_np,
            conf=CONFIDENCE_THRESHOLD,
            verbose=False,
            stream=False,
        )

    detections: list[dict] = []
    seen: set[str] = set()

    for result in results:
        names: dict[int, str] = result.names
        boxes = result.boxes
        if boxes is None:
            continue

        for box in boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            raw_label = names.get(cls_id, f"class_{cls_id}")
            # Normalise to canonical label; unknown labels are kept as-is.
            label = LABEL_MAP.get(raw_label.lower().strip(), raw_label)
            detections.append({"label": label, "confidence": round(conf, 4)})
            seen.add(label)

    logger.info(
        "Inference done — %d box(es) found, classes: %s",
        len(detections),
        sorted(seen),
    )
    return detections
