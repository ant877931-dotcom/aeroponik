"""
validation.py
─────────────
Input sanitisation and anti-mimicry-attack guards for uploaded image files.

Three independent defence layers:
  1. Extension whitelist  – rejects non-image filenames before reading any bytes.
  2. Magic-byte check     – inspects the first 16 raw bytes to verify the TRUE
                           file format, regardless of declared Content-Type or
                           extension (defeats file-rename mimicry).
  3. Pillow re-encode     – opens the image through Pillow and re-saves it to a
                           clean BytesIO buffer (PNG), stripping EXIF metadata,
                           polyglot payloads, embedded scripts, and any other
                           non-pixel data (defeats ZIP-inside-JPEG, etc.).
"""

from __future__ import annotations

import io
import logging
import os
from typing import Tuple

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Tuneable constants
# ──────────────────────────────────────────────────────────────────────────────

#: Hard upper limit on upload size to prevent memory-exhaustion DoS.
MAX_FILE_BYTES: int = 20 * 1024 * 1024  # 20 MB

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
)

# Each entry: (bytes_prefix, human-readable format name)
# Order matters – longer/more specific signatures should come first.
MAGIC_SIGNATURES: list[Tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"BM", "BMP"),
    (b"RIFF", "WEBP/RIFF"),       # WEBP uses a RIFF container
    (b"II*\x00", "TIFF (LE)"),
    (b"MM\x00*", "TIFF (BE)"),
]


# ──────────────────────────────────────────────────────────────────────────────
# Public interface
# ──────────────────────────────────────────────────────────────────────────────

async def validate_and_sanitize(upload: UploadFile) -> io.BytesIO:
    """
    Validate and sanitise an uploaded file.

    Reads the raw bytes once, runs all checks, then returns a *clean*
    PNG-encoded BytesIO buffer stripped of any non-pixel content.

    Raises ``HTTPException`` on any violation; never leaks internal details.
    """
    _check_extension(upload.filename or "")

    raw: bytes = await upload.read()

    _check_size(raw)
    _check_magic_bytes(raw)
    clean_buffer = _reencode_image(raw)

    return clean_buffer


# ──────────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────────

def _check_extension(filename: str) -> None:
    """Layer 1 – extension whitelist."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning("Blocked upload: disallowed extension %r", ext)
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )


def _check_size(data: bytes) -> None:
    """Layer 1b – size cap."""
    size_mb = len(data) / (1024 * 1024)
    if len(data) > MAX_FILE_BYTES:
        logger.warning("Blocked upload: file too large (%.2f MB)", size_mb)
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Maximum allowed is 20 MB.",
        )


def _check_magic_bytes(data: bytes) -> None:
    """
    Layer 2 – magic-byte fingerprinting.

    Reads only the first 16 bytes and compares against known image signatures.
    A file that passes the extension check but fails here is almost certainly a
    mimicry attack (e.g., a shell script renamed to photo.jpg).
    """
    header = data[:16]
    for signature, fmt_name in MAGIC_SIGNATURES:
        if header.startswith(signature):
            logger.debug("Magic-byte match: %s", fmt_name)
            return

    logger.warning("Blocked upload: magic bytes do not match any known image format")
    raise HTTPException(
        status_code=422,
        detail=(
            "File content does not correspond to a supported image format. "
            "Upload rejected."
        ),
    )


def _reencode_image(data: bytes) -> io.BytesIO:
    """
    Layer 3 – Pillow re-encode.

    Opens the image through Pillow (which itself validates structure) and
    writes pixel data only to a fresh PNG buffer, discarding all metadata,
    embedded streams, and appended data — defeating polyglot payloads.

    Returns a BytesIO positioned at offset 0.
    Raises HTTPException for corrupt or unrecognisable images.
    """
    try:
        # First pass: verify() checks structure without decoding pixels.
        Image.open(io.BytesIO(data)).verify()

        # Second pass: decode pixels (verify() exhausts the internal pointer).
        img = Image.open(io.BytesIO(data)).convert("RGB")

        out = io.BytesIO()
        img.save(out, format="PNG")
        out.seek(0)
        return out

    except UnidentifiedImageError:
        logger.warning("Blocked upload: Pillow could not identify image format")
        raise HTTPException(
            status_code=422,
            detail="Uploaded file is not a valid or recognisable image.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Image re-encode error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=422,
            detail="Image could not be processed — it may be corrupted or malformed.",
        )
