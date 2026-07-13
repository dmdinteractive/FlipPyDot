"""
variables.py — Tokens, filters, and the background updater.

Any text anywhere in the app can contain {tokens}, which are replaced with
live values at render time (not at edit time) — that's why a clock on a
"static" screen still ticks.

    {time}                      13:45:02
    {date}                      MON 13 JUL
    {quake_place}               4 km S of Guánica, Puerto Rico
    {iss_position}              23.7N 91.6W

Filters do the formatting, so you can shape a value to fit an 84-dot-wide
panel without editing the data:

    {quake_place|upper|trunc:24} 4 KM S OF GUÁNICA, PUER…
    {temp|round:0}°{weather_units}   72°F
    {quake_mag|pad:4}            2.7
    {now|fmt:%H:%M}              13:45
    {cal_next|default:NOTHING ON}

Values are stored RAW (floats stay floats, datetimes stay datetimes) and are
only turned into strings after the filters run — otherwise |round and |fmt
would be doing string surgery on already-formatted text.
"""

import re
import time
import logging
import threading
from datetime import datetime

import datasources as ds

log = logging.getLogger(__name__)

# ── Config / state ────────────────────────────────────────────────
_config = {
    "sources": [],          # [{id, type, name, enabled, interval, rotate_every, config}]
}

_values  = {}               # token -> raw value
_status  = {}               # source id -> {ok, error, last_update, count}
_rot     = {}               # source id -> rotation index
_owned   = {}               # source id -> set of token names it produced
_lock    = threading.RLock()
_running = False
_thread  = None
_last_fetch = {}            # source id -> monotonic timestamp


# ── Public API ────────────────────────────────────────────────────
def configure(cfg):
    """Replace the source config. Sources are re-fetched on the next tick."""
    with _lock:
        _config["sources"] = cfg.get("sources", []) or []
        # Drop state for sources that no longer exist.
        live = {s.get("id") for s in _config["sources"]}
        for d in (_status, _rot, _last_fetch):
            for k in list(d):
                if k not in live:
                    d.pop(k, None)
        for k in list(_owned):
            if k not in live:
                for tok in _owned.pop(k, ()):
                    _values.pop(tok, None)
    refresh_now()
    log.info(f"Configured {len(_config['sources'])} data source(s)")


def get_config():
    with _lock:
        return {"sources": list(_config["sources"])}


def get_status():
    with _lock:
        return {
            "config":  {"sources": list(_config["sources"])},
            "sources": dict(_status),
            "running": _running,
            "values":  {k: _stringify(v) for k, v in get_all_values().items()},
        }


def refresh_now():
    """Force every source to re-fetch on the next tick."""
    with _lock:
        _last_fetch.clear()


# ── Built-in time tokens ──────────────────────────────────────────
def _builtin():
    now = datetime.now()
    return {
        "now":       now,
        "time":      now.strftime("%H:%M:%S"),
        "time_hm":   now.strftime("%H:%M"),
        "time12":    now.strftime("%I:%M %p").lstrip("0"),
        "hour":      now.strftime("%H"),
        "minute":    now.strftime("%M"),
        "second":    now.strftime("%S"),
        "date":      now.strftime("%a %d %b").upper(),
        "date_num":  now.strftime("%d/%m/%Y"),
        "date_long": now.strftime("%A %B %d %Y").upper(),
        "day":       now.strftime("%A").upper(),
        "day_short": now.strftime("%a").upper(),
        "month":     now.strftime("%B").upper(),
        "year":      now.strftime("%Y"),
    }


def get_all_values():
    """Every token -> raw value. Built-ins are recomputed on every call, which
    is what makes a clock zone tick without anything re-fetching."""
    out = _builtin()
    with _lock:
        out.update(_values)
    return out


# ── Substitution ──────────────────────────────────────────────────
# {token} or {token|filter|filter:arg}
_TOKEN_RE = re.compile(r"\{([a-zA-Z_][\w]*)((?:\|[a-z_]+(?::[^}|]*)?)*)\}")


def substitute(text):
    text = str(text)
    if "{" not in text:
        return text
    values = get_all_values()

    def repl(m):
        key, filt = m.group(1), m.group(2) or ""
        if key in values:
            val = values[key]
        elif "|default:" in filt:
            # Supplying a default is exactly how you say "this token might not
            # resolve", so honour it rather than printing the raw {token}.
            val = None
        else:
            return m.group(0)          # leave unknown tokens visible, not blank
        for f in filt.split("|"):
            if not f:
                continue
            name, _, arg = f.partition(":")
            val = _apply_filter(val, name, arg)
        return _stringify(val)

    return _TOKEN_RE.sub(repl, text)


def _stringify(v):
    if v is None:
        return "—"
    if isinstance(v, datetime):
        return v.strftime("%H:%M")
    if isinstance(v, bool):
        return "YES" if v else "NO"
    if isinstance(v, float):
        # Trim a pointless trailing .0 — "72" beats "72.0" when every dot counts.
        return str(int(v)) if v == int(v) else str(v)
    return str(v)


def _apply_filter(val, name, arg):
    try:
        if name == "upper":
            return _stringify(val).upper()
        if name == "lower":
            return _stringify(val).lower()
        if name == "title":
            return _stringify(val).title()
        if name == "trunc":
            n = int(arg or 20)
            s = _stringify(val)
            return s if len(s) <= n else s[:max(0, n - 1)].rstrip() + "…"
        if name == "round":
            n = int(arg or 0)
            f = round(float(val), n)
            return int(f) if n <= 0 else f
        if name == "int":
            return int(float(val))
        if name == "abs":
            return abs(float(val))
        if name == "pad":                       # right-pad to width
            return _stringify(val).ljust(int(arg or 0))
        if name == "padl":                      # left-pad (right-align numbers)
            return _stringify(val).rjust(int(arg or 0))
        if name == "fmt":
            if isinstance(val, datetime):
                return val.strftime(arg or "%H:%M")
            return _stringify(val)
        if name == "default":
            s = _stringify(val)
            return arg if (val is None or s in ("", "—")) else val
        if name == "strip":
            return _stringify(val).strip()
    except (ValueError, TypeError):
        return val
    return val


# ── Rotation ──────────────────────────────────────────────────────
def _rotate_items(src, data):
    """List sources expose the item currently in rotation, plus every item by
    index. Rotation is time-based so a single zone cycles on its own."""
    sid   = src.get("id")
    name  = src.get("name") or sid
    items = data.get("_items") or []
    out   = {}

    if not items:
        return out

    every = float(src.get("rotate_every", 10) or 10)
    idx   = int(time.time() / every) % len(items) if every > 0 else 0
    _rot[sid] = idx

    for k, v in items[idx].items():             # current item -> {quake_place}
        out[f"{name}_{k}"] = v
    for i, item in enumerate(items):            # by index -> {quake_0_place}
        for k, v in item.items():
            out[f"{name}_{i}_{k}"] = v
    out[f"{name}_index"] = idx + 1
    return out


# ── Updater ───────────────────────────────────────────────────────
def _tick():
    now = time.monotonic()
    with _lock:
        sources = list(_config["sources"])

    for src in sources:
        sid = src.get("id")
        if not sid or not src.get("enabled", True):
            continue

        spec     = ds.REGISTRY.get(src.get("type"), {})
        # "live" sources (countdown, custom) are cheap and local — recompute
        # every tick so a countdown actually counts down.
        interval = 0 if spec.get("live") else float(
            src.get("interval") or spec.get("interval", 300))

        last = _last_fetch.get(sid)
        if last is not None and (now - last) < interval:
            continue

        data, err = ds.fetch(src)
        _last_fetch[sid] = now

        name = src.get("name") or sid
        with _lock:
            # Clear the tokens this source produced last time, so a failed
            # fetch can't leave stale values on the wall pretending to be
            # current. Track ownership explicitly — a "bare" source's tokens
            # aren't name-prefixed, so we can't infer them from the name.
            for k in _owned.pop(sid, ()):
                _values.pop(k, None)

            if err:
                _status[sid] = {"ok": False, "error": err,
                                "last_update": datetime.now().isoformat(),
                                "count": 0}
                continue

            # Custom values are already named by the user, so they are used
            # bare — {venue}, not {myvalues_venue}.
            bare = spec.get("bare", False)

            flat = {}
            for k, v in data.items():
                if k == "_items":
                    continue
                flat[k if bare else f"{name}_{k}"] = v
            if not bare:
                flat.update(_rotate_items(src, data))
            _values.update(flat)
            _owned[sid] = set(flat)

            _status[sid] = {
                "ok": True, "error": None,
                "last_update": datetime.now().isoformat(),
                "count": len(data.get("_items") or []) or 1,
                "tokens": sorted(flat.keys()),
            }


def _loop():
    while _running:
        try:
            _tick()
        except Exception as e:
            log.error(f"Variable updater error: {e}", exc_info=True)
        time.sleep(1.0)


def start():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="variables")
    _thread.start()
    log.info("Variable system started")


def stop():
    global _running
    _running = False


# ── Token discovery (for the editor's chip list) ──────────────────
def list_tokens():
    """Every token that currently resolves, grouped for the UI."""
    groups = [{
        "group":  "Time & date",
        "source": None,
        "tokens": [{"token": k, "value": _stringify(v)}
                   for k, v in sorted(_builtin().items())],
    }]

    with _lock:
        sources = list(_config["sources"])
        vals    = dict(_values)

    for src in sources:
        sid  = src.get("id")
        name = src.get("name") or sid
        spec = ds.REGISTRY.get(src.get("type"), {})
        owned = _owned.get(sid, set())
        # Only the un-indexed tokens go in the chip list — {quake_0_place} etc.
        # are real and usable, just too numerous to show as buttons.
        toks = []
        for k in sorted(owned):
            if k not in vals:
                continue
            if re.match(rf"^{re.escape(name)}_\d+_", k):
                continue
            toks.append({"token": k, "value": _stringify(vals[k])})
        groups.append({
            "group":  f"{spec.get('label', src.get('type'))} — {name}",
            "source": sid,
            "ok":     _status.get(sid, {}).get("ok"),
            "error":  _status.get(sid, {}).get("error"),
            "tokens": toks,
        })

    return groups
