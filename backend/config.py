"""
config.py
---------
Configuration management. All config lives in ~/.flipdot/ and is
never inside the git repository. This means git pull / git reset
can never destroy settings.

Files:
    ~/.flipdot/config.json    — serial port, baud rate
    ~/.flipdot/layout.json    — panel layout mapping
    ~/.flipdot/variables.json — weather API key, RSS URL, city
"""

import os
import json
import logging

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser("~/.flipdot")

DEFAULTS = {
    "config": {
        "port":      "/dev/cu.usbserial-BG01DCHX",
        "baud_rate": 57600,
    },
    "layout": [
        [0,  2,  4],
        [1,  3,  5],
        [6,  8,  10],
        [7,  9,  11],
        [12, 14, 16],
        [13, 15, 17],
    ],
    "variables": {
        "weather_api_key":  "",
        "weather_city":     "San Francisco",
        "weather_units":    "imperial",
        "rss_url":          "https://feeds.bbci.co.uk/news/rss.xml",
        "rss_max_items":    10,
        "update_interval":  300,
    },
}


def _ensure_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def _path(name):
    return os.path.join(CONFIG_DIR, f"{name}.json")


def load(name):
    """Load a config file, returning defaults if missing or corrupt."""
    _ensure_dir()
    p = _path(name)
    if os.path.isfile(p):
        try:
            with open(p) as f:
                data = json.load(f)
            # Merge with defaults so new keys always exist
            merged = dict(DEFAULTS.get(name, {}))
            merged.update(data)
            return merged
        except Exception as e:
            log.warning(f"Config load error ({name}): {e} — using defaults")
    return dict(DEFAULTS.get(name, {}))


def save(name, data):
    """Save config atomically — write to .tmp then rename."""
    _ensure_dir()
    p     = _path(name)
    p_tmp = p + ".tmp"
    try:
        with open(p_tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(p_tmp, p)
        log.debug(f"Config saved: {name}")
        return True
    except Exception as e:
        log.error(f"Config save error ({name}): {e}")
        if os.path.isfile(p_tmp):
            os.remove(p_tmp)
        return False


def get(name, key, default=None):
    """Get a single value from a config file."""
    return load(name).get(key, default)


def set_value(name, key, value):
    """Set a single value in a config file."""
    data = load(name)
    data[key] = value
    return save(name, data)


def setup_interactive():
    """
    Interactive first-run setup. Walks the operator through
    the minimum required config. Safe to run multiple times —
    existing values are shown as defaults.
    """
    print("\n── FLIPDOT SETUP ──────────────────────────────")
    print(f"Config directory: {CONFIG_DIR}\n")

    cfg = load("config")

    port = input(f"Serial port [{cfg['port']}]: ").strip()
    if port:
        cfg["port"] = port

    baud = input(f"Baud rate [{cfg['baud_rate']}]: ").strip()
    if baud:
        try:
            cfg["baud_rate"] = int(baud)
        except ValueError:
            pass

    save("config", cfg)

    varcfg = load("variables")
    print("\nWeather (optional — press Enter to skip)")
    api_key = input(f"OpenWeatherMap API key [{varcfg['weather_api_key'][:8] or 'none'}...]: ").strip()
    if api_key:
        varcfg["weather_api_key"] = api_key

    city = input(f"City [{varcfg['weather_city']}]: ").strip()
    if city:
        varcfg["weather_city"] = city

    rss = input(f"RSS URL [{varcfg['rss_url']}]: ").strip()
    if rss:
        varcfg["rss_url"] = rss

    save("variables", varcfg)

    print("\n✓ Config saved to ~/.flipdot/")
    print("─────────────────────────────────────────────\n")


def summary():
    """Return a human-readable summary of current config."""
    cfg    = load("config")
    varcfg = load("variables")
    lines  = [
        f"Port:     {cfg['port']}",
        f"Baud:     {cfg['baud_rate']}",
        f"City:     {varcfg['weather_city']}",
        f"Weather:  {'configured' if varcfg['weather_api_key'] else 'not configured'}",
        f"RSS:      {varcfg['rss_url'][:50]}",
    ]
    return "\n".join(lines)
