"""
fonts.py — Font registry.

Two kinds of face:
  builtin — hand-drawn bitmap fonts (bitmapfonts.py). Integer-scaled, no
            antialiasing, always available. Best choice for flipdot.
  ttf     — any .ttf/.otf dropped into fonts/ (or uploaded via the UI).
            Rendered through PIL and hard-thresholded to 1-bit.

Both expose the same interface so renderer.py doesn't care which it got:
    face.render(text, px)  -> tight (h, w) uint8 bitmap
    face.height(px)        -> actual rendered height for a requested px size
"""

import os
import logging
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bitmapfonts import BITMAP_FONTS

log = logging.getLogger(__name__)

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts")
TTF_EXTS  = (".ttf", ".otf")

# PIL's built-in fallback face, exposed as a real choice so there is always a
# usable non-bitmap option even on a machine with no fonts installed.
DEFAULT_KEY = "px5x7"


class BitmapFace:
    kind = "bitmap"

    def __init__(self, font):
        self._f       = font
        self.key      = font.key
        self.name     = font.name
        self.native_h = font.gh

    def sizes(self):
        """The px heights this face renders at exactly (integer multiples)."""
        return [self.native_h * s for s in range(1, 7) if self.native_h * s <= 64]

    def height(self, px):
        return self._f.height(self._f.scale_for_height(px))

    def render(self, text, px, tracking=1, leading=1):
        scale = self._f.scale_for_height(px)
        return self._f.render(text, scale=scale, tracking=tracking, leading=leading)


class TTFFace:
    kind = "ttf"

    def __init__(self, key, name, path):
        self.key      = key
        self.name     = name
        self.path     = path
        self.native_h = None
        self._cache   = {}

    def sizes(self):
        return []          # freely scalable

    def _font(self, px):
        px = max(4, int(px))
        if px not in self._cache:
            try:
                self._cache[px] = ImageFont.truetype(self.path, px)
            except Exception:
                self._cache[px] = ImageFont.load_default(size=px)
        return self._cache[px]

    def height(self, px):
        return int(px)

    def render(self, text, px, tracking=0, leading=1):
        font  = self._font(px)
        lines = str(text).split("\n")

        # Measure first so the bitmap is tight — the renderer does the placing.
        widths, heights = [], []
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        for ln in lines:
            bbox = probe.textbbox((0, 0), ln or " ", font=font)
            widths.append(bbox[2] - bbox[0] + max(0, tracking) * max(0, len(ln) - 1))
            heights.append(bbox[3] - bbox[1])

        w = max(widths + [1])
        line_h = max(heights + [int(px)]) + leading
        h = len(lines) * line_h - leading

        # Pad generously, draw, then crop back to the ink.
        img = Image.new("L", (w + int(px) * 2, h + int(px) * 2), 255)
        d   = ImageDraw.Draw(img)
        for li, ln in enumerate(lines):
            if tracking:
                # Per-glyph advance so letter-spacing works on TTF too.
                x = int(px)
                for ch in ln:
                    d.text((x, int(px) + li * line_h), ch, fill=0, font=font)
                    x += int(d.textlength(ch, font=font)) + tracking
            else:
                d.text((int(px), int(px) + li * line_h), ln, fill=0, font=font)

        bits = (np.array(img) < 128).astype(np.uint8)
        ys, xs = np.nonzero(bits)
        if len(ys) == 0:
            return np.zeros((self.height(px), 0), dtype=np.uint8)
        return bits[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


class PILDefaultFace(TTFFace):
    kind = "builtin-vector"

    def __init__(self):
        self.key      = "vector"
        self.name     = "Vector (scalable)"
        self.path     = None
        self.native_h = None
        self._cache   = {}

    def _font(self, px):
        px = max(4, int(px))
        if px not in self._cache:
            self._cache[px] = ImageFont.load_default(size=px)
        return self._cache[px]


_faces = {}


def _scan():
    global _faces
    faces = {}
    for f in BITMAP_FONTS.values():
        faces[f.key] = BitmapFace(f)
    faces["vector"] = PILDefaultFace()

    if os.path.isdir(FONTS_DIR):
        for fn in sorted(os.listdir(FONTS_DIR)):
            if fn.lower().endswith(TTF_EXTS):
                key = os.path.splitext(fn)[0]
                faces[key] = TTFFace(key, key.replace("_", " ").replace("-", " ").title(),
                                     os.path.join(FONTS_DIR, fn))
    _faces = faces
    return faces


def refresh():
    return _scan()


def get(key):
    if not _faces:
        _scan()
    return _faces.get(key) or _faces.get(DEFAULT_KEY) or _faces["vector"]


def list_fonts():
    if not _faces:
        _scan()
    return [
        {"key": f.key, "name": f.name, "kind": f.kind, "sizes": f.sizes()}
        for f in _faces.values()
    ]


def save_upload(filename, data):
    """Persist an uploaded font file into fonts/ and re-scan."""
    if not filename.lower().endswith(TTF_EXTS):
        raise ValueError("Font must be .ttf or .otf")
    safe = os.path.basename(filename).replace("..", "")
    os.makedirs(FONTS_DIR, exist_ok=True)
    path = os.path.join(FONTS_DIR, safe)
    with open(path, "wb") as fh:
        fh.write(data)
    try:
        ImageFont.truetype(path, 16)          # validate before we keep it
    except Exception as e:
        os.remove(path)
        raise ValueError(f"Not a usable font file: {e}")
    _scan()
    log.info(f"Font uploaded: {safe}")
    return os.path.splitext(safe)[0]


def delete(key):
    face = _faces.get(key)
    if not isinstance(face, TTFFace) or not getattr(face, "path", None):
        return False                          # builtins are not deletable
    try:
        os.remove(face.path)
    except OSError:
        return False
    _scan()
    return True


_scan()
