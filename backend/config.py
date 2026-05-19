"""
config.py — Configuration management
All config lives in ~/.flipdot/ and is never inside the git repo.
git pull / git reset --hard can never destroy settings.
"""
import os
import json
import logging

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser("~/.flipdot")

DEFAULT_LAYOUT = [
    [0,  2,  4],
    [1,  3,  5],
    [6,  8,  10],
    [7,  9,  11],
    [12, 14, 16],
    [13, 15, 17],
]

DEFAULTS = {
    "config": {
        "port":      "/dev/cu.usbserial-BG01DCHX",
        "baud_rate": 57600,
    },
    "variables": {
        "weather_api_key": "",
        "weather_city":    "San Francisco",
        "weather_units":   "imperial",
        "rss_url":         "https://feeds.bbci.co.uk/news/rss.xml",
        "rss_max_items":   10,
        "update_interval": 300,
    },
}


def _ensure():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def _path(name):
    return os.path.join(CONFIG_DIR, f"{name}.json")


def load(name):
    """Load config, returning defaults if missing or corrupt."""
    _ensure()
    if name == "layout":
        p = _path("layout")
        if os.path.isfile(p):
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Layout load error: {e} — using default")
        # Also check old project location for migration
        old = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "layout.json")
        if os.path.isfile(old):
            try:
                with open(old) as f:
                    layout = json.load(f)
                save("layout", layout)
                log.info(f"Migrated layout from {old}")
                return layout
            except Exception:
                pass
        return list(DEFAULT_LAYOUT)

    default = dict(DEFAULTS.get(name, {}))
    p = _path(name)
    if os.path.isfile(p):
        try:
            with open(p) as f:
                data = json.load(f)
            default.update(data)
            return default
        except Exception as e:
            log.warning(f"Config load error ({name}): {e} — using defaults")
    return default


def save(name, data):
    """Save config atomically — write .tmp then rename."""
    _ensure()
    p     = _path(name)
    p_tmp = p + ".tmp"
    try:
        with open(p_tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(p_tmp, p)
        return True
    except Exception as e:
        log.error(f"Config save error ({name}): {e}")
        if os.path.isfile(p_tmp):
            os.remove(p_tmp)
        return False


def get(name, key, default=None):
    return load(name).get(key, default)


def set_value(name, key, value):
    data = load(name)
    data[key] = value
    return save(name, data)
