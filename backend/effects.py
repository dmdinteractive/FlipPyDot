"""
effects.py — Real-time effects engine.
Runs continuously on top of the current display buffer.

Effects:
  flicker    — random dots invert at a given rate
  pulse      — periodic full invert of buffer
  chase      — single-dot line sweeping across display
  scanline   — horizontal scanline moving top to bottom
  noise      — random noise overlay at given density
"""
import threading, time, random, numpy as np, logging
log = logging.getLogger(__name__)

class EffectsEngine:
    def __init__(self, get_buf_fn, send_fn):
        self._get_buf   = get_buf_fn   # returns current buffer np array
        self._send      = send_fn      # sends a frame to display
        self.active     = {}           # name -> config dict
        self._thread    = None
        self._running   = False
        self._lock      = threading.Lock()

    def add(self, name, effect_type, **params):
        with self._lock:
            self.active[name] = {"type":effect_type,"params":params,"frame":0}
        if not self._running: self._start()
        log.info(f"Effect added: {name} [{effect_type}]")

    def remove(self, name):
        with self._lock:
            self.active.pop(name, None)
        if not self.active: self._stop()

    def clear(self):
        with self._lock: self.active.clear()
        self._stop()

    def get_status(self):
        return {"running":self._running, "effects": dict(self.active)}

    def _start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _stop(self):
        self._running = False

    def _loop(self):
        while self._running and self.active:
            base = self._get_buf().copy()
            with self._lock:
                effects = dict(self.active)
            frame = base.copy()
            for name, cfg in effects.items():
                try:
                    frame = self._apply(frame, cfg)
                    cfg["frame"] += 1
                except: pass
            self._send(frame)
            time.sleep(0.05)
        self._running = False

    def _apply(self, frame, cfg):
        et = cfg["type"]
        p  = cfg.get("params", {})
        n  = cfg["frame"]
        h, w = frame.shape

        if et == "flicker":
            rate    = float(p.get("rate", 0.05))
            mask    = np.random.rand(h, w) < rate
            frame   = np.where(mask, 1 - frame, frame).astype(np.uint8)

        elif et == "pulse":
            speed  = float(p.get("speed", 0.5))
            period = max(1, int(1.0 / (speed * 0.05)))
            if n % period == 0:
                frame = (1 - frame).astype(np.uint8)

        elif et == "chase":
            speed = float(p.get("speed", 1.0))
            x     = int(n * speed) % w
            frame[:, x] = 1 - frame[:, x]

        elif et == "scanline":
            speed = float(p.get("speed", 0.5))
            y     = int(n * speed) % h
            frame[y, :] = 1

        elif et == "noise":
            density = float(p.get("density", 0.05))
            mask    = np.random.rand(h, w) < density
            frame   = np.where(mask, np.random.randint(0, 2, (h, w)), frame).astype(np.uint8)

        return frame

EFFECTS_REGISTRY = {
    "flicker":  {"label":"Flicker",  "params":[{"id":"rate","label":"Rate","type":"range","min":0.01,"max":0.3,"step":0.01,"default":0.05}]},
    "pulse":    {"label":"Pulse",    "params":[{"id":"speed","label":"Speed","type":"range","min":0.1,"max":5.0,"step":0.1,"default":0.5}]},
    "chase":    {"label":"Chase",    "params":[{"id":"speed","label":"Speed","type":"range","min":0.5,"max":5.0,"step":0.5,"default":1.0}]},
    "scanline": {"label":"Scanline", "params":[{"id":"speed","label":"Speed","type":"range","min":0.2,"max":3.0,"step":0.2,"default":0.5}]},
    "noise":    {"label":"Noise",    "params":[{"id":"density","label":"Density","type":"range","min":0.01,"max":0.3,"step":0.01,"default":0.05}]},
}
