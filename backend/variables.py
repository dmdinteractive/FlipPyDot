"""
variables.py
------------
Live variable system for text substitution.

Supported tokens:
  {time}        — current time HH:MM:SS
  {time12}      — current time 12h format
  {date}        — current date e.g. MON 19 MAY
  {date_long}   — full date e.g. Monday May 19 2026
  {temp}        — temperature from weather API (°F or °C)
  {temp_c}      — temperature in Celsius
  {temp_f}      — temperature in Fahrenheit
  {conditions}  — weather conditions e.g. CLEAR
  {humidity}    — humidity %
  {rss}         — latest RSS headline (cycles through items)
  {rss_N}       — Nth RSS item (0-indexed)

Usage in text:
  "TEMP: {temp}°  |  {time}"
  "TODAY IS {date_long}"
  "LATEST: {rss}"
"""

import threading
import logging
import time
import re
from datetime import datetime

log = logging.getLogger(__name__)

# ── Config (updated via API) ──────────────────────────────────────
_config = {
    "weather_api_key":  "",           # OpenWeatherMap free API key
    "weather_city":     "San Francisco",
    "weather_units":    "imperial",   # 'imperial' (°F) or 'metric' (°C)
    "rss_url":          "https://feeds.bbci.co.uk/news/rss.xml",
    "rss_max_items":    10,
    "update_interval":  300,          # seconds between weather/RSS fetches
}

# ── State ─────────────────────────────────────────────────────────
_weather = {
    "temp": None, "temp_c": None, "temp_f": None,
    "conditions": "—", "humidity": None,
    "last_update": None, "error": None,
}
_rss_items    = []
_rss_index    = 0
_running      = False
_thread       = None
_lock         = threading.Lock()


# ── Public API ────────────────────────────────────────────────────

def configure(cfg: dict):
    """Update variable system config."""
    _config.update(cfg)
    log.info(f"Variables config updated: {list(cfg.keys())}")

def get_config() -> dict:
    return dict(_config)

def get_all_values() -> dict:
    """Return current values of all variables."""
    now = datetime.now()
    with _lock:
        w    = dict(_weather)
        rss  = list(_rss_items)
        ridx = _rss_index

    temp_unit = "°F" if _config["weather_units"] == "imperial" else "°C"
    temp_val  = w["temp_f"] if _config["weather_units"] == "imperial" else w["temp_c"]

    values = {
        "time":        now.strftime("%H:%M:%S"),
        "time12":      now.strftime("%I:%M %p").lstrip("0"),
        "date":        now.strftime("%a %d %b").upper(),
        "date_long":   now.strftime("%A %B %d %Y"),
        "day":         now.strftime("%A").upper(),
        "month":       now.strftime("%B").upper(),
        "year":        now.strftime("%Y"),
        "temp":        f"{temp_val}{temp_unit}" if temp_val is not None else "—",
        "temp_c":      f"{w['temp_c']}°C" if w["temp_c"] is not None else "—",
        "temp_f":      f"{w['temp_f']}°F" if w["temp_f"] is not None else "—",
        "conditions":  w["conditions"],
        "humidity":    f"{w['humidity']}%" if w["humidity"] is not None else "—",
        "rss":         rss[ridx % len(rss)] if rss else "—",
    }

    # Individual RSS items
    for i, item in enumerate(rss[:_config["rss_max_items"]]):
        values[f"rss_{i}"] = item

    return values

def substitute(text: str) -> str:
    """Replace all {token} in text with live values."""
    if "{" not in text:
        return text
    values = get_all_values()
    def replacer(m):
        key = m.group(1)
        return str(values.get(key, m.group(0)))
    return re.sub(r"\{(\w+)\}", replacer, text)

def advance_rss():
    """Advance to the next RSS headline."""
    global _rss_index
    with _lock:
        if _rss_items:
            _rss_index = (_rss_index + 1) % len(_rss_items)

def start():
    global _running, _thread
    if _running: return
    _running = True
    _thread  = threading.Thread(target=_update_loop, daemon=True)
    _thread.start()
    log.info("Variable system started")

def stop():
    global _running
    _running = False

def get_status() -> dict:
    return {
        "config":   _config,
        "weather":  _weather,
        "rss_count":len(_rss_items),
        "rss_index":_rss_index,
        "running":  _running,
        "values":   get_all_values(),
    }


# ── Background updater ────────────────────────────────────────────

def _update_loop():
    _fetch_all()
    while _running:
        time.sleep(_config["update_interval"])
        _fetch_all()

def _fetch_all():
    _fetch_weather()
    _fetch_rss()

def _fetch_weather():
    global _weather
    key  = _config.get("weather_api_key", "").strip()
    city = _config.get("weather_city", "").strip()
    if not key or not city:
        return

    try:
        import urllib.request, json
        units = _config.get("weather_units", "imperial")
        url   = (f"https://api.openweathermap.org/data/2.5/weather"
                 f"?q={city}&appid={key}&units=metric")
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read())

        temp_c = round(d["main"]["temp"], 1)
        temp_f = round(temp_c * 9/5 + 32, 1)

        with _lock:
            _weather.update({
                "temp":        temp_f if units == "imperial" else temp_c,
                "temp_c":      temp_c,
                "temp_f":      temp_f,
                "conditions":  d["weather"][0]["main"].upper(),
                "humidity":    d["main"]["humidity"],
                "last_update": datetime.now().isoformat(),
                "error":       None,
            })
        log.info(f"Weather updated: {temp_f}°F {_weather['conditions']}")

    except Exception as e:
        with _lock:
            _weather["error"] = str(e)
        log.warning(f"Weather fetch failed: {e}")

def _fetch_rss():
    global _rss_items
    url = _config.get("rss_url", "").strip()
    if not url: return

    try:
        import urllib.request
        import xml.etree.ElementTree as ET

        with urllib.request.urlopen(url, timeout=10) as r:
            tree = ET.fromstring(r.read())

        items = []
        ns = {"media": "http://search.yahoo.com/mrss/"}
        for item in tree.findall(".//item"):
            title = item.findtext("title", "").strip()
            if title:
                items.append(title)
            if len(items) >= _config["rss_max_items"]:
                break

        with _lock:
            _rss_items = items

        log.info(f"RSS updated: {len(items)} items from {url}")

    except Exception as e:
        log.warning(f"RSS fetch failed: {e}")
