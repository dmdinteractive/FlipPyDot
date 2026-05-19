"""
image_processor.py
------------------
Convert images and animated GIFs to 1-bit flipdot bitmaps.

Supports:
  - PNG, JPG, BMP, WEBP → single frame
  - Animated GIF → list of frames with timing
  - Adjustable threshold, brightness, contrast
  - Floyd-Steinberg and ordered (Bayer) dithering
  - Auto-resize to fit display with aspect ratio options
"""

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import logging

log = logging.getLogger(__name__)


def process_image(
    data: bytes,
    display_w: int = 84,
    display_h: int = 42,
    threshold: int = 128,
    brightness: float = 1.0,
    contrast: float = 1.0,
    dither: str = "none",       # 'none', 'floyd', 'bayer'
    scale: str = "fit",         # 'fit', 'fill', 'stretch'
    invert: bool = False,
) -> list:
    """
    Convert image bytes to a list of (bitmap, duration_ms) tuples.
    For static images, returns one frame with duration=0.
    For animated GIFs, returns one tuple per frame.

    bitmap: np.uint8 array shape (display_h, display_w), values 0 or 1
    """
    try:
        img = Image.open(io.BytesIO(data))
    except Exception as e:
        log.error(f"Image open failed: {e}")
        raise ValueError(f"Cannot open image: {e}")

    frames = []

    # Handle animated GIF
    is_animated = hasattr(img, "n_frames") and img.n_frames > 1

    if is_animated:
        for i in range(img.n_frames):
            img.seek(i)
            duration = img.info.get("duration", 100)  # ms per frame
            frame_img = img.copy().convert("RGBA")
            bmp = _convert_frame(frame_img, display_w, display_h,
                                  threshold, brightness, contrast,
                                  dither, scale, invert)
            frames.append((bmp, duration))
    else:
        frame_img = img.convert("RGBA")
        bmp = _convert_frame(frame_img, display_w, display_h,
                              threshold, brightness, contrast,
                              dither, scale, invert)
        frames.append((bmp, 0))

    log.info(f"Image processed: {len(frames)} frame(s), {display_w}x{display_h}")
    return frames


def _convert_frame(
    img: Image.Image,
    w: int, h: int,
    threshold: int,
    brightness: float,
    contrast: float,
    dither: str,
    scale: str,
    invert: bool,
) -> np.ndarray:
    """Convert one PIL frame to a 1-bit numpy array."""

    # White background composite (handles transparency)
    bg = Image.new("RGB", img.size, (255, 255, 255))
    if img.mode == "RGBA":
        bg.paste(img, mask=img.split()[3])
    else:
        bg.paste(img)
    img = bg

    # Resize
    img = _resize(img, w, h, scale)

    # Convert to grayscale
    img = img.convert("L")

    # Brightness / contrast adjustments
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    # Dithering
    if dither == "floyd":
        # PIL's built-in Floyd-Steinberg
        img = img.convert("1", dither=Image.FLOYDSTEINBERG)
        arr = (np.array(img, dtype=np.uint8) > 0).astype(np.uint8)
    elif dither == "bayer":
        arr = _bayer_dither(np.array(img, dtype=np.float32), threshold)
    else:
        # Simple threshold
        arr = (np.array(img, dtype=np.uint8) < threshold).astype(np.uint8)

    if invert:
        arr = 1 - arr

    # Ensure correct size
    result = np.zeros((h, w), dtype=np.uint8)
    fh, fw = arr.shape
    result[:min(fh,h), :min(fw,w)] = arr[:min(fh,h), :min(fw,w)]
    return result


def _resize(img: Image.Image, w: int, h: int, mode: str) -> Image.Image:
    if mode == "stretch":
        return img.resize((w, h), Image.LANCZOS)
    elif mode == "fill":
        # Crop to fill
        ratio = max(w / img.width, h / img.height)
        nw    = int(img.width  * ratio)
        nh    = int(img.height * ratio)
        img   = img.resize((nw, nh), Image.LANCZOS)
        left  = (nw - w) // 2
        top   = (nh - h) // 2
        return img.crop((left, top, left + w, top + h))
    else:
        # Fit — letterbox
        ratio = min(w / img.width, h / img.height)
        nw    = int(img.width  * ratio)
        nh    = int(img.height * ratio)
        img   = img.resize((nw, nh), Image.LANCZOS)
        result = Image.new("L", (w, h), 255)
        result.paste(img.convert("L"), ((w-nw)//2, (h-nh)//2))
        return result


def _bayer_dither(gray: np.ndarray, threshold: int = 128) -> np.ndarray:
    """4x4 Bayer ordered dithering."""
    bayer = np.array([
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5],
    ], dtype=np.float32) / 16.0 * 255

    h, w = gray.shape
    bayer_tiled = np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w]
    dithered = gray + (bayer_tiled - 128) * 0.5
    return (dithered < threshold).astype(np.uint8)


def bitmap_to_json(bitmap: np.ndarray) -> list:
    """Convert numpy bitmap to JSON-serializable list."""
    return bitmap.tolist()


def frames_to_json(frames: list) -> list:
    """Convert list of (bitmap, duration) to JSON-serializable list."""
    return [{"bitmap": f[0].tolist(), "duration": f[1]} for f in frames]
