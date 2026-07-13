"""
effects.py — Real-time effects, applied as a filter on the way to the panel.

V7 ran effects on their own thread: read display.buffer, apply the effect,
send the result back. That had two problems. It wrote to the serial port at
the same time as the animation thread, and — worse — its own output landed in
display.buffer and became the *input* to the next iteration, so a flicker
would compound into noise and a pulse would invert an already-inverted frame.

Now an effect is a pure function of (clean content frame, tick). The Player
owns the clock and calls apply() on every frame just before it hits the wire,
so effects always layer over the real content and never feed back on
themselves.
"""

import random
import logging
import threading

import numpy as np

log = logging.getLogger(__name__)


class EffectsEngine:
    def __init__(self):
        self.active = {}                 # name -> {"type", "params", "frame"}
        self._lock  = threading.Lock()

    # ── stack management ──────────────────────────────────────────
    def add(self, name, effect_type, **params):
        if effect_type not in EFFECTS_REGISTRY:
            raise ValueError(f"Unknown effect: {effect_type}")
        with self._lock:
            self.active[name] = {"type": effect_type, "params": params, "frame": 0}
        log.info(f"Effect added: {name} [{effect_type}]")

    def remove(self, name):
        with self._lock:
            self.active.pop(name, None)

    def clear(self):
        with self._lock:
            self.active.clear()

    @property
    def any_active(self):
        return bool(self.active)

    def get_status(self):
        with self._lock:
            return {"running": bool(self.active), "effects": dict(self.active)}

    # ── the filter ────────────────────────────────────────────────
    def apply(self, frame):
        """Layer every active effect over a clean content frame."""
        with self._lock:
            if not self.active:
                return frame
            stack = list(self.active.values())

        out = frame.copy()
        for cfg in stack:
            try:
                out = self._one(out, cfg)
                cfg["frame"] += 1
            except Exception as e:
                log.warning(f"Effect {cfg.get('type')} failed: {e}")
        return out

    def _one(self, frame, cfg):
        et   = cfg["type"]
        p    = cfg.get("params", {})
        n    = cfg["frame"]
        h, w = frame.shape

        if et == "flicker":
            mask = np.random.rand(h, w) < float(p.get("rate", 0.05))
            return np.where(mask, 1 - frame, frame).astype(np.uint8)

        if et == "pulse":
            # Smooth on/off cycle rather than V7's "invert every Nth frame",
            # which depended on the content's framerate and so ran at a
            # different speed for every piece of content.
            speed  = max(0.05, float(p.get("speed", 0.5)))
            period = max(2, int(round((1.0 / speed) / 0.05)))
            return (1 - frame).astype(np.uint8) if (n // period) % 2 else frame

        if et == "chase":
            x = int(n * float(p.get("speed", 1.0))) % w
            frame[:, x] = 1 - frame[:, x]
            return frame

        if et == "scanline":
            y = int(n * float(p.get("speed", 0.5))) % h
            frame[y, :] = 1
            return frame

        if et == "noise":
            mask = np.random.rand(h, w) < float(p.get("density", 0.05))
            return np.where(mask, np.random.randint(0, 2, (h, w)), frame).astype(np.uint8)

        if et == "invert":
            return (1 - frame).astype(np.uint8)

        if et == "mirror":
            # Fold the left half onto the right — cheap kaleidoscope.
            half = w // 2
            frame[:, w - half:] = np.fliplr(frame[:, :half])
            return frame

        return frame


EFFECTS_REGISTRY = {
    "flicker":  {"label": "Flicker",  "params": [
        {"id": "rate", "label": "Rate", "type": "range",
         "min": 0.01, "max": 0.3, "step": 0.01, "default": 0.05}]},
    "pulse":    {"label": "Pulse",    "params": [
        {"id": "speed", "label": "Speed", "type": "range",
         "min": 0.1, "max": 5.0, "step": 0.1, "default": 0.5}]},
    "chase":    {"label": "Chase",    "params": [
        {"id": "speed", "label": "Speed", "type": "range",
         "min": 0.5, "max": 5.0, "step": 0.5, "default": 1.0}]},
    "scanline": {"label": "Scanline", "params": [
        {"id": "speed", "label": "Speed", "type": "range",
         "min": 0.2, "max": 3.0, "step": 0.2, "default": 0.5}]},
    "noise":    {"label": "Noise",    "params": [
        {"id": "density", "label": "Density", "type": "range",
         "min": 0.01, "max": 0.3, "step": 0.01, "default": 0.05}]},
    "invert":   {"label": "Invert",   "params": []},
    "mirror":   {"label": "Mirror",   "params": []},
}
