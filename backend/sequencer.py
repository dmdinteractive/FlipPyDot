"""
sequencer.py — Playlist + overlays.

The V7 "scheduler" was a cron poller: every item decided independently whether
it was due, fired, and stomped on whatever was already showing. `duration` was
stored on every item and never read by anything, so "show this for 8 seconds"
silently did nothing.

This replaces it with two layers that compose:

  PLAYLIST — an ordered list of steps. Each step plays its content for its
             duration, then the next one does, and at the end it loops. This
             is the thing you actually want 95% of the time ("rotate my six
             messages"), and it was impossible to express before.

  OVERLAYS — time-triggered content (daily / weekly / every-N / once) that
             INTERRUPTS the playlist, plays for its duration, then hands
             control back to the step it interrupted. This is the old cron
             behaviour, but scoped so it can't fight with the playlist.

One thread drives both, and it is the only caller of Player.play(), so two
pieces of content can never be on screen at once.
"""

import time
import uuid
import logging
import threading
from datetime import datetime, time as dtime

log = logging.getLogger(__name__)


def _uid():
    return uuid.uuid4().hex[:8]


class Step:
    """One entry in the playlist."""

    def __init__(self, label="", content=None, duration=8.0, enabled=True,
                 transition=None, id=None):
        self.id         = id or _uid()
        self.label      = label
        self.content    = content or {"kind": "text", "text": ""}
        self.duration   = float(duration)
        self.enabled    = bool(enabled)
        self.transition = transition      # {"animation": "wipe_right", "params": {...}}
        self.last_run   = None

    def to_dict(self):
        return {
            "id": self.id, "label": self.label, "content": self.content,
            "duration": self.duration, "enabled": self.enabled,
            "transition": self.transition, "last_run": self.last_run,
        }

    @classmethod
    def from_dict(cls, d):
        s = cls(
            label=d.get("label", ""), content=d.get("content"),
            duration=d.get("duration", 8.0), enabled=d.get("enabled", True),
            transition=d.get("transition"), id=d.get("id"),
        )
        s.last_run = d.get("last_run")
        return s


class Overlay:
    """Time-triggered content that pre-empts the playlist."""

    DAILY    = "daily"       # at HH:MM every day
    WEEKLY   = "weekly"      # at HH:MM on selected weekdays
    INTERVAL = "interval"    # every N seconds
    ONCE     = "once"        # at an absolute datetime, one time only

    def __init__(self, label="", content=None, duration=8.0, enabled=True,
                 trigger=None, priority=0, id=None):
        self.id       = id or _uid()
        self.label    = label
        self.content  = content or {"kind": "text", "text": ""}
        self.duration = float(duration)
        self.enabled  = bool(enabled)
        self.priority = int(priority)
        # {"type": "daily",    "at": "17:00"}
        # {"type": "weekly",   "at": "09:00", "days": [0,1,2,3,4]}
        # {"type": "interval", "every": 1800}
        # {"type": "once",     "at": "2026-07-20T17:00:00"}
        self.trigger  = trigger or {"type": self.INTERVAL, "every": 1800}
        self.last_run = None
        self.fired    = False            # for ONCE

    # ── due logic ─────────────────────────────────────────────────
    def is_due(self, now_ts, now_dt=None):
        if not self.enabled:
            return False
        now_dt = now_dt or datetime.now()
        t = self.trigger or {}
        kind = t.get("type", self.INTERVAL)

        if kind == self.INTERVAL:
            every = float(t.get("every", 1800) or 1800)
            if self.last_run is None:
                return True
            return (now_ts - self.last_run) >= every

        if kind == self.ONCE:
            if self.fired:
                return False
            at = self._parse_dt(t.get("at"))
            return bool(at) and now_dt >= at

        if kind in (self.DAILY, self.WEEKLY):
            at = self._parse_time(t.get("at"))
            if not at:
                return False
            if kind == self.WEEKLY:
                days = t.get("days") or []
                if days and now_dt.weekday() not in days:
                    return False
            # Fire inside a 60s window after the trigger time, but only once
            # per day — otherwise it would re-fire every second for a minute.
            if (now_dt.hour, now_dt.minute) != (at.hour, at.minute):
                return False
            if self.last_run and (now_ts - self.last_run) < 90:
                return False
            return True

        return False

    def mark_fired(self, now_ts):
        self.last_run = now_ts
        if (self.trigger or {}).get("type") == self.ONCE:
            self.fired = True

    @staticmethod
    def _parse_time(s):
        if not s:
            return None
        try:
            return dtime.fromisoformat(str(s))
        except ValueError:
            return None

    @staticmethod
    def _parse_dt(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s))
        except (ValueError, TypeError):
            return None

    def to_dict(self):
        return {
            "id": self.id, "label": self.label, "content": self.content,
            "duration": self.duration, "enabled": self.enabled,
            "trigger": self.trigger, "priority": self.priority,
            "last_run": self.last_run, "fired": self.fired,
        }

    @classmethod
    def from_dict(cls, d):
        o = cls(
            label=d.get("label", ""), content=d.get("content"),
            duration=d.get("duration", 8.0), enabled=d.get("enabled", True),
            trigger=d.get("trigger"), priority=d.get("priority", 0),
            id=d.get("id"),
        )
        o.last_run = d.get("last_run")
        o.fired    = d.get("fired", False)
        return o


class Sequencer:
    POLL = 0.25          # how often we re-check overlays while a step plays

    def __init__(self, player):
        self._player   = player
        self.steps     = []
        self.overlays  = []
        self.loop      = True
        self.running   = False
        self.index     = 0               # index into the ENABLED steps
        self._thread   = None
        self._wake     = threading.Event()
        self._lock     = threading.Lock()
        self.on_change = lambda: None    # host hooks persistence in here

    # ── playlist CRUD ─────────────────────────────────────────────
    def add_step(self, step, at=None):
        with self._lock:
            if at is None:
                self.steps.append(step)
            else:
                self.steps.insert(max(0, min(len(self.steps), int(at))), step)
        self.on_change()
        return step

    def update_step(self, sid, data):
        with self._lock:
            for s in self.steps:
                if s.id == sid:
                    for k in ("label", "content", "duration", "enabled", "transition"):
                        if k in data:
                            setattr(s, k, data[k])
                    s.duration = float(s.duration)
                    self.on_change()
                    return s
        return None

    def remove_step(self, sid):
        with self._lock:
            before = len(self.steps)
            self.steps = [s for s in self.steps if s.id != sid]
            changed = len(self.steps) != before
        if changed:
            self.on_change()
        return changed

    def reorder(self, ids):
        """Reorder the playlist to match `ids`. Unlisted steps keep their tail order."""
        with self._lock:
            by_id = {s.id: s for s in self.steps}
            new = [by_id.pop(i) for i in ids if i in by_id]
            new.extend(s for s in self.steps if s.id in by_id)
            self.steps = new
        self.on_change()
        return self.steps

    def duplicate_step(self, sid):
        with self._lock:
            for i, s in enumerate(self.steps):
                if s.id == sid:
                    import copy
                    clone = Step.from_dict(s.to_dict())
                    clone.id = _uid()
                    clone.label = (s.label or "Step") + " copy"
                    clone.content = copy.deepcopy(s.content)
                    clone.last_run = None
                    self.steps.insert(i + 1, clone)
                    self.on_change()
                    return clone
        return None

    # ── overlay CRUD ──────────────────────────────────────────────
    def add_overlay(self, ov):
        with self._lock:
            self.overlays.append(ov)
            self.overlays.sort(key=lambda o: -o.priority)
        self.on_change()
        return ov

    def update_overlay(self, oid, data):
        with self._lock:
            for o in self.overlays:
                if o.id == oid:
                    for k in ("label", "content", "duration", "enabled",
                              "trigger", "priority"):
                        if k in data:
                            setattr(o, k, data[k])
                    o.duration = float(o.duration)
                    o.priority = int(o.priority)
                    if "trigger" in data:
                        o.fired = False       # re-arm a edited one-shot
                    self.overlays.sort(key=lambda x: -x.priority)
                    self.on_change()
                    return o
        return None

    def remove_overlay(self, oid):
        with self._lock:
            before = len(self.overlays)
            self.overlays = [o for o in self.overlays if o.id != oid]
            changed = len(self.overlays) != before
        if changed:
            self.on_change()
        return changed

    # ── transport ─────────────────────────────────────────────────
    def start(self):
        if self.running:
            return
        self.running = True
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Sequencer started")

    def stop(self, clear=False):
        self.running = False
        self._wake.set()
        if clear:
            self._player.stop()
        log.info("Sequencer stopped")

    def next(self):
        self.index += 1
        self._wake.set()

    def prev(self):
        self.index -= 1
        self._wake.set()

    def goto(self, i):
        self.index = int(i)
        self._wake.set()

    # ── the drive loop ────────────────────────────────────────────
    def _enabled_steps(self):
        return [s for s in self.steps if s.enabled]

    def _due_overlay(self, now_ts):
        now_dt = datetime.now()
        for o in self.overlays:          # already sorted by priority desc
            if o.is_due(now_ts, now_dt):
                return o
        return None

    def _loop(self):
        while self.running:
            now = time.time()

            ov = self._due_overlay(now)
            if ov:
                ov.mark_fired(now)
                log.info(f"Overlay fired: {ov.label or ov.id}")
                self._player.play(ov.content, duration=ov.duration)
                self._sleep(ov.duration, allow_overlay=False)
                self.on_change()
                continue                 # then fall back into the playlist

            steps = self._enabled_steps()
            if not steps:
                self._player.stop(clear=False)
                self._sleep(0.5)
                continue

            self.index %= len(steps)
            step = steps[self.index]

            if step.transition and step.transition.get("animation"):
                self._player.play(
                    {"kind": "animation",
                     "animation": step.transition["animation"],
                     "params": step.transition.get("params", {})},
                    loop=False,
                )
                self._player.wait(timeout=3.0)

            step.last_run = now
            self._player.play(step.content, duration=step.duration)

            # Sleep out the step, but stay responsive: an overlay coming due
            # or a manual next/prev breaks out early.
            interrupted = self._sleep(step.duration, allow_overlay=True)
            if interrupted == "overlay":
                continue                 # replay this same step after the overlay
            if interrupted == "wake":
                continue                 # index already moved by next/prev/goto

            self.index += 1
            if not self.loop and self.index >= len(steps):
                self.running = False
                self._player.stop()
                break

        log.info("Sequencer loop exited")

    def _sleep(self, seconds, allow_overlay=True):
        """Sleep, returning early on overlay/manual-wake. Returns the reason."""
        end = time.time() + float(seconds)
        while self.running:
            remaining = end - time.time()
            if remaining <= 0:
                return None
            if self._wake.wait(min(self.POLL, remaining)):
                self._wake.clear()
                return "wake"
            if allow_overlay and self._due_overlay(time.time()):
                return "overlay"
        return "stopped"

    # ── status + persistence ──────────────────────────────────────
    def get_status(self):
        steps = self._enabled_steps()
        cur = steps[self.index % len(steps)].id if steps else None
        return {
            "running":  self.running,
            "loop":     self.loop,
            "index":    self.index % len(steps) if steps else 0,
            "current":  cur,
            "steps":    [s.to_dict() for s in self.steps],
            "overlays": [o.to_dict() for o in self.overlays],
        }

    def to_dict(self):
        return {
            "loop":     self.loop,
            "running":  self.running,
            "steps":    [s.to_dict() for s in self.steps],
            "overlays": [o.to_dict() for o in self.overlays],
        }

    def load(self, data):
        with self._lock:
            self.steps    = [Step.from_dict(d)    for d in data.get("steps", [])]
            self.overlays = [Overlay.from_dict(d) for d in data.get("overlays", [])]
            self.overlays.sort(key=lambda o: -o.priority)
            self.loop     = data.get("loop", True)
            self.index    = 0
