"""
main.py
───────
FastAPI application — entry point for the Pakcoy Plant Health Detection API.

Endpoints
─────────
  GET  /          Root health check
  GET  /health    Detailed health check (model load status)
  POST /deteksi   YOLOv8 disease detection from an uploaded plant image
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.inference import _model  # noqa: F401 — imported for /health check
from app.inference import load_model, run_inference, unload_model
from app.validation import validate_and_sanitize

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# CORS origins
# Read from the ALLOWED_ORIGINS env var (comma-separated list).
# Falls back to "*" for local dev. ALWAYS set the env var in production.
#
# Example (Render → Environment):
#   ALLOWED_ORIGINS=https://your-app.vercel.app,https://www.your-app.vercel.app
# ──────────────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS: list[str] = (
    ["*"] if _raw_origins.strip() == "*" else [o.strip() for o in _raw_origins.split(",")]
)


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan (replaces deprecated @app.on_event)
# ──────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup; release thread pool on shutdown."""
    logger.info("=== Startup: loading YOLOv8 model ===")
    try:
        load_model()
        logger.info("=== Model ready. Accepting requests. ===")
    except FileNotFoundError as exc:
        logger.error("STARTUP FAILURE — model not found: %s", exc)
        # Continue anyway so /health can report the degraded state.
    yield
    logger.info("=== Shutdown: releasing resources ===")
    unload_model()


# ──────────────────────────────────────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Pakcoy Plant Health Detection API",
    description=(
        "YOLOv8-powered REST API for detecting plant diseases in Pakcoy. "
        "Designed to integrate with an ESP32 camera + Vercel-hosted web dashboard."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # allow_credentials must be False when allow_origins contains "*"
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
    max_age=600,   # cache pre-flight for 10 minutes
)

logger.info("CORS configured for origins: %s", ALLOWED_ORIGINS)


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"], summary="Root health check")
async def root():
    """Returns 200 OK if the API server is reachable."""
    return {
        "status": "ok",
        "service": "Pakcoy Plant Health Detection API",
        "version": "1.0.0",
    }


@app.get("/health", tags=["Health"], summary="Detailed health check")
async def health_check():
    """Reports whether the YOLOv8 model is loaded and ready."""
    import app.inference as _inf  # local import avoids circular reference at module level

    model_ready = _inf._model is not None
    return JSONResponse(
        status_code=200 if model_ready else 503,
        content={
            "status": "healthy" if model_ready else "degraded",
            "model_loaded": model_ready,
        },
    )


@app.post("/deteksi", tags=["Inference"], summary="Detect plant diseases")
async def deteksi(
    file: UploadFile = File(
        ...,
        description="Plant photo — JPEG, PNG, BMP, WEBP, or TIFF (max 20 MB)",
    ),
):
    """
    Run YOLOv8 inference on an uploaded plant image.

    **Returns**:
    ```json
    {
      "status": "success",
      "detected_classes": ["Sehat"],
      "detections": [
        {"label": "Sehat", "confidence": 0.912}
      ],
      "count": 1,
      "inference_time_ms": 134.5
    }
    ```
    """
    t_start = time.perf_counter()

    # ── Step 1: validate + sanitise (mimicry-attack guards) ────────────────────
    try:
        clean_image = await validate_and_sanitize(file)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unexpected validation error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Image validation failed unexpectedly.")

    # ── Step 2: async-safe, race-condition-proof inference ─────────────────────
    try:
        detections = await run_inference(clean_image)
    except RuntimeError as exc:
        logger.error("Model not ready: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Model is not ready yet. Please retry in a moment.",
        )
    except Exception as exc:
        logger.error("Inference error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Inference failed unexpectedly.")

    # ── Step 3: build clean response ───────────────────────────────────────────
    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
    detected_classes = sorted({d["label"] for d in detections})

    return {
        "status": "success",
        "detected_classes": detected_classes,
        "detections": detections,
        "count": len(detections),
        "inference_time_ms": elapsed_ms,
    }
