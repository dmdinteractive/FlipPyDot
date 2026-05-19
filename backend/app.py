"""
app.py — Flipdot Console V5
Professional control software with cue engine + scheduler.
Run: cd backend && python3 app.py
"""

import os, sys, time, threading, logging, numpy as np
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
import serial

# ── Paths ─────────────────────────────────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE, "..", "frontend")
sys.path.insert(0, BASE)

# ── Config ────────────────────────────────────────────────────────
PORT      = "/dev/cu.usbserial-BG01DCHX"
BAUD_RATE = 57600
LAYOUT    = [
    [0,  2,  4],
    [1,  3,  5],
    [6,  8,  10],
    [7,  9,  11],
    [12, 14, 16],
    [13, 15, 17],
]

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(BASE, "..", "flipdot.log"))
    ]
)
log = logging.getLogger(__name__)

# ── Imports ───────────────────────────────────────────────────────
from animations import list_animations, get_animation, anim_scroll_text
from cue_engine import CueEngine, Cue
from scheduler  import Scheduler, ScheduleItem
from wizard     import PanelWizard
import show as show_mgr

# ── Display core ──────────────────────────────────────────────────
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
    return send_frame(get_buf())

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
            time.sleep(delay)
    _anim_thread = threading.Thread(target=_run, daemon=True)
    _anim_thread.start()

def stop_anim():
    _anim_stop.set()

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
    w = w or W or 84; h = h or H or 42
    img = Image.new("L", (w, h), 255)
    ImageDraw.Draw(img).text((x, y), str(text), fill=0, font=get_font(fname, fsize))
    return (np.array(img) < 128).astype(np.uint8)

def render_scrolling(text, fname="default", fsize=14):
    font = get_font(fname, fsize)
    img  = Image.new("L", (8192, H or 42), 255)
    bbox = ImageDraw.Draw(img).textbbox((0,0), str(text), font=font)
    tw   = bbox[2] - bbox[0] + (W or 84) * 2
    return render_text(text, fname, fsize, x=(W or 84), w=tw)

# ── Cue executor ──────────────────────────────────────────────────
def execute_cue(cue: Cue):
    """Called by CueEngine to render a cue to the display."""
    global buffer
    ct = cue.content_type
    c  = cue.content
    opts = cue.options

    stop_anim()

    if ct == "clear":
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
        flush()
    elif ct == "fill":
        buffer = np.ones((H or 42, W or 84), dtype=np.uint8)
        flush()
    elif ct == "text":
        text   = c.get("text", "")
        fname  = c.get("font", "default")
        fsize  = int(c.get("font_size", 14))
        x      = int(c.get("x", 0))
        y      = int(c.get("y", 0))
        scroll = c.get("scroll", False)
        if scroll:
            run_anim(anim_scroll_text, render_scrolling(text, fname, fsize), W or 84)
        else:
            buffer = render_text(text, fname, fsize, x, y)
            flush()
    elif ct == "animation":
        anim_id = c.get("animation_id", "flash")
        fn = get_animation(anim_id)
        if fn:
            anim_opts = dict(opts)
            anim_opts.update(c.get("params", {}))
            run_anim(fn, W or 84, H or 42, **anim_opts)

    log.info(f"Executed cue {cue.number}: {cue.label} [{ct}]")


def execute_schedule_item(item: ScheduleItem):
    """Called by Scheduler to execute a schedule item."""
    fake_cue = Cue(
        label        = item.label,
        content_type = item.content_type,
        content      = item.content,
        duration     = item.duration,
        options      = item.options,
    )
    execute_cue(fake_cue)


# ── Core objects ──────────────────────────────────────────────────
cue_eng   = CueEngine(execute_cue)
scheduler = Scheduler(execute_schedule_item)
wizard    = PanelWizard(lambda: ser, total=18)

# ── Flask ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=FRONTEND)
CORS(app)

@app.route("/")
def index(): return send_from_directory(FRONTEND, "index.html")

@app.route("/<path:p>")
def static_f(p): return send_from_directory(FRONTEND, p)

# ── STATUS ────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify({
        "connected":  bool(ser and ser.is_open),
        "port":       PORT, "baud_rate": BAUD_RATE,
        "width":      W, "height": H,
        "cue_engine": cue_eng.get_status(),
        "scheduler":  scheduler.get_status(),
        "timestamp":  datetime.now().isoformat(),
    })

@app.route("/api/ports")
def api_ports():
    import serial.tools.list_ports
    return jsonify([{"port": p.device, "description": p.description}
                    for p in serial.tools.list_ports.comports()])

@app.route("/api/connect", methods=["POST"])
def api_connect():
    ok = connect_serial()
    return jsonify({"success": ok, "connected": ok})

@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    if ser: ser.close()
    return jsonify({"success": True})

# ── DISPLAY ───────────────────────────────────────────────────────
@app.route("/api/buffer")
def api_buf(): return jsonify({"buffer": get_buf().tolist()})

@app.route("/api/display/fill", methods=["POST"])
def api_fill():
    global buffer
    stop_anim()
    buffer = np.ones((H or 42, W or 84), dtype=np.uint8)
    flush(); return jsonify({"success": True})

@app.route("/api/display/clear", methods=["POST"])
def api_clear():
    global buffer
    stop_anim()
    buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    flush(); return jsonify({"success": True})

@app.route("/api/display/text", methods=["POST"])
def api_text():
    global buffer
    d      = request.get_json() or {}
    text   = d.get("text", "")
    fname  = d.get("font", "default")
    fsize  = int(d.get("font_size", 14))
    x      = int(d.get("x", 0))
    y      = int(d.get("y", 0))
    scroll = d.get("scroll", False)
    if d.get("clear", True):
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    stop_anim()
    if scroll:
        run_anim(anim_scroll_text, render_scrolling(text, fname, fsize), W or 84)
    else:
        bmp = render_text(text, fname, fsize, x, y)
        h_, w_ = bmp.shape
        hw = H or 42; ww = W or 84
        buffer[:min(h_,hw), :min(w_,ww)] = bmp[:min(h_,hw), :min(w_,ww)]
        flush()
    return jsonify({"success": True})

# ── ANIMATIONS ────────────────────────────────────────────────────
@app.route("/api/animations")
def api_anims(): return jsonify({"animations": list_animations()})

@app.route("/api/animations/run", methods=["POST"])
def api_run_anim():
    global _cur_anim
    d    = request.get_json() or {}
    name = d.get("name", "flash")
    fn   = get_animation(name)
    if not fn: return jsonify({"error": "Unknown animation"}), 404
    _cur_anim = name
    run_anim(fn, W or 84, H or 42, **d.get("options", {}))
    return jsonify({"success": True})

@app.route("/api/animations/stop", methods=["POST"])
def api_stop_anim():
    global _cur_anim
    stop_anim(); _cur_anim = None
    return jsonify({"success": True})

# ── CUE ENGINE ────────────────────────────────────────────────────
@app.route("/api/cues")
def api_get_cues(): return jsonify(cue_eng.get_status())

@app.route("/api/cues", methods=["POST"])
def api_add_cue():
    d   = request.get_json() or {}
    num = d.get("number")
    if num is None:
        nums = [c.number for c in cue_eng.cues if c.number is not None]
        num  = round((max(nums) + 1.0) if nums else 1.0, 3)
    cue = Cue(
        number       = float(num),
        label        = d.get("label", f"Cue {num}"),
        content_type = d.get("content_type", "clear"),
        content      = d.get("content", {}),
        pre_wait     = float(d.get("pre_wait", 0)),
        duration     = float(d.get("duration", 5)),
        fade_in      = float(d.get("fade_in", 0)),
        auto_follow  = bool(d.get("auto_follow", False)),
        options      = d.get("options", {}),
    )
    cue_eng.add_cue(cue)
    return jsonify({"success": True, "cue": cue.to_dict()})

@app.route("/api/cues/<cue_id>", methods=["PUT"])
def api_update_cue(cue_id):
    d   = request.get_json() or {}
    cue = cue_eng.update_cue(cue_id, d)
    return jsonify({"success": bool(cue), "cue": cue.to_dict() if cue else None})

@app.route("/api/cues/<cue_id>", methods=["DELETE"])
def api_del_cue(cue_id):
    cue_eng.remove_cue(cue_id)
    return jsonify({"success": True})

@app.route("/api/cues/renumber", methods=["POST"])
def api_renumber():
    cue_eng.renumber()
    return jsonify({"success": True, "cues": cue_eng.to_list()})

# Transport
@app.route("/api/transport/go", methods=["POST"])
def api_go():
    cue_eng.go()
    return jsonify({"success": True, "status": cue_eng.get_status()})

@app.route("/api/transport/back", methods=["POST"])
def api_back():
    cue_eng.back()
    return jsonify({"success": True, "status": cue_eng.get_status()})

@app.route("/api/transport/jump", methods=["POST"])
def api_jump():
    d = request.get_json() or {}
    cue_eng.jump(d.get("cue"))
    return jsonify({"success": True})

@app.route("/api/transport/release", methods=["POST"])
def api_release():
    cue_eng.release()
    return jsonify({"success": True})

@app.route("/api/transport/hold", methods=["POST"])
def api_hold():
    cue_eng.hold()
    return jsonify({"success": True})

# ── SCHEDULER ─────────────────────────────────────────────────────
@app.route("/api/scheduler")
def api_get_sched(): return jsonify(scheduler.get_status())

@app.route("/api/scheduler", methods=["POST"])
def api_add_sched():
    d = request.get_json() or {}
    st = d.get("start_time")
    if st:
        try: st = datetime.fromisoformat(st)
        except: st = None
    item = ScheduleItem(
        label        = d.get("label", ""),
        content_type = d.get("content_type", "text"),
        content      = d.get("content", {}),
        mode         = d.get("mode", ScheduleItem.REPEAT),
        duration     = float(d.get("duration", 5)),
        interval     = float(d.get("interval", 60)),
        start_time   = st,
        end_time     = d.get("end_time"),
        days         = d.get("days", []),
        priority     = int(d.get("priority", 0)),
        options      = d.get("options", {}),
    )
    scheduler.add(item)
    return jsonify({"success": True, "item": item.to_dict()})

@app.route("/api/scheduler/<item_id>", methods=["PUT"])
def api_update_sched(item_id):
    d    = request.get_json() or {}
    item = scheduler.update(item_id, d)
    return jsonify({"success": bool(item)})

@app.route("/api/scheduler/<item_id>", methods=["DELETE"])
def api_del_sched(item_id):
    scheduler.remove(item_id)
    return jsonify({"success": True})

@app.route("/api/scheduler/start", methods=["POST"])
def api_start_sched():
    scheduler.start()
    return jsonify({"success": True})

@app.route("/api/scheduler/stop", methods=["POST"])
def api_stop_sched():
    scheduler.stop()
    return jsonify({"success": True})

# ── SHOW FILES ────────────────────────────────────────────────────
@app.route("/api/shows")
def api_list_shows():
    return jsonify({"shows": show_mgr.list_shows()})

@app.route("/api/shows/save", methods=["POST"])
def api_save_show():
    d    = request.get_json() or {}
    name = d.get("name", "untitled")
    cfg  = {"port": PORT, "baud_rate": BAUD_RATE, "layout": LAYOUT}
    path = show_mgr.save_show(name, cue_eng, scheduler, cfg)
    return jsonify({"success": True, "path": path})

@app.route("/api/shows/load", methods=["POST"])
def api_load_show():
    d    = request.get_json() or {}
    name = d.get("name", "")
    try:
        data = show_mgr.load_show(name, cue_eng, scheduler)
        return jsonify({"success": True, "meta": data.get("meta", {})})
    except FileNotFoundError as e:
        return jsonify({"success": False, "error": str(e)}), 404

@app.route("/api/shows/<name>", methods=["DELETE"])
def api_del_show(name):
    ok = show_mgr.delete_show(name)
    return jsonify({"success": ok})

# ── WIZARD ────────────────────────────────────────────────────────
@app.route("/api/wizard/state")
def api_wiz_state(): return jsonify(wizard.get_state())

@app.route("/api/wizard/start", methods=["POST"])
def api_wiz_start():
    d = request.get_json() or {}
    return jsonify(wizard.start(d.get("total", 18)))

@app.route("/api/wizard/assign", methods=["POST"])
def api_wiz_assign():
    d = request.get_json() or {}
    return jsonify(wizard.assign(int(d["address"]), int(d["col"]), int(d["row"]), d["half"]))

@app.route("/api/wizard/skip", methods=["POST"])
def api_wiz_skip():
    d = request.get_json() or {}
    return jsonify(wizard.skip(int(d.get("address", 0))))

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
        panel  = FP(new_layout, 28, 7, module_rotation=0, screen_preview=False)
        W      = panel.get_total_width()
        H      = panel.get_total_height()
        buffer = np.zeros((H, W), dtype=np.uint8)
        return jsonify({"success": True, "layout": new_layout, "width": W, "height": H})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── BOOT ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 56)
    log.info("  FLIPDOT CONSOLE V5")
    log.info("=" * 56)
    connect_serial()
    log.info(f"Open: http://localhost:5000")
    log.info("=" * 56)
    app.run(host="0.0.0.0", port=5000, debug=False)
