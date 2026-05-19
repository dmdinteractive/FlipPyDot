"""
app.py — FlipDot Console V7
Single-page Exploratorium UI.
Run: cd FlipPyDot && ./start.sh
"""
import os
import sys
import time
import threading
import logging
import logging.handlers
import json
import numpy as np

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
import serial

# ── Paths ─────────────────────────────────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE, "frontend")
BACKEND  = os.path.join(BASE, "backend")
sys.path.insert(0, BACKEND)

# ── Logging ───────────────────────────────────────────────────────
LOG_DIR  = os.path.join(BASE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "flipdot.log")
os.makedirs(LOG_DIR, exist_ok=True)

handler_file = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
handler_file.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s"))

handler_console = logging.StreamHandler(sys.stdout)
handler_console.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(level=logging.INFO,
                    handlers=[handler_file, handler_console])
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────
import config as cfg_mod

device_cfg = cfg_mod.load("config")
var_cfg    = cfg_mod.load("variables")
layout     = cfg_mod.load("layout")

PORT   = os.environ.get("FLIPDOT_PORT", device_cfg.get("port", "/dev/cu.usbserial-BG01DCHX"))
BAUD   = int(os.environ.get("FLIPDOT_BAUD", device_cfg.get("baud_rate", 57600)))

# ── Display ───────────────────────────────────────────────────────
from display import Display

display = Display(PORT, BAUD, layout)

def get_W():
    return display.W or 84

def get_H():
    return display.H or 42

# ── Imports ───────────────────────────────────────────────────────
from animations      import list_animations, get_animation, anim_scroll_text
from scheduler       import Scheduler, ScheduleItem
from variables       import substitute, get_all_values, get_status as var_status
from image_processor import process_image, frames_to_json
from effects         import EffectsEngine, EFFECTS_REGISTRY
from wizard          import PanelWizard
import variables     as var_mod
import show          as show_mgr

# ── Animation runner ──────────────────────────────────────────────
_anim_stop   = threading.Event()
_anim_thread = None
_cur_anim    = None

def run_anim(fn, *args, **kwargs):
    global _anim_thread, _cur_anim
    _anim_stop.set()
    time.sleep(0.05)
    _anim_stop.clear()

    def _run():
        for frame, delay in fn(*args, **kwargs):
            if _anim_stop.is_set():
                break
            display.send(frame)
            time.sleep(delay)

    _anim_thread = threading.Thread(target=_run, daemon=True)
    _anim_thread.start()

def stop_anim():
    global _cur_anim
    _anim_stop.set()
    _cur_anim = None

def play_gif(frames, loop=1):
    def _run():
        for _ in range(loop if loop > 0 else 999999):
            for bmp, dur in frames:
                if _anim_stop.is_set():
                    return
                display.send(np.array(bmp, dtype=np.uint8))
                time.sleep(max(0.033, dur / 1000.0))
    stop_anim()
    time.sleep(0.05)
    _anim_stop.clear()
    threading.Thread(target=_run, daemon=True).start()

# ── Text rendering ────────────────────────────────────────────────
from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = os.path.join(BASE, "fonts")

def get_font(name, size):
    if name and name != "default":
        p = os.path.join(FONTS_DIR, name)
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, int(size))
            except Exception:
                pass
    return ImageFont.load_default()

def render_text(text, fname="default", fsize=14, x=0, y=0):
    text = substitute(str(text))
    w    = get_W()
    h    = get_H()
    img  = Image.new("L", (w, h), 255)
    ImageDraw.Draw(img).text((x, y), text, fill=0,
                             font=get_font(fname, fsize))
    return (np.array(img) < 128).astype(np.uint8)

def render_scroll_source(text, fname="default", fsize=14):
    text = substitute(str(text))
    w    = get_W()
    h    = get_H()
    font = get_font(fname, fsize)
    img  = Image.new("L", (8192, h), 255)
    bbox = ImageDraw.Draw(img).textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0] + w * 2
    src_img = Image.new("L", (tw, h), 255)
    ImageDraw.Draw(src_img).text((w, 0), text, fill=0, font=font)
    return (np.array(src_img) < 128).astype(np.uint8)

def scroll_gen(source, w):
    sw = source.shape[1]
    x  = 0
    while x < sw - w:
        frame = np.zeros((source.shape[0], w), dtype=np.uint8)
        chunk = source[:, x:x + w]
        frame[:, :chunk.shape[1]] = chunk
        yield frame, 0.04
        x += 1

# ── Scheduler executor ────────────────────────────────────────────
def execute_schedule_item(item):
    ct = item.content_type
    c  = item.content or {}
    stop_anim()

    if ct == "clear":
        display.clear()
    elif ct == "fill":
        display.fill()
    elif ct == "text":
        txt    = c.get("text", "")
        scroll = c.get("scroll", False)
        fname  = c.get("font", "default")
        fsize  = int(c.get("font_size", 14))
        if scroll:
            run_anim(scroll_gen, render_scroll_source(txt, fname, fsize), get_W())
        else:
            display.send(render_text(txt, fname, fsize))
    elif ct == "animation":
        fn = get_animation(c.get("animation_id", "flash"))
        if fn:
            run_anim(fn, get_W(), get_H(), **c.get("params", {}))

    log.info(f"Scheduler executed: {item.label} [{ct}]")

# ── Core objects ──────────────────────────────────────────────────
scheduler = Scheduler(execute_schedule_item)
effects   = EffectsEngine(lambda: display.buffer, display.send)
wizard    = PanelWizard(lambda: display._ser, total=18)

# ── Show save/load ────────────────────────────────────────────────
SHOWS_DIR = os.path.join(BASE, "shows")
show_mgr.SHOWS_DIR = SHOWS_DIR

def save_last_show():
    """Save current state as 'last' show — called on every change."""
    try:
        data = {
            "meta": {"name": "last", "saved": datetime.now().isoformat()},
            "scheduler": [i.to_dict() for i in scheduler.items],
            "scheduler_running": scheduler.running,
            "var_config": cfg_mod.load("variables"),
        }
        os.makedirs(SHOWS_DIR, exist_ok=True)
        p     = os.path.join(SHOWS_DIR, "last.json")
        p_tmp = p + ".tmp"
        with open(p_tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(p_tmp, p)
    except Exception as e:
        log.warning(f"Could not save last show: {e}")

def load_last_show():
    """Load last show on startup."""
    p = os.path.join(SHOWS_DIR, "last.json")
    if not os.path.isfile(p):
        return
    try:
        with open(p) as f:
            data = json.load(f)
        for item_data in data.get("scheduler", []):
            item = ScheduleItem.from_dict(item_data)
            scheduler.add(item)
        if data.get("scheduler_running"):
            scheduler.start()
        log.info("Last show restored")
    except Exception as e:
        log.warning(f"Could not load last show: {e}")

# ── Flask ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=FRONTEND)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")

@app.route("/<path:p>")
def static_files(p):
    return send_from_directory(FRONTEND, p)

# ── Status ────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify({
        "connected":  display.connected,
        "port":       display.port,
        "baud_rate":  display.baud,
        "width":      display.W,
        "height":     display.H,
        "error":      display.connect_error,
        "scheduler":  {
            "running": scheduler.running,
            "items":   [i.to_dict() for i in scheduler.items],
        },
        "effects":    effects.get_status(),
        "cur_anim":   _cur_anim,
        "timestamp":  datetime.now().isoformat(),
    })

@app.route("/api/ports")
def api_ports():
    import serial.tools.list_ports
    return jsonify([
        {"port": p.device, "description": p.description}
        for p in serial.tools.list_ports.comports()
    ])

@app.route("/api/connect", methods=["POST"])
def api_connect():
    d    = request.get_json() or {}
    port = d.get("port", display.port)
    baud = int(d.get("baud_rate", display.baud))
    cfg_mod.set_value("config", "port", port)
    cfg_mod.set_value("config", "baud_rate", baud)
    display.reconnect(port=port, baud=baud)
    return jsonify({"success": display.connected,
                    "connected": display.connected,
                    "error": display.connect_error})

@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    display.stop()
    return jsonify({"success": True})

# ── Buffer ────────────────────────────────────────────────────────
@app.route("/api/buffer")
def api_buffer():
    return jsonify({"buffer": display.buffer.tolist()})

# ── Display commands ──────────────────────────────────────────────
@app.route("/api/display/fill", methods=["POST"])
def api_fill():
    stop_anim()
    display.fill()
    return jsonify({"success": True})

@app.route("/api/display/clear", methods=["POST"])
def api_clear():
    stop_anim()
    display.clear()
    return jsonify({"success": True})

@app.route("/api/display/text", methods=["POST"])
def api_text():
    global _cur_anim
    d      = request.get_json() or {}
    text   = d.get("text", "")
    fname  = d.get("font", "default")
    fsize  = int(d.get("font_size", 14))
    x      = int(d.get("x", 0))
    y      = int(d.get("y", 0))
    scroll = d.get("scroll", False)

    stop_anim()

    if scroll:
        _cur_anim = "scroll"
        run_anim(scroll_gen,
                 render_scroll_source(text, fname, fsize), get_W())
    else:
        frame = render_text(text, fname, fsize, x, y)
        display.send(frame)

    return jsonify({"success": True})

# ── Animations ────────────────────────────────────────────────────
@app.route("/api/animations")
def api_animations():
    return jsonify({"animations": list_animations()})

@app.route("/api/animations/run", methods=["POST"])
def api_run_anim():
    global _cur_anim
    d  = request.get_json() or {}
    fn = get_animation(d.get("name", "flash"))
    if not fn:
        return jsonify({"error": "Unknown animation"}), 404
    _cur_anim = d.get("name")
    run_anim(fn, get_W(), get_H(), **d.get("options", {}))
    return jsonify({"success": True})

@app.route("/api/animations/stop", methods=["POST"])
def api_stop_anim():
    stop_anim()
    return jsonify({"success": True})

# ── Image import ──────────────────────────────────────────────────
@app.route("/api/image/upload", methods=["POST"])
def api_image_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    data = request.files["file"].read()
    try:
        frames = process_image(
            data,
            get_W(), get_H(),
            int(request.form.get("threshold", 128)),
            float(request.form.get("brightness", 1.0)),
            float(request.form.get("contrast",   1.0)),
            request.form.get("dither", "none"),
            request.form.get("scale",  "fit"),
            request.form.get("invert", "false").lower() == "true",
        )
        return jsonify({
            "success":     True,
            "frames":      frames_to_json(frames),
            "frame_count": len(frames),
            "animated":    len(frames) > 1,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/image/display", methods=["POST"])
def api_image_display():
    d      = request.get_json() or {}
    frames_data = d.get("frames", [])
    if not frames_data:
        return jsonify({"success": False, "error": "No frames"}), 400
    frames = [(np.array(f["bitmap"], dtype=np.uint8), f["duration"])
              for f in frames_data]
    loop   = int(d.get("loop", 1))
    if len(frames) == 1 and frames[0][1] == 0:
        display.send(frames[0][0])
    else:
        play_gif(frames, loop)
    return jsonify({"success": True, "frames": len(frames)})

# ── Variables ─────────────────────────────────────────────────────
@app.route("/api/variables")
def api_variables():
    return jsonify(var_status())

@app.route("/api/variables/config", methods=["POST"])
def api_variables_config():
    d = request.get_json() or {}
    var_mod.configure(d)
    cfg_mod.save("variables", d)
    return jsonify({"success": True})

@app.route("/api/variables/values")
def api_variables_values():
    return jsonify(get_all_values())

@app.route("/api/variables/preview", methods=["POST"])
def api_variables_preview():
    d = request.get_json() or {}
    t = d.get("text", "")
    return jsonify({"original": t, "substituted": substitute(t)})

# ── Scheduler ─────────────────────────────────────────────────────
@app.route("/api/scheduler")
def api_scheduler():
    return jsonify({
        "running": scheduler.running,
        "items":   [i.to_dict() for i in scheduler.items],
    })

@app.route("/api/scheduler", methods=["POST"])
def api_add_schedule():
    d  = request.get_json() or {}
    ct = d.get("content_type", "text")
    c  = d.get("content", {})

    if not c and ct == "text":
        c = {
            "text":      d.get("text", ""),
            "font_size": int(d.get("font_size", 14)),
            "scroll":    bool(d.get("scroll", False)),
        }
    elif not c and ct == "animation":
        c = {"animation_id": d.get("animation_id", "flash")}

    item = ScheduleItem(
        label        = d.get("label", ""),
        content_type = ct,
        content      = c,
        mode         = d.get("mode", "repeat"),
        duration     = float(d.get("duration", 5)),
        interval     = float(d.get("interval", 60)),
        priority     = int(d.get("priority", 0)),
    )
    scheduler.add(item)
    save_last_show()
    return jsonify({"success": True, "item": item.to_dict()})

@app.route("/api/scheduler/<item_id>", methods=["DELETE"])
def api_delete_schedule(item_id):
    scheduler.remove(item_id)
    save_last_show()
    return jsonify({"success": True})

@app.route("/api/scheduler/<item_id>", methods=["PUT"])
def api_update_schedule(item_id):
    d = request.get_json() or {}
    scheduler.update(item_id, d)
    save_last_show()
    return jsonify({"success": True})

@app.route("/api/scheduler/start", methods=["POST"])
def api_start_scheduler():
    scheduler.start()
    save_last_show()
    return jsonify({"success": True})

@app.route("/api/scheduler/stop", methods=["POST"])
def api_stop_scheduler():
    scheduler.stop()
    save_last_show()
    return jsonify({"success": True})

# ── Effects ───────────────────────────────────────────────────────
@app.route("/api/effects")
def api_effects():
    return jsonify({
        "registry": EFFECTS_REGISTRY,
        **effects.get_status(),
    })

@app.route("/api/effects", methods=["POST"])
def api_add_effect():
    d = request.get_json() or {}
    effects.add(d.get("name", "fx"), d.get("type", "flicker"),
                **d.get("params", {}))
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
    d    = request.get_json() or {}
    name = d.get("name", "untitled")
    path = show_mgr.save_show(
        name, None, scheduler,
        {"port": PORT, "baud_rate": BAUD, "layout": layout})
    return jsonify({"success": True, "path": path})

@app.route("/api/shows/load", methods=["POST"])
def api_load_show():
    d    = request.get_json() or {}
    name = d.get("name", "")
    try:
        data = show_mgr.load_show(name, None, scheduler)
        save_last_show()
        return jsonify({"success": True, "meta": data.get("meta", {})})
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
    d = request.get_json() or {}
    return jsonify(wizard.start(d.get("total", 18)))

@app.route("/api/wizard/assign", methods=["POST"])
def api_wizard_assign():
    d = request.get_json() or {}
    return jsonify(wizard.assign(
        int(d["address"]), int(d["col"]), int(d["row"]), d["half"]))

@app.route("/api/wizard/skip", methods=["POST"])
def api_wizard_skip():
    d = request.get_json() or {}
    return jsonify(wizard.skip(int(d.get("address", 0))))

@app.route("/api/wizard/stop", methods=["POST"])
def api_wizard_stop():
    return jsonify(wizard.stop())

@app.route("/api/wizard/save", methods=["POST"])
def api_wizard_save():
    if not wizard.mappings:
        return jsonify({"success": False, "error": "No mappings"}), 400
    try:
        from flippydot import Panel
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
    log.info("  FLIPDOT CONSOLE V7")
    log.info("=" * 52)

    display.start()
    time.sleep(1.5)

    var_mod.configure(var_cfg)
    var_mod.start()

    load_last_show()

    log.info(f"Open: http://localhost:5000")
    log.info("=" * 52)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
