"""
app.py — Flipdot Console V5.1
Adds: WebSockets, image import, pixel editor, variable system
Run: cd backend && python3 app.py
"""

import os, sys, time, threading, logging, numpy as np, json
from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from datetime import datetime
import serial

BASE     = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE, "..", "frontend")
sys.path.insert(0, BASE)

# ── Config ────────────────────────────────────────────────────────
def load_config():
    cfg_path = os.path.join(BASE, "..", "config", "config.json")
    defaults = {"port": "/dev/cu.usbserial-BG01DCHX", "baud_rate": 57600}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path) as f:
                return {**defaults, **json.load(f)}
        except: pass
    return defaults

def load_layout():
    lyt_path = os.path.join(BASE, "..", "config", "layout.json")
    default  = [[0,2,4],[1,3,5],[6,8,10],[7,9,11],[12,14,16],[13,15,17]]
    if os.path.isfile(lyt_path):
        try:
            with open(lyt_path) as f: return json.load(f)
        except: pass
    return default

def save_layout(layout):
    os.makedirs(os.path.join(BASE, "..", "config"), exist_ok=True)
    with open(os.path.join(BASE, "..", "config", "layout.json"), "w") as f:
        json.dump(layout, f, indent=2)

cfg    = load_config()
PORT      = os.environ.get("FLIPDOT_PORT", cfg["port"])
BAUD_RATE = int(os.environ.get("FLIPDOT_BAUD", cfg["baud_rate"]))
LAYOUT    = load_layout()

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(BASE, "..", "flipdot.log"))])
log = logging.getLogger(__name__)

# ── Imports ───────────────────────────────────────────────────────
from animations     import list_animations, get_animation, anim_scroll_text
from cue_engine     import CueEngine, Cue
from scheduler      import Scheduler, ScheduleItem
from wizard         import PanelWizard
from variables      import substitute, get_all_values, get_status as var_status
from image_processor import process_image, frames_to_json, bitmap_to_json
import variables as var_mod
import show as show_mgr

# ── Display ───────────────────────────────────────────────────────
from flippydot import Panel
from PIL import Image, ImageDraw, ImageFont

ser = panel = None
W = H = 0
buffer = None

def connect_serial():
    global ser, panel, W, H, buffer
    try:
        ser   = serial.Serial(port=PORT, baudrate=BAUD_RATE,
                              bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                              stopbits=serial.STOPBITS_ONE, timeout=1.0)
        panel = Panel(LAYOUT, 28, 7, module_rotation=0, screen_preview=False)
        W     = panel.get_total_width()
        H     = panel.get_total_height()
        buffer = np.zeros((H, W), dtype=np.uint8)
        log.info(f"Connected: {PORT} @ {BAUD_RATE} — {W}x{H}")
        return True
    except Exception as e:
        log.error(f"Connect failed: {e}")
        W = 84; H = 42
        buffer = np.zeros((H, W), dtype=np.uint8)
        return False

def get_buf():
    global buffer
    if buffer is None:
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    return buffer

def send_frame(frame):
    if not ser or not ser.is_open or panel is None: return False
    try:
        data = panel.apply_frame(frame)
        raw  = b"".join(data.flatten().tolist()) if isinstance(data, np.ndarray) else bytes(data)
        ser.write(raw)
        return True
    except Exception as e:
        log.error(f"Send error: {e}")
        return False

def flush():
    ok = send_frame(get_buf())
    if ok: _emit_buffer()
    return ok

def _emit_buffer():
    """Push buffer update to all connected WebSocket clients."""
    try:
        socketio.emit("buffer", {"buffer": get_buf().tolist()})
    except: pass

# ── Animation runner ──────────────────────────────────────────────
_anim_thread = None
_anim_stop   = threading.Event()
_cur_anim    = None

def run_anim(fn, *args, **kwargs):
    global _anim_thread, _cur_anim, buffer
    _anim_stop.set()
    time.sleep(0.05)
    _anim_stop.clear()
    def _run():
        global buffer
        for frame, delay in fn(*args, **kwargs):
            if _anim_stop.is_set(): break
            buffer = frame
            send_frame(frame)
            _emit_buffer()
            time.sleep(delay)
    _anim_thread = threading.Thread(target=_run, daemon=True)
    _anim_thread.start()

def stop_anim():
    _anim_stop.set()

# ── GIF playback ──────────────────────────────────────────────────
def play_gif_frames(frames: list, loop: int = 1):
    """Play a list of (bitmap, duration_ms) frames."""
    def _run():
        global buffer
        for _ in range(loop if loop > 0 else 9999):
            for bmp, dur in frames:
                if _anim_stop.is_set(): return
                arr = np.array(bmp, dtype=np.uint8)
                buffer = arr
                send_frame(arr)
                _emit_buffer()
                time.sleep(max(0.033, dur / 1000.0))
    stop_anim()
    time.sleep(0.05)
    _anim_stop.clear()
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# ── Text renderer ─────────────────────────────────────────────────
FONTS_DIR = os.path.join(BASE, "..", "fonts")

def get_font(name, size):
    if name and name != "default":
        p = os.path.join(FONTS_DIR, name)
        if os.path.isfile(p):
            try: return ImageFont.truetype(p, int(size))
            except: pass
    return ImageFont.load_default()

def render_text(text, fname="default", fsize=14, x=0, y=0, w=None, h=None):
    text = substitute(text)   # Apply variable substitution
    w = w or W or 84; h = h or H or 42
    img = Image.new("L", (w, h), 255)
    ImageDraw.Draw(img).text((x, y), str(text), fill=0, font=get_font(fname, fsize))
    return (np.array(img) < 128).astype(np.uint8)

def render_scrolling(text, fname="default", fsize=14):
    text = substitute(text)
    font = get_font(fname, fsize)
    img  = Image.new("L", (8192, H or 42), 255)
    bbox = ImageDraw.Draw(img).textbbox((0,0), str(text), font=font)
    tw   = bbox[2] - bbox[0] + (W or 84) * 2
    return render_text(text, fname, fsize, x=(W or 84), w=tw)

# ── Cue executor ──────────────────────────────────────────────────
def execute_cue(cue: Cue):
    global buffer
    ct = cue.content_type
    c  = cue.content or {}
    stop_anim()
    if ct == "clear":
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8); flush()
    elif ct == "fill":
        buffer = np.ones((H or 42, W or 84), dtype=np.uint8); flush()
    elif ct == "text":
        text   = c.get("text", "")
        fname  = c.get("font", "default")
        fsize  = int(c.get("font_size", 14))
        x, y   = int(c.get("x",0)), int(c.get("y",0))
        scroll = c.get("scroll", False)
        if scroll: run_anim(anim_scroll_text, render_scrolling(text,fname,fsize), W or 84)
        else:
            buffer = render_text(text, fname, fsize, x, y); flush()
    elif ct == "animation":
        fn = get_animation(c.get("animation_id","flash"))
        if fn: run_anim(fn, W or 84, H or 42, **c.get("params", {}))
    elif ct == "image":
        frames_data = c.get("frames", [])
        if frames_data:
            frames = [(np.array(f["bitmap"], dtype=np.uint8), f["duration"]) for f in frames_data]
            play_gif_frames(frames, loop=c.get("loop", 1))
    _emit_status()
    log.info(f"Executed cue {cue.number}: {cue.label} [{ct}]")

def execute_schedule_item(item: ScheduleItem):
    fake = Cue(label=item.label, content_type=item.content_type,
               content=item.content, duration=item.duration, options=item.options)
    execute_cue(fake)

# ── Core objects ──────────────────────────────────────────────────
cue_eng   = CueEngine(execute_cue)
scheduler = Scheduler(execute_schedule_item)
wizard    = PanelWizard(lambda: ser, total=18)

# ── Flask + SocketIO ──────────────────────────────────────────────
app       = Flask(__name__, static_folder=FRONTEND)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio  = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

@app.route("/")
def index(): return send_from_directory(FRONTEND, "index.html")

@app.route("/<path:p>")
def static_f(p): return send_from_directory(FRONTEND, p)

# ── WebSocket events ──────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    log.info(f"WebSocket client connected")
    emit("status",  _build_status())
    emit("buffer",  {"buffer": get_buf().tolist()})

@socketio.on("disconnect")
def on_disconnect():
    log.info("WebSocket client disconnected")

@socketio.on("go")
def on_go(_):      cue_eng.go();      _emit_status()

@socketio.on("back")
def on_back(_):    cue_eng.back();    _emit_status()

@socketio.on("release")
def on_release(_): cue_eng.release(); _emit_status()

@socketio.on("hold")
def on_hold(_):    cue_eng.hold();    _emit_status()

def _emit_status():
    socketio.emit("status", _build_status())

def _build_status():
    return {
        "connected":  bool(ser and ser.is_open),
        "port": PORT, "baud_rate": BAUD_RATE,
        "width": W, "height": H,
        "cue_engine": cue_eng.get_status(),
        "scheduler":  {"running": scheduler.running,
                       "items": [i.to_dict() for i in scheduler.items]},
        "timestamp":  datetime.now().isoformat(),
    }

# ── Status polling endpoint (fallback) ───────────────────────────
@app.route("/api/status")
def api_status(): return jsonify(_build_status())

@app.route("/api/ports")
def api_ports():
    import serial.tools.list_ports
    return jsonify([{"port":p.device,"description":p.description}
                    for p in serial.tools.list_ports.comports()])

@app.route("/api/connect", methods=["POST"])
def api_connect():
    ok = connect_serial()
    _emit_status()
    return jsonify({"success": ok, "connected": ok})

@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    if ser: ser.close()
    _emit_status()
    return jsonify({"success": True})

# ── Display ───────────────────────────────────────────────────────
@app.route("/api/buffer")
def api_buf(): return jsonify({"buffer": get_buf().tolist()})

@app.route("/api/buffer", methods=["POST"])
def api_set_buf():
    global buffer
    d = request.get_json() or {}
    b = d.get("buffer")
    if not b: return jsonify({"success": False}), 400
    buffer = np.array(b, dtype=np.uint8)
    flush()
    return jsonify({"success": True})

@app.route("/api/display/fill", methods=["POST"])
def api_fill():
    global buffer
    stop_anim(); buffer = np.ones((H or 42, W or 84), dtype=np.uint8); flush()
    return jsonify({"success": True})

@app.route("/api/display/clear", methods=["POST"])
def api_clear():
    global buffer
    stop_anim(); buffer = np.zeros((H or 42, W or 84), dtype=np.uint8); flush()
    return jsonify({"success": True})

@app.route("/api/display/text", methods=["POST"])
def api_text():
    global buffer
    d = request.get_json() or {}
    text   = d.get("text", "")
    fname  = d.get("font", "default")
    fsize  = int(d.get("font_size", 14))
    x, y   = int(d.get("x",0)), int(d.get("y",0))
    scroll = d.get("scroll", False)
    if d.get("clear", True):
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    stop_anim()
    if scroll:
        run_anim(anim_scroll_text, render_scrolling(text,fname,fsize), W or 84)
    else:
        bmp = render_text(text, fname, fsize, x, y)
        hw = H or 42; ww = W or 84
        buffer[:min(bmp.shape[0],hw), :min(bmp.shape[1],ww)] = bmp[:min(bmp.shape[0],hw),:min(bmp.shape[1],ww)]
        flush()
    return jsonify({"success": True})

# ── IMAGE UPLOAD ──────────────────────────────────────────────────
@app.route("/api/image/upload", methods=["POST"])
def api_image_upload():
    """Upload image file and convert to 1-bit bitmap."""
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    data = file.read()

    threshold  = int(request.form.get("threshold", 128))
    brightness = float(request.form.get("brightness", 1.0))
    contrast   = float(request.form.get("contrast", 1.0))
    dither     = request.form.get("dither", "none")
    scale      = request.form.get("scale", "fit")
    invert     = request.form.get("invert", "false").lower() == "true"

    try:
        frames = process_image(data, W or 84, H or 42,
                               threshold, brightness, contrast,
                               dither, scale, invert)
        return jsonify({
            "success":    True,
            "frames":     frames_to_json(frames),
            "frame_count":len(frames),
            "animated":   len(frames) > 1,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/image/display", methods=["POST"])
def api_image_display():
    """Display previously processed image frames."""
    global buffer
    d      = request.get_json() or {}
    frames_data = d.get("frames", [])
    loop   = int(d.get("loop", 1))
    if not frames_data:
        return jsonify({"success": False, "error": "No frames"}), 400
    frames = [(np.array(f["bitmap"], dtype=np.uint8), f["duration"]) for f in frames_data]
    if len(frames) == 1 and frames[0][1] == 0:
        buffer = frames[0][0]
        flush()
    else:
        play_gif_frames(frames, loop=loop)
    return jsonify({"success": True, "frames": len(frames)})

# ── PIXEL EDITOR ──────────────────────────────────────────────────
@app.route("/api/pixel/push", methods=["POST"])
def api_pixel_push():
    """Push pixel editor buffer to display."""
    global buffer
    d = request.get_json() or {}
    b = d.get("buffer")
    if not b: return jsonify({"success": False}), 400
    buffer = np.array(b, dtype=np.uint8)
    flush()
    return jsonify({"success": True})

# ── VARIABLES ─────────────────────────────────────────────────────
@app.route("/api/variables")
def api_vars_status(): return jsonify(var_status())

@app.route("/api/variables/config", methods=["POST"])
def api_vars_config():
    d = request.get_json() or {}
    var_mod.configure(d)
    return jsonify({"success": True})

@app.route("/api/variables/values")
def api_vars_values(): return jsonify(get_all_values())

@app.route("/api/variables/preview", methods=["POST"])
def api_vars_preview():
    """Preview variable substitution in a text string."""
    d    = request.get_json() or {}
    text = d.get("text", "")
    return jsonify({"original": text, "substituted": substitute(text)})

@app.route("/api/variables/advance_rss", methods=["POST"])
def api_advance_rss():
    var_mod.advance_rss()
    return jsonify({"success": True})

# ── ANIMATIONS ────────────────────────────────────────────────────
@app.route("/api/animations")
def api_anims(): return jsonify({"animations": list_animations()})

@app.route("/api/animations/run", methods=["POST"])
def api_run_anim():
    global _cur_anim
    d = request.get_json() or {}
    fn = get_animation(d.get("name","flash"))
    if not fn: return jsonify({"error": "Unknown"}), 404
    _cur_anim = d.get("name")
    run_anim(fn, W or 84, H or 42, **d.get("options", {}))
    return jsonify({"success": True})

@app.route("/api/animations/stop", methods=["POST"])
def api_stop_anim_route():
    global _cur_anim; stop_anim(); _cur_anim = None
    return jsonify({"success": True})

# ── CUE ENGINE ────────────────────────────────────────────────────
@app.route("/api/cues")
def api_get_cues(): return jsonify(cue_eng.get_status())

@app.route("/api/cues", methods=["POST"])
def api_add_cue():
    d = request.get_json() or {}
    num = d.get("number")
    if num is None:
        nums = [c.number for c in cue_eng.cues if c.number is not None]
        num  = round((max(nums) + 1.0) if nums else 1.0, 3)
    cue = Cue(number=float(num), label=d.get("label", f"Cue {num}"),
              content_type=d.get("content_type","clear"), content=d.get("content",{}),
              pre_wait=float(d.get("pre_wait",0)), duration=float(d.get("duration",5)),
              fade_in=float(d.get("fade_in",0)), auto_follow=bool(d.get("auto_follow",False)),
              options=d.get("options",{}))
    cue_eng.add_cue(cue)
    _emit_status()
    return jsonify({"success": True, "cue": cue.to_dict()})

@app.route("/api/cues/<cue_id>", methods=["PUT"])
def api_update_cue(cue_id):
    d = request.get_json() or {}
    cue = cue_eng.update_cue(cue_id, d)
    _emit_status()
    return jsonify({"success": bool(cue), "cue": cue.to_dict() if cue else None})

@app.route("/api/cues/<cue_id>", methods=["DELETE"])
def api_del_cue(cue_id):
    cue_eng.remove_cue(cue_id); _emit_status()
    return jsonify({"success": True})

@app.route("/api/cues/renumber", methods=["POST"])
def api_renumber():
    cue_eng.renumber(); _emit_status()
    return jsonify({"success": True})

@app.route("/api/transport/go",      methods=["POST"])
def api_go():      cue_eng.go();      _emit_status(); return jsonify({"success": True})
@app.route("/api/transport/back",    methods=["POST"])
def api_back():    cue_eng.back();    _emit_status(); return jsonify({"success": True})
@app.route("/api/transport/jump",    methods=["POST"])
def api_jump():
    d = request.get_json() or {}; cue_eng.jump(d.get("cue")); _emit_status()
    return jsonify({"success": True})
@app.route("/api/transport/release", methods=["POST"])
def api_release(): cue_eng.release(); _emit_status(); return jsonify({"success": True})
@app.route("/api/transport/hold",    methods=["POST"])
def api_hold():    cue_eng.hold();    _emit_status(); return jsonify({"success": True})

# ── SCHEDULER ─────────────────────────────────────────────────────
@app.route("/api/scheduler")
def api_get_sched():
    return jsonify({"running": scheduler.running,
                    "items": [i.to_dict() for i in scheduler.items]})

@app.route("/api/scheduler", methods=["POST"])
def api_add_sched():
    d  = request.get_json() or {}
    st = d.get("start_time")
    if st:
        try: st = datetime.fromisoformat(st)
        except: st = None
    item = ScheduleItem(label=d.get("label",""), content_type=d.get("content_type","text"),
                        content=d.get("content",{}), mode=d.get("mode","repeat"),
                        duration=float(d.get("duration",5)), interval=float(d.get("interval",60)),
                        start_time=st, end_time=d.get("end_time"), days=d.get("days",[]),
                        priority=int(d.get("priority",0)), options=d.get("options",{}))
    scheduler.add(item)
    return jsonify({"success": True, "item": item.to_dict()})

@app.route("/api/scheduler/<item_id>", methods=["PUT"])
def api_update_sched(item_id):
    scheduler.update(item_id, request.get_json() or {})
    return jsonify({"success": True})

@app.route("/api/scheduler/<item_id>", methods=["DELETE"])
def api_del_sched(item_id):
    scheduler.remove(item_id); return jsonify({"success": True})

@app.route("/api/scheduler/start", methods=["POST"])
def api_start_sched():
    scheduler.start(); _emit_status(); return jsonify({"success": True})

@app.route("/api/scheduler/stop", methods=["POST"])
def api_stop_sched():
    scheduler.stop(); _emit_status(); return jsonify({"success": True})

# ── SHOWS ─────────────────────────────────────────────────────────
@app.route("/api/shows")
def api_list_shows(): return jsonify({"shows": show_mgr.list_shows()})

@app.route("/api/shows/save", methods=["POST"])
def api_save_show():
    d    = request.get_json() or {}
    name = d.get("name", "untitled")
    path = show_mgr.save_show(name, cue_eng, scheduler,
                              {"port": PORT, "baud_rate": BAUD_RATE, "layout": LAYOUT})
    return jsonify({"success": True, "path": path})

@app.route("/api/shows/load", methods=["POST"])
def api_load_show():
    d    = request.get_json() or {}
    name = d.get("name","")
    try:
        data = show_mgr.load_show(name, cue_eng, scheduler)
        _emit_status()
        return jsonify({"success": True, "meta": data.get("meta",{})})
    except FileNotFoundError as e:
        return jsonify({"success": False, "error": str(e)}), 404

@app.route("/api/shows/<name>", methods=["DELETE"])
def api_del_show(name):
    return jsonify({"success": show_mgr.delete_show(name)})

# ── WIZARD ────────────────────────────────────────────────────────
@app.route("/api/wizard/state")
def api_wiz_state(): return jsonify(wizard.get_state())

@app.route("/api/wizard/start", methods=["POST"])
def api_wiz_start():
    d = request.get_json() or {}
    return jsonify(wizard.start(d.get("total",18)))

@app.route("/api/wizard/assign", methods=["POST"])
def api_wiz_assign():
    d = request.get_json() or {}
    return jsonify(wizard.assign(int(d["address"]),int(d["col"]),int(d["row"]),d["half"]))

@app.route("/api/wizard/skip", methods=["POST"])
def api_wiz_skip():
    d = request.get_json() or {}
    return jsonify(wizard.skip(int(d.get("address",0))))

@app.route("/api/wizard/stop", methods=["POST"])
def api_wiz_stop(): return jsonify(wizard.stop())

@app.route("/api/wizard/save", methods=["POST"])
def api_wiz_save():
    global panel, W, H, buffer
    if not wizard.mappings:
        return jsonify({"success": False, "error": "No mappings"}), 400
    try:
        from flippydot import Panel as FP
        new_layout = wizard.build_layout()
        save_layout(new_layout)
        panel  = FP(new_layout, 28, 7, module_rotation=0, screen_preview=False)
        W      = panel.get_total_width()
        H      = panel.get_total_height()
        buffer = np.zeros((H, W), dtype=np.uint8)
        return jsonify({"success": True, "layout": new_layout})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── BOOT ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 56)
    log.info("  FLIPDOT CONSOLE V5.1")
    log.info("=" * 56)
    connect_serial()
    var_mod.start()
    log.info("Open: http://localhost:5000")
    log.info("=" * 56)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False,
                 allow_unsafe_werkzeug=True)
