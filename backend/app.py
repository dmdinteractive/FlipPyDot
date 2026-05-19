"""
app.py — Flipdot Console V6
Workspaces: Live / Program / Setup / Monitor
Run: cd backend && python3 app.py
"""
import os,sys,time,threading,logging,numpy as np,json
from flask import Flask,request,jsonify,send_from_directory
from flask_socketio import SocketIO,emit
from flask_cors import CORS
from datetime import datetime
import serial

BASE=os.path.dirname(os.path.abspath(__file__))
FRONTEND=os.path.join(BASE,"..","frontend")
sys.path.insert(0,BASE)

# ── Config ────────────────────────────────────────────────────────
def _load_json(path, default):
    if os.path.isfile(path):
        try:
            with open(path) as f: return {**default, **json.load(f)}
        except: pass
    return default

def load_layout():
    p=os.path.join(BASE,"..","config","layout.json")
    if os.path.isfile(p):
        try:
            with open(p) as f: return json.load(f)
        except: pass
    return [[0,2,4],[1,3,5],[6,8,10],[7,9,11],[12,14,16],[13,15,17]]

def save_layout(layout):
    os.makedirs(os.path.join(BASE,"..","config"),exist_ok=True)
    with open(os.path.join(BASE,"..","config","layout.json"),"w") as f:
        json.dump(layout,f,indent=2)

cfg    = _load_json(os.path.join(BASE,"..","config","config.json"),{"port":"/dev/cu.usbserial-BG01DCHX","baud_rate":57600})
PORT   = os.environ.get("FLIPDOT_PORT", cfg["port"])
BAUD   = int(os.environ.get("FLIPDOT_BAUD", cfg["baud_rate"]))
LAYOUT = load_layout()

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(BASE,"..","flipdot.log"))])
log=logging.getLogger(__name__)

# ── Module imports ────────────────────────────────────────────────
from animations      import list_animations, get_animation, anim_scroll_text
from cue_engine      import CueEngine, Cue
from scheduler       import Scheduler, ScheduleItem
from playlist        import Playlist, PlaylistItem
from wizard          import PanelWizard
from variables       import substitute, get_all_values, get_status as var_status
from image_processor import process_image, frames_to_json
from effects         import EffectsEngine, EFFECTS_REGISTRY
import variables  as var_mod
import assets     as asset_lib
import show       as show_mgr

# ── Display ───────────────────────────────────────────────────────
from flippydot import Panel
from PIL import Image, ImageDraw, ImageFont

ser=panel=None; W=H=0; buffer=None

def connect_serial():
    global ser,panel,W,H,buffer
    try:
        ser=serial.Serial(port=PORT,baudrate=BAUD,bytesize=serial.EIGHTBITS,
                          parity=serial.PARITY_NONE,stopbits=serial.STOPBITS_ONE,timeout=1.0)
        panel=Panel(LAYOUT,28,7,module_rotation=0,screen_preview=False)
        W=panel.get_total_width(); H=panel.get_total_height()
        buffer=np.zeros((H,W),dtype=np.uint8)
        log.info(f"Connected: {PORT} @ {BAUD} — {W}x{H}"); return True
    except Exception as e:
        log.error(f"Connect failed: {e}"); W=84; H=42
        buffer=np.zeros((H,W),dtype=np.uint8); return False

def get_buf():
    global buffer
    if buffer is None: buffer=np.zeros((H or 42,W or 84),dtype=np.uint8)
    return buffer

def send_frame(frame):
    if not ser or not ser.is_open or panel is None: return False
    try:
        data=panel.apply_frame(frame)
        raw=b"".join(data.flatten().tolist()) if isinstance(data,np.ndarray) else bytes(data)
        ser.write(raw); return True
    except Exception as e: log.error(f"Send: {e}"); return False

def flush():
    ok=send_frame(get_buf())
    if ok: _emit_buf()
    return ok

def _emit_buf():
    try: socketio.emit("buffer",{"buffer":get_buf().tolist()})
    except: pass

# ── Animation runner ──────────────────────────────────────────────
_anim_stop=threading.Event(); _anim_thread=None

def run_anim(fn,*args,**kwargs):
    global _anim_thread,buffer
    _anim_stop.set(); time.sleep(0.05); _anim_stop.clear()
    def _r():
        global buffer
        for frame,delay in fn(*args,**kwargs):
            if _anim_stop.is_set(): break
            buffer=frame; send_frame(frame); _emit_buf(); time.sleep(delay)
    _anim_thread=threading.Thread(target=_r,daemon=True); _anim_thread.start()

def stop_anim(): _anim_stop.set()

def play_gif_frames(frames,loop=1):
    def _r():
        global buffer
        for _ in range(loop if loop>0 else 9999):
            for bmp,dur in frames:
                if _anim_stop.is_set(): return
                arr=np.array(bmp,dtype=np.uint8); buffer=arr
                send_frame(arr); _emit_buf(); time.sleep(max(0.033,dur/1000.0))
    stop_anim(); time.sleep(0.05); _anim_stop.clear()
    threading.Thread(target=_r,daemon=True).start()

# ── Text renderer ─────────────────────────────────────────────────
FONTS_DIR=os.path.join(BASE,"..","fonts")

def get_font(name,size):
    if name and name!="default":
        p=os.path.join(FONTS_DIR,name)
        if os.path.isfile(p):
            try: return ImageFont.truetype(p,int(size))
            except: pass
    return ImageFont.load_default()

def render_text(text,fname="default",fsize=14,x=0,y=0,w=None,h=None):
    text=substitute(str(text)); w=w or W or 84; h=h or H or 42
    img=Image.new("L",(w,h),255)
    ImageDraw.Draw(img).text((x,y),text,fill=0,font=get_font(fname,fsize))
    return (np.array(img)<128).astype(np.uint8)

def render_scrolling(text,fname="default",fsize=14):
    text=substitute(str(text)); font=get_font(fname,fsize)
    img=Image.new("L",(8192,H or 42),255)
    bbox=ImageDraw.Draw(img).textbbox((0,0),text,font=font)
    tw=bbox[2]-bbox[0]+(W or 84)*2
    return render_text(text,fname,fsize,x=(W or 84),w=tw)

# ── Cue executor ──────────────────────────────────────────────────
def execute_cue(cue):
    global buffer
    ct=cue.content_type; c=cue.content or {}; stop_anim()
    if   ct=="clear":  buffer=np.zeros((H or 42,W or 84),dtype=np.uint8); flush()
    elif ct=="fill":   buffer=np.ones((H or 42,W or 84),dtype=np.uint8); flush()
    elif ct=="text":
        txt=c.get("text",""); scroll=c.get("scroll",False)
        if scroll: run_anim(anim_scroll_text,render_scrolling(txt,c.get("font","default"),int(c.get("font_size",14))),W or 84)
        else:      buffer=render_text(txt,c.get("font","default"),int(c.get("font_size",14)),int(c.get("x",0)),int(c.get("y",0))); flush()
    elif ct=="animation":
        fn=get_animation(c.get("animation_id","flash"))
        if fn: run_anim(fn,W or 84,H or 42,**c.get("params",{}))
    elif ct=="image":
        frames_data=c.get("frames",[])
        if frames_data: play_gif_frames([(np.array(f["bitmap"],dtype=np.uint8),f["duration"]) for f in frames_data],c.get("loop",1))
    elif ct=="asset":
        a=asset_lib.get(c.get("asset_id",""))
        if a: execute_cue(type("C",(),{"content_type":a["type"],"content":a.get("data",{}),"options":{}})())
    _emit_status()

def execute_playlist_item(item):
    execute_cue(type("C",(),{"content_type":item.content_type,"content":item.content,"options":item.to_dict()})())

def execute_schedule_item(item):
    execute_cue(type("C",(),{"content_type":item.content_type,"content":item.content,"options":item.options})())

# ── Core objects ──────────────────────────────────────────────────
cue_eng   = CueEngine(execute_cue)
scheduler = Scheduler(execute_schedule_item)
playlist  = Playlist(execute_playlist_item)
effects   = EffectsEngine(get_buf, send_frame)
wizard    = PanelWizard(lambda: ser, total=18)

# ── Flask / SocketIO ──────────────────────────────────────────────
app=Flask(__name__,static_folder=FRONTEND)
CORS(app,resources={r"/*":{"origins":"*"}})
socketio=SocketIO(app,cors_allowed_origins="*",async_mode="threading")

@app.route("/"); def index(): return send_from_directory(FRONTEND,"index.html")
@app.route("/<path:p>"); def static_f(p): return send_from_directory(FRONTEND,p)

# WebSocket
@socketio.on("connect")
def on_connect(): emit("status",_build_status()); emit("buffer",{"buffer":get_buf().tolist()})
@socketio.on("go")
def on_go(_):      cue_eng.go();      _emit_status()
@socketio.on("back")
def on_back(_):    cue_eng.back();    _emit_status()
@socketio.on("release")
def on_release(_): cue_eng.release(); _emit_status()
@socketio.on("hold")
def on_hold(_):    cue_eng.hold();    _emit_status()

def _emit_status(): socketio.emit("status",_build_status())
def _build_status():
    return {"connected":bool(ser and ser.is_open),"port":PORT,"baud_rate":BAUD,
            "width":W,"height":H,"cue_engine":cue_eng.get_status(),
            "scheduler":{"running":scheduler.running,"items":[i.to_dict() for i in scheduler.items]},
            "playlist":playlist.get_status(),
            "effects":effects.get_status(),
            "timestamp":datetime.now().isoformat()}

# Status
@app.route("/api/status"); def api_status(): return jsonify(_build_status())
@app.route("/api/ports"); def api_ports():
    import serial.tools.list_ports
    return jsonify([{"port":p.device,"description":p.description} for p in serial.tools.list_ports.comports()])
@app.route("/api/connect",methods=["POST"]); def api_connect(): ok=connect_serial(); _emit_status(); return jsonify({"success":ok,"connected":ok})
@app.route("/api/disconnect",methods=["POST"]); def api_disconnect():
    if ser: ser.close()
    _emit_status(); return jsonify({"success":True})

# Display
@app.route("/api/buffer"); def api_buf(): return jsonify({"buffer":get_buf().tolist()})
@app.route("/api/display/fill",methods=["POST"]); def api_fill():
    global buffer; stop_anim(); buffer=np.ones((H or 42,W or 84),dtype=np.uint8); flush(); return jsonify({"success":True})
@app.route("/api/display/clear",methods=["POST"]); def api_clear():
    global buffer; stop_anim(); buffer=np.zeros((H or 42,W or 84),dtype=np.uint8); flush(); return jsonify({"success":True})
@app.route("/api/display/text",methods=["POST"]); def api_text():
    global buffer; d=request.get_json() or {}
    text=d.get("text",""); fname=d.get("font","default"); fsize=int(d.get("font_size",14))
    x,y=int(d.get("x",0)),int(d.get("y",0)); scroll=d.get("scroll",False)
    if d.get("clear",True): buffer=np.zeros((H or 42,W or 84),dtype=np.uint8)
    stop_anim()
    if scroll: run_anim(anim_scroll_text,render_scrolling(text,fname,fsize),W or 84)
    else:
        bmp=render_text(text,fname,fsize,x,y); hw=H or 42; ww=W or 84
        buffer[:min(bmp.shape[0],hw),:min(bmp.shape[1],ww)]=bmp[:min(bmp.shape[0],hw),:min(bmp.shape[1],ww)]
        flush()
    return jsonify({"success":True})

# Animations
@app.route("/api/animations"); def api_anims(): return jsonify({"animations":list_animations()})
@app.route("/api/animations/run",methods=["POST"]); def api_run_anim():
    d=request.get_json() or {}; fn=get_animation(d.get("name","flash"))
    if not fn: return jsonify({"error":"Unknown"}),404
    run_anim(fn,W or 84,H or 42,**d.get("options",{})); return jsonify({"success":True})
@app.route("/api/animations/stop",methods=["POST"]); def api_stop_anim_r(): stop_anim(); return jsonify({"success":True})

# Image
@app.route("/api/image/upload",methods=["POST"])
def api_image_upload():
    if "file" not in request.files: return jsonify({"error":"No file"}),400
    data=request.files["file"].read()
    try:
        frames=process_image(data,W or 84,H or 42,
            int(request.form.get("threshold",128)),float(request.form.get("brightness",1.0)),
            float(request.form.get("contrast",1.0)),request.form.get("dither","none"),
            request.form.get("scale","fit"),request.form.get("invert","false").lower()=="true")
        return jsonify({"success":True,"frames":frames_to_json(frames),"frame_count":len(frames),"animated":len(frames)>1})
    except Exception as e: return jsonify({"success":False,"error":str(e)}),400

@app.route("/api/image/display",methods=["POST"])
def api_image_display():
    global buffer; d=request.get_json() or {}
    frames=[(np.array(f["bitmap"],dtype=np.uint8),f["duration"]) for f in d.get("frames",[])]
    if not frames: return jsonify({"success":False}),400
    if len(frames)==1 and frames[0][1]==0: buffer=frames[0][0]; flush()
    else: play_gif_frames(frames,int(d.get("loop",1)))
    return jsonify({"success":True,"frames":len(frames)})

# Pixel editor
@app.route("/api/pixel/push",methods=["POST"])
def api_pixel():
    global buffer; d=request.get_json() or {}; b=d.get("buffer")
    if not b: return jsonify({"success":False}),400
    buffer=np.array(b,dtype=np.uint8); flush(); return jsonify({"success":True})

# Variables
@app.route("/api/variables"); def api_vars(): return jsonify(var_status())
@app.route("/api/variables/config",methods=["POST"]); def api_vars_cfg(): var_mod.configure(request.get_json() or {}); return jsonify({"success":True})
@app.route("/api/variables/values"); def api_vars_vals(): return jsonify(get_all_values())
@app.route("/api/variables/preview",methods=["POST"]); def api_vars_prev():
    d=request.get_json() or {}; t=d.get("text",""); return jsonify({"original":t,"substituted":substitute(t)})

# Cue engine
@app.route("/api/cues"); def api_cues(): return jsonify(cue_eng.get_status())
@app.route("/api/cues",methods=["POST"])
def api_add_cue():
    d=request.get_json() or {}; num=d.get("number")
    if num is None:
        nums=[c.number for c in cue_eng.cues if c.number is not None]
        num=round((max(nums)+1.0) if nums else 1.0,3)
    cue=Cue(number=float(num),label=d.get("label",f"Cue {num}"),
            content_type=d.get("content_type","clear"),content=d.get("content",{}),
            pre_wait=float(d.get("pre_wait",0)),duration=float(d.get("duration",5)),
            fade_in=float(d.get("fade_in",0)),auto_follow=bool(d.get("auto_follow",False)))
    cue_eng.add_cue(cue); _emit_status(); return jsonify({"success":True,"cue":cue.to_dict()})
@app.route("/api/cues/<cue_id>",methods=["PUT"])
def api_upd_cue(cue_id): cue=cue_eng.update_cue(cue_id,request.get_json() or {}); _emit_status(); return jsonify({"success":bool(cue)})
@app.route("/api/cues/<cue_id>",methods=["DELETE"])
def api_del_cue(cue_id): cue_eng.remove_cue(cue_id); _emit_status(); return jsonify({"success":True})
@app.route("/api/cues/renumber",methods=["POST"]); def api_renum(): cue_eng.renumber(); _emit_status(); return jsonify({"success":True})
@app.route("/api/transport/go",methods=["POST"]);      def api_go():      cue_eng.go();      _emit_status(); return jsonify({"success":True})
@app.route("/api/transport/back",methods=["POST"]);    def api_back():    cue_eng.back();    _emit_status(); return jsonify({"success":True})
@app.route("/api/transport/jump",methods=["POST"]);    def api_jump():
    cue_eng.jump((request.get_json() or {}).get("cue")); _emit_status(); return jsonify({"success":True})
@app.route("/api/transport/release",methods=["POST"]); def api_release(): cue_eng.release(); _emit_status(); return jsonify({"success":True})
@app.route("/api/transport/hold",methods=["POST"]);    def api_hold():    cue_eng.hold();    _emit_status(); return jsonify({"success":True})

# Scheduler
@app.route("/api/scheduler"); def api_sched(): return jsonify({"running":scheduler.running,"items":[i.to_dict() for i in scheduler.items]})
@app.route("/api/scheduler",methods=["POST"])
def api_add_sched():
    d=request.get_json() or {}
    st=d.get("start_time")
    if st:
        try: st=datetime.fromisoformat(st)
        except: st=None
    item=ScheduleItem(label=d.get("label",""),content_type=d.get("content_type","text"),
                      content=d.get("content",{}),mode=d.get("mode","repeat"),
                      duration=float(d.get("duration",5)),interval=float(d.get("interval",60)),
                      start_time=st,days=d.get("days",[]),priority=int(d.get("priority",0)))
    scheduler.add(item); return jsonify({"success":True,"item":item.to_dict()})
@app.route("/api/scheduler/<id>",methods=["DELETE"]); def api_del_sched(id): scheduler.remove(id); return jsonify({"success":True})
@app.route("/api/scheduler/start",methods=["POST"]);  def api_start_sched(): scheduler.start(); _emit_status(); return jsonify({"success":True})
@app.route("/api/scheduler/stop",methods=["POST"]);   def api_stop_sched():  scheduler.stop();  _emit_status(); return jsonify({"success":True})

# Playlist
@app.route("/api/playlist"); def api_playlist(): return jsonify(playlist.get_status())
@app.route("/api/playlist",methods=["POST"])
def api_add_playlist():
    d=request.get_json() or {}
    item=PlaylistItem(d.get("content_type","clear"),d.get("content",{}),
                      d.get("label",""),float(d.get("duration",5)),float(d.get("weight",1)))
    playlist.add(item); _emit_status(); return jsonify({"success":True,"item":item.to_dict()})
@app.route("/api/playlist/<id>",methods=["DELETE"]); def api_del_pl(id): playlist.remove(id); _emit_status(); return jsonify({"success":True})
@app.route("/api/playlist/<id>",methods=["PUT"]); def api_upd_pl(id): playlist.update(id,request.get_json() or {}); return jsonify({"success":True})
@app.route("/api/playlist/start",methods=["POST"])
def api_start_pl():
    d=request.get_json() or {}; playlist.start(d.get("mode")); _emit_status(); return jsonify({"success":True})
@app.route("/api/playlist/stop",methods=["POST"]);  def api_stop_pl():  playlist.stop(); _emit_status(); return jsonify({"success":True})
@app.route("/api/playlist/skip",methods=["POST"]);  def api_skip_pl():  playlist.skip(); return jsonify({"success":True})
@app.route("/api/playlist/move",methods=["POST"])
def api_move_pl():
    d=request.get_json() or {}; playlist.move(d.get("id"),d.get("direction","down")); return jsonify({"success":True})

# Assets
@app.route("/api/assets"); def api_list_assets(): return jsonify({"assets":asset_lib.list_all(request.args.get("type"),request.args.get("tag"))})
@app.route("/api/assets",methods=["POST"])
def api_create_asset():
    d=request.get_json() or {}
    a=asset_lib.create(d.get("name","Untitled"),d.get("type","text_preset"),d.get("data",{}),d.get("tags",[]))
    return jsonify({"success":True,"asset":a})
@app.route("/api/assets/<id>"); def api_get_asset(id): a=asset_lib.get(id); return jsonify(a) if a else (jsonify({"error":"Not found"}),404)
@app.route("/api/assets/<id>",methods=["PUT"]); def api_upd_asset(id): a=asset_lib.update(id,request.get_json() or {}); return jsonify({"success":bool(a)})
@app.route("/api/assets/<id>",methods=["DELETE"]); def api_del_asset(id): return jsonify({"success":asset_lib.delete(id)})
@app.route("/api/assets/search"); def api_search_assets(): return jsonify({"assets":asset_lib.search(request.args.get("q",""))})

# Effects
@app.route("/api/effects"); def api_effects_status(): return jsonify({**effects.get_status(),"registry":EFFECTS_REGISTRY})
@app.route("/api/effects",methods=["POST"])
def api_add_effect():
    d=request.get_json() or {}; name=d.get("name","fx"); et=d.get("type","flicker")
    effects.add(name,et,**d.get("params",{})); return jsonify({"success":True})
@app.route("/api/effects/<name>",methods=["DELETE"]); def api_del_effect(name): effects.remove(name); return jsonify({"success":True})
@app.route("/api/effects/clear",methods=["POST"]); def api_clear_effects(): effects.clear(); return jsonify({"success":True})

# Webhooks — fire a named cue or action via HTTP POST
@app.route("/api/webhook/<trigger>",methods=["POST"])
def api_webhook(trigger):
    log.info(f"Webhook: {trigger}")
    # Find cue by label or number
    for cue in cue_eng.cues:
        if cue.label.lower()==trigger.lower() or str(cue.number)==trigger:
            cue_eng.jump(cue.id); _emit_status()
            return jsonify({"success":True,"fired":cue.label})
    # Built-in triggers
    if trigger=="go":      cue_eng.go();      _emit_status()
    elif trigger=="back":  cue_eng.back();    _emit_status()
    elif trigger=="clear": api_clear()
    elif trigger=="fill":  api_fill()
    return jsonify({"success":True,"trigger":trigger})

# Shows
@app.route("/api/shows"); def api_list_shows(): return jsonify({"shows":show_mgr.list_shows()})
@app.route("/api/shows/save",methods=["POST"])
def api_save_show():
    d=request.get_json() or {}; name=d.get("name","untitled")
    path=show_mgr.save_show(name,cue_eng,scheduler,{"port":PORT,"baud_rate":BAUD,"layout":LAYOUT})
    return jsonify({"success":True,"path":path})
@app.route("/api/shows/load",methods=["POST"])
def api_load_show():
    d=request.get_json() or {}
    try: data=show_mgr.load_show(d.get("name",""),cue_eng,scheduler); _emit_status(); return jsonify({"success":True,"meta":data.get("meta",{})})
    except FileNotFoundError as e: return jsonify({"success":False,"error":str(e)}),404
@app.route("/api/shows/<name>",methods=["DELETE"]); def api_del_show(name): return jsonify({"success":show_mgr.delete_show(name)})

# Wizard
@app.route("/api/wizard/state"); def api_wiz_state(): return jsonify(wizard.get_state())
@app.route("/api/wizard/start",methods=["POST"]); def api_wiz_start(): return jsonify(wizard.start((request.get_json() or {}).get("total",18)))
@app.route("/api/wizard/assign",methods=["POST"])
def api_wiz_assign():
    d=request.get_json() or {}; return jsonify(wizard.assign(int(d["address"]),int(d["col"]),int(d["row"]),d["half"]))
@app.route("/api/wizard/skip",methods=["POST"]); def api_wiz_skip(): d=request.get_json() or {}; return jsonify(wizard.skip(int(d.get("address",0))))
@app.route("/api/wizard/stop",methods=["POST"]); def api_wiz_stop(): return jsonify(wizard.stop())
@app.route("/api/wizard/save",methods=["POST"])
def api_wiz_save():
    global panel,W,H,buffer
    if not wizard.mappings: return jsonify({"success":False,"error":"No mappings"}),400
    try:
        from flippydot import Panel as FP
        nl=wizard.build_layout(); save_layout(nl)
        panel=FP(nl,28,7,module_rotation=0,screen_preview=False)
        W=panel.get_total_width(); H=panel.get_total_height(); buffer=np.zeros((H,W),dtype=np.uint8)
        return jsonify({"success":True,"layout":nl})
    except Exception as e: return jsonify({"success":False,"error":str(e)}),500

# Boot
if __name__=="__main__":
    log.info("="*56)
    log.info("  FLIPDOT CONSOLE V6")
    log.info("="*56)
    connect_serial(); var_mod.start()
    log.info("Open: http://localhost:5000")
    socketio.run(app,host="0.0.0.0",port=5000,debug=False,allow_unsafe_werkzeug=True)
