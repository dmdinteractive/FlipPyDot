"""
show.py — Show file save/load.

A show is the whole sequencer state: the playlist, the overlays, and the
variable config needed to make {tokens} resolve the same way on another
machine. Written atomically (.tmp then rename) so a crash mid-save can't
leave a half-written show behind.

V7 shows (a flat `schedule:` list of cron items) are migrated on load — each
old item becomes either a playlist step or an overlay depending on whether it
was a plain repeat or a real time trigger.
"""

import os
import yaml
import logging
from datetime import datetime

log = logging.getLogger(__name__)

SHOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "shows")
VERSION   = 8


def _ensure():
    os.makedirs(SHOWS_DIR, exist_ok=True)


def _path(name):
    safe = os.path.basename(str(name)).replace("..", "").strip() or "untitled"
    return os.path.join(SHOWS_DIR, f"{safe}.yaml")


def save_show(name, sequencer, config=None, var_config=None):
    _ensure()
    data = {
        "meta": {
            "name":    name,
            "version": VERSION,
            "saved":   datetime.now().isoformat(),
        },
        "config":    config or {},
        "variables": var_config or {},
        "sequencer": sequencer.to_dict() if sequencer else {},
    }
    path     = _path(name)
    path_tmp = path + ".tmp"
    with open(path_tmp, "w") as f:
        yaml.dump(data, f, default_flow_style=False,
                  sort_keys=False, allow_unicode=True)
    os.replace(path_tmp, path)
    log.info(f"Show saved: {path}")
    return path


def load_show(name, sequencer):
    path = _path(name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Show not found: {name}")
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    seq = data.get("sequencer")
    if seq is None and "schedule" in data:
        seq = migrate_v7(data["schedule"])
        log.info(f"Migrated V7 show '{name}': {len(seq['steps'])} steps, "
                 f"{len(seq['overlays'])} overlays")

    if sequencer and seq:
        sequencer.load(seq)

    log.info(f"Show loaded: {path}")
    return data


def migrate_v7(items):
    """Old flat cron list -> playlist + overlays.

    A V7 'repeat' item was almost always just "put this in the rotation", so it
    becomes a playlist step. Genuine time triggers (once/weekly) become
    overlays, which is what they always meant.
    """
    steps, overlays = [], []

    for it in items or []:
        ct = it.get("content_type", "text")
        c  = it.get("content", {}) or {}

        if ct == "text":
            content = {
                "kind":   "text",
                "text":   c.get("text", ""),
                "font":   "px5x7",
                "size":   int(c.get("font_size", 14) or 14),
                "align":  "center",
                "valign": "middle",
                "motion": "scroll_left" if c.get("scroll") else "static",
                "speed":  30,
            }
        elif ct == "animation":
            content = {
                "kind":      "animation",
                "animation": c.get("animation_id", "flash"),
                "params":    c.get("params", {}) or {},
            }
        elif ct in ("clear", "fill"):
            content = {"kind": ct}
        else:
            continue

        common = {
            "label":    it.get("label", ""),
            "content":  content,
            "duration": float(it.get("duration", 8) or 8),
            "enabled":  it.get("enabled", True),
        }
        mode = it.get("mode", "repeat")

        if mode == "weekly":
            overlays.append({
                **common,
                "priority": int(it.get("priority", 0) or 0),
                "trigger": {
                    "type": "weekly",
                    "at":   str(it.get("start_time") or "09:00")[:5],
                    "days": it.get("days") or [],
                },
            })
        elif mode == "once":
            overlays.append({
                **common,
                "priority": int(it.get("priority", 0) or 0),
                "trigger": {"type": "once", "at": it.get("start_time")},
            })
        else:
            steps.append(common)

    return {"steps": steps, "overlays": overlays, "loop": True, "running": False}


def list_shows():
    _ensure()
    shows = []
    for fname in sorted(os.listdir(SHOWS_DIR)):
        if not fname.endswith(".yaml"):
            continue
        path = os.path.join(SHOWS_DIR, fname)
        try:
            with open(path) as f:
                d = yaml.safe_load(f) or {}
            meta = d.get("meta", {})
            seq  = d.get("sequencer", {}) or {}
            shows.append({
                "name":     meta.get("name", fname[:-5]),
                "saved":    meta.get("saved", ""),
                "version":  meta.get("version", 7),
                "steps":    len(seq.get("steps", d.get("schedule", []) or [])),
                "overlays": len(seq.get("overlays", [])),
            })
        except Exception:
            shows.append({"name": fname[:-5], "saved": "", "version": 0,
                          "steps": 0, "overlays": 0})
    return shows


def delete_show(name):
    path = _path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
