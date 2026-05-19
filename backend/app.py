"""
app.py — Flipdot Controller Web Server
Built directly on the working flipPyDot foundation.
Run: python3 backend/app.py
Open: http://localhost:5000
"""

import os, sys, time, threading, logging
import numpy as np
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
import serial

sys.path.insert(0, os.path.dirname(__file__))

# ── Config ────────────────────────────────────────────────────────
PORT       = "/dev/cu.usbserial-BG01DCHX"
BAUD_RATE  = 57600
LAYOUT     = [
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
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("flipdot.log")]
)
log = logging.getLogger(__name__)

# ── Display core (same as working flipdot.py) ─────────────────────
from flippydot import Panel

ser   = None
panel = None
W     = 0
H     = 0

def connect_serial():
    global ser, panel, W, H
    try:
        ser = serial.Serial(
            port=PORT, baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE, timeout=1.0
        )
        panel = Panel(LAYOUT, 28, 7, module_rotation=0, screen_preview=False)
        W = panel.get_total_width()
        H = panel.get_total_height()
        log.info(f"Connected: {PORT} @ {BAUD_RATE} — display {W}x{H}")
        return True
    except Exception as e:
        log.error(f"Connection failed: {e}")
        return False

def send_frame(frame: np.ndarray) -> bool:
    if ser is None or not ser.is_open: return False
    try:
        data = panel.apply_frame(frame)
        raw  = b"".join(data.flatten().tolist()) if isinstance(data, np.ndarray) else bytes(data)
        ser.write(raw)
        return True
    except Exception as e:
        log.error(f"Send failed: {e}")
        return False

# Virtual buffer
buffer = None
def get_buffer():
    global buffer
    if buffer is None:
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    return buffer

def flush():
    return send_frame(get_buffer())

# ── Animation control ─────────────────────────────────────────────
_anim_thread   = None
_anim_stop     = threading.Event()
_anim_lock     = threading.Lock()
_current_anim  = None

def run_animation(gen_fn, *args, **kwargs):
    global _anim_thread, _current_anim
    _anim_stop.set()
    time.sleep(0.05)
    _anim_stop.clear()
    def _run():
        for frame, delay in gen_fn(*args, **kwargs):
            if _anim_stop.is_set(): break
            global buffer
            buffer = frame
            send_frame(frame)
            time.sleep(delay)
    _anim_thread = threading.Thread(target=_run, daemon=True)
    _anim_thread.start()

def stop_animation():
    _anim_stop.set()

# ── Animations ────────────────────────────────────────────────────
def anim_fill(w, h, delay=0.015):
    frame = np.zeros((h, w), dtype=np.uint8)
    for x in range(w):
        frame[:, x] = 1
        yield frame.copy(), delay

def anim_clear_sweep(w, h, delay=0.015):
    frame = np.ones((h, w), dtype=np.uint8)
    for x in range(w):
        frame[:, x] = 0
        yield frame.copy(), delay

def anim_flash(w, h, times=6, delay=0.12):
    for _ in range(times):
        yield np.ones((h, w),  dtype=np.uint8), delay
        yield np.zeros((h, w), dtype=np.uint8), delay

def anim_checkerboard(w, h, cycles=8, delay=0.18):
    for phase in range(cycles):
        frame = np.fromfunction(lambda y, x: (x + y + phase) % 2, (h, w), dtype=int).astype(np.uint8)
        yield frame, delay

def anim_rain(w, h, frames=80, delay=0.06):
    import random
    drops = np.zeros(w, dtype=int)
    for _ in range(frames):
        frame = np.zeros((h, w), dtype=np.uint8)
        for x in range(w):
            if random.random() < 0.3:
                drops[x] = (drops[x] + 1) % (h + 3)
            y = drops[x]
            if y < h:     frame[y, x] = 1
            if y-1 >= 0:  frame[y-1, x] = 1
        yield frame, delay

def anim_bounce(w, h, frames=150, delay=0.04):
    import math
    x, y, dx, dy = w//2, h//2, 1, 1
    for _ in range(frames):
        frame = np.zeros((h, w), dtype=np.uint8)
        for by in range(max(0,y-1), min(h,y+2)):
            for bx in range(max(0,x-1), min(w,x+2)):
                frame[by, bx] = 1
        yield frame, delay
        x += dx; y += dy
        if x <= 0 or x >= w-1: dx *= -1
        if y <= 0 or y >= h-1: dy *= -1

def anim_sine(w, h, frames=80, delay=0.04):
    import math
    for n in range(frames):
        frame = np.zeros((h, w), dtype=np.uint8)
        for x in range(w):
            y = int((math.sin((x/w)*4*math.pi + n*0.15)+1)/2*(h-1))
            frame[min(y, h-1), x] = 1
            if y+1 < h: frame[y+1, x] = 1
        yield frame, delay

def anim_scroll_text(bitmap: np.ndarray, dw: int, delay=0.04):
    bw = bitmap.shape[1]
    for offset in range(bw - dw + 1):
        yield bitmap[:, offset:offset+dw].copy(), delay

ANIMATIONS = {
    "wipe_on":       (anim_fill,          "Wipe On"),
    "wipe_off":      (anim_clear_sweep,   "Wipe Off"),
    "flash":         (anim_flash,         "Flash"),
    "checkerboard":  (anim_checkerboard,  "Checkerboard"),
    "rain":          (anim_rain,          "Rain"),
    "bounce":        (anim_bounce,        "Bounce Ball"),
    "sine":          (anim_sine,          "Sine Wave"),
}

# ── Text renderer ─────────────────────────────────────────────────
from PIL import Image, ImageDraw, ImageFont
import os

FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")

def get_font(name, size):
    if name and name != "default":
        path = os.path.join(FONTS_DIR, name)
        if os.path.isfile(path):
            try: return ImageFont.truetype(path, size)
            except: pass
    return ImageFont.load_default()

def render_text(text, font_name="default", font_size=14, x=0, y=0, w=None, h=None):
    w = w or W; h = h or H
    img  = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    draw.text((x, y), text, fill=0, font=get_font(font_name, font_size))
    return (np.array(img, dtype=np.uint8) < 128).astype(np.uint8)

def render_scrolling(text, font_name="default", font_size=14, padding=84):
    font     = get_font(font_name, font_size)
    img_test = Image.new("L", (8192, H), 255)
    draw     = ImageDraw.Draw(img_test)
    bbox     = draw.textbbox((0,0), text, font=font)
    tw       = bbox[2] - bbox[0] + padding * 2
    return render_text(text, font_name, font_size, x=padding, w=tw)

# ── Scheduler ─────────────────────────────────────────────────────
import uuid as _uuid

schedule_items = []
scheduler_running = False
scheduler_thread  = None

class ScheduleItem:
    def __init__(self, type_, content, duration=5.0, repeat=False,
                 interval=60.0, start_time=None, options=None):
        self.id         = str(_uuid.uuid4())[:8]
        self.type       = type_
        self.content    = content
        self.duration   = duration
        self.repeat     = repeat
        self.interval   = interval
        self.start_time = start_time
        self.options    = options or {}
        self.last_run   = None
        self.enabled    = True

    def to_dict(self):
        return {
            "id": self.id, "type": self.type, "content": self.content,
            "duration": self.duration, "repeat": self.repeat,
            "interval": self.interval,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "last_run": self.last_run, "enabled": self.enabled,
            "options": self.options,
        }

def scheduler_loop():
    global scheduler_running
    while scheduler_running:
        now = time.time()
        for item in list(schedule_items):
            if not item.enabled: continue
            if item.start_time and item.start_time > datetime.now(): continue
            if item.last_run is None or (item.repeat and now - item.last_run >= item.interval):
                item.last_run = now
                _execute_item(item)
        time.sleep(1.0)

def _execute_item(item):
    opts = item.options
    if item.type == "text":
        scroll = opts.get("scroll", False)
        font   = opts.get("font", "default")
        fsize  = int(opts.get("font_size", 14))
        if scroll:
            bmp = render_scrolling(item.content, font, fsize)
            run_animation(anim_scroll_text, bmp, W)
        else:
            global buffer
            buffer = render_text(item.content, font, fsize)
            flush()
            time.sleep(item.duration)
    elif item.type == "animation":
        fn_tuple = ANIMATIONS.get(item.content)
        if fn_tuple:
            run_animation(fn_tuple[0], W, H)
            time.sleep(item.duration)

# ── Flask app ─────────────────────────────────────────────────────
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")
app      = Flask(__name__, static_folder=FRONTEND)
CORS(app)

@app.route("/")
def index(): return send_from_directory(FRONTEND, "index.html")

@app.route("/<path:p>")
def static_f(p): return send_from_directory(FRONTEND, p)

# Status
@app.route("/api/status")
def api_status():
    connected = ser is not None and ser.is_open
    return jsonify({
        "connected": connected,
        "port": PORT, "baud_rate": BAUD_RATE,
        "width": W, "height": H,
        "scheduler_running": scheduler_running,
        "current_animation": _current_anim,
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

# Buffer
@app.route("/api/buffer")
def api_get_buffer():
    return jsonify({"buffer": get_buffer().tolist()})

@app.route("/api/display/fill", methods=["POST"])
def api_fill():
    global buffer
    buffer = np.ones((H, W), dtype=np.uint8)
    flush()
    return jsonify({"success": True})

@app.route("/api/display/clear", methods=["POST"])
def api_clear():
    global buffer
    buffer = np.zeros((H, W), dtype=np.uint8)
    flush()
    return jsonify({"success": True})

# Text
@app.route("/api/display/text", methods=["POST"])
def api_text():
    global buffer
    d         = request.get_json() or {}
    text      = d.get("text", "")
    font      = d.get("font", "default")
    font_size = int(d.get("font_size", 14))
    x         = int(d.get("x", 0))
    y         = int(d.get("y", 0))
    scroll    = d.get("scroll", False)
    if d.get("clear", True): buffer = np.zeros((H, W), dtype=np.uint8)
    if scroll:
        bmp = render_scrolling(text, font, font_size)
        run_animation(anim_scroll_text, bmp, W)
    else:
        bmp = render_text(text, font, font_size, x, y)
        h_, w_ = bmp.shape
        buffer[:min(h_, H), :min(w_, W)] = bmp[:min(h_, H), :min(w_, W)]
        flush()
    return jsonify({"success": True})

# Animations
@app.route("/api/animations")
def api_anims():
    return jsonify({"animations": [{"id": k, "name": v[1]} for k, v in ANIMATIONS.items()]})

@app.route("/api/animations/run", methods=["POST"])
def api_run_anim():
    global _current_anim
    d    = request.get_json() or {}
    name = d.get("name", "flash")
    fn_t = ANIMATIONS.get(name)
    if not fn_t: return jsonify({"error": "Unknown animation"}), 404
    _current_anim = name
    run_animation(fn_t[0], W, H)
    return jsonify({"success": True})

@app.route("/api/animations/stop", methods=["POST"])
def api_stop_anim():
    global _current_anim
    stop_animation()
    _current_anim = None
    return jsonify({"success": True})

# Schedule
@app.route("/api/schedule")
def api_get_sched():
    return jsonify({"items": [i.to_dict() for i in schedule_items],
                    "running": scheduler_running})

@app.route("/api/schedule", methods=["POST"])
def api_add_sched():
    d  = request.get_json() or {}
    st = d.get("start_time")
    if st: st = datetime.fromisoformat(st)
    item = ScheduleItem(
        type_    = d.get("type", "text"),
        content  = d.get("content", ""),
        duration = float(d.get("duration", 5)),
        repeat   = d.get("repeat", False),
        interval = float(d.get("interval", 60)),
        start_time = st,
        options  = d.get("options", {}),
    )
    schedule_items.append(item)
    return jsonify({"success": True, "item": item.to_dict()})

@app.route("/api/schedule/<id>", methods=["DELETE"])
def api_del_sched(id):
    global schedule_items
    schedule_items = [i for i in schedule_items if i.id != id]
    return jsonify({"success": True})

@app.route("/api/schedule/start", methods=["POST"])
def api_start_sched():
    global scheduler_running, scheduler_thread
    if not scheduler_running:
        scheduler_running = True
        scheduler_thread  = threading.Thread(target=scheduler_loop, daemon=True)
        scheduler_thread.start()
    return jsonify({"success": True})

@app.route("/api/schedule/stop", methods=["POST"])
def api_stop_sched():
    global scheduler_running
    scheduler_running = False
    return jsonify({"success": True})

# ── Panel Mapping Wizard ──────────────────────────────────────────
from wizard import PanelWizard

def _get_ser():
    return ser

wizard = PanelWizard(_get_ser, total=18)

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
        address = int(d["address"]),
        col     = int(d["col"]),
        row     = int(d["row"]),
        half    = d["half"]
    ))

@app.route("/api/wizard/skip", methods=["POST"])
def api_wizard_skip():
    d = request.get_json() or {}
    return jsonify(wizard.skip(int(d.get("address", 0))))

@app.route("/api/wizard/stop", methods=["POST"])
def api_wizard_stop():
    return jsonify(wizard.stop())

@app.route("/api/wizard/save", methods=["POST"])
def api_wizard_save():
    """Build new LAYOUT from wizard mappings and apply it live."""
    global panel, W, H, buffer
    if not wizard.mappings:
        return jsonify({"success": False, "error": "No mappings to save"}), 400
    try:
        from flippydot import Panel as FPPanel
        new_layout = wizard.build_layout()
        panel  = FPPanel(new_layout, 28, 7, module_rotation=0, screen_preview=False)
        W      = panel.get_total_width()
        H      = panel.get_total_height()
        buffer = np.zeros((H, W), dtype=np.uint8)
        log.info(f"Wizard: new layout applied — {W}x{H}")
        log.info(f"Layout: {new_layout}")
        return jsonify({"success": True, "layout": new_layout, "width": W, "height": H})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── Boot ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("─" * 50)
    log.info("Flipdot Controller UI starting...")
    connect_serial()
    log.info(f"Open: http://localhost:5000")
    log.info("─" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
