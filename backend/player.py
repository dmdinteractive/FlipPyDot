"""
player.py — The single owner of the display.

V7 had three independent ways to drive the panel (run_anim, play_gif, direct
display.send) and they raced: starting an animation while a GIF was playing
left both threads writing frames to the same serial port, so you'd get
interleaved garbage until one happened to finish.

Here exactly one thread ever writes to the display. Jobs are handed to it with
a monotonically increasing generation number; the moment a new job arrives the
old loop sees a stale generation and returns without sending another frame.
Nothing else in the app is allowed to call display.send().
"""

import time
import logging
import threading

import renderer

log = logging.getLogger(__name__)

# How finely we chop up a sleep. Long holds must still react to a stop within
# a fraction of a second, so we never sleep longer than this in one go.
TICK = 0.02


# While an effect is running, static content still has to be re-sent for the
# effect to animate over it. This is that refresh rate.
FX_FPS = 20


class Player:
    def __init__(self, display, get_size, effects=None):
        self._display  = display
        self._get_size = get_size
        self._effects  = effects       # applied to every frame on the way out
        self._lock     = threading.Lock()
        self._gen      = 0
        self._thread   = None
        self._done     = threading.Event()
        self._done.set()
        self.current   = None          # spec currently playing, for /api/status

    # ── control ───────────────────────────────────────────────────
    def play(self, spec, duration=None, loop=True):
        """Start playing `spec`. Returns immediately.

        duration — seconds to keep it up, or None to run until replaced.
        loop     — restart the content when its frames run out. Re-running the
                   generator also re-substitutes {variables}, which is how a
                   scrolling {time} stays live instead of freezing at the value
                   it had when the step started.
        """
        with self._lock:
            self._gen += 1
            gen = self._gen
            self.current = spec

        self._done.clear()
        t = threading.Thread(target=self._run, args=(spec, duration, loop, gen),
                             daemon=True)
        self._thread = t
        t.start()
        return gen

    def stop(self, clear=True):
        with self._lock:
            self._gen += 1
            self.current = None
        self._done.set()
        if clear:
            self._display.clear()

    def wait(self, timeout=None):
        """Block until the current job finishes on its own. True if it did."""
        return self._done.wait(timeout)

    @property
    def busy(self):
        return not self._done.is_set()

    # ── the one and only render loop ──────────────────────────────
    def _run(self, spec, duration, loop, gen):
        deadline = (time.time() + duration) if duration else None
        w, h = self._get_size()

        try:
            while self._current(gen):
                produced = False

                for frame, delay in renderer.frames(spec, w, h):
                    if not self._current(gen):
                        return
                    self._emit(frame)
                    produced = True

                    # delay=None means "hold". Sit on this frame until the
                    # step's deadline, or forever if it has none.
                    if delay is None:
                        if not self._hold(frame, deadline, gen):
                            return
                        break
                    if not self._sleep(delay, gen):
                        return
                    if deadline and time.time() >= deadline:
                        return

                if deadline and time.time() >= deadline:
                    return
                if not loop:
                    break
                if not produced:
                    return                    # empty generator — don't hot-spin

            # Ran out of content before the deadline (loop=False): sit on the
            # last frame rather than going dark early.
            if deadline:
                self._sleep(max(0.0, deadline - time.time()), gen)

        except Exception as e:
            log.error(f"Player error: {e}", exc_info=True)
        finally:
            with self._lock:
                if self._gen == gen:
                    self._done.set()

    # ── output ────────────────────────────────────────────────────
    def _emit(self, frame):
        """The only path to the panel. Effects are layered on here, over the
        clean content frame, so they never compound on their own output."""
        if self._effects is not None and self._effects.any_active:
            frame = self._effects.apply(frame)
        self._display.send(frame)

    # ── generation-aware sleeping ─────────────────────────────────
    def _current(self, gen):
        return self._gen == gen

    def _sleep(self, seconds, gen):
        """Sleep in TICK slices. False as soon as this job is superseded."""
        end = time.time() + seconds
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return self._current(gen)
            if not self._current(gen):
                return False
            time.sleep(min(TICK, remaining))

    def _hold(self, frame, deadline, gen):
        """Sit on one frame until `deadline` (or forever if None).

        If an effect is running we must keep re-sending, otherwise a flicker
        over static text would draw exactly one frame and then freeze.
        """
        while self._current(gen):
            if deadline is not None and time.time() >= deadline:
                return True
            if self._effects is not None and self._effects.any_active:
                self._emit(frame)
                if not self._sleep(1.0 / FX_FPS, gen):
                    return False
            else:
                time.sleep(TICK)
        return False

    # ── status ────────────────────────────────────────────────────
    def get_status(self):
        spec = self.current or {}
        return {
            "playing": self.busy,
            "kind":    spec.get("kind"),
            "label":   spec.get("text") or spec.get("animation") or spec.get("kind"),
        }
