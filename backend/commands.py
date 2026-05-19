"""
commands.py
-----------
Command parser. Takes a text line and dispatches to the engine.

This is shared by:
  - The interactive CLI prompt
  - The script engine
  - The daemon Unix socket listener

Every command returns (success: bool, message: str).

Command syntax is intentionally minimal:
  verb [arg] [key=value ...]

Examples:
  text Hello world
  text Hello size=21
  scroll "Today is {date}" size=14
  anim rain speed=0.05
  go 3
  sched add label="Time" type=text content="{time}" interval=60
"""

import os
import sys
import logging
import shlex

log = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_kwargs(tokens):
    """
    Split a token list into positional args and key=value kwargs.
    Returns (positional_str, kwargs_dict)
    """
    positional = []
    kwargs     = {}
    for token in tokens:
        if "=" in token and not token.startswith("="):
            k, _, v = token.partition("=")
            # Try to coerce numeric values
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    if v.lower() == "true":
                        v = True
                    elif v.lower() == "false":
                        v = False
            kwargs[k] = v
        else:
            positional.append(token)
    return " ".join(positional).strip(), kwargs


class CommandHandler:
    def __init__(self, engine):
        self.engine = engine
        self.e      = engine  # shorthand

    def handle(self, line):
        """
        Parse and execute one command line.
        Returns (success, message).
        """
        line = line.strip()
        if not line or line.startswith("#"):
            return True, ""

        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = line.split()

        if not tokens:
            return True, ""

        verb = tokens[0].lower()
        args = tokens[1:]

        # Route to handler
        handlers = {
            "text":     self._text,
            "scroll":   self._scroll,
            "fill":     self._fill,
            "clear":    self._clear,
            "image":    self._image,
            "gif":      self._gif,
            "anim":     self._anim,
            "go":       self._go,
            "back":     self._back,
            "hold":     self._hold,
            "release":  self._release,
            "cue":      self._cue,
            "sched":    self._sched,
            "playlist": self._playlist,
            "pl":       self._playlist,
            "fx":       self._fx,
            "vars":     self._vars,
            "assets":   self._assets,
            "show":     self._show,
            "script":   self._script,
            "connect":  self._connect,
            "disconnect":self._disconnect,
            "ports":    self._ports,
            "status":   self._status,
            "log":      self._log_cmd,
            "test":     self._test,
            "preview":  self._preview,
            "pixel":    self._pixel,
            "update":   self._update,
            "help":     self._help,
            "?":        self._help,
        }

        handler = handlers.get(verb)
        if handler is None:
            return False, f"Unknown command: {verb}  (type 'help' for list)"

        try:
            return handler(args)
        except Exception as e:
            log.error(f"Command error [{verb}]: {e}", exc_info=True)
            return False, f"Error: {e}"

    # ── Display ───────────────────────────────────────────────────

    def _text(self, args):
        if not args:
            return False, "Usage: text <message> [size=14] [x=0] [y=0]"
        text, kw = parse_kwargs(args)
        fname = str(kw.get("font", "default"))
        fsize = int(kw.get("size", kw.get("font_size", 14)))
        x     = int(kw.get("x", 0))
        y     = int(kw.get("y", 0))
        self.e.cmd_text(text, fname, fsize, x, y)
        return True, f"Text: {text!r}"

    def _scroll(self, args):
        if not args:
            return False, "Usage: scroll <message> [size=14]"
        text, kw = parse_kwargs(args)
        fname = str(kw.get("font", "default"))
        fsize = int(kw.get("size", kw.get("font_size", 14)))
        self.e.cmd_scroll(text, fname, fsize)
        return True, f"Scrolling: {text!r}"

    def _fill(self, args):
        self.e.stop_anim()
        self.e.display.fill()
        return True, "Display filled"

    def _clear(self, args):
        self.e.stop_anim()
        self.e.display.clear()
        return True, "Display cleared"

    def _image(self, args):
        if not args:
            return False, "Usage: image <path> [threshold=128] [dither=none|floyd|bayer] [scale=fit|fill|stretch] [invert=false]"
        path, kw = parse_kwargs(args)
        if not os.path.isabs(path):
            path = os.path.join(BASE, path)
        return self.e.cmd_image(
            path,
            threshold  = int(kw.get("threshold", 128)),
            brightness = float(kw.get("brightness", 1.0)),
            contrast   = float(kw.get("contrast", 1.0)),
            dither     = str(kw.get("dither", "none")),
            scale      = str(kw.get("scale", "fit")),
            invert     = bool(kw.get("invert", False)),
            loop       = int(kw.get("loop", 1)),
        )

    def _gif(self, args):
        if not args:
            return False, "Usage: gif <path> [loop=0]"
        path, kw = parse_kwargs(args)
        if not os.path.isabs(path):
            path = os.path.join(BASE, path)
        return self.e.cmd_image(path, loop=int(kw.get("loop", 0)))

    # ── Animations ────────────────────────────────────────────────

    def _anim(self, args):
        if not args:
            anims = self.e.list_anims()
            names = [a["id"] for a in anims]
            return True, "Animations: " + "  ".join(names)
        sub = args[0].lower()
        if sub == "list":
            anims = self.e.list_anims()
            lines = []
            for a in anims:
                params = ", ".join(f"{p['id']}={p['default']}"
                                   for p in a.get("params", []))
                lines.append(f"  {a['id']:<20} {a['name']:<24} {params}")
            return True, "Available animations:\n" + "\n".join(lines)
        if sub == "stop":
            self.e.stop_anim()
            return True, "Animation stopped"
        # Run animation
        name = sub
        _, kw = parse_kwargs(args[1:])
        return self.e.cmd_anim(name, **kw)

    # ── Transport ─────────────────────────────────────────────────

    def _go(self, args):
        if args:
            self.e.cue_eng.jump(args[0])
            return True, f"Jumped to cue {args[0]}"
        self.e.cue_eng.go()
        return True, "GO"

    def _back(self, args):
        self.e.cue_eng.back()
        return True, "BACK"

    def _hold(self, args):
        self.e.cue_eng.hold()
        return True, "HOLD"

    def _release(self, args):
        self.e.cue_eng.release()
        return True, "RELEASE"

    # ── Cue engine ────────────────────────────────────────────────

    def _cue(self, args):
        if not args:
            return False, "Usage: cue list|add|edit|del|show|load|clear"
        sub = args[0].lower()

        if sub == "list":
            cues = self.e.cue_eng.cues
            if not cues:
                return True, "Cue list is empty"
            lines = [f"  {'CUE':<8} {'LABEL':<24} {'TYPE':<12} {'DUR':<8} AUTO"]
            lines.append("  " + "─" * 60)
            for c in cues:
                auto = "→" if c.auto_follow else " "
                dur  = "HOLD" if c.duration < 0 else f"{c.duration}s"
                lines.append(
                    f"  {c.number:<8} {c.label:<24} {c.content_type:<12} {dur:<8} {auto}")
            return True, "\n".join(lines)

        if sub == "add":
            _, kw = parse_kwargs(args[1:])
            ct    = str(kw.get("type", kw.get("content_type", "clear")))
            label = str(kw.get("label", f"Cue {len(self.e.cue_eng.cues)+1}"))
            num   = float(kw.get("num", kw.get("number",
                          round((max((c.number for c in self.e.cue_eng.cues), default=0)) + 1, 3))))
            content = {}
            if ct == "text":
                content = {"text": str(kw.get("content", kw.get("text", ""))),
                           "font_size": int(kw.get("size", 14)),
                           "scroll": bool(kw.get("scroll", False))}
            elif ct in ("scroll", "text_scroll"):
                ct      = "text"
                content = {"text": str(kw.get("content", kw.get("text", ""))),
                           "font_size": int(kw.get("size", 14)),
                           "scroll": True}
            elif ct == "anim":
                ct      = "animation"
                content = {"animation_id": str(kw.get("content", kw.get("anim", "flash")))}
            elif ct == "animation":
                content = {"animation_id": str(kw.get("content", kw.get("anim", "flash")))}

            cue = self.e.Cue(
                number       = num,
                label        = label,
                content_type = ct,
                content      = content,
                pre_wait     = float(kw.get("wait", kw.get("pre_wait", 0))),
                duration     = float(kw.get("dur", kw.get("duration", 5))),
                fade_in      = float(kw.get("fade", 0)),
                auto_follow  = bool(kw.get("auto", False)),
            )
            self.e.cue_eng.add_cue(cue)
            return True, f"Cue {num} added: {label}"

        if sub in ("del", "delete", "remove"):
            if len(args) < 2:
                return False, "Usage: cue del <number|id>"
            target = args[1]
            # Find by number or id
            before = len(self.e.cue_eng.cues)
            self.e.cue_eng.cues = [
                c for c in self.e.cue_eng.cues
                if str(c.number) != target and c.id != target
            ]
            after = len(self.e.cue_eng.cues)
            if before == after:
                return False, f"Cue not found: {target}"
            return True, f"Cue {target} deleted"

        if sub == "clear":
            self.e.cue_eng.cues = []
            self.e.cue_eng.release()
            return True, "Cue list cleared"

        if sub == "load":
            if len(args) < 2:
                return False, "Usage: cue load <showname>"
            try:
                self.e.show_mgr.load_show(args[1], self.e.cue_eng, self.e.scheduler)
                return True, f"Show loaded: {args[1]}"
            except FileNotFoundError:
                return False, f"Show not found: {args[1]}"

        if sub == "renumber":
            self.e.cue_eng.renumber()
            return True, "Cues renumbered"

        if sub == "show" and len(args) > 1:
            target = args[1]
            cue    = next((c for c in self.e.cue_eng.cues
                           if str(c.number) == target or c.id == target), None)
            if not cue:
                return False, f"Cue not found: {target}"
            d = cue.to_dict()
            lines = [f"  {k}: {v}" for k, v in d.items()]
            return True, "\n".join(lines)

        return False, f"Unknown cue sub-command: {sub}"

    # ── Scheduler ─────────────────────────────────────────────────

    def _sched(self, args):
        if not args:
            return False, "Usage: sched list|add|del|on|off|clear"
        sub = args[0].lower()

        if sub == "list":
            items = self.e.scheduler.items
            if not items:
                return True, "Scheduler is empty"
            lines = [f"  {'#':<4} {'LABEL':<20} {'MODE':<10} {'TYPE':<10} {'INTERVAL':<10} EN"]
            lines.append("  " + "─" * 58)
            for i, item in enumerate(items):
                en = "✓" if item.enabled else "✗"
                lines.append(
                    f"  {i:<4} {item.label:<20} {item.mode:<10} "
                    f"{item.content_type:<10} {item.interval:<10} {en}")
            return True, "\n".join(lines)

        if sub == "add":
            _, kw = parse_kwargs(args[1:])
            ct    = str(kw.get("type", "text"))
            raw   = str(kw.get("content", kw.get("text", "")))
            content = {}
            if ct == "text":
                content = {"text": raw, "font_size": int(kw.get("size", 14))}
            elif ct == "animation":
                content = {"animation_id": raw}
            item = self.e.ScheduleItem(
                label        = str(kw.get("label", raw[:20])),
                content_type = ct,
                content      = content,
                mode         = str(kw.get("mode", "repeat")),
                duration     = float(kw.get("dur", kw.get("duration", 5))),
                interval     = float(kw.get("interval", 60)),
                priority     = int(kw.get("priority", 0)),
            )
            self.e.scheduler.add(item)
            return True, f"Scheduled: {item.label} every {item.interval}s"

        if sub in ("del", "delete"):
            if len(args) < 2:
                return False, "Usage: sched del <number>"
            try:
                idx  = int(args[1])
                item = self.e.scheduler.items[idx]
                self.e.scheduler.remove(item.id)
                return True, f"Removed schedule item {idx}"
            except (IndexError, ValueError):
                return False, f"Item not found: {args[1]}"

        if sub in ("on", "start"):
            self.e.scheduler.start()
            return True, "Scheduler started"

        if sub in ("off", "stop"):
            self.e.scheduler.stop()
            return True, "Scheduler stopped"

        if sub == "clear":
            self.e.scheduler.items = []
            return True, "Scheduler cleared"

        return False, f"Unknown sched sub-command: {sub}"

    # ── Playlist ──────────────────────────────────────────────────

    def _playlist(self, args):
        if not args:
            return False, "Usage: playlist list|add|del|mode|start|stop|skip|clear"
        sub = args[0].lower()

        if sub == "list":
            pl = self.e.playlist
            items = pl.items
            if not items:
                return True, "Playlist is empty"
            status = f"Mode: {pl.mode}  Running: {pl.running}"
            lines  = [status, f"  {'#':<4} {'LABEL':<24} {'TYPE':<12} {'DUR':<6} WEIGHT"]
            lines.append("  " + "─" * 56)
            for i, item in enumerate(items):
                cur = "▶" if pl.current_item and pl.current_item.id == item.id else " "
                lines.append(
                    f"{cur} {i:<4} {item.label:<24} {item.content_type:<12} "
                    f"{item.duration:<6} {item.weight}  (played {item.play_count}x)")
            return True, "\n".join(lines)

        if sub == "add":
            _, kw = parse_kwargs(args[1:])
            ct    = str(kw.get("type", "text"))
            raw   = str(kw.get("content", kw.get("text", "")))
            label = str(kw.get("label", raw[:24]))
            content = {}
            if ct == "text":
                content = {"text": raw, "font_size": int(kw.get("size", 14)),
                           "scroll": bool(kw.get("scroll", False))}
            elif ct == "animation":
                content = {"animation_id": raw}
            item = self.e.PlaylistItem(
                content_type = ct,
                content      = content,
                label        = label,
                duration     = float(kw.get("dur", kw.get("duration", 5))),
                weight       = float(kw.get("weight", 1.0)),
            )
            self.e.playlist.add(item)
            return True, f"Added to playlist: {label}"

        if sub in ("del", "delete"):
            if len(args) < 2:
                return False, "Usage: playlist del <number>"
            try:
                idx  = int(args[1])
                item = self.e.playlist.items[idx]
                self.e.playlist.remove(item.id)
                return True, f"Removed playlist item {idx}"
            except (IndexError, ValueError):
                return False, f"Item not found: {args[1]}"

        if sub == "mode":
            if len(args) < 2:
                return False, "Usage: playlist mode sequential|shuffle|weighted"
            m = args[1].lower()
            if m not in ("sequential", "shuffle", "weighted"):
                return False, "Mode must be: sequential, shuffle, or weighted"
            self.e.playlist.mode = m
            return True, f"Playlist mode: {m}"

        if sub in ("start", "on"):
            if len(args) > 1:
                m = args[1].lower()
                self.e.playlist.mode = m
            self.e.playlist.start()
            return True, f"Playlist started ({self.e.playlist.mode})"

        if sub in ("stop", "off"):
            self.e.playlist.stop()
            return True, "Playlist stopped"

        if sub == "skip":
            self.e.playlist.skip()
            return True, "Skipped"

        if sub == "clear":
            self.e.playlist.stop()
            self.e.playlist.items = []
            return True, "Playlist cleared"

        if sub == "load":
            if len(args) < 2:
                return False, "Usage: playlist load <showname>"
            try:
                self.e.show_mgr.load_show(args[1], self.e.cue_eng, self.e.scheduler)
                return True, f"Loaded: {args[1]}"
            except FileNotFoundError:
                return False, f"Not found: {args[1]}"

        return False, f"Unknown playlist sub-command: {sub}"

    # ── Effects ───────────────────────────────────────────────────

    def _fx(self, args):
        if not args:
            return False, "Usage: fx list|add|del|clear"
        sub = args[0].lower()

        if sub == "list":
            reg    = self.e.EFFECTS_REG
            active = self.e.effects.active
            lines  = ["Available effects:"]
            for eid, info in reg.items():
                a = " [ACTIVE]" if eid in active else ""
                params = ", ".join(f"{p['id']}={p['default']}"
                                   for p in info.get("params", []))
                lines.append(f"  {eid:<12} {info['label']:<16} {params}{a}")
            return True, "\n".join(lines)

        if sub == "add":
            if len(args) < 2:
                return False, "Usage: fx add <type> [name=fx1] [param=value ...]"
            et   = args[1].lower()
            _, kw = parse_kwargs(args[2:])
            name  = str(kw.pop("name", et))
            self.e.effects.add(name, et, **kw)
            return True, f"Effect added: {name} [{et}]"

        if sub in ("del", "remove"):
            if len(args) < 2:
                return False, "Usage: fx del <name>"
            self.e.effects.remove(args[1])
            return True, f"Effect removed: {args[1]}"

        if sub == "clear":
            self.e.effects.clear()
            return True, "All effects cleared"

        return False, f"Unknown fx sub-command: {sub}"

    # ── Variables ─────────────────────────────────────────────────

    def _vars(self, args):
        if not args or args[0].lower() == "list":
            vals  = self.e.var_mod.get_all_values()
            lines = [f"  {'{'+k+'}':<20} {v}" for k, v in vals.items()
                     if not k.startswith("rss_")]
            return True, "Live variable values:\n" + "\n".join(lines)

        if args[0].lower() == "set" and len(args) >= 3:
            key = args[1]
            val = " ".join(args[2:])
            import backend.config as config
            varcfg = config.load("variables")
            varcfg[key] = val
            config.save("variables", varcfg)
            self.e.var_mod.configure(varcfg)
            return True, f"Variable config set: {key} = {val}"

        if args[0].lower() == "refresh":
            # Force immediate fetch in background
            import threading
            t = threading.Thread(
                target=self.e.var_mod._fetch_all, daemon=True)
            t.start()
            return True, "Fetching weather and RSS..."

        return False, "Usage: vars [list] | vars set <key> <value> | vars refresh"

    def _preview(self, args):
        if not args:
            return False, "Usage: preview <text with {tokens}>"
        text = " ".join(args)
        result = self.e.var_mod.substitute(text)
        return True, f"Input:  {text}\nOutput: {result}"

    # ── Assets ────────────────────────────────────────────────────

    def _assets(self, args):
        if not args or args[0].lower() == "list":
            assets = self.e.asset_lib.list_all()
            if not assets:
                return True, "No assets saved"
            lines = [f"  {'NAME':<24} {'TYPE':<16} TAGS"]
            lines.append("  " + "─" * 52)
            for a in assets:
                tags = ", ".join(a.get("tags", []))
                lines.append(f"  {a['name']:<24} {a['type']:<16} {tags}")
            return True, "\n".join(lines)

        if args[0].lower() == "save":
            name = " ".join(args[1:]) if len(args) > 1 else "unnamed"
            buf  = self.e.display.get_buffer()
            frames = [{"bitmap": buf.tolist(), "duration": 0}]
            self.e.asset_lib.create(name, "image", {"frames": frames}, ["display"])
            return True, f"Saved as asset: {name}"

        if args[0].lower() == "load":
            if len(args) < 2:
                return False, "Usage: assets load <name>"
            name   = " ".join(args[1:])
            assets = self.e.asset_lib.list_all()
            match  = next((a for a in assets
                           if a["name"].lower() == name.lower()), None)
            if not match:
                return False, f"Asset not found: {name}"
            a = self.e.asset_lib.get(match["id"])
            if a and a.get("type") == "image":
                frames_data = a.get("data", {}).get("frames", [])
                if frames_data:
                    import numpy as np
                    frames = [(np.array(f["bitmap"], dtype=np.uint8), 0)
                              for f in frames_data]
                    self.e.display.send(frames[0][0])
                    return True, f"Asset loaded: {name}"
            return False, f"Cannot load asset type: {a.get('type')}"

        if args[0].lower() in ("del", "delete"):
            name   = " ".join(args[1:])
            assets = self.e.asset_lib.list_all()
            match  = next((a for a in assets
                           if a["name"].lower() == name.lower()), None)
            if not match:
                return False, f"Asset not found: {name}"
            self.e.asset_lib.delete(match["id"])
            return True, f"Asset deleted: {name}"

        return False, "Usage: assets list|save|load|del"

    # ── Show files ────────────────────────────────────────────────

    def _show(self, args):
        if not args:
            return False, "Usage: show list|save|load|new"
        sub = args[0].lower()

        if sub == "list":
            shows = self.e.show_mgr.list_shows()
            if not shows:
                return True, "No saved shows"
            lines = [f"  {'NAME':<24} {'SAVED':<20} CUES"]
            lines.append("  " + "─" * 48)
            for s in shows:
                lines.append(
                    f"  {s['name']:<24} {s.get('saved','')[:19]:<20} {s.get('cues',0)}")
            return True, "\n".join(lines)

        if sub == "save":
            name = " ".join(args[1:]) if len(args) > 1 else "default"
            import backend.config as config
            cfg    = config.load("config")
            layout = config.load("layout")
            path   = self.e.show_mgr.save_show(
                name, self.e.cue_eng, self.e.scheduler,
                {"port": cfg["port"], "baud_rate": cfg["baud_rate"],
                 "layout": layout})
            return True, f"Show saved: {name}"

        if sub == "load":
            if len(args) < 2:
                return False, "Usage: show load <name>"
            name = " ".join(args[1:])
            try:
                self.e.show_mgr.load_show(name, self.e.cue_eng, self.e.scheduler)
                return True, f"Show loaded: {name}"
            except FileNotFoundError:
                return False, f"Show not found: {name}"

        if sub == "new":
            self.e.cue_eng.cues = []
            self.e.cue_eng.release()
            self.e.scheduler.items = []
            self.e.scheduler.stop()
            self.e.playlist.stop()
            self.e.playlist.items = []
            return True, "New show — all cues, schedule, playlist cleared"

        return False, f"Unknown show sub-command: {sub}"

    # ── Scripts ───────────────────────────────────────────────────

    def _script(self, args):
        if not args or args[0].lower() == "list":
            scripts = self.e.script_engine.list_scripts()
            if not scripts:
                return True, f"No scripts in {self.e.script_engine.list_scripts.__doc__ or 'scripts/'}"
            return True, "Scripts:\n" + "\n".join(f"  {s}" for s in scripts)

        if args[0].lower() in ("run", "play"):
            if len(args) < 2:
                return False, "Usage: script run <name>"
            return self.e.script_engine.run(" ".join(args[1:]))

        if args[0].lower() == "spawn":
            if len(args) < 2:
                return False, "Usage: script spawn <name>"
            return self.e.script_engine.run(" ".join(args[1:]))

        if args[0].lower() == "stop":
            self.e.script_engine.stop()
            return True, "Script stopped"

        if args[0].lower() == "status":
            return True, self.e.script_engine.status()

        return False, f"Unknown script sub-command: {args[0]}"

    # ── System ────────────────────────────────────────────────────

    def _connect(self, args):
        if args:
            self.e.display.set_port(args[0])
        # Force reconnection by marking disconnected
        self.e.display.connected = False
        return True, f"Connecting to {self.e.display.port}..."

    def _disconnect(self, args):
        self.e.display.stop()
        return True, "Disconnected"

    def _ports(self, args):
        try:
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            if not ports:
                return True, "No serial ports found"
            lines = [f"  {p.device:<30} {p.description}" for p in ports]
            return True, "Available ports:\n" + "\n".join(lines)
        except Exception as e:
            return False, str(e)

    def _status(self, args):
        st  = self.e.status_dict()
        eng = st["cue_engine"]
        cur = eng.get("current_cue")
        lines = [
            f"  Connection:  {'CONNECTED' if st['connected'] else 'OFFLINE'}  {st['port']}",
            f"  Display:     {st['dimensions']}",
            "  Cue engine:  " + eng["state"] + ("  [" + str(cur["number"]) + " " + cur["label"] + "]" if cur else ""),
            f"  Scheduler:   {'RUNNING' if st['scheduler']['running'] else 'OFF'}  ({st['scheduler']['items']} items)",
            f"  Playlist:    {'RUNNING ('+st['playlist']['mode']+')' if st['playlist']['running'] else 'OFF'}  ({st['playlist']['items']} items)",
            f"  Effects:     {', '.join(st['effects']) or 'none'}",
            f"  Variables:   time={st['variables'].get('time','?')}  temp={st['variables'].get('temp','?')}",
        ]
        return True, "\n".join(lines)

    def _log_cmd(self, args):
        log_path = os.path.join(BASE, "logs", "flipdot.log")
        if not os.path.isfile(log_path):
            return False, "Log file not found"
        try:
            n = int(args[0]) if args else 20
        except ValueError:
            n = 20
        with open(log_path) as f:
            lines = f.readlines()
        return True, "".join(lines[-n:]).rstrip()

    def _test(self, args):
        if not args:
            return False, "Usage: test fill|clear|flash|panel <n>"
        sub = args[0].lower()
        if sub == "fill":
            self.e.display.fill()
            return True, "Test: filled"
        if sub == "clear":
            self.e.display.clear()
            return True, "Test: cleared"
        if sub == "flash":
            import threading
            def _flash():
                for _ in range(3):
                    self.e.display.fill()
                    import time; time.sleep(0.5)
                    self.e.display.clear()
                    time.sleep(0.5)
            threading.Thread(target=_flash, daemon=True).start()
            return True, "Test: flashing 3 times"
        if sub == "panel" and len(args) > 1:
            return True, f"Panel test: {args[1]} (use panel wizard for hardware testing)"
        return False, f"Unknown test: {sub}"

    def _pixel(self, args):
        if not args:
            return False, "Usage: pixel load <file.txt> | pixel save <name>"
        sub = args[0].lower()
        if sub == "load" and len(args) > 1:
            path = args[1]
            if not os.path.isabs(path):
                path = os.path.join(BASE, path)
            try:
                import numpy as np
                with open(path) as f:
                    rows = []
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            rows.append([int(c) for c in line.split()])
                frame = np.array(rows, dtype=np.uint8)
                self.e.display.send(frame)
                return True, f"Pixel buffer loaded: {frame.shape[1]}x{frame.shape[0]}"
            except Exception as e:
                return False, f"Pixel load error: {e}"
        if sub == "save" and len(args) > 1:
            name = args[1]
            if not name.endswith(".txt"):
                name += ".txt"
            path = os.path.join(BASE, name)
            buf  = self.e.display.get_buffer()
            try:
                with open(path, "w") as f:
                    for row in buf:
                        f.write(" ".join(str(v) for v in row) + "\n")
                return True, f"Pixel buffer saved: {path}"
            except Exception as e:
                return False, f"Pixel save error: {e}"
        return False, "Usage: pixel load <file.txt> | pixel save <name>"

    def _update(self, args):
        import subprocess
        project_dir = BASE
        result = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=project_dir, capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"Git fetch failed: {result.stderr}"
        result = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            cwd=project_dir, capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"Git reset failed: {result.stderr}"
        return True, f"Updated:\n{result.stdout}\nRestart to apply changes."

    def _help(self, args):
        lines = [
            "── DISPLAY ──────────────────────────────────────────────",
            "  text <msg> [size=14] [x=0] [y=0]",
            "  scroll <msg> [size=14]",
            "  fill | clear",
            "  image <path> [threshold=128] [dither=none|floyd|bayer]",
            "  gif <path> [loop=0]",
            "",
            "── ANIMATIONS ───────────────────────────────────────────",
            "  anim list",
            "  anim <name> [param=value ...]",
            "  anim stop",
            "",
            "── CUE ENGINE ───────────────────────────────────────────",
            "  cue list | cue add [type=text] [label=...] [content=...] [dur=5]",
            "  cue del <number> | cue clear | cue renumber",
            "  go [cue#] | back | hold | release",
            "",
            "── SCHEDULER ────────────────────────────────────────────",
            "  sched list | sched add [label=...] [type=text] [content=...] [interval=60]",
            "  sched del <#> | sched clear | sched on | sched off",
            "",
            "── PLAYLIST ─────────────────────────────────────────────",
            "  playlist list | playlist add [label=...] [type=text] [content=...] [weight=1]",
            "  playlist mode sequential|shuffle|weighted",
            "  playlist start [mode] | playlist stop | playlist skip",
            "",
            "── EFFECTS ──────────────────────────────────────────────",
            "  fx list | fx add <type> [name=fx1] [param=value ...]",
            "  fx del <name> | fx clear",
            "",
            "── VARIABLES ────────────────────────────────────────────",
            "  vars | vars set <key> <value> | vars refresh",
            "  preview <text with {tokens}>",
            "",
            "── SCRIPTS ──────────────────────────────────────────────",
            "  script list | script run <name> | script stop | script status",
            "",
            "── ASSETS & SHOWS ───────────────────────────────────────",
            "  assets list | assets save <name> | assets load <name>",
            "  show list | show save [name] | show load <name> | show new",
            "",
            "── SYSTEM ───────────────────────────────────────────────",
            "  status | connect [port] | disconnect | ports",
            "  pixel load <file> | pixel save <name>",
            "  test fill|clear|flash | log [n]",
            "  update | help",
        ]
        return True, "\n".join(lines)
