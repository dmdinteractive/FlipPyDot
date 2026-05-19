"""
cue_engine.py
-------------
Professional cue list engine modelled on theatrical lighting console behaviour.

Concepts:
  Cue       — a named display state with timing metadata
  Cue List  — ordered sequence of cues
  Transport — Go / Back / Jump / Release / Hold

Cue timing fields:
  pre_wait   — seconds to wait before executing (delay after GO pressed)
  duration   — how long to hold the state (-1 = infinite / manual)
  fade_in    — transition time from previous state (0 = snap)
  auto_follow — if True, automatically GO to next cue after duration
"""

import time
import threading
import logging
import uuid
import copy

log = logging.getLogger(__name__)

# ── Cue ───────────────────────────────────────────────────────────

class Cue:
    def __init__(self, number=None, label="", content_type="clear",
                 content=None, pre_wait=0.0, duration=5.0,
                 fade_in=0.0, auto_follow=False, options=None):
        self.id          = str(uuid.uuid4())[:8]
        self.number      = number          # Float cue number e.g. 1.0, 1.5, 2.0
        self.label       = label
        self.content_type= content_type    # 'text','animation','image','clear','fill'
        self.content     = content or {}   # type-specific payload
        self.pre_wait    = float(pre_wait)
        self.duration    = float(duration) # -1 = hold until next GO
        self.fade_in     = float(fade_in)
        self.auto_follow = bool(auto_follow)
        self.options     = options or {}
        self.notes       = ""

    def to_dict(self):
        return {
            "id": self.id, "number": self.number, "label": self.label,
            "content_type": self.content_type, "content": self.content,
            "pre_wait": self.pre_wait, "duration": self.duration,
            "fade_in": self.fade_in, "auto_follow": self.auto_follow,
            "options": self.options, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d):
        c = cls()
        for k, v in d.items():
            if hasattr(c, k): setattr(c, k, v)
        return c


# ── Cue Engine ────────────────────────────────────────────────────

class CueEngine:
    """
    Manages a cue list and drives the display through them.

    States:
      IDLE      — no cue active, display holds last state
      PRE_WAIT  — cue triggered, waiting pre_wait seconds
      ACTIVE    — cue is live on display
      HOLDING   — duration = -1, waiting for next GO
    """

    IDLE     = "IDLE"
    PRE_WAIT = "PRE_WAIT"
    ACTIVE   = "ACTIVE"
    HOLDING  = "HOLDING"

    def __init__(self, execute_fn):
        """
        execute_fn: callable(cue) that renders a cue to the display.
        """
        self._execute    = execute_fn
        self.cues        = []            # List[Cue], ordered by number
        self.current_idx = -1           # Index in self.cues (-1 = none)
        self.state       = self.IDLE
        self.elapsed     = 0.0
        self._thread     = None
        self._stop_evt   = threading.Event()
        self._lock       = threading.Lock()
        self.pending_go  = False

    # ── Cue list management ───────────────────────────────────────

    def add_cue(self, cue: Cue):
        with self._lock:
            self.cues.append(cue)
            self.cues.sort(key=lambda c: c.number if c.number else 0)
        return cue

    def remove_cue(self, cue_id: str):
        with self._lock:
            self.cues = [c for c in self.cues if c.id != cue_id]

    def update_cue(self, cue_id: str, data: dict):
        with self._lock:
            for c in self.cues:
                if c.id == cue_id:
                    for k, v in data.items():
                        if hasattr(c, k): setattr(c, k, v)
                    self.cues.sort(key=lambda x: x.number if x.number else 0)
                    return c
        return None

    def get_cue(self, cue_id: str):
        return next((c for c in self.cues if c.id == cue_id), None)

    def renumber(self, start=1.0, step=1.0):
        """Renumber all cues sequentially."""
        with self._lock:
            for i, c in enumerate(self.cues):
                c.number = round(start + i * step, 3)

    # ── Transport ─────────────────────────────────────────────────

    def go(self):
        """Advance to next cue or complete current pre-wait."""
        with self._lock:
            if self.state in (self.IDLE, self.HOLDING, self.ACTIVE):
                next_idx = self.current_idx + 1
                if next_idx < len(self.cues):
                    self._trigger_cue(next_idx)
                else:
                    log.info("CueEngine: end of list")
            elif self.state == self.PRE_WAIT:
                # Override pre-wait, execute immediately
                self.pending_go = True

    def back(self):
        """Return to previous cue."""
        with self._lock:
            prev_idx = max(0, self.current_idx - 1)
            if self.cues:
                self._trigger_cue(prev_idx)

    def jump(self, cue_id_or_number):
        """Jump to a specific cue by id or number."""
        with self._lock:
            target = None
            for i, c in enumerate(self.cues):
                if str(c.id) == str(cue_id_or_number) or \
                   str(c.number) == str(cue_id_or_number):
                    target = i
                    break
            if target is not None:
                self._trigger_cue(target)
            else:
                log.warning(f"CueEngine: cue not found: {cue_id_or_number}")

    def release(self):
        """Stop playback and return to idle."""
        self._stop_evt.set()
        with self._lock:
            self.state       = self.IDLE
            self.current_idx = -1
            self.elapsed     = 0.0
        log.info("CueEngine: released")

    def hold(self):
        """Pause auto-follow on current cue."""
        with self._lock:
            if self.state == self.ACTIVE:
                self.state = self.HOLDING

    def _trigger_cue(self, idx: int):
        """Internal — start executing cue at index."""
        self._stop_evt.set()
        time.sleep(0.02)
        self._stop_evt.clear()
        self.current_idx = idx
        self.state       = self.PRE_WAIT if self.cues[idx].pre_wait > 0 else self.ACTIVE
        self.elapsed     = 0.0
        self._thread     = threading.Thread(
            target=self._run_cue, args=(idx,), daemon=True)
        self._thread.start()

    def _run_cue(self, idx: int):
        cue = self.cues[idx]
        log.info(f"CueEngine: running cue {cue.number} '{cue.label}'")

        # Pre-wait
        if cue.pre_wait > 0:
            start = time.time()
            while time.time() - start < cue.pre_wait:
                if self._stop_evt.is_set() or self.pending_go: break
                self.elapsed = time.time() - start
                time.sleep(0.05)
            self.pending_go = False

        if self._stop_evt.is_set(): return

        # Execute
        self.state = self.ACTIVE
        self.elapsed = 0.0
        try:
            self._execute(cue)
        except Exception as e:
            log.error(f"CueEngine: execute error: {e}")

        if self._stop_evt.is_set(): return

        # Duration
        if cue.duration < 0:
            self.state = self.HOLDING
            return

        start = time.time()
        while time.time() - start < cue.duration:
            if self._stop_evt.is_set(): return
            self.elapsed = time.time() - start
            time.sleep(0.05)

        if self._stop_evt.is_set(): return

        # Auto-follow
        if cue.auto_follow:
            next_idx = idx + 1
            if next_idx < len(self.cues):
                with self._lock:
                    self._trigger_cue(next_idx)

    # ── Status ────────────────────────────────────────────────────

    def get_status(self):
        cur  = self.cues[self.current_idx] if 0 <= self.current_idx < len(self.cues) else None
        nxt  = self.cues[self.current_idx + 1] if 0 <= self.current_idx + 1 < len(self.cues) else None
        return {
            "state":       self.state,
            "current_cue": cur.to_dict() if cur else None,
            "next_cue":    nxt.to_dict() if nxt else None,
            "current_idx": self.current_idx,
            "total_cues":  len(self.cues),
            "elapsed":     round(self.elapsed, 2),
            "cues":        [c.to_dict() for c in self.cues],
        }

    # ── Show file I/O ─────────────────────────────────────────────

    def to_list(self):
        return [c.to_dict() for c in self.cues]

    def from_list(self, data: list):
        with self._lock:
            self.cues = [Cue.from_dict(d) for d in data]
