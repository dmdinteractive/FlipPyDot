"""
sms.py — Visitors text a phone number; their message appears on the panel.

Uses a Twilio phone number. Two ways for messages to reach this Mac mini:

  POLL (default)  Every few seconds we ask Twilio's API "any new messages to
                  my number?". Nothing on the museum network has to be opened
                  up — the Mac only makes outbound HTTPS requests, exactly
                  like the weather source does.

  WEBHOOK         Twilio POSTs each message to /api/sms/twilio the instant it
                  arrives. Faster, but the Mac must be reachable from the
                  internet (port forward or a tunnel). Every request is
                  checked against Twilio's signature so nobody else can post
                  to the panel.

Messages are shown exactly as sent. The only changes are the ones the panel
physically needs: accents are folded to plain letters, characters the dot
fonts can't draw (emoji) are dropped, { } become ( ) so text can't trigger
{tokens}, and very long messages are trimmed to the configured length.

Senders' phone numbers are kept in memory only long enough to send the
optional auto-reply; the log and UI only ever show the last four digits.
"""

import re
import ssl
import json
import time
import hmac
import base64
import hashlib
import logging
import threading
import unicodedata
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

log = logging.getLogger(__name__)

API = "https://api.twilio.com/2010-04-01"

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()

DEFAULTS = {
    "enabled":      False,
    "mode":         "poll",          # poll | webhook
    "account_sid":  "",
    "auth_token":   "",
    "number":       "",              # the Twilio number, e.g. +17205550123
    "public_url":   "",              # webhook mode: URL Twilio posts to
    "poll_seconds": 5,
    "when":         "interrupt",     # interrupt | between (wait for step end)
    "seconds":      8,               # minimum on-screen time per message
    "max_length":   160,
    "header":       "NEW TEXT!",     # shown briefly before each message; "" = off
    "reply":        "",              # auto-reply text; "" = don't reply
    "style": {                       # how messages look — set from the Create tab
        "kind": "text", "text": "{message}", "font": "px5x7",
        "align": "center", "valign": "middle",
        "intro": "flap", "idle": "", "outro": "dissolve", "fx_speed": 1.0,
    },
}

PRINTABLE = re.compile(r"[^ -~]")


def clean(text, max_len=160):
    """Make a message drawable. Never changes what it says."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = (t.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("—", "-").replace("–", "-").replace("…", "..."))
    t = PRINTABLE.sub("", t.replace("\n", " ").replace("\t", " "))
    t = t.replace("{", "(").replace("}", ")")
    t = re.sub(r" {2,}", " ", t).strip()
    if max_len and len(t) > int(max_len):
        t = t[:int(max_len) - 1].rstrip() + "~"
    return t


def mask(number):
    d = re.sub(r"\D", "", str(number or ""))
    return ("…" + d[-4:]) if len(d) >= 4 else "…"


def fit(message, style, w, h):
    """Turn a message into a text spec that fits the panel.

    Tries big type first and works down, word-wrapping as it goes; anything
    too long for even the smallest font scrolls instead. The style's
    intro/idle/outro/background are kept whatever size wins.
    """
    import fonts as font_mod
    from renderer import wrap_text

    base = {k: v for k, v in (style or {}).items()}
    base["kind"] = "text"
    tries = [("px5x7", 21, 1), ("px5x7", 14, 1), ("px5x7", 7, 1), ("px3x5", 5, 1)]
    want = base.get("font")
    if want and want not in ("px5x7", "px3x5"):
        tries = [(want, s, 1) for s in (28, 21, 16, 12, 10, 8)] + tries[-2:]

    for font, size, lead in tries:
        face = font_mod.get(font)
        wrapped = wrap_text(face, message, size, 1, w)
        bmp = face.render(wrapped, size, tracking=1, leading=lead)
        if bmp.shape[1] <= w and bmp.shape[0] <= h:
            spec = dict(base, text=wrapped, font=font, size=size, leading=lead,
                        tracking=1, motion="static")
            n = len(message)
            read = max(float(base.get("_seconds", 0) or 0), 3.0 + n * 0.12)
            # The intro and outro eat into on-screen time; give it back.
            extra = (1.0 + n * 0.03) if base.get("intro") else 0.0
            extra += 1.5 if base.get("outro") else 0.0
            return spec, read + extra

    spec = dict(base, text=message, font="px5x7", size=14, motion="scroll_left",
                speed=40, gap=w, intro="", outro="", idle="")
    px = len(message) * 12 + w
    return spec, px / 40.0 + 1.0


class SMSInbox:
    def __init__(self, cfg_load, cfg_save):
        self._load, self._save = cfg_load, cfg_save
        self.cfg = dict(DEFAULTS)
        self.cfg.update(cfg_load() or {})
        self.queue = deque(maxlen=200)
        self.log = deque(maxlen=100)
        self._seen = deque(maxlen=500)
        self._since = None
        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self.status = {"ok": None, "error": None, "last_poll": None}
        self.showing = None
        self.skip_event = threading.Event()

    # ── config ────────────────────────────────────────────────────
    def public_config(self):
        c = dict(self.cfg)
        if c.get("auth_token"):
            c["auth_token"] = "••••" + c["auth_token"][-4:]
        return c

    def update(self, d):
        d = dict(d or {})
        if str(d.get("auth_token", "")).startswith("••••"):
            d.pop("auth_token")                 # unchanged masked value
        style = d.pop("style", None)
        for k, lo, hi in (("poll_seconds", 2, 300), ("seconds", 1, 120), ("max_length", 10, 1000)):
            if k in d:
                try:
                    d[k] = min(hi, max(lo, float(d[k])))
                except (TypeError, ValueError):
                    d.pop(k)
        if "max_length" in d:
            d["max_length"] = int(d["max_length"])
        if "mode" in d and d["mode"] not in ("poll", "webhook"):
            d.pop("mode")
        if "when" in d and d["when"] not in ("interrupt", "between"):
            d.pop("when")
        if style is not None and not isinstance(style, dict):
            style = None
        self.cfg.update({k: v for k, v in d.items() if k in DEFAULTS})
        if style:
            self.cfg["style"] = style
        self._save(self.cfg)
        self._since = None                      # re-baseline on reconnect
        return self.public_config()

    # ── lifecycle ─────────────────────────────────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sms")
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                self._poll_once()
            except Exception as e:                 # never let polling die
                log.error(f"SMS loop error: {e}", exc_info=True)
            try:
                wait = max(2.0, float(self.cfg.get("poll_seconds", 5) or 5))
            except (TypeError, ValueError):
                wait = 5.0
            time.sleep(wait)

    def _poll_once(self):
        c = self.cfg
        if c.get("enabled") and c.get("mode") == "poll" and c.get("account_sid") \
                and c.get("auth_token") and c.get("number"):
            try:
                self._poll()
                self.status.update(ok=True, error=None,
                                   last_poll=datetime.now().isoformat(timespec="seconds"))
            except Exception as e:
                self.status.update(ok=False, error=str(e))
                log.warning(f"SMS poll failed: {e}")

    # ── Twilio ────────────────────────────────────────────────────
    def _auth(self):
        tok = f"{self.cfg['account_sid']}:{self.cfg['auth_token']}".encode()
        return "Basic " + base64.b64encode(tok).decode()

    def _api(self, path, data=None):
        url = f"{API}/Accounts/{self.cfg['account_sid']}/{path}"
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers={"Authorization": self._auth()})
        with urllib.request.urlopen(req, timeout=12, context=_SSL) as r:
            return json.loads(r.read().decode())

    def _poll(self):
        q = urllib.parse.urlencode({"To": self.cfg["number"], "PageSize": 20})
        d = self._api(f"Messages.json?{q}")
        msgs = [m for m in d.get("messages", []) if m.get("direction") == "inbound"]
        if self._since is None:
            # First poll after start/config: everything already there is
            # history. Mark it seen so a restart doesn't replay old texts.
            self._since = datetime.now(timezone.utc)
            for m in msgs:
                self._seen.append(m.get("sid"))
            return
        for m in reversed(msgs):                 # oldest first
            if m.get("sid") in self._seen:
                continue
            self._seen.append(m.get("sid"))
            try:
                sent = parsedate_to_datetime(m.get("date_sent") or m.get("date_created"))
                if sent < self._since:
                    continue
            except Exception:
                pass
            self.receive(m.get("from"), m.get("body"), sid=m.get("sid"))

    def verify_webhook(self, url, params, signature):
        """Twilio request signing: HMAC-SHA1 over URL + sorted POST params."""
        tok = self.cfg.get("auth_token") or ""
        if not tok or not signature:
            return False
        s = (self.cfg.get("public_url") or url) + "".join(
            k + v for k, v in sorted(params.items()))
        mac = base64.b64encode(hmac.new(tok.encode(), s.encode(), hashlib.sha1).digest()).decode()
        return hmac.compare_digest(mac, signature)

    def reply(self, to):
        text = (self.cfg.get("reply") or "").strip()
        if not text or not to:
            return
        n = len(self.queue)
        text = text.replace("{position}", str(max(1, n)))
        try:
            self._api("Messages.json", {"From": self.cfg["number"], "To": to, "Body": text})
        except Exception as e:
            log.warning(f"SMS auto-reply failed: {e}")

    # ── inbox ─────────────────────────────────────────────────────
    def receive(self, sender, body, sid=None, test=False):
        text = clean(body, self.cfg.get("max_length", 160))
        entry = {
            "id":   sid or f"local-{int(time.time() * 1000)}",
            "from": "test" if test else mask(sender),
            "text": text,
            "raw_len": len(str(body or "")),
            "at":   datetime.now().isoformat(timespec="seconds"),
            "state": "queued" if text else "empty",
        }
        with self._lock:
            self.log.appendleft(entry)
            if text:
                self.queue.append(entry)
        log.info(f"SMS from {entry['from']}: {text!r}")
        if text and not test and sender:
            threading.Thread(target=self.reply, args=(sender,), daemon=True).start()
        return entry

    def pending(self):
        return bool(self.queue) and self.cfg.get("enabled")

    def next_specs(self, w, h):
        """Pop the next message as [(spec, seconds), ...] to play in order."""
        with self._lock:
            if not self.queue:
                return None
            entry = self.queue.popleft()
        entry["state"] = "shown"
        self.showing = entry
        style = dict(self.cfg.get("style") or DEFAULTS["style"])
        style["_seconds"] = float(self.cfg.get("seconds", 8) or 8)
        try:
            spec, secs = fit(entry["text"], style, w, h)
        except Exception as e:
            # A broken saved style must not lose the message: show it plain.
            log.error(f"SMS style failed ({e}); showing message unstyled")
            spec, secs = fit(entry["text"], {}, w, h)
        spec.pop("_seconds", None)
        spec["label"] = "SMS " + entry["from"]
        out = []
        header = (self.cfg.get("header") or "").strip()
        if header:
            card, _ = fit(clean(header, 40), {"intro": "flap", "align": "center",
                                              "valign": "middle"}, w, h)
            card["label"] = "SMS header"
            out.append((card, 2.0))
        out.append((spec, secs))
        return out

    def get_status(self):
        return {
            "enabled": bool(self.cfg.get("enabled")),
            "mode":    self.cfg.get("mode"),
            "queued":  len(self.queue),
            "showing": self.showing,
            "log":     list(self.log)[:50],
            **self.status,
        }
