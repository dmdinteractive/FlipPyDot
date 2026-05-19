"""
show.py — Show file save/load.
Saves scheduler state to YAML. Atomic write — crash safe.
"""
import os
import yaml
import logging
from datetime import datetime

log = logging.getLogger(__name__)

SHOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "shows")


def _ensure():
    os.makedirs(SHOWS_DIR, exist_ok=True)


def save_show(name, cue_engine, scheduler, config):
    _ensure()
    data = {
        "meta": {
            "name":    name,
            "version": 7,
            "saved":   datetime.now().isoformat(),
        },
        "config":   config,
        "schedule": [i.to_dict() for i in scheduler.items] if scheduler else [],
    }
    path     = os.path.join(SHOWS_DIR, f"{name}.yaml")
    path_tmp = path + ".tmp"
    with open(path_tmp, "w") as f:
        yaml.dump(data, f, default_flow_style=False,
                  sort_keys=False, allow_unicode=True)
    os.replace(path_tmp, path)
    log.info(f"Show saved: {path}")
    return path


def load_show(name, cue_engine, scheduler):
    path = os.path.join(SHOWS_DIR, f"{name}.yaml")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Show not found: {name}")
    with open(path) as f:
        data = yaml.safe_load(f)
    if scheduler:
        from scheduler import ScheduleItem
        scheduler.items = [
            ScheduleItem.from_dict(d) for d in data.get("schedule", [])]
    log.info(f"Show loaded: {path}")
    return data


def list_shows():
    _ensure()
    shows = []
    for fname in sorted(os.listdir(SHOWS_DIR)):
        if fname.endswith(".yaml"):
            path = os.path.join(SHOWS_DIR, fname)
            try:
                with open(path) as f:
                    d = yaml.safe_load(f)
                shows.append({
                    "name":  d.get("meta", {}).get("name", fname[:-5]),
                    "saved": d.get("meta", {}).get("saved", ""),
                })
            except Exception:
                shows.append({"name": fname[:-5], "saved": ""})
    return shows


def delete_show(name):
    path = os.path.join(SHOWS_DIR, f"{name}.yaml")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
