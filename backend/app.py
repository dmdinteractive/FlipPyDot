"""
app.py — Flipdot Controller
Run: cd backend && python3 app.py
Open: http://localhost:5000
"""

import os, sys, time, threading, logging, numpy as np
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
import serial

# ── Paths ─────────────────────────────────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE, "..", "frontend")

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
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(BASE, "..", "flipdot.log"))])
log = logging.getLogger(__name__)

# ── Animations import (same directory) ───────────────────────────
from animations import list_animations, get_animation, anim_scroll_text

# ── Display ───────────────────────────────────────────────────────
from flippydot import Panel

ser = panel = None
W = H = 0

def connect_serial():
    global ser, panel, W, H
    try:
        ser   = serial.Serial(port=PORT, baudrate=BAUD_RATE,
                              bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                              stopbits=serial.STOPBITS_ONE, timeout=1.0)
        panel = Panel(LAYOUT, 28, 7, module_rotation=0, screen_preview=False)
        W     = panel.get_total_width()
        H     = panel.get_total_height()
        log.info(f"Connected: {PORT} @ {BAUD_RATE} — {W}x{H}")
        return True
    except Exception as e:
        log.error(f"Connect failed: {e}")
        return False

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

buffer = None
def get_buf():
    global buffer
    if buffer is None or buffer.shape != (H or 42, W or 84):
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    return buffer

def flush(): return send_frame(get_buf())

# ── Animation runner ──────────────────────────────────────────────
_anim_thread = None
_anim_stop   = threading.Event()
_cur_anim    = None

def run_anim(fn, *args, **kwargs):
    global _anim_thread, _cur_anim
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

# ── Text renderer ─────────────────────────────────────────────────
from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = os.path.join(BASE, "..", "fonts")

def get_font(name, size):
    if name and name != "default":
        p = os.path.join(FONTS_DIR, name)
        if os.path.isfile(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

def render_text(text, fname="default", fsize=14, x=0, y=0, w=None, h=None):
    w = w or W or 84; h = h or H or 42
    img  = Image.new("L", (w, h), 255)
    ImageDraw.Draw(img).text((x, y), text, fill=0, font=get_font(fname, fsize))
    return (np.array(img) < 128).astype(np.uint8)

def render_scrolling(text, fname="default", fsize=14):
    font = get_font(fname, fsize)
    img  = Image.new("L", (8192, H or 42), 255)
    bbox = ImageDraw.Draw(img).textbbox((0,0), text, font=font)
    tw   = bbox[2] - bbox[0] + (W or 84) * 2
    return render_text(text, fname, fsize, x=(W or 84), w=tw)

# ── Scheduler ─────────────────────────────────────────────────────
import uuid as _uuid

schedule_items   = []
sched_running    = False
sched_thread     = None

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
        return {"id":self.id,"type":self.type,"content":self.content,
                "duration":self.duration,"repeat":self.repeat,"interval":self.interval,
                "start_time":self.start_time.isoformat() if self.start_time else None,
                "last_run":self.last_run,"enabled":self.enabled,"options":self.options}

def sched_loop():
    global sched_running
    while sched_running:
        now = time.time()
        for item in list(schedule_items):
            if not item.enabled: continue
            if item.start_time and item.start_time > datetime.now(): continue
            if item.last_run is None or (item.repeat and now - item.last_run >= item.interval):
                item.last_run = now
                _exec_item(item)
        time.sleep(1.0)

def _exec_item(item):
    global buffer
    opts = item.options
    if item.type == "text":
        scroll = opts.get("scroll", False)
        fname  = opts.get("font", "default")
        fsize  = int(opts.get("font_size", 14))
        if scroll:
            bmp = render_scrolling(item.content, fname, fsize)
            run_anim(anim_scroll_text, bmp, W or 84)
        else:
            buffer = render_text(item.content, fname, fsize)
            flush()
            time.sleep(item.duration)
    elif item.type == "animation":
        fn = get_animation(item.content)
        if fn:
            run_anim(fn, W or 84, H or 42, **opts)
            time.sleep(item.duration)

# ── Wizard ────────────────────────────────────────────────────────
from wizard import PanelWizard
wizard = PanelWizard(lambda: ser, total=18)

# ── Flask ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=FRONTEND)
CORS(app)

@app.route("/")
def index(): return send_from_directory(FRONTEND, "index.html")

@app.route("/<path:p>")
def static_f(p): return send_from_directory(FRONTEND, p)

# Status
@app.route("/api/status")
def api_status():
    return jsonify({"connected": bool(ser and ser.is_open),
                    "port":PORT,"baud_rate":BAUD_RATE,
                    "width":W,"height":H,
                    "scheduler_running":sched_running})

@app.route("/api/ports")
def api_ports():
    import serial.tools.list_ports
    return jsonify([{"port":p.device,"description":p.description}
                    for p in serial.tools.list_ports.comports()])

@app.route("/api/connect", methods=["POST"])
def api_connect():
    ok = connect_serial()
    return jsonify({"success":ok,"connected":ok})

@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    if ser: ser.close()
    return jsonify({"success":True})

# Buffer
@app.route("/api/buffer")
def api_buf(): return jsonify({"buffer":get_buf().tolist()})

@app.route("/api/display/fill", methods=["POST"])
def api_fill():
    global buffer
    buffer = np.ones((H or 42, W or 84), dtype=np.uint8)
    flush(); return jsonify({"success":True})

@app.route("/api/display/clear", methods=["POST"])
def api_clear():
    global buffer
    buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    flush(); return jsonify({"success":True})

# Text
@app.route("/api/display/text", methods=["POST"])
def api_text():
    global buffer
    d      = request.get_json() or {}
    text   = d.get("text","")
    fname  = d.get("font","default")
    fsize  = int(d.get("font_size",14))
    x      = int(d.get("x",0)); y = int(d.get("y",0))
    scroll = d.get("scroll",False)
    if d.get("clear",True):
        buffer = np.zeros((H or 42, W or 84), dtype=np.uint8)
    if scroll:
        run_anim(anim_scroll_text, render_scrolling(text,fname,fsize), W or 84)
    else:
        bmp = render_text(text, fname, fsize, x, y)
        h_, w_ = bmp.shape
        hw = H or 42; ww = W or 84
        buffer[:min(h_,hw), :min(w_,ww)] = bmp[:min(h_,hw),:min(w_,ww)]
        flush()
    return jsonify({"success":True})

# Animations
@app.route("/api/animations")
def api_anims():
    return jsonify({"animations": list_animations()})

@app.route("/api/animations/run", methods=["POST"])
def api_run():
    global _cur_anim
    d    = request.get_json() or {}
    name = d.get("name","flash")
    fn   = get_animation(name)
    if not fn: return jsonify({"error":"Unknown animation"}), 404
    _cur_anim = name
    opts = d.get("options", {})
    run_anim(fn, W or 84, H or 42, **opts)
    return jsonify({"success":True})

@app.route("/api/animations/stop", methods=["POST"])
def api_stop():
    global _cur_anim
    _anim_stop.set(); _cur_anim = None
    return jsonify({"success":True})

# Schedule
@app.route("/api/schedule")
def api_sched(): return jsonify({"items":[i.to_dict() for i in schedule_items],"running":sched_running})

@app.route("/api/schedule", methods=["POST"])
def api_add_sched():
    d  = request.get_json() or {}
    st = d.get("start_time")
    if st: st = datetime.fromisoformat(st)
    item = ScheduleItem(d.get("type","text"),d.get("content",""),
                        float(d.get("duration",5)),d.get("repeat",False),
                        float(d.get("interval",60)),st,d.get("options",{}))
    schedule_items.append(item)
    return jsonify({"success":True,"item":item.to_dict()})

@app.route("/api/schedule/<id>", methods=["DELETE"])
def api_del_sched(id):
    global schedule_items
    schedule_items = [i for i in schedule_items if i.id != id]
    return jsonify({"success":True})

@app.route("/api/schedule/start", methods=["POST"])
def api_start_sched():
    global sched_running, sched_thread
    if not sched_running:
        sched_running = True
        sched_thread  = threading.Thread(target=sched_loop, daemon=True)
        sched_thread.start()
    return jsonify({"success":True})

@app.route("/api/schedule/stop", methods=["POST"])
def api_stop_sched():
    global sched_running
    sched_running = False
    return jsonify({"success":True})

# Wizard
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
        return jsonify({"success":False,"error":"No mappings"}), 400
    try:
        from flippydot import Panel as FP
        layout = wizard.build_layout()
        panel  = FP(layout, 28, 7, module_rotation=0, screen_preview=False)
        W      = panel.get_total_width()
        H      = panel.get_total_height()
        buffer = np.zeros((H, W), dtype=np.uint8)
        log.info(f"Wizard saved layout: {layout}")
        return jsonify({"success":True,"layout":layout,"width":W,"height":H})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)}), 500

# ── Boot ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("─"*50)
    log.info("Flipdot Controller starting...")
    connect_serial()
    log.info("Open: http://localhost:5000")
    log.info("─"*50)
    app.run(host="0.0.0.0", port=5000, debug=False)
