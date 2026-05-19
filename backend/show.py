"""
show.py
-------
Show file management — save and load complete show state to/from YAML.

A show file contains:
  - metadata (name, created, modified)
  - device config (layout, port, baud)
  - cue list
  - scheduler entries
  - content presets
"""

import os
import yaml
import logging
from datetime import datetime

log = logging.getLogger(__name__)

SHOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "shows")


def ensure_shows_dir():
    os.makedirs(SHOWS_DIR, exist_ok=True)


def save_show(name: str, cue_engine, scheduler, config: dict) -> str:
    ensure_shows_dir()
    data = {
        "meta": {
            "name":     name,
            "version":  5,
            "saved":    datetime.now().isoformat(),
        },
        "config":    config,
        "cues":      cue_engine.to_list(),
        "schedule":  [i.to_dict() for i in scheduler.items],
    }
    path = os.path.join(SHOWS_DIR, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True)
    log.info(f"Show saved: {path}")
    return path


def load_show(name: str, cue_engine, scheduler) -> dict:
    path = os.path.join(SHOWS_DIR, f"{name}.yaml")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Show not found: {name}")
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    cue_engine.from_list(data.get("cues", []))
    scheduler.from_list(data.get("schedule", []))
    log.info(f"Show loaded: {path}")
    return data


def list_shows() -> list:
    ensure_shows_dir()
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
                    "cues":  len(d.get("cues", [])),
                })
            except Exception:
                shows.append({"name": fname[:-5], "saved": "", "cues": 0})
    return shows


def delete_show(name: str) -> bool:
    path = os.path.join(SHOWS_DIR, f"{name}.yaml")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
