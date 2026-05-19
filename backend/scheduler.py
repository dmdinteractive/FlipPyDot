"""
scheduler.py
------------
Calendar-aware scheduler for unattended operation.

Schedule items support:
  - One-shot at a specific datetime
  - Repeating on an interval
  - Weekly recurring (days of week + time range)
  - Priority levels — higher priority preempts lower
"""

import time
import threading
import uuid
import logging
from datetime import datetime, time as dtime

log = logging.getLogger(__name__)


class ScheduleItem:
    ONCE    = "once"
    REPEAT  = "repeat"
    WEEKLY  = "weekly"

    def __init__(self, label="", content_type="text", content=None,
                 mode=REPEAT, duration=5.0, interval=60.0,
                 start_time=None, end_time=None, days=None,
                 priority=0, options=None):
        self.id           = str(uuid.uuid4())[:8]
        self.label        = label
        self.content_type = content_type
        self.content      = content or {}
        self.mode         = mode
        self.duration     = float(duration)
        self.interval     = float(interval)
        self.start_time   = start_time    # datetime or None
        self.end_time     = end_time      # datetime or None (for weekly: time string "HH:MM")
        self.days         = days or []    # [0-6] Mon=0 for weekly mode
        self.priority     = int(priority)
        self.options      = options or {}
        self.enabled      = True
        self.last_run     = None

    def is_due(self, now: float) -> bool:
        if not self.enabled: return False
        if self.mode == self.ONCE:
            if self.start_time and self.last_run is None:
                return datetime.now() >= self.start_time
            return False
        if self.mode == self.REPEAT:
            if self.last_run is None: return True
            return (now - self.last_run) >= self.interval
        if self.mode == self.WEEKLY:
            dt  = datetime.now()
            dow = dt.weekday()
            if self.days and dow not in self.days: return False
            if self.start_time:
                t_start = dtime.fromisoformat(self.start_time) if isinstance(self.start_time, str) else self.start_time
                t_end   = dtime.fromisoformat(self.end_time)   if self.end_time and isinstance(self.end_time, str) else None
                if dt.time() < t_start: return False
                if t_end and dt.time() > t_end: return False
            if self.last_run is None: return True
            return (now - self.last_run) >= self.interval
        return False

    def to_dict(self):
        return {
            "id": self.id, "label": self.label,
            "content_type": self.content_type, "content": self.content,
            "mode": self.mode, "duration": self.duration,
            "interval": self.interval,
            "start_time": self.start_time.isoformat() if hasattr(self.start_time, "isoformat") else self.start_time,
            "end_time": self.end_time,
            "days": self.days, "priority": self.priority,
            "options": self.options, "enabled": self.enabled,
            "last_run": self.last_run,
        }

    @classmethod
    def from_dict(cls, d):
        item = cls()
        for k, v in d.items():
            if hasattr(item, k): setattr(item, k, v)
        if isinstance(item.start_time, str):
            try: item.start_time = datetime.fromisoformat(item.start_time)
            except: pass
        return item


class Scheduler:
    def __init__(self, execute_fn):
        self._execute = execute_fn
        self.items    = []
        self.running  = False
        self._thread  = None

    def add(self, item: ScheduleItem):
        self.items.append(item)
        self.items.sort(key=lambda x: -x.priority)
        return item

    def remove(self, item_id: str):
        self.items = [i for i in self.items if i.id != item_id]

    def update(self, item_id: str, data: dict):
        for item in self.items:
            if item.id == item_id:
                for k, v in data.items():
                    if hasattr(item, k): setattr(item, k, v)
                return item
        return None

    def start(self):
        if self.running: return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Scheduler started")

    def stop(self):
        self.running = False
        log.info("Scheduler stopped")

    def _loop(self):
        while self.running:
            now = time.time()
            for item in list(self.items):
                if item.is_due(now):
                    item.last_run = now
                    try:
                        self._execute(item)
                    except Exception as e:
                        log.error(f"Scheduler execute error: {e}")
            time.sleep(1.0)

    def get_status(self):
        return {
            "running": self.running,
            "items":   [i.to_dict() for i in self.items],
        }

    def to_list(self):
        return [i.to_dict() for i in self.items]

    def from_list(self, data: list):
        self.items = [ScheduleItem.from_dict(d) for d in data]
