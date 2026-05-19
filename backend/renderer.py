"""
renderer.py
-----------
Content rendering — text, images, scrolling — decoupled from hardware.
All functions return numpy uint8 arrays ready to send via display.send().
"""

import os
import numpy as np
import logging

log = logging.getLogger(__name__)

FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")


def get_font(name="default", size=14):
    from PIL import ImageFont
    if name and name != "default":
        p = os.path.join(FONTS_DIR, name)
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, int(size))
            except Exception:
                pass
    return ImageFont.load_default()


def render_text(text, fname="default", fsize=14, x=0, y=0, w=84, h=42):
    """Render text string to a 1-bit numpy array."""
    from PIL import Image, ImageDraw
    img  = Image.new("L", (w, h), 255)
    ImageDraw.Draw(img).text((x, y), str(text), fill=0, font=get_font(fname, fsize))
    return (np.array(img) < 128).astype(np.uint8)


def render_scroll_source(text, fname="default", fsize=14, w=84, h=42):
    """
    Render a wide bitmap for scrolling text.
    Returns array wider than w — the scroll loop moves it leftward.
    """
    from PIL import Image, ImageDraw
    font = get_font(fname, fsize)
    img  = Image.new("L", (8192, h), 255)
    bbox = ImageDraw.Draw(img).textbbox((0, 0), str(text), font=font)
    tw   = bbox[2] - bbox[0] + w * 2
    return render_text(text, fname, fsize, x=w, w=tw, h=h)


def scroll_frames(text, fname="default", fsize=14, w=84, h=42, speed=1):
    """
    Generator yielding (frame, delay) for a complete scroll cycle.
    speed: pixels per frame (higher = faster scroll)
    delay: seconds between frames
    """
    source = render_scroll_source(text, fname, fsize, w, h)
    sw     = source.shape[1]
    delay  = 0.04
    x      = 0
    while x < sw - w:
        frame = np.zeros((h, w), dtype=np.uint8)
        chunk = source[:, x:x + w]
        cw    = chunk.shape[1]
        frame[:, :cw] = chunk
        yield frame, delay
        x += int(speed)
