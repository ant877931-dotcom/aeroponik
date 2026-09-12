"""
camera_node.py — Edge Camera Streaming Client
=============================================
Device  : Raspberry Pi 5
Camera  : Logitech C920 Pro HD Webcam (USB)
Backend : FastAPI + YOLO11 on laptop

Captures frames from the USB webcam, resizes them to the YOLO model's
expected input size, and POSTs them to the backend at a controlled rate.

Usage:
    python3 camera_node.py

Stop with Ctrl+C — the camera will be released cleanly.
"""

import cv2
import time
import requests
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# USB camera device index (0 = first USB/default camera)
CAMERA_INDEX = 0

# Native capture resolution for the Logitech C920 Pro HD
CAPTURE_WIDTH  = 1280
CAPTURE_HEIGHT = 720

# YOLO model expected input — resize before sending to reduce network payload
INFER_WIDTH  = 800
INFER_HEIGHT = 800

# Backend endpoint — update if the laptop's IP changes
BACKEND_URL = "http://10.253.52.254:8000/deteksi"

# multipart/form-data field name expected by the FastAPI endpoint
FORM_FIELD_NAME = "file"

# Maximum frames to send per second (throttle to protect the backend)
TARGET_FPS  = 2
FRAME_DELAY = 1.0 / TARGET_FPS  # 0.5 s between frames

# HTTP request timeout in seconds — (connect_timeout, read_timeout)
REQUEST_TIMEOUT = (5, 10)

# JPEG encoding quality (0–100); 85 balances file size vs. image quality
JPEG_QUALITY = 85


# ---------------------------------------------------------------------------
# Camera initialisation
# ---------------------------------------------------------------------------

def open_camera(index: int) -> cv2.VideoCapture:
    """
    Open the USB camera and configure it for the C920's HD capture resolution.
    Exits the program immediately if the camera cannot be opened.
    """
    cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        print(
            f"[ERROR] Cannot open camera at index {index}. "
            "Verify the webcam is connected and not in use by another process.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Request the native HD resolution from the C920
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)

    # Confirm the resolution the OS/driver actually negotiated
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[INFO] Camera opened — actual capture resolution: {actual_w}x{actual_h}")

    return cap


# ---------------------------------------------------------------------------
# Frame pre-processing
# ---------------------------------------------------------------------------

def preprocess_frame(frame) -> bytes:
    """
    Resize the captured frame to the YOLO model's expected input size and
    encode it as a JPEG byte buffer entirely in memory (no disk I/O).

    Args:
        frame: Raw BGR frame from cv2.VideoCapture.read()

    Returns:
        Raw JPEG bytes ready to be POSTed over the network.

    Raises:
        RuntimeError: If cv2.imencode fails to produce a valid buffer.
    """
    # Resize to YOLO inference dimensions (reduces network payload significantly)
    resized = cv2.resize(
        frame,
        (INFER_WIDTH, INFER_HEIGHT),
        interpolation=cv2.INTER_LINEAR,
    )

    # Encode to JPEG in memory — no temporary files needed
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    success, buffer = cv2.imencode(".jpg", resized, encode_params)

    if not success:
        raise RuntimeError(
            "cv2.imencode failed — could not encode frame as JPEG."
        )

    return buffer.tobytes()


# ---------------------------------------------------------------------------
# HTTP transmission
# ---------------------------------------------------------------------------

def send_frame(jpeg_bytes: bytes) -> None:
    """
    POST a single JPEG frame to the FastAPI backend as multipart/form-data.

    All network errors are caught and logged to the console WITHOUT raising,
    so the capture loop continues running even when the backend is temporarily
    unreachable (e.g. laptop sleeping, network switch, backend restart).
    """
    try:
        # Build multipart payload: (filename, file-like bytes, MIME type)
        files = {
            FORM_FIELD_NAME: ("frame.jpg", jpeg_bytes, "image/jpeg")
        }

        response = requests.post(
            BACKEND_URL,
            files=files,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 200:
            # Optionally log the detection result returned by the backend
            print(f"[OK]   HTTP {response.status_code} | {response.text[:160]}")
        else:
            print(
                f"[WARN] Backend returned HTTP {response.status_code}: "
                f"{response.text[:120]}"
            )

    except requests.exceptions.ConnectTimeout:
        print(
            "[WARN] Connect timed out — backend may be starting up or "
            "the IP is unreachable. Will retry on the next frame."
        )

    except requests.exceptions.ReadTimeout:
        print(
            "[WARN] Read timed out — backend received the frame but did not "
            "respond in time. Consider increasing REQUEST_TIMEOUT."
        )

    except requests.exceptions.ConnectionError:
        print(
            "[WARN] Connection refused or network unreachable — "
            "is the FastAPI backend running on the laptop?"
        )

    except requests.exceptions.RequestException as exc:
        # Broad catch-all for any other requests-related failure
        print(f"[WARN] Unexpected request error: {exc}")


# ---------------------------------------------------------------------------
# Main capture loop
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Main entry point:
      1. Open the USB camera and set capture resolution.
      2. Enter capture loop: read → preprocess → send, throttled to TARGET_FPS.
      3. On Ctrl+C, exit gracefully and release all camera resources.
    """
    print("=" * 60)
    print("  camera_node.py — Aeroponic Edge Camera Client")
    print("=" * 60)
    print(f"[INFO] Backend URL  : {BACKEND_URL}")
    print(f"[INFO] Capture size : {CAPTURE_WIDTH}x{CAPTURE_HEIGHT}")
    print(f"[INFO] Infer size   : {INFER_WIDTH}x{INFER_HEIGHT}")
    print(f"[INFO] Send rate    : {TARGET_FPS} FPS  (delay: {FRAME_DELAY:.2f} s)")
    print("[INFO] Press Ctrl+C to stop.\n")

    cap = open_camera(CAMERA_INDEX)

    frame_count = 0   # Total frames successfully sent this session
    error_count = 0   # Consecutive capture failures

    try:
        while True:
            loop_start = time.monotonic()

            # ------------------------------------------------------------------
            # Step 1 — Capture a raw frame from the webcam
            # ------------------------------------------------------------------
            ret, frame = cap.read()

            if not ret or frame is None:
                error_count += 1
                print(
                    f"[WARN] Failed to read frame (consecutive failures: {error_count}). "
                    "Check the webcam connection."
                )
                # Short pause before retrying to avoid a busy-spin loop
                time.sleep(0.5)
                continue

            # Reset error counter on a successful read
            error_count = 0

            # ------------------------------------------------------------------
            # Step 2 — Pre-process: resize to YOLO input size + JPEG encode
            # ------------------------------------------------------------------
            try:
                jpeg_bytes = preprocess_frame(frame)
            except RuntimeError as exc:
                print(f"[WARN] Pre-processing failed: {exc}")
                time.sleep(FRAME_DELAY)
                continue

            # ------------------------------------------------------------------
            # Step 3 — Send to backend (all errors handled inside send_frame)
            # ------------------------------------------------------------------
            send_frame(jpeg_bytes)
            frame_count += 1

            # ------------------------------------------------------------------
            # Step 4 — Throttle: sleep for the remaining time in this period
            # ------------------------------------------------------------------
            elapsed    = time.monotonic() - loop_start
            sleep_time = FRAME_DELAY - elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        # Ctrl+C — user-initiated shutdown
        print(f"\n[INFO] Shutdown requested via Ctrl+C.")
        print(f"[INFO] Frames sent this session: {frame_count}")

    finally:
        # Always release hardware resources, regardless of how we exited.
        # The 'finally' block runs even after an unhandled exception.
        print("[INFO] Releasing camera …")
        cap.release()
        cv2.destroyAllWindows()
        print("[INFO] Camera released. Exiting.")


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
