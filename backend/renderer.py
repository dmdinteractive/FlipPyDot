"""
renderer.py — Content spec -> frames.

Everything that can appear on the display is described by one JSON shape, a
"spec". The renderer is the only thing that knows how to turn a spec into
frames, so live preview in the browser and real playback on the panel go
through identical code and cannot drift apart.

    {"kind": "text",  "text": "OPEN {time}", "font": "px5x7", "size": 14,
     "align": "center", "valign": "middle", "motion": "scroll_left",
     "speed": 30, "gap": 84, "invert": false, "blink": 0}

    {"kind": "animation", "animation": "bounce_balls", "params": {...}}
    {"kind": "image", "frames": [{"bitmap": [[...]], "duration": 80}]}
    {"kind": "clear"} | {"kind": "fill"}

frames(spec, w, h) yields (numpy_frame, delay_seconds). A delay of None means
"hold this frame until something else happens" — the player decides how long.

Speed is authored in PIXELS PER SECOND, not frame delay. "30" means the same
visual pace whether the text is 20px or 900px wide, which is the thing that
actually made the old scroll impossible to tune.
"""

import numpy as np

import fonts as font_mod
from variables import substitute
from animations import get_animation

# Flipdot panels physically cannot flip faster than this; asking for more just
# drops frames on the serial line.
MAX_FPS = 30
MIN_DELAY = 1.0 / MAX_FPS


# ── helpers ───────────────────────────────────────────────────────
def blank(w, h):
    return np.zeros((h, w), dtype=np.uint8)


def compose(canvas, bmp, align="center", valign="middle", dx=0, dy=0):
    """Blit `bmp` onto `canvas` at the requested alignment, clipping overflow."""
    ch, cw = canvas.shape
    bh, bw = bmp.shape
    if bh == 0 or bw == 0:
        return canvas

    if   align == "left":   x = 0
    elif align == "right":  x = cw - bw
    else:                   x = (cw - bw) // 2

    if   valign == "top":    y = 0
    elif valign == "bottom": y = ch - bh
    else:                    y = (ch - bh) // 2

    x += int(dx)
    y += int(dy)

    # Intersect source and destination rectangles.
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x),  max(0, y)
    cpw = min(bw - sx0, cw - dx0)
    cph = min(bh - sy0, ch - dy0)
    if cpw <= 0 or cph <= 0:
        return canvas

    canvas[dy0:dy0 + cph, dx0:dx0 + cpw] = bmp[sy0:sy0 + cph, sx0:sx0 + cpw]
    return canvas


def _step_and_delay(speed):
    """px/sec -> (pixels to advance per frame, seconds to sleep).

    Below MAX_FPS we advance 1px and vary the delay. Above it we hold the
    delay at the panel's limit and advance several pixels instead, so high
    speeds stay smooth-ish rather than silently capping out.
    """
    speed = max(1.0, float(speed))
    if speed <= MAX_FPS:
        return 1, 1.0 / speed
    step = max(1, int(round(speed / MAX_FPS)))
    return step, step / speed


def render_text_bitmap(spec):
    """The text of a spec as a tight bitmap, with {variables} substituted."""
    text = substitute(str(spec.get("text", "")))
    face = font_mod.get(spec.get("font", font_mod.DEFAULT_KEY))
    bmp  = face.render(
        text,
        int(spec.get("size", 14)),
        tracking=int(spec.get("tracking", 1)),
        leading=int(spec.get("leading", 1)),
    )
    if spec.get("bold"):
        bmp = np.clip(bmp + np.roll(bmp, 1, axis=1), 0, 1).astype(np.uint8)
    return bmp


# ── text ──────────────────────────────────────────────────────────
def _text_frames(spec, w, h):
    bmp    = render_text_bitmap(spec)
    motion = spec.get("motion", "static")
    align  = spec.get("align", "center")
    valign = spec.get("valign", "middle")
    dx     = int(spec.get("dx", 0))
    dy     = int(spec.get("dy", 0))
    blink  = float(spec.get("blink", 0) or 0)

    if bmp.shape[1] == 0:
        yield blank(w, h), None
        return

    if motion == "static":
        frame = compose(blank(w, h), bmp, align, valign, dx, dy)
        if blink > 0:
            half = max(MIN_DELAY, 1.0 / (2 * blink))
            yield frame, half
            yield blank(w, h), half
        else:
            yield frame, None
        return

    horizontal = motion in ("scroll_left", "scroll_right")
    gap        = int(spec.get("gap", w if horizontal else h))
    step, delay = _step_and_delay(spec.get("speed", 30))

    if horizontal:
        bh, bw = bmp.shape
        # Strip = text + gap. Sampling it modulo its own width makes the loop
        # seamless: the tail of one pass and the head of the next are the same
        # continuous surface, so there is no jump when it wraps.
        strip_w = bw + max(1, gap)
        strip   = np.zeros((bh, strip_w), dtype=np.uint8)
        strip[:, :bw] = bmp

        # Vertical placement is fixed; only x moves.
        canvas_probe = compose(blank(w, h), np.zeros((bh, 1), dtype=np.uint8),
                               align, valign, 0, dy)
        ys = np.nonzero(canvas_probe.any(axis=1))[0]
        y0 = ys[0] if len(ys) else max(0, (h - bh) // 2)
        y0 = max(0, min(h - 1, y0))

        idx = np.arange(w)
        pos = 0
        while True:
            if motion == "scroll_left":
                cols = (pos + idx) % strip_w
            else:
                cols = (-pos + idx) % strip_w
            frame = blank(w, h)
            slice_ = strip[:, cols]
            vis_h  = min(bh, h - y0)
            frame[y0:y0 + vis_h, :] = slice_[:vis_h, :]
            yield frame, delay
            pos = (pos + step) % strip_w
            if pos == 0:
                return                     # one full pass; player loops us

    else:
        bh, bw = bmp.shape
        strip_h = bh + max(1, gap)
        strip   = np.zeros((strip_h, bw), dtype=np.uint8)
        strip[:bh, :] = bmp

        if   align == "left":  x0 = 0
        elif align == "right": x0 = w - bw
        else:                  x0 = (w - bw) // 2
        x0 += dx

        idx = np.arange(h)
        pos = 0
        while True:
            if motion == "scroll_up":
                rows = (pos + idx) % strip_h
            else:
                rows = (-pos + idx) % strip_h
            frame  = blank(w, h)
            slice_ = strip[rows, :]
            sx0, dx0 = max(0, -x0), max(0, x0)
            cpw = min(bw - sx0, w - dx0)
            if cpw > 0:
                frame[:, dx0:dx0 + cpw] = slice_[:, sx0:sx0 + cpw]
            yield frame, delay
            pos = (pos + step) % strip_h
            if pos == 0:
                return


# ── animation ─────────────────────────────────────────────────────
def _anim_frames(spec, w, h):
    fn = get_animation(spec.get("animation", "flash"))
    if not fn:
        yield blank(w, h), None
        return

    params = dict(spec.get("params", {}) or {})
    params.pop("w", None)
    params.pop("h", None)
    for frame, delay in fn(w, h, **params):
        yield frame, max(MIN_DELAY, float(delay))


# ── image ─────────────────────────────────────────────────────────
def _image_frames(spec, w, h):
    frames = spec.get("frames") or []
    if not frames:
        yield blank(w, h), None
        return

    if len(frames) == 1:
        bmp = np.array(frames[0].get("bitmap", []), dtype=np.uint8)
        yield _fit(bmp, w, h), None
        return

    for f in frames:
        bmp = np.array(f.get("bitmap", []), dtype=np.uint8)
        dur = float(f.get("duration", 80)) / 1000.0
        yield _fit(bmp, w, h), max(MIN_DELAY, dur)


def _fit(bmp, w, h):
    if bmp.ndim != 2 or bmp.size == 0:
        return blank(w, h)
    if bmp.shape == (h, w):
        return bmp
    out = blank(w, h)
    ch = min(h, bmp.shape[0])
    cw = min(w, bmp.shape[1])
    out[:ch, :cw] = bmp[:ch, :cw]
    return out


# ── entry point ───────────────────────────────────────────────────
def frames(spec, w, h):
    """Yield (frame, delay) for any spec. delay=None means hold indefinitely."""
    spec = spec or {}
    kind = spec.get("kind", "text")

    if kind == "clear":
        yield blank(w, h), None
    elif kind == "fill":
        yield np.ones((h, w), dtype=np.uint8), None
    elif kind == "animation":
        yield from _anim_frames(spec, w, h)
    elif kind == "image":
        yield from _image_frames(spec, w, h)
    else:
        yield from _text_frames(spec, w, h)


def preview(spec, w, h, max_frames=240):
    """Render a spec to a bounded list of frames for the browser preview.

    Never touches the display. `hold` marks a frame the player would sit on
    rather than advance past, so the UI knows not to flicker through it.
    """
    out = []
    for frame, delay in frames(spec, w, h):
        out.append({
            "bitmap": frame.astype(int).tolist(),
            "delay":  None if delay is None else round(float(delay), 4),
            "hold":   delay is None,
        })
        if len(out) >= max_frames:
            break
    return out


def measure(spec, w, h):
    """How big the content is, and whether it will fit.

    Static text wider than the panel is silently cropped by compose(), which
    is a miserable thing to discover on the wall. The editor uses this to say
    so up front and suggest the fix.
    """
    spec = spec or {}
    if spec.get("kind", "text") != "text":
        return {"fits": True}

    bmp = render_text_bitmap(spec)
    bw, bh = bmp.shape[1], bmp.shape[0]
    scrolls_x = spec.get("motion") in ("scroll_left", "scroll_right")
    scrolls_y = spec.get("motion") in ("scroll_up", "scroll_down")

    over_x = bw > w and not scrolls_x
    over_y = bh > h and not scrolls_y

    hint = None
    if over_x:
        hint = (f"Text is {bw}px wide — {bw - w}px wider than the panel, so the "
                f"ends will be cut off. Use a smaller size, a narrower font, "
                f"or set motion to Scroll ←.")
    elif over_y:
        hint = (f"Text is {bh}px tall — taller than the {h}px panel. "
                f"Reduce the size or line spacing.")

    return {"fits": not (over_x or over_y), "text_w": bw, "text_h": bh,
            "panel_w": w, "panel_h": h, "hint": hint}


def is_static(spec):
    """True if the spec resolves to a single held frame."""
    spec = spec or {}
    kind = spec.get("kind", "text")
    if kind in ("clear", "fill"):
        return True
    if kind == "image":
        return len(spec.get("frames") or []) <= 1
    if kind == "text":
        return (spec.get("motion", "static") == "static"
                and not float(spec.get("blink", 0) or 0))
    return False
