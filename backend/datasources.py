"""
datasources.py — Pluggable live data sources.

Each source fetches on its own schedule and returns a flat dict of values.
Those get namespaced by the source's `name` and become {tokens} you can drop
into any text: a source named "quake" of type usgs_quakes exposes {quake_mag},
{quake_place}, {quake_count}, and so on.

List-shaped sources (quakes, volcanoes, RSS) expose three things at once:
    {quake_place}     the item currently in rotation
    {quake_0_place}   a specific item by index
    {quake_count}     how many there are
The rotation advances on a timer, so a single zone on the panel can cycle
through the last ten earthquakes without you building ten zones.

Values are kept RAW (floats stay floats, times stay datetimes) and are only
stringified at the end of substitution — that's what lets |round:1 and
|fmt:%H:%M actually work instead of doing string surgery.

Adding a source type = write a fetch function + one REGISTRY entry.
"""

import ssl
import json
import time
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

log = logging.getLogger(__name__)

USER_AGENT = "FlipPyDot/8 (flipdot display controller)"

# macOS ships a Python whose urllib has no CA bundle wired up, so every HTTPS
# fetch dies with CERTIFICATE_VERIFY_FAILED unless you run
# "Install Certificates.command". Lean on certifi when it's there so the box
# just works; fall back to the system default otherwise.
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()


class FetchError(Exception):
    pass


def _get(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        ctx = _SSL if url.lower().startswith("https") else None
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read()
    except Exception as e:
        raise FetchError(str(e))


def _get_json(url, headers=None, timeout=12):
    try:
        return json.loads(_get(url, headers, timeout))
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"Bad JSON: {e}")


def dig(obj, path):
    """Pull a value out of nested JSON with a dotted path: a.b[0].c"""
    cur = obj
    for part in str(path).replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _ms_to_dt(ms):
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0)
    except (TypeError, ValueError):
        return None


# ── USGS earthquakes ──────────────────────────────────────────────
QUAKE_FEEDS = {
    "significant_week": "Significant — past week",
    "4.5_day":          "M4.5+ — past day",
    "2.5_day":          "M2.5+ — past day",
    "1.0_day":          "M1.0+ — past day",
    "all_hour":         "All — past hour",
    "all_day":          "All — past day",
}


def fetch_usgs_quakes(cfg):
    feed = cfg.get("feed", "2.5_day")
    if feed not in QUAKE_FEEDS:
        feed = "2.5_day"
    url = (f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/"
           f"{feed}.geojson")
    d = _get_json(url)

    min_mag = float(cfg.get("min_mag", 0) or 0)
    items = []
    for f in d.get("features", []):
        p = f.get("properties", {}) or {}
        mag = p.get("mag")
        if mag is None or float(mag) < min_mag:
            continue
        coords = (f.get("geometry", {}) or {}).get("coordinates", [None, None, None])
        when = _ms_to_dt(p.get("time"))
        items.append({
            "mag":   round(float(mag), 1),
            "place": p.get("place") or "",
            "title": p.get("title") or "",
            "depth": round(float(coords[2]), 1) if len(coords) > 2 and coords[2] is not None else None,
            "lat":   round(float(coords[1]), 2) if len(coords) > 1 and coords[1] is not None else None,
            "lon":   round(float(coords[0]), 2) if coords and coords[0] is not None else None,
            "time":  when,
            "ago":   _ago(when),
        })

    items.sort(key=lambda i: i["time"] or datetime.min, reverse=True)
    biggest = max(items, key=lambda i: i["mag"]) if items else None
    return {
        "_items":   items,
        "count":    len(items),
        "max_mag":  biggest["mag"] if biggest else None,
        "max_place": biggest["place"] if biggest else None,
    }


# ── USGS volcanoes ────────────────────────────────────────────────
def fetch_usgs_volcanoes(cfg):
    """Volcanoes currently at an elevated alert level (USGS HANS)."""
    d = _get_json("https://volcanoes.usgs.gov/hans-public/api/volcano/"
                  "getElevatedVolcanoes")
    rows = d if isinstance(d, list) else d.get("features", [])

    order = {"RED": 4, "ORANGE": 3, "YELLOW": 2, "GREEN": 1, "UNASSIGNED": 0}
    items = []
    for v in rows:
        items.append({
            "name":     v.get("volcano_name") or "",
            "color":    (v.get("color_code") or "").upper(),
            "alert":    (v.get("alert_level") or "").upper(),
            "obs":      (v.get("obs_abbr") or "").upper(),
            "sent":     v.get("sent_utc") or "",
        })
    items.sort(key=lambda i: order.get(i["color"], 0), reverse=True)

    top = items[0] if items else None
    return {
        "_items":    items,
        "count":     len(items),
        "top_name":  top["name"] if top else None,
        "top_alert": top["alert"] if top else None,
        "top_color": top["color"] if top else None,
    }


# ── ISS ───────────────────────────────────────────────────────────
def fetch_iss(cfg):
    """Where the ISS is right now. wheretheiss.at is HTTPS and reliable."""
    d = _get_json("https://api.wheretheiss.at/v1/satellites/25544")
    lat = float(d.get("latitude", 0))
    lon = float(d.get("longitude", 0))
    units = cfg.get("units", "metric")

    alt_km = float(d.get("altitude", 0))
    vel_kmh = float(d.get("velocity", 0))
    if units == "imperial":
        alt, vel, au, vu = alt_km * 0.621371, vel_kmh * 0.621371, "mi", "mph"
    else:
        alt, vel, au, vu = alt_km, vel_kmh, "km", "km/h"

    return {
        "lat":        round(lat, 2),
        "lon":        round(lon, 2),
        # A compass-style position reads far better on a 84x42 panel than a
        # raw signed float does.
        "position":   f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'} "
                      f"{abs(lon):.1f}{'E' if lon >= 0 else 'W'}",
        "altitude":   round(alt),
        "alt_units":  au,
        "velocity":   round(vel),
        "vel_units":  vu,
        "visibility": (d.get("visibility") or "").upper(),
    }


def fetch_iss_crew(cfg):
    """Who is in space right now (open-notify). HTTP only, and sometimes down."""
    d = _get_json("http://api.open-notify.org/astros.json")
    people = d.get("people", []) or []
    craft = cfg.get("craft", "").strip()
    if craft:
        people = [p for p in people if (p.get("craft") or "").lower() == craft.lower()]

    items = [{"name": p.get("name", ""), "craft": p.get("craft", "")} for p in people]
    return {
        "_items": items,
        "count":  len(items),
        "names":  ", ".join(i["name"] for i in items),
        "crafts": ", ".join(sorted({i["craft"] for i in items if i["craft"]})),
    }


# ── ZenQuotes ─────────────────────────────────────────────────────
def fetch_zenquotes(cfg):
    mode = cfg.get("mode", "today")        # today | random
    url = ("https://zenquotes.io/api/random" if mode == "random"
           else "https://zenquotes.io/api/today")
    d = _get_json(url)
    if not isinstance(d, list) or not d:
        raise FetchError("Empty response")
    q = d[0]
    text = (q.get("q") or "").strip()
    if q.get("a") == "zenquotes.io":
        raise FetchError("Rate limited by zenquotes.io")
    return {
        "text":   text,
        "author": (q.get("a") or "").strip(),
        "full":   f"{text} — {q.get('a', '').strip()}" if text else "",
    }


# ── Weather (OpenWeatherMap) ──────────────────────────────────────
def fetch_weather(cfg):
    key  = (cfg.get("api_key") or "").strip()
    city = (cfg.get("city") or "").strip()
    if not key or not city:
        raise FetchError("Needs an API key and a city")

    units = cfg.get("units", "imperial")
    url = ("https://api.openweathermap.org/data/2.5/weather?"
           + urllib.parse.urlencode({"q": city, "appid": key, "units": "metric"}))
    d = _get_json(url)

    def c2f(c):
        return round(c * 9 / 5 + 32, 1)

    main = d.get("main", {})
    temp_c = round(float(main.get("temp", 0)), 1)
    feels_c = round(float(main.get("feels_like", temp_c)), 1)
    hi_c = round(float(main.get("temp_max", temp_c)), 1)
    lo_c = round(float(main.get("temp_min", temp_c)), 1)
    imperial = units == "imperial"

    wind_ms = float((d.get("wind") or {}).get("speed", 0))
    sys = d.get("sys", {})

    return {
        "temp":       c2f(temp_c) if imperial else temp_c,
        "feels":      c2f(feels_c) if imperial else feels_c,
        "hi":         c2f(hi_c) if imperial else hi_c,
        "lo":         c2f(lo_c) if imperial else lo_c,
        "temp_c":     temp_c,
        "temp_f":     c2f(temp_c),
        "units":      "F" if imperial else "C",
        "conditions": (d.get("weather", [{}])[0].get("main") or "").upper(),
        "describe":   (d.get("weather", [{}])[0].get("description") or "").upper(),
        "humidity":   main.get("humidity"),
        "pressure":   main.get("pressure"),
        "wind":       round(wind_ms * 2.23694) if imperial else round(wind_ms),
        "wind_units": "mph" if imperial else "m/s",
        "city":       d.get("name") or city,
        "sunrise":    datetime.fromtimestamp(sys["sunrise"]) if sys.get("sunrise") else None,
        "sunset":     datetime.fromtimestamp(sys["sunset"]) if sys.get("sunset") else None,
    }


# ── RSS ───────────────────────────────────────────────────────────
def fetch_rss(cfg):
    url = (cfg.get("url") or "").strip()
    if not url:
        raise FetchError("Needs a feed URL")
    root = ET.fromstring(_get(url))

    items = []
    limit = int(cfg.get("max_items", 10) or 10)
    for it in root.findall(".//item")[:limit]:
        title = (it.findtext("title") or "").strip()
        if title:
            items.append({"title": title,
                          "link": (it.findtext("link") or "").strip(),
                          "desc": (it.findtext("description") or "").strip()})
    if not items:                       # Atom
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for it in root.findall(".//a:entry", ns)[:limit]:
            title = (it.findtext("a:title", "", ns) or "").strip()
            if title:
                items.append({"title": title, "link": "", "desc": ""})

    return {"_items": items, "count": len(items)}


# ── Generic JSON ──────────────────────────────────────────────────
def fetch_json(cfg):
    """Any REST API. You supply the URL and a field->path map.

    This is the escape hatch: anything I didn't build a source type for, you
    can still wire up without touching Python.
    """
    url = (cfg.get("url") or "").strip()
    if not url:
        raise FetchError("Needs a URL")
    d = _get_json(url, cfg.get("headers") or {})

    fields = cfg.get("fields") or {}
    if not fields:
        raise FetchError("Needs at least one field mapping")

    out = {}
    for name, path in fields.items():
        out[str(name)] = dig(d, path)
    return out


# ── Countdown / custom (no network) ───────────────────────────────
def fetch_countdown(cfg):
    target = cfg.get("target")
    if not target:
        raise FetchError("Needs a target date")
    try:
        t = datetime.fromisoformat(str(target))
    except ValueError:
        raise FetchError(f"Bad date: {target}")

    delta = t - datetime.now()
    secs  = int(delta.total_seconds())
    past  = secs < 0
    secs  = abs(secs)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, s = divmod(rem, 60)

    return {
        "days":    days,
        "hours":   hours,
        "minutes": mins,
        "hms":     f"{hours:02d}:{mins:02d}:{s:02d}",
        "dhms":    f"{days}d {hours:02d}:{mins:02d}:{s:02d}",
        "total_h": days * 24 + hours,
        "past":    past,
        "target":  t,
    }


def fetch_custom(cfg):
    """Your own static key/values — {venue}, {tagline}, whatever."""
    return dict(cfg.get("values") or {})


# ── Registry ──────────────────────────────────────────────────────
# `tokens` drives the UI: it's how the editor knows to offer you {quake_mag}.
# `live` marks sources computed locally each tick (no fetch, no interval).
REGISTRY = {
    "usgs_quakes": {
        "label": "USGS Earthquakes",
        "fetch": fetch_usgs_quakes,
        "interval": 300,
        "list": True,
        "help": "Live earthquake feed from the USGS. Rotates through recent quakes.",
        "config": [
            {"id": "feed", "label": "Feed", "type": "select", "default": "2.5_day",
             "options": [{"value": k, "label": v} for k, v in QUAKE_FEEDS.items()]},
            {"id": "min_mag", "label": "Minimum magnitude", "type": "number", "default": 0},
        ],
        "tokens": [
            ("mag", "Magnitude of the quake in rotation"),
            ("place", "Location, e.g. '4 km S of Guánica, Puerto Rico'"),
            ("title", "Full title, e.g. 'M 2.7 - 4 km S of ...'"),
            ("depth", "Depth in km"),
            ("lat", "Latitude"), ("lon", "Longitude"),
            ("ago", "How long ago, e.g. '12 min ago'"),
            ("count", "Number of quakes in the feed"),
            ("max_mag", "Largest magnitude in the feed"),
            ("max_place", "Where the largest one was"),
        ],
    },
    "usgs_volcanoes": {
        "label": "USGS Volcano Alerts",
        "fetch": fetch_usgs_volcanoes,
        "interval": 900,
        "list": True,
        "help": "US volcanoes currently at an elevated alert level.",
        "config": [],
        "tokens": [
            ("name", "Volcano in rotation"),
            ("alert", "Alert level: NORMAL / ADVISORY / WATCH / WARNING"),
            ("color", "Aviation colour code: GREEN / YELLOW / ORANGE / RED"),
            ("obs", "Observatory, e.g. AVO"),
            ("count", "How many are elevated"),
            ("top_name", "Highest-alert volcano"),
            ("top_alert", "Its alert level"),
            ("top_color", "Its colour code"),
        ],
    },
    "iss": {
        "label": "ISS Position",
        "fetch": fetch_iss,
        "interval": 15,
        "help": "Where the International Space Station is right now.",
        "config": [
            {"id": "units", "label": "Units", "type": "select", "default": "metric",
             "options": [{"value": "metric", "label": "Metric (km)"},
                         {"value": "imperial", "label": "Imperial (mi)"}]},
        ],
        "tokens": [
            ("position", "Compass position, e.g. '23.7N 91.6W'"),
            ("lat", "Latitude"), ("lon", "Longitude"),
            ("altitude", "Altitude"), ("alt_units", "km or mi"),
            ("velocity", "Speed"), ("vel_units", "km/h or mph"),
            ("visibility", "DAYLIGHT or ECLIPSED"),
        ],
    },
    "iss_crew": {
        "label": "People in Space",
        "fetch": fetch_iss_crew,
        "interval": 3600,
        "list": True,
        "help": "Who is currently in orbit (open-notify.org).",
        "config": [
            {"id": "craft", "label": "Only this craft (blank = all)",
             "type": "text", "default": ""},
        ],
        "tokens": [
            ("name", "Astronaut in rotation"),
            ("craft", "Their spacecraft"),
            ("count", "How many people are in space"),
            ("names", "All names, comma separated"),
        ],
    },
    "zenquotes": {
        "label": "Zen Quotes",
        "fetch": fetch_zenquotes,
        "interval": 3600,
        "help": "An inspirational quote. 'Today' changes daily; 'random' each fetch.",
        "config": [
            {"id": "mode", "label": "Mode", "type": "select", "default": "today",
             "options": [{"value": "today", "label": "Quote of the day"},
                         {"value": "random", "label": "Random each refresh"}]},
        ],
        "tokens": [
            ("text", "The quote"),
            ("author", "Who said it"),
            ("full", "Quote — Author"),
        ],
    },
    "weather": {
        "label": "Weather (OpenWeatherMap)",
        "fetch": fetch_weather,
        "interval": 600,
        "help": "Needs a free API key from openweathermap.org.",
        "config": [
            {"id": "api_key", "label": "API key", "type": "text", "default": ""},
            {"id": "city", "label": "City", "type": "text", "default": "San Francisco"},
            {"id": "units", "label": "Units", "type": "select", "default": "imperial",
             "options": [{"value": "imperial", "label": "Fahrenheit"},
                         {"value": "metric", "label": "Celsius"}]},
        ],
        "tokens": [
            ("temp", "Temperature"), ("units", "F or C"),
            ("feels", "Feels like"), ("hi", "High"), ("lo", "Low"),
            ("conditions", "CLEAR / RAIN / SNOW"), ("describe", "Longer description"),
            ("humidity", "Humidity %"), ("wind", "Wind speed"),
            ("wind_units", "mph or m/s"), ("city", "City name"),
            ("sunrise", "Sunrise time"), ("sunset", "Sunset time"),
        ],
    },
    "rss": {
        "label": "RSS Feed",
        "fetch": fetch_rss,
        "interval": 600,
        "list": True,
        "help": "Any RSS or Atom feed. Rotates through the headlines.",
        "config": [
            {"id": "url", "label": "Feed URL", "type": "text",
             "default": "https://feeds.bbci.co.uk/news/rss.xml"},
            {"id": "max_items", "label": "Max items", "type": "number", "default": 10},
        ],
        "tokens": [
            ("title", "Headline in rotation"),
            ("desc", "Its description"),
            ("count", "Number of headlines"),
        ],
    },
    "json": {
        "label": "Custom JSON API",
        "fetch": fetch_json,
        "interval": 300,
        "help": ("Any REST API. Map a field name to a dotted path into the "
                 "response — e.g. price → bpi.USD.rate — and it becomes a token."),
        "config": [
            {"id": "url", "label": "URL", "type": "text", "default": ""},
            {"id": "headers", "label": "Headers (JSON object)", "type": "json", "default": {}},
            {"id": "fields", "label": "Fields (name → path)", "type": "fields", "default": {}},
        ],
        "tokens": [],          # discovered from the user's own field map
    },
    "countdown": {
        "label": "Countdown",
        "fetch": fetch_countdown,
        "interval": 1,
        "live": True,
        "help": "Counts down to a date. Recomputed every second, so it ticks.",
        "config": [
            {"id": "target", "label": "Target date & time", "type": "datetime", "default": ""},
        ],
        "tokens": [
            ("days", "Whole days remaining"), ("hours", "Hours part"),
            ("minutes", "Minutes part"), ("hms", "HH:MM:SS"),
            ("dhms", "1d 02:03:04"), ("total_h", "Total hours"),
            ("past", "True once the date has passed"),
        ],
    },
    "custom": {
        "label": "Custom Values",
        "fetch": fetch_custom,
        "interval": 3600,
        "live": True,
        "bare": True,          # tokens are used as-is: {venue}, not {mine_venue}
        "help": "Your own fixed key/value pairs.",
        "config": [
            {"id": "values", "label": "Values (name → text)", "type": "fields", "default": {}},
        ],
        "tokens": [],
    },
}


def _ago(dt):
    if not dt:
        return ""
    secs = (datetime.now() - dt).total_seconds()
    if secs < 0:
        return "just now"
    if secs < 90:
        return f"{int(secs)} sec ago"
    if secs < 5400:
        return f"{int(secs // 60)} min ago"
    if secs < 172800:
        return f"{int(secs // 3600)} hr ago"
    return f"{int(secs // 86400)} days ago"


def fetch(source):
    """Run one source. Returns (values, error)."""
    spec = REGISTRY.get(source.get("type"))
    if not spec:
        return {}, f"Unknown source type: {source.get('type')}"
    try:
        return spec["fetch"](source.get("config") or {}), None
    except FetchError as e:
        return {}, str(e)
    except Exception as e:
        log.warning(f"Source {source.get('name')} failed: {e}")
        return {}, str(e)


def describe():
    """Registry for the UI — what types exist and what each one offers."""
    return [{
        "type":     k,
        "label":    v["label"],
        "help":     v.get("help", ""),
        "interval": v.get("interval", 300),
        "list":     v.get("list", False),
        "live":     v.get("live", False),
        "config":   v.get("config", []),
        "tokens":   [{"suffix": s, "help": h} for s, h in v.get("tokens", [])],
    } for k, v in REGISTRY.items()]
