"""
player.py — The single owner of the display.

Exactly one thread ever posts frames to the display, and a monotonically
increasing generation number retires the old job the moment a new one starts
(unchanged from V8 — that part worked).

What changed in V9 is the CLOCK. V8 walked through the renderer's frames one
by one and slept each frame's delay. If anything downstream was slow, every
frame still got shown, just late — content drifted behind real time.

Now content is a Clip: "what should be on the panel at t seconds?" The player
samples it against the wall clock. If the panel can only take 12 frames a
second and the content was authored at 20, the in-between frames are simply
never drawn; a 3-second scroll still takes 3 seconds. Combined with the
display's one-frame mailbox, there is nowhere for lag to accumulate.
"""

import time
import logging
import threading

import numpy as np

from clip import Clip

log = logging.getLogger(__name__)

TICK = 0.02            # longest single sleep — keeps stop() responsive
FX_FPS = 20            # resample rate while an effect is animating


class Player:
    def __init__(self, display, get_size, effects=None):
        self._display  = display
        self._get_size = get_size
        self._effects  = effects
        self._lock     = threading.Lock()
        self._gen      = 0
        self._done     = threading.Event()
        self._done.set()
        self._last_sent = None
        self.current   = None

    # ── control ───────────────────────────────────────────────────
    def play(self, spec, duration=None, loop=True):
        """Start playing `spec`. Returns immediately.

        duration — seconds to keep it up, or None to run until replaced.
        loop     — restart the content when it runs out (re-substituting
                   {tokens} each pass).
        """
        with self._lock:
            self._gen += 1
            gen = self._gen
            self.current = spec
            self._last_sent = None
        self._done.clear()
        threading.Thread(target=self._run, args=(spec, duration, loop, gen),
                         daemon=True, name="player").start()
        return gen

    def stop(self, clear=True):
        # Clear under the same lock _emit posts under, so a render that was
        # mid-frame when stop() arrived can't land after the clear.
        with self._lock:
            self._gen += 1
            self.current = None
            self._last_sent = None
            if clear:
                self._display.clear()
        self._done.set()

    @property
    def generation(self):
        return self._gen

    def wait(self, timeout=None):
        return self._done.wait(timeout)

    @property
    def busy(self):
        return not self._done.is_set()

    # ── the one and only render loop ──────────────────────────────
    def _run(self, spec, duration, loop, gen):
        w, h = self._get_size()
        try:
            clip = Clip(spec, w, h, loop=loop, duration=duration)
            t0 = time.monotonic()
            while self._gen == gen:
                t = time.monotonic() - t0
                if duration and t >= duration:
                    return
                frame = clip.at(t)
                if frame is not None and not self._emit(frame, gen):
                    return

                if clip.finished and not duration:
                    return                       # one-shot with no hold time

                # Sleep until the content next changes — but never longer than
                # one display frame if an effect needs re-sampling, and never
                # past the step's deadline.
                wake = clip.next_change
                if self._effects is not None and self._effects.any_active:
                    wake = min(wake, t + 1.0 / max(1.0, min(FX_FPS, self._display.max_fps)))
                if duration:
                    wake = min(wake, duration)
                # Don't render faster than the panel can flip; anything between
                # two panel frames would be thrown away by the mailbox anyway.
                wake = max(wake, t + 1.0 / max(1.0, self._display.max_fps) * 0.5)
                if not self._sleep_until(t0 + wake, gen):
                    return
        except Exception as e:
            log.error(f"Player error: {e}", exc_info=True)
        finally:
            with self._lock:
                if self._gen == gen:
                    self._done.set()

    def _sleep_until(self, deadline, gen):
        while self._gen == gen:
            left = deadline - time.monotonic()
            if left <= 0:
                return True
            time.sleep(min(TICK, left))
        return False

    # ── output ────────────────────────────────────────────────────
    def _emit(self, frame, gen):
        """The only path to the panel. Effects layer on the clean frame here
        so they never compound; identical frames are not re-posted.

        The generation check and the post happen under one lock: a job that
        was superseded while it was rendering must never get its frame onto
        the wall after the new job's first frame. Returns False if superseded.
        """
        if self._effects is not None and self._effects.any_active:
            frame = self._effects.apply(frame)
            fx = True
        else:
            fx = False
        with self._lock:
            if self._gen != gen:
                return False
            if not fx and self._last_sent is not None and np.array_equal(frame, self._last_sent):
                return True
            self._last_sent = None if fx else frame.copy()
            self._display.send(frame)
        return True

    # ── status ────────────────────────────────────────────────────
    def get_status(self):
        spec = self.current or {}
        return {
            "playing": self.busy,
            "kind":    spec.get("kind"),
            "label":   spec.get("label") or spec.get("text") or spec.get("animation") or spec.get("kind"),
        }
