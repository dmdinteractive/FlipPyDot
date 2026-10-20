"""
clip.py — Sample any renderer content at an arbitrary time t.

The renderer describes content as a generator of (frame, delay). That's a
convenient way to WRITE an animation, but the player, the live preview and
the text-over-visual compositor all need to ask "what's showing at t?"
instead. Clip is the adapter.

Each frame occupies [start, start + delay). delay=None holds that frame
indefinitely. If the content has {tokens} and the hold is the only frame of
its pass (plain static text), the clip re-renders once a second so a static
"{time}" keeps ticking.
"""

import json

MAX_CATCHUP = 2000     # generator frames we'll fast-forward through in one call


class Clip:
    def __init__(self, spec, w, h, loop=True, duration=None):
        self.spec = spec or {}
        self.w, self.h = w, h
        self.loop = loop
        self.duration = duration
        self.tokens = ("{" in json.dumps(self.spec.get("text", ""))
                       or "{" in json.dumps(self.spec.get("zones", "")))
        self.frame = None
        self.start = 0.0
        self.end = 0.0
        self.finished = False
        self._new_pass()

    def _new_pass(self):
        import renderer                  # late: renderer imports Clip too
        self._gen = renderer.frames(self.spec, self.w, self.h, duration=self.duration)
        self._n_in_pass = 0

    @property
    def next_change(self):
        return self.end

    def at(self, t):
        guard = 0
        while not self.finished and t >= self.end:
            guard += 1
            if guard > MAX_CATCHUP:
                self.start = self.end = t        # hopelessly behind: rebase
                break
            try:
                frame, delay = next(self._gen)
            except StopIteration:
                if self.loop and self._n_in_pass:
                    self._new_pass()
                    continue
                self.finished = True
                self.end = float("inf")
                break
            self._n_in_pass += 1
            self.frame = frame
            self.start = self.end
            if delay is None:
                if self.tokens and self._n_in_pass == 1:
                    self.end = self.start + 1.0
                    self._new_pass()
                else:
                    self.end = float("inf")
            else:
                self.end = self.start + max(0.0, float(delay))
        return self.frame
