"""
engine.py
---------
Central runtime. Owns all subsystems and provides a single
execute() method that all commands and scripts call.

This is the only place that imports and combines:
  Display, CueEngine, Scheduler, Playlist, Animations,
  Variables, ImageProcessor, Effects, Assets, Show, Renderer

Everything else (CLI, script engine) calls engine.execute()
and never touches subsystems directly.
"""

import os
import sys
import time
import threading
import logging
import numpy as np

log = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "backend"))


class Engine:
    def __init__(self, display):
        self.display = display

        # Import subsystems
        from cue_engine      import CueEngine, Cue
        from scheduler       import Scheduler, ScheduleItem
        from playlist        import Playlist, PlaylistItem
        from effects         import EffectsEngine, EFFECTS_REGISTRY
        import variables     as var_mod
        import assets        as asset_lib
        import show          as show_mgr
        from animations      import list_animations, get_animation, anim_scroll_text
        from renderer        import render_text, render_scroll_source, scroll_frames
        from image_processor import process_image, frames_to_json

        self.Cue           = Cue
        self.ScheduleItem  = ScheduleItem
        self.PlaylistItem  = PlaylistItem
        self.EFFECTS_REG   = EFFECTS_REGISTRY
        self.var_mod       = var_mod
        self.asset_lib     = asset_lib
        self.show_mgr      = show_mgr
        self.list_anims    = list_animations
        self.get_anim      = get_animation
        self.anim_scroll   = anim_scroll_text
        self.render_text   = render_text
        self.render_scroll = render_scroll_source
        self.scroll_frames = scroll_frames
        self.process_image = process_image
        self.frames_to_json= frames_to_json

        self.cue_eng   = CueEngine(self._execute_cue)
        self.scheduler = Scheduler(self._execute_schedule_item)
        self.playlist  = Playlist(self._execute_playlist_item)
        self.effects   = EffectsEngine(self.display.get_buffer, self.display.send)

        # Animation thread control
        self._anim_stop   = threading.Event()
        self._anim_thread = None

        # Set shows/assets dirs relative to project root
        self.show_mgr.SHOWS_DIR = os.path.join(BASE, "shows")
        self.asset_lib.ASSETS_DIR = os.path.join(BASE, "assets")

    def start(self):
        """Start background systems."""
        self.var_mod.start()
        log.info("Engine started")

    def stop(self):
        """Shutdown all subsystems."""
        self.stop_anim()
        self.scheduler.stop()
        self.playlist.stop()
        self.effects.clear()
        self.var_mod.stop()
        log.info("Engine stopped")

    # ── Animation runner ──────────────────────────────────────────

    def run_anim(self, fn, *args, **kwargs):
        self.stop_anim()
        time.sleep(0.05)
        self._anim_stop.clear()
        def _r():
            for frame, delay in fn(*args, **kwargs):
                if self._anim_stop.is_set():
                    break
                self.display.send(frame)
                time.sleep(delay)
        self._anim_thread = threading.Thread(target=_r, daemon=True)
        self._anim_thread.start()

    def stop_anim(self):
        self._anim_stop.set()

    def play_gif(self, frames, loop=1):
        self.stop_anim()
        time.sleep(0.05)
        self._anim_stop.clear()
        def _r():
            for _ in range(loop if loop > 0 else 999999):
                for bmp, dur in frames:
                    if self._anim_stop.is_set():
                        return
                    arr = np.array(bmp, dtype=np.uint8)
                    self.display.send(arr)
                    time.sleep(max(0.033, dur / 1000.0))
        threading.Thread(target=_r, daemon=True).start()

    # ── Cue executor ──────────────────────────────────────────────

    def _execute_cue(self, cue):
        ct = cue.content_type
        c  = cue.content or {}
        self.stop_anim()

        sub = self.var_mod.substitute

        W = self.display.W
        H = self.display.H

        if ct == "clear":
            self.display.clear()
        elif ct == "fill":
            self.display.fill()
        elif ct == "text":
            txt    = sub(c.get("text", ""))
            fname  = c.get("font", "default")
            fsize  = int(c.get("font_size", 14))
            x      = int(c.get("x", 0))
            y      = int(c.get("y", 0))
            scroll = c.get("scroll", False)
            if scroll:
                self.run_anim(self.scroll_frames, txt, fname, fsize, W, H)
            else:
                frame = self.render_text(txt, fname, fsize, x, y, W, H)
                self.display.send(frame)
        elif ct == "animation":
            fn = self.get_anim(c.get("animation_id", "flash"))
            if fn:
                self.run_anim(fn, W, H, **c.get("params", {}))
        elif ct == "image":
            frames_data = c.get("frames", [])
            if frames_data:
                frames = [(np.array(f["bitmap"], dtype=np.uint8), f["duration"])
                          for f in frames_data]
                self.play_gif(frames, c.get("loop", 1))
        elif ct == "asset":
            a = self.asset_lib.get(c.get("asset_id", ""))
            if a:
                fake = type("C", (), {
                    "content_type": a["type"],
                    "content":      a.get("data", {}),
                })()
                self._execute_cue(fake)

        log.debug(f"Cue executed: {getattr(cue, 'number', '?')} [{ct}]")

    def _execute_schedule_item(self, item):
        fake = type("C", (), {
            "content_type": item.content_type,
            "content":      item.content,
            "number":       "SCHED",
        })()
        self._execute_cue(fake)

    def _execute_playlist_item(self, item):
        fake = type("C", (), {
            "content_type": item.content_type,
            "content":      item.content,
            "number":       "PL",
        })()
        self._execute_cue(fake)

    # ── High-level command handlers ───────────────────────────────

    def cmd_text(self, text, fname="default", fsize=14, x=0, y=0):
        self.stop_anim()
        text  = self.var_mod.substitute(str(text))
        W, H  = self.display.W, self.display.H
        frame = self.render_text(text, fname, fsize, x, y, W, H)
        self.display.send(frame)

    def cmd_scroll(self, text, fname="default", fsize=14):
        text = self.var_mod.substitute(str(text))
        W, H = self.display.W, self.display.H
        self.run_anim(self.scroll_frames, text, fname, fsize, W, H)

    def cmd_anim(self, name, **params):
        fn = self.get_anim(name)
        if not fn:
            return False, f"Unknown animation: {name}"
        W, H = self.display.W, self.display.H
        self.run_anim(fn, W, H, **params)
        return True, f"Animation running: {name}"

    def cmd_image(self, path, threshold=128, brightness=1.0,
                  contrast=1.0, dither="none", scale="fit",
                  invert=False, loop=1):
        if not os.path.isfile(path):
            return False, f"File not found: {path}"
        try:
            with open(path, "rb") as f:
                data = f.read()
            frames = self.process_image(
                data, self.display.W, self.display.H,
                threshold, brightness, contrast, dither, scale, invert)
            if len(frames) == 1 and frames[0][1] == 0:
                self.display.send(frames[0][0])
            else:
                self.play_gif(frames, loop)
            return True, f"Image loaded: {len(frames)} frame(s)"
        except Exception as e:
            return False, str(e)

    def status_dict(self):
        return {
            "connected":   self.display.connected,
            "port":        self.display.port,
            "baud":        self.display.baud,
            "dimensions":  f"{self.display.W}x{self.display.H}",
            "cue_engine":  self.cue_eng.get_status(),
            "scheduler":   {"running": self.scheduler.running,
                            "items":   len(self.scheduler.items)},
            "playlist":    {"running": self.playlist.running,
                            "mode":    self.playlist.mode,
                            "items":   len(self.playlist.items)},
            "effects":     list(self.effects.active.keys()),
            "variables":   self.var_mod.get_all_values(),
        }
