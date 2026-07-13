"""
app.py — FlipDot Console V8

Everything that can go on the panel is a "spec" (see backend/renderer.py).
The same spec drives live preview in the browser, a one-off send, and a step in
the sequencer — so what you see in the preview is exactly what the panel does.

Run: cd FlipPyDot && ./start.sh
"""
import os
import sys
import time
import json
import logging
import logging.handlers
from datetime import datetime

import numpy as np
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import serial

# ── Paths ─────────────────────────────────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE, "frontend")
BACKEND  = os.path.join(BASE, "backend")
SHOWS_DIR = os.path.join(BASE, "shows")
sys.path.insert(0, BACKEND)

# ── Logging ───────────────────────────────────────────────────────
LOG_DIR  = os.path.join(BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_fh = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, "flipdot.log"), maxBytes=5 * 1024 * 1024, backupCount=3)
_ch = logging.StreamHandler(sys.stdout)
for h in (_fh, _ch):
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
log = logging.getLogger(__name__)

# ── Backend ───────────────────────────────────────────────────────
import config as cfg_mod

device_cfg = cfg_mod.load("config")
var_cfg    = cfg_mod.load("variables")
layout     = cfg_mod.load("layout")

PORT = os.environ.get("FLIPDOT_PORT", device_cfg.get("port", "/dev/cu.usbserial-BG01DCHX"))
BAUD = int(os.environ.get("FLIPDOT_BAUD", device_cfg.get("baud_rate", 57600)))

from display   import Display
from effects   import EffectsEngine, EFFECTS_REGISTRY
from player    import Player
from sequencer import Sequencer, Step, Overlay
from animations      import list_animations
from image_processor import process_image, frames_to_json
from variables       import substitute, get_all_values, get_status as var_status
from wizard          import PanelWizard
import renderer
import fonts    as font_mod
import variables as var_mod
import show      as show_mgr

show_mgr.SHOWS_DIR = SHOWS_DIR

display = Display(PORT, BAUD, layout)


def size():
    return (display.W or 84, display.H or 42)


effects   = EffectsEngine()
player    = Player(display, size, effects=effects)
sequencer = Sequencer(player)
wizard    = PanelWizard(lambda: display._ser, total=18)


# ── Autosave ──────────────────────────────────────────────────────
def save_last():
    """Persist the sequencer after every mutation so a power cut costs nothing."""
    try:
        os.makedirs(SHOWS_DIR, exist_ok=True)
        p = os.path.join(SHOWS_DIR, "last.json")
        with open(p + ".tmp", "w") as f:
            json.dump({
                "saved":     datetime.now().isoformat(),
                "sequencer": sequencer.to_dict(),
            }, f, indent=2)
        os.replace(p + ".tmp", p)
    except Exception as e:
        log.warning(f"Autosave failed: {e}")


sequencer.on_change = save_last


def load_last():
    p = os.path.join(SHOWS_DIR, "last.json")
    if not os.path.isfile(p):
        return
    try:
        with open(p) as f:
            data = json.load(f)
        seq = data.get("sequencer", {})
        sequencer.load(seq)
        if seq.get("running"):
            sequencer.start()
        log.info(f"Restored: {len(sequencer.steps)} steps, "
                 f"{len(sequencer.overlays)} overlays")
    except Exception as e:
        log.warning(f"Could not restore last state: {e}")


# ── Flask ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=FRONTEND)
CORS(app, resources={r"/*": {"origins": "*"}})


def body():
    return request.get_json(silent=True) or {}


@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.route("/<path:p>")
def static_files(p):
    return send_from_directory(FRONTEND, p)


# ── Status / connection ───────────────────────────────────────────
@app.route("/api/status")
def api_status():
    w, h = size()
    return jsonify({
        "connected": display.connected,
        "port":      display.port,
        "baud_rate": display.baud,
        "width":     w,
        "height":    h,
        "error":     display.connect_error,
        "player":    player.get_status(),
        "sequencer": sequencer.get_status(),
        "effects":   effects.get_status(),
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/ports")
def api_ports():
    import serial.tools.list_ports
    return jsonify([{"port": p.device, "description": p.description}
                    for p in serial.tools.list_ports.comports()])


@app.route("/api/connect", methods=["POST"])
def api_connect():
    d = body()
    port = d.get("port", display.port)
    baud = int(d.get("baud_rate", display.baud))
    cfg_mod.set_value("config", "port", port)
    cfg_mod.set_value("config", "baud_rate", baud)
    display.reconnect(port=port, baud=baud)
    return jsonify({"success": display.connected, "connected": display.connected,
                    "error": display.connect_error})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    display.stop()
    return jsonify({"success": True})


@app.route("/api/buffer")
def api_buffer():
    return jsonify({"buffer": display.buffer.tolist()})


# ── Preview: render a spec without touching hardware ───────────────
@app.route("/api/preview", methods=["POST"])
def api_preview():
    d = body()
    spec = d.get("spec", d)
    w, h = size()
    try:
        frames = renderer.preview(spec, w, h,
                                  max_frames=int(d.get("max_frames", 240)))
        return jsonify({
            "success": True,
            "frames":  frames,
            "static":  renderer.is_static(spec),
            "width":   w,
            "height":  h,
        })
    except Exception as e:
        log.warning(f"Preview failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 400


# ── Transport: play a spec right now ──────────────────────────────
@app.route("/api/play", methods=["POST"])
def api_play():
    d = body()
    spec = d.get("spec", d)
    dur  = d.get("duration")
    if d.get("stop_sequencer", True) and sequencer.running:
        sequencer.stop()
    player.play(spec, duration=float(dur) if dur else None,
                loop=bool(d.get("loop", True)))
    return jsonify({"success": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    sequencer.stop()
    player.stop()
    return jsonify({"success": True})


@app.route("/api/display/clear", methods=["POST"])
def api_clear():
    sequencer.stop()
    player.play({"kind": "clear"})
    return jsonify({"success": True})


@app.route("/api/display/fill", methods=["POST"])
def api_fill():
    sequencer.stop()
    player.play({"kind": "fill"})
    return jsonify({"success": True})


# ── Fonts ─────────────────────────────────────────────────────────
@app.route("/api/fonts")
def api_fonts():
    return jsonify({"fonts": font_mod.list_fonts(),
                    "default": font_mod.DEFAULT_KEY})


@app.route("/api/fonts/upload", methods=["POST"])
def api_font_upload():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file"}), 400
    f = request.files["file"]
    try:
        key = font_mod.save_upload(f.filename, f.read())
        return jsonify({"success": True, "key": key,
                        "fonts": font_mod.list_fonts()})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/fonts/<key>", methods=["DELETE"])
def api_font_delete(key):
    ok = font_mod.delete(key)
    return jsonify({"success": ok, "fonts": font_mod.list_fonts()})


# ── Animations ────────────────────────────────────────────────────
@app.route("/api/animations")
def api_animations():
    return jsonify({"animations": list_animations()})


# ── Sequencer: playlist ───────────────────────────────────────────
@app.route("/api/sequencer")
def api_sequencer():
    return jsonify(sequencer.get_status())


@app.route("/api/sequencer/steps", methods=["POST"])
def api_add_step():
    d = body()
    step = Step(
        label=d.get("label", ""),
        content=d.get("content") or {"kind": "text", "text": ""},
        duration=d.get("duration", 8),
        enabled=d.get("enabled", True),
        transition=d.get("transition"),
    )
    sequencer.add_step(step, at=d.get("at"))
    return jsonify({"success": True, "step": step.to_dict()})


@app.route("/api/sequencer/steps/<sid>", methods=["PUT"])
def api_update_step(sid):
    s = sequencer.update_step(sid, body())
    if not s:
        return jsonify({"success": False, "error": "No such step"}), 404
    return jsonify({"success": True, "step": s.to_dict()})


@app.route("/api/sequencer/steps/<sid>", methods=["DELETE"])
def api_delete_step(sid):
    return jsonify({"success": sequencer.remove_step(sid)})


@app.route("/api/sequencer/steps/<sid>/duplicate", methods=["POST"])
def api_duplicate_step(sid):
    s = sequencer.duplicate_step(sid)
    if not s:
        return jsonify({"success": False, "error": "No such step"}), 404
    return jsonify({"success": True, "step": s.to_dict()})


@app.route("/api/sequencer/steps/<sid>/preview", methods=["POST"])
def api_preview_step(sid):
    """Push one step to the panel on its own, so you can eyeball it in place."""
    for s in sequencer.steps:
        if s.id == sid:
            sequencer.stop()
            player.play(s.content, duration=s.duration)
            return jsonify({"success": True})
    return jsonify({"success": False, "error": "No such step"}), 404


@app.route("/api/sequencer/reorder", methods=["POST"])
def api_reorder():
    sequencer.reorder(body().get("ids", []))
    return jsonify({"success": True, "steps": [s.to_dict() for s in sequencer.steps]})


# ── Sequencer: overlays ───────────────────────────────────────────
@app.route("/api/sequencer/overlays", methods=["POST"])
def api_add_overlay():
    d = body()
    ov = Overlay(
        label=d.get("label", ""),
        content=d.get("content") or {"kind": "text", "text": ""},
        duration=d.get("duration", 8),
        enabled=d.get("enabled", True),
        trigger=d.get("trigger"),
        priority=d.get("priority", 0),
    )
    sequencer.add_overlay(ov)
    return jsonify({"success": True, "overlay": ov.to_dict()})


@app.route("/api/sequencer/overlays/<oid>", methods=["PUT"])
def api_update_overlay(oid):
    o = sequencer.update_overlay(oid, body())
    if not o:
        return jsonify({"success": False, "error": "No such overlay"}), 404
    return jsonify({"success": True, "overlay": o.to_dict()})


@app.route("/api/sequencer/overlays/<oid>", methods=["DELETE"])
def api_delete_overlay(oid):
    return jsonify({"success": sequencer.remove_overlay(oid)})


# ── Sequencer: transport ──────────────────────────────────────────
@app.route("/api/sequencer/start", methods=["POST"])
def api_seq_start():
    sequencer.start()
    save_last()
    return jsonify({"success": True})


@app.route("/api/sequencer/stop", methods=["POST"])
def api_seq_stop():
    sequencer.stop()
    save_last()
    return jsonify({"success": True})


@app.route("/api/sequencer/next", methods=["POST"])
def api_seq_next():
    sequencer.next()
    return jsonify({"success": True})


@app.route("/api/sequencer/prev", methods=["POST"])
def api_seq_prev():
    sequencer.prev()
    return jsonify({"success": True})


@app.route("/api/sequencer/goto", methods=["POST"])
def api_seq_goto():
    sequencer.goto(int(body().get("index", 0)))
    return jsonify({"success": True})


@app.route("/api/sequencer/loop", methods=["POST"])
def api_seq_loop():
    sequencer.loop = bool(body().get("loop", True))
    save_last()
    return jsonify({"success": True, "loop": sequencer.loop})


# ── Image ─────────────────────────────────────────────────────────
@app.route("/api/image/upload", methods=["POST"])
def api_image_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    w, h = size()
    try:
        frames = process_image(
            request.files["file"].read(), w, h,
            int(request.form.get("threshold", 128)),
            float(request.form.get("brightness", 1.0)),
            float(request.form.get("contrast", 1.0)),
            request.form.get("dither", "none"),
            request.form.get("scale", "fit"),
            request.form.get("invert", "false").lower() == "true",
        )
        return jsonify({"success": True, "frames": frames_to_json(frames),
                        "frame_count": len(frames), "animated": len(frames) > 1})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


# ── Variables ─────────────────────────────────────────────────────
@app.route("/api/variables")
def api_variables():
    return jsonify(var_status())


@app.route("/api/variables/config", methods=["POST"])
def api_variables_config():
    d = body()
    var_mod.configure(d)
    cfg_mod.save("variables", d)
    return jsonify({"success": True})


@app.route("/api/variables/values")
def api_variables_values():
    return jsonify(get_all_values())


@app.route("/api/variables/preview", methods=["POST"])
def api_variables_preview():
    t = body().get("text", "")
    return jsonify({"original": t, "substituted": substitute(t)})


# ── Effects ───────────────────────────────────────────────────────
@app.route("/api/effects")
def api_effects():
    return jsonify({"registry": EFFECTS_REGISTRY, **effects.get_status()})


@app.route("/api/effects", methods=["POST"])
def api_add_effect():
    d = body()
    try:
        effects.add(d.get("name", "fx"), d.get("type", "flicker"),
                    **d.get("params", {}))
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": True})


@app.route("/api/effects/<name>", methods=["DELETE"])
def api_delete_effect(name):
    effects.remove(name)
    return jsonify({"success": True})


@app.route("/api/effects/clear", methods=["POST"])
def api_clear_effects():
    effects.clear()
    return jsonify({"success": True})


# ── Shows ─────────────────────────────────────────────────────────
@app.route("/api/shows")
def api_list_shows():
    return jsonify({"shows": show_mgr.list_shows()})


@app.route("/api/shows/save", methods=["POST"])
def api_save_show():
    name = body().get("name", "untitled")
    path = show_mgr.save_show(
        name, sequencer,
        config={"port": PORT, "baud_rate": BAUD, "layout": layout},
        var_config=cfg_mod.load("variables"))
    return jsonify({"success": True, "path": path})


@app.route("/api/shows/load", methods=["POST"])
def api_load_show():
    name = body().get("name", "")
    try:
        data = show_mgr.load_show(name, sequencer)
        save_last()
        return jsonify({"success": True, "meta": data.get("meta", {}),
                        "sequencer": sequencer.get_status()})
    except FileNotFoundError as e:
        return jsonify({"success": False, "error": str(e)}), 404


@app.route("/api/shows/<name>", methods=["DELETE"])
def api_delete_show(name):
    return jsonify({"success": show_mgr.delete_show(name)})


# ── Wizard ────────────────────────────────────────────────────────
@app.route("/api/wizard/state")
def api_wizard_state():
    return jsonify(wizard.get_state())


@app.route("/api/wizard/start", methods=["POST"])
def api_wizard_start():
    return jsonify(wizard.start(body().get("total", 18)))


@app.route("/api/wizard/assign", methods=["POST"])
def api_wizard_assign():
    d = body()
    return jsonify(wizard.assign(int(d["address"]), int(d["col"]),
                                 int(d["row"]), d["half"]))


@app.route("/api/wizard/skip", methods=["POST"])
def api_wizard_skip():
    return jsonify(wizard.skip(int(body().get("address", 0))))


@app.route("/api/wizard/stop", methods=["POST"])
def api_wizard_stop():
    return jsonify(wizard.stop())


@app.route("/api/wizard/save", methods=["POST"])
def api_wizard_save():
    if not wizard.mappings:
        return jsonify({"success": False, "error": "No mappings"}), 400
    try:
        new_layout = wizard.build_layout()
        cfg_mod.save("layout", new_layout)
        display.layout = new_layout
        display.reconnect()
        log.info(f"Layout saved: {new_layout}")
        return jsonify({"success": True, "layout": new_layout})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Boot ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 52)
    log.info("  FLIPDOT CONSOLE V8")
    log.info("=" * 52)

    display.start()
    time.sleep(1.5)

    var_mod.configure(var_cfg)
    var_mod.start()

    load_last()

    log.info(f"Fonts: {', '.join(f['key'] for f in font_mod.list_fonts())}")
    log.info("Open: http://localhost:5000")
    log.info("=" * 52)

    app.run(host="0.0.0.0", port=int(os.environ.get("FLIPDOT_WEB_PORT", 5000)), debug=False, threaded=True)
