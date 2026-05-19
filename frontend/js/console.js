/**
 * console.js — Flipdot Console V5.1
 * Uses WebSockets for real-time updates instead of polling
 */

const API = window.location.origin;
let socket       = null;
let isConnected  = false;
let editingCueId = null;

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupDayButtons();
  setupPixelEditor();
  scanPorts();
  loadAnimations();
  connectWebSocket();
  updateClock();
  setInterval(updateClock, 1000);
  loadShowsList();
  loadVariablesConfig();
});

// ── WebSocket ─────────────────────────────────────────────────────
function connectWebSocket() {
  if (typeof io === "undefined") {
    console.error("Socket.IO not loaded — falling back to polling");
    startPollingFallback();
    return;
  }
  socket = io(API, {transports: ["websocket","polling"]});

  socket.on("connect", () => {
    console.log("WebSocket connected");
    showToast("Real-time connected", "ok");
  });

  socket.on("disconnect", () => {
    console.log("WebSocket disconnected");
  });

  socket.on("status", d => {
    updateConnectionUI(d);
    updateCueEngineUI(d.cue_engine);
    updateSchedulerUI(d.scheduler);
  });

  socket.on("buffer", d => {
    if (d.buffer) updateBuffer(d.buffer);
  });
}

// Fallback polling if WebSocket not available
function startPollingFallback() {
  poll(); pollBuffer();
  setInterval(poll, 1500);
  setInterval(pollBuffer, 600);
}

async function poll() {
  const d = await apiGet("/api/status");
  if (!d) return;
  updateConnectionUI(d);
  updateCueEngineUI(d.cue_engine);
  updateSchedulerUI(d.scheduler);
}

async function pollBuffer() {
  const d = await apiGet("/api/buffer");
  if (d?.buffer) updateBuffer(d.buffer);
}

// ── Tabs ──────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll(".ws-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ws-tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".ws-pane").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab)?.classList.add("active");
    });
  });
}

// ── Clock ─────────────────────────────────────────────────────────
function updateClock() {
  const t = new Date().toTimeString().slice(0,8);
  const el = document.getElementById("sys-clock");
  if (el) el.textContent = t;
  const sb = document.getElementById("sb-time");
  if (sb) sb.textContent = new Date().toLocaleString();
}

// ── API ───────────────────────────────────────────────────────────
async function apiPost(url, body = {}) {
  try {
    const r = await fetch(API + url, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(body)
    });
    return await r.json();
  } catch(e) { showToast("Server unreachable","error"); return null; }
}

async function apiGet(url) {
  try { return await (await fetch(API+url)).json(); }
  catch { return null; }
}

async function apiDelete(url) {
  try { await fetch(API+url,{method:"DELETE"}); } catch {}
}

// Transport via WebSocket (instant) with HTTP fallback
function wsGo()      { socket ? socket.emit("go",{})      : apiPost("/api/transport/go"); }
function wsBack()    { socket ? socket.emit("back",{})    : apiPost("/api/transport/back"); }
function wsRelease() { socket ? socket.emit("release",{}) : apiPost("/api/transport/release"); }
function wsHold()    { socket ? socket.emit("hold",{})    : apiPost("/api/transport/hold"); }

// ── Connection UI ─────────────────────────────────────────────────
function updateConnectionUI(d) {
  isConnected = d.connected;
  const tally = document.getElementById("tally-conn");
  const label = document.getElementById("tally-conn-label");
  const sb    = document.getElementById("sb-conn");
  if (d.connected) {
    tally?.classList.add("online");
    if (label) label.textContent = d.port?.split("/").pop() || "ONLINE";
    if (sb) { sb.textContent = `SERIAL: ${d.port?.split("/").pop()} OK`; sb.className = "sb-item ok"; }
  } else {
    tally?.classList.remove("online","on-air");
    if (label) label.textContent = "OFFLINE";
    if (sb)    { sb.textContent = "SERIAL: OFFLINE"; sb.className = "sb-item err"; }
  }
  if (d.width)  document.getElementById("sys-dims") && (document.getElementById("sys-dims").textContent = `${d.width}×${d.height}`);
}

// ── Cue Engine UI ─────────────────────────────────────────────────
function updateCueEngineUI(eng) {
  if (!eng) return;
  const cur  = eng.current_cue;
  const nxt  = eng.next_cue;

  document.getElementById("t-cur-num").textContent  = cur ? cur.number : "—";
  document.getElementById("t-cur-name").textContent = cur ? cur.label  : "NO CUE ACTIVE";
  document.getElementById("t-elapsed").textContent  = (eng.elapsed||0).toFixed(1);

  const stEl = document.getElementById("t-state");
  if (stEl) { stEl.textContent = eng.state; stEl.className = "t-state " + eng.state.toLowerCase().replace("_","-"); }

  const tally = document.getElementById("tally-cue");
  const label = document.getElementById("tally-cue-label");
  if (tally) tally.className = "tally" + (eng.state !== "IDLE" ? " on-air" : "");
  if (label) label.textContent = eng.state;

  document.getElementById("pgm-cue-num")  && (document.getElementById("pgm-cue-num").textContent  = cur ? cur.number : "—");
  document.getElementById("pgm-cue-label")&& (document.getElementById("pgm-cue-label").textContent = cur ? cur.label : "NO CUE");
  document.getElementById("pvw-cue-num")  && (document.getElementById("pvw-cue-num").textContent   = nxt ? nxt.number : "—");
  document.getElementById("pvw-cue-label")&& (document.getElementById("pvw-cue-label").textContent = nxt ? nxt.label  : "END");

  const sb = document.getElementById("sb-cue");
  if (sb) sb.textContent = `CUE ENGINE: ${eng.state}${cur ? ` [${cur.number} ${cur.label}]` : ""}`;

  document.querySelectorAll(".cue-table tr[data-cue-id]").forEach(row => {
    row.classList.toggle("active-cue", cur && row.dataset.cueId === cur.id);
  });
  if (eng.cues) renderCueTable(eng.cues);
}

// ── Scheduler UI ─────────────────────────────────────────────────
function updateSchedulerUI(sched) {
  if (!sched) return;
  const tally = document.getElementById("tally-sched");
  const label = document.getElementById("tally-sched-label");
  const btn   = document.getElementById("sched-toggle");
  const sb    = document.getElementById("sb-sched");
  if (sched.running) {
    tally?.classList.add("running");
    if (label) label.textContent = "SCHED RUN";
    if (btn)   { btn.textContent = "⏸ STOP SCHEDULER"; btn.classList.add("tb-primary"); }
    if (sb)    { sb.textContent = "SCHEDULER: RUNNING"; sb.className = "sb-item ok"; }
  } else {
    tally?.classList.remove("running");
    if (label) label.textContent = "SCHED OFF";
    if (btn)   { btn.textContent = "▶ START SCHEDULER"; btn.classList.remove("tb-primary"); }
    if (sb)    { sb.textContent = "SCHEDULER: OFF"; sb.className = "sb-item"; }
  }
  renderScheduleTable(sched.items || []);
}

// ── Connection ────────────────────────────────────────────────────
async function toggleConnect() {
  if (isConnected) {
    await apiPost("/api/disconnect");
    showToast("Disconnected");
  } else {
    const port = document.getElementById("port-select")?.value;
    if (!port) { showToast("Select a port first","error"); return; }
    const d = await apiPost("/api/connect",{port});
    showToast(d?.success ? "Connected: "+port : "Connection failed", d?.success ? "ok" : "error");
  }
}

async function scanPorts() {
  const sel = document.getElementById("port-select");
  if (!sel) return;
  sel.innerHTML = "<option>Scanning…</option>";
  const d = await apiGet("/api/ports");
  if (!d?.length) { sel.innerHTML = "<option value=''>No ports found</option>"; return; }
  sel.innerHTML = "";
  d.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.port;
    opt.textContent = p.port.split("/").pop() + " — " + p.description;
    sel.appendChild(opt);
  });
}

// ── Cue Table ─────────────────────────────────────────────────────
function renderCueTable(cues) {
  const tbody = document.getElementById("cue-tbody");
  const empty = document.getElementById("cue-empty");
  if (!tbody) return;
  if (!cues.length) { tbody.innerHTML = ""; if (empty) empty.style.display = "block"; return; }
  if (empty) empty.style.display = "none";
  const key = cues.map(c => c.id+c.label+c.duration).join("|");
  if (tbody._lastKey === key) return;
  tbody._lastKey = key;
  tbody.innerHTML = cues.map(cue => {
    const ct = cue.content_type || "clear";
    const c  = cue.content || {};
    const cs = ct==="text"?(c.text||"—"):ct==="animation"?(c.animation_id||"—"):ct==="image"?"[IMAGE]":ct;
    return `<tr data-cue-id="${cue.id}">
      <td class="col-num">${cue.number}</td>
      <td class="col-label" title="${cue.label}">${cue.label}</td>
      <td class="col-type"><span class="type-badge ${ct}">${ct.toUpperCase()}</span></td>
      <td class="col-content" title="${cs}">${cs}</td>
      <td class="col-wait">${cue.pre_wait}s</td>
      <td class="col-dur">${cue.duration<0?"HOLD":cue.duration+"s"}</td>
      <td class="col-fade">${cue.fade_in}s</td>
      <td class="col-follow">${cue.auto_follow?"AUTO":"—"}</td>
      <td class="col-actions">
        <button class="row-btn go-btn" onclick="fireJump('${cue.id}')">GO</button>
        <button class="row-btn" onclick="openCueEditor('${cue.id}')">EDIT</button>
        <button class="row-btn del-btn" onclick="deleteCue('${cue.id}')">DEL</button>
      </td></tr>`;
  }).join("");
}

function addCue() { openCueEditor(null); }

function openCueEditor(cueId) {
  editingCueId = cueId;
  const editor = document.getElementById("cue-editor");
  if (!editor) return;
  editor.style.display = "block";
  if (cueId) {
    apiGet("/api/cues").then(d => {
      const cue = d?.cues?.find(c => c.id === cueId);
      if (!cue) return;
      document.getElementById("ed-cue-num").textContent  = cue.number;
      document.getElementById("ed-number").value   = cue.number;
      document.getElementById("ed-label").value    = cue.label;
      document.getElementById("ed-type").value     = cue.content_type;
      document.getElementById("ed-prewait").value  = cue.pre_wait;
      document.getElementById("ed-duration").value = cue.duration;
      document.getElementById("ed-fade").value     = cue.fade_in;
      document.getElementById("ed-auto").value     = cue.auto_follow ? "true" : "false";
      const c = cue.content || {};
      if (cue.content_type === "text") {
        document.getElementById("ed-text").value     = c.text || "";
        document.getElementById("ed-fontsize").value = c.font_size || 14;
        document.getElementById("ed-scroll").value   = c.scroll ? "true" : "false";
      } else if (cue.content_type === "animation") {
        const sel = document.getElementById("ed-anim");
        if (sel) sel.value = c.animation_id || "";
      }
      updateEditorType();
    });
  } else {
    document.getElementById("ed-cue-num").textContent = "NEW";
    ["ed-number","ed-label","ed-text"].forEach(id => { const el=document.getElementById(id); if(el) el.value=""; });
    document.getElementById("ed-type").value     = "clear";
    document.getElementById("ed-prewait").value  = 0;
    document.getElementById("ed-duration").value = 5;
    document.getElementById("ed-fade").value     = 0;
    document.getElementById("ed-auto").value     = "false";
    updateEditorType();
  }
  editor.scrollIntoView({behavior:"smooth",block:"end"});
}

function updateEditorType() {
  const type = document.getElementById("ed-type")?.value;
  const show = (id, vis) => { const el=document.getElementById(id); if(el) el.style.display=vis?"block":"none"; };
  show("ed-text-field",    type==="text");
  show("ed-fontsize-field",type==="text");
  show("ed-scroll-field",  type==="text");
  show("ed-anim-field",    type==="animation");
}

async function saveCueEdit() {
  const type     = document.getElementById("ed-type").value;
  const number   = parseFloat(document.getElementById("ed-number").value)||undefined;
  const label    = document.getElementById("ed-label").value || `Cue ${number||""}`;
  const prewait  = parseFloat(document.getElementById("ed-prewait").value)||0;
  const duration = parseFloat(document.getElementById("ed-duration").value)||5;
  const fade     = parseFloat(document.getElementById("ed-fade").value)||0;
  const auto     = document.getElementById("ed-auto").value === "true";
  let content = {};
  if (type==="text") content = {text:document.getElementById("ed-text").value, font_size:parseInt(document.getElementById("ed-fontsize").value), scroll:document.getElementById("ed-scroll").value==="true"};
  else if (type==="animation") content = {animation_id:document.getElementById("ed-anim").value};
  const payload = {number,label,content_type:type,content,pre_wait:prewait,duration,fade_in:fade,auto_follow:auto};
  let d;
  if (editingCueId) {
    d = await fetch(`${API}/api/cues/${editingCueId}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}).then(r=>r.json());
    if (d.success) showToast("Cue updated","ok");
  } else {
    d = await apiPost("/api/cues",payload);
    if (d?.success) showToast(`Cue ${d.cue?.number} added`,"ok");
  }
  cancelCueEdit();
}

function cancelCueEdit() {
  editingCueId = null;
  const ed = document.getElementById("cue-editor");
  if (ed) ed.style.display = "none";
}

async function deleteCue(id)   { await apiDelete(`/api/cues/${id}`); showToast("Cue deleted"); }
async function fireJump(id)    { await apiPost("/api/transport/jump",{cue:id}); showToast("Jumped to cue","ok"); }
async function clearCueList()  {
  const d = await apiGet("/api/cues");
  for (const c of d?.cues||[]) await apiDelete(`/api/cues/${c.id}`);
  showToast("Cue list cleared");
}

// ── Scheduler ─────────────────────────────────────────────────────
function setupDayButtons() {
  document.querySelectorAll(".day-btn").forEach(btn => {
    btn.addEventListener("click", () => btn.classList.toggle("active"));
  });
}

function updateSchedMode() {
  const mode = document.getElementById("sf-mode")?.value;
  const show = (id,v) => { const el=document.getElementById(id); if(el) el.style.display=v?"block":"none"; };
  show("sf-interval-wrap", mode==="repeat"||mode==="weekly");
  show("sf-time-wrap",     mode==="once");
  show("sf-days-wrap",     mode==="weekly");
}

function addScheduleItem() {
  const form = document.getElementById("sched-form");
  if (form) form.style.display = form.style.display==="none" ? "block" : "none";
}

async function submitScheduleItem() {
  const mode  = document.getElementById("sf-mode").value;
  const ctype = document.getElementById("sf-ctype").value;
  const raw   = document.getElementById("sf-content").value.trim();
  const label = document.getElementById("sf-label").value.trim() || raw;
  let content = {};
  if (ctype==="text") content = {text:raw,font_size:14};
  else if (ctype==="animation") content = {animation_id:raw};
  const days = [];
  document.querySelectorAll(".day-btn.active").forEach(b => days.push(parseInt(b.dataset.day)));
  const startEl = document.getElementById("sf-start")?.value;
  const d = await apiPost("/api/scheduler",{
    label,content_type:ctype,content,mode,
    duration:parseFloat(document.getElementById("sf-dur")?.value||"5"),
    interval:parseFloat(document.getElementById("sf-interval")?.value||"60"),
    priority:parseInt(document.getElementById("sf-priority")?.value||"0"),
    start_time: startEl ? new Date(startEl).toISOString() : null, days,
  });
  if (d?.success) { showToast("Item added","ok"); document.getElementById("sf-content").value=""; }
}

function renderScheduleTable(items) {
  const tbody = document.getElementById("sched-tbody");
  const empty = document.getElementById("sched-empty");
  if (!tbody) return;
  if (!items.length) { tbody.innerHTML=""; if(empty) empty.style.display="block"; return; }
  if (empty) empty.style.display = "none";
  const key = items.map(i=>i.id+i.enabled+i.last_run).join("|");
  if (tbody._lastKey === key) return;
  tbody._lastKey = key;
  const dayN = ["M","T","W","T","F","S","S"];
  tbody.innerHTML = items.map(item => {
    const c = item.content||{};
    const cs = c.text||c.animation_id||item.content_type;
    const lr = item.last_run ? new Date(item.last_run*1000).toLocaleTimeString() : "never";
    return `<tr>
      <td>${item.label||"—"}</td>
      <td><span class="type-badge">${item.mode.toUpperCase()}</span></td>
      <td><span class="type-badge ${item.content_type}">${item.content_type.toUpperCase()}</span></td>
      <td title="${cs}">${cs}</td>
      <td>${item.duration}s</td>
      <td>${item.mode==="once"?"—":item.interval+"s"}</td>
      <td>${item.priority}</td><td>${lr}</td>
      <td><button class="row-btn" onclick="toggleSchedItem('${item.id}',${!item.enabled})">${item.enabled?"ON":"OFF"}</button></td>
      <td><button class="row-btn del-btn" onclick="deleteSchedItem('${item.id}')">DEL</button></td>
    </tr>`;
  }).join("");
}

async function toggleSchedItem(id,en) {
  await fetch(`${API}/api/scheduler/${id}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:en})});
}
async function deleteSchedItem(id) { await apiDelete(`/api/scheduler/${id}`); showToast("Item removed"); }
async function toggleScheduler() {
  const d = await apiGet("/api/status");
  await apiPost(d?.scheduler?.running ? "/api/scheduler/stop" : "/api/scheduler/start");
  showToast(d?.scheduler?.running ? "Scheduler stopped" : "Scheduler started","ok");
}

// ── Text ──────────────────────────────────────────────────────────
async function sendText() {
  const text   = document.getElementById("txt-msg")?.value?.trim();
  const fsize  = document.getElementById("txt-size")?.value || "14";
  const x      = document.getElementById("txt-x")?.value || "0";
  const y      = document.getElementById("txt-y")?.value || "0";
  const scroll = document.getElementById("txt-scroll")?.value === "true";
  if (!text) { showToast("Enter a message","error"); return; }

  // Preview variable substitution
  const prev = await apiPost("/api/variables/preview", {text});
  if (prev?.substituted && prev.substituted !== text) {
    document.getElementById("txt-preview") && (document.getElementById("txt-preview").textContent = "→ " + prev.substituted);
  }

  const d = await apiPost("/api/display/text",{text,font_size:parseInt(fsize),x:parseInt(x),y:parseInt(y),scroll,clear:true});
  if (d?.success) showToast(scroll?"Scrolling…":"Text sent","ok");
}

// ── IMAGE TAB ─────────────────────────────────────────────────────
let _imageFrames  = [];
let _imagePreview = null;

async function uploadImage() {
  const input = document.getElementById("img-file");
  if (!input?.files[0]) { showToast("Choose a file first","error"); return; }

  const form = new FormData();
  form.append("file",       input.files[0]);
  form.append("threshold",  document.getElementById("img-threshold")?.value || "128");
  form.append("brightness", document.getElementById("img-brightness")?.value || "1.0");
  form.append("contrast",   document.getElementById("img-contrast")?.value || "1.0");
  form.append("dither",     document.getElementById("img-dither")?.value || "none");
  form.append("scale",      document.getElementById("img-scale")?.value || "fit");
  form.append("invert",     document.getElementById("img-invert")?.checked ? "true" : "false");

  showToast("Processing image…","warn");
  try {
    const r = await fetch(`${API}/api/image/upload`, {method:"POST", body:form});
    const d = await r.json();
    if (d.success) {
      _imageFrames = d.frames;
      renderImagePreview(d.frames[0].bitmap);
      const info = document.getElementById("img-info");
      if (info) info.textContent = `${d.frame_count} frame${d.frame_count>1?"s":""} — ${d.animated?"animated":"static"}`;
      showToast(`Image processed: ${d.frame_count} frame(s)`,"ok");
    } else {
      showToast(d.error||"Processing failed","error");
    }
  } catch(e) { showToast("Upload failed","error"); }
}

function renderImagePreview(bitmap) {
  const canvas = document.getElementById("img-preview-canvas");
  if (!canvas || !bitmap) return;
  const DW=84, DH=42, DOT=4, GAP=1;
  const step = DOT+GAP;
  canvas.width  = DW*step+GAP;
  canvas.height = DH*step+GAP;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#080808";
  ctx.fillRect(0,0,canvas.width,canvas.height);
  for (let row=0;row<DH;row++) {
    for (let col=0;col<DW;col++) {
      const on = bitmap[row]&&bitmap[row][col];
      ctx.fillStyle = on ? "#e8e8e0" : "#161614";
      ctx.fillRect(col*step+GAP, row*step+GAP, DOT, DOT);
    }
  }
}

async function sendImageToDisplay() {
  if (!_imageFrames.length) { showToast("Upload an image first","error"); return; }
  const loop = parseInt(document.getElementById("img-loop")?.value||"1");
  const d    = await apiPost("/api/image/display",{frames:_imageFrames,loop});
  if (d?.success) showToast(`Sending ${d.frames} frame(s)`,"ok");
}

async function addImageToCue() {
  if (!_imageFrames.length) { showToast("Upload an image first","error"); return; }
  const label = document.getElementById("img-cue-label")?.value || "Image cue";
  const loop  = parseInt(document.getElementById("img-loop")?.value||"1");
  const d = await apiPost("/api/cues",{
    label, content_type:"image",
    content:{frames:_imageFrames, loop},
    duration:parseFloat(document.getElementById("img-dur")?.value||"10"),
  });
  if (d?.success) { showToast(`Cue '${label}' added`,"ok"); }
}

// ── PIXEL EDITOR ──────────────────────────────────────────────────
const PE = {
  canvas: null, ctx: null,
  W:84, H:42, DOT:6, GAP:1,
  buf: null, tool:"pencil", drawing:false, drawVal:1,
};

function setupPixelEditor() {
  PE.canvas = document.getElementById("pe-canvas");
  if (!PE.canvas) return;
  PE.ctx = PE.canvas.getContext("2d");
  const step = PE.DOT + PE.GAP;
  PE.canvas.width  = PE.W * step + PE.GAP;
  PE.canvas.height = PE.H * step + PE.GAP;
  PE.buf = Array.from({length:PE.H},()=>Array(PE.W).fill(0));
  peRender();

  PE.canvas.addEventListener("mousedown",  e => { PE.drawing=true; peApply(e); });
  PE.canvas.addEventListener("mousemove",  e => { if(PE.drawing) peApply(e); });
  PE.canvas.addEventListener("mouseup",    () => PE.drawing=false);
  PE.canvas.addEventListener("mouseleave", () => PE.drawing=false);
  PE.canvas.addEventListener("touchstart", e => { e.preventDefault(); PE.drawing=true; peApplyTouch(e); },{passive:false});
  PE.canvas.addEventListener("touchmove",  e => { e.preventDefault(); if(PE.drawing) peApplyTouch(e); },{passive:false});
  PE.canvas.addEventListener("touchend",   () => PE.drawing=false);
}

function peDotFromEvent(e) {
  const rect = PE.canvas.getBoundingClientRect();
  const step = PE.DOT + PE.GAP;
  const sx   = PE.canvas.width  / rect.width;
  const sy   = PE.canvas.height / rect.height;
  const col  = Math.floor((e.clientX - rect.left)  * sx / step);
  const row  = Math.floor((e.clientY - rect.top)   * sy / step);
  return {col, row};
}

function peApply(e) {
  const {col,row} = peDotFromEvent(e);
  if (col<0||col>=PE.W||row<0||row>=PE.H) return;
  if (e.type === "mousedown") PE.drawVal = PE.tool==="eraser" ? 0 : (PE.buf[row][col]===1?0:1);
  if (PE.tool === "fill") { peFill(col,row,PE.buf[row][col],1-PE.buf[row][col]); }
  else { PE.buf[row][col] = PE.drawVal; }
  peRender();
}

function peApplyTouch(e) {
  const touch = e.touches[0];
  peApply({clientX:touch.clientX, clientY:touch.clientY, type:e.type==="touchstart"?"mousedown":"mousemove"});
}

function peFill(x, y, target, replacement) {
  if (target === replacement) return;
  const stack = [[x,y]];
  while (stack.length) {
    const [cx,cy] = stack.pop();
    if (cx<0||cx>=PE.W||cy<0||cy>=PE.H||PE.buf[cy][cx]!==target) continue;
    PE.buf[cy][cx] = replacement;
    stack.push([cx+1,cy],[cx-1,cy],[cx,cy+1],[cx,cy-1]);
  }
}

function peRender() {
  const step = PE.DOT + PE.GAP;
  PE.ctx.fillStyle = "#080808";
  PE.ctx.fillRect(0,0,PE.canvas.width,PE.canvas.height);
  for (let r=0;r<PE.H;r++) {
    for (let c=0;c<PE.W;c++) {
      PE.ctx.fillStyle = PE.buf[r][c] ? "#e8e8e0" : "#161614";
      PE.ctx.fillRect(c*step+PE.GAP, r*step+PE.GAP, PE.DOT, PE.DOT);
    }
  }
}

function peSetTool(tool) {
  PE.tool = tool;
  document.querySelectorAll(".pe-tool").forEach(b => b.classList.toggle("active", b.dataset.tool===tool));
}

function peClear()   { PE.buf = Array.from({length:PE.H},()=>Array(PE.W).fill(0)); peRender(); }
function peFillAll() { PE.buf = Array.from({length:PE.H},()=>Array(PE.W).fill(1)); peRender(); }
function peInvert()  { PE.buf = PE.buf.map(r=>r.map(v=>1-v)); peRender(); }

async function pePush() {
  const d = await apiPost("/api/pixel/push", {buffer: PE.buf});
  if (d?.success) showToast("Pixel buffer pushed","ok");
}

async function peAddToCue() {
  const label = document.getElementById("pe-cue-label")?.value || "Pixel cue";
  const frames = [{bitmap: PE.buf, duration:0}];
  const d = await apiPost("/api/cues",{
    label, content_type:"image",
    content:{frames, loop:1},
    duration:parseFloat(document.getElementById("pe-dur")?.value||"5"),
  });
  if (d?.success) showToast(`Cue '${label}' added`,"ok");
}

function peSyncFromDisplay() {
  apiGet("/api/buffer").then(d => {
    if (d?.buffer) {
      PE.buf = d.buffer.map(row => row.map(v => v ? 1 : 0));
      peRender();
      showToast("Display copied to editor","ok");
    }
  });
}

// ── VARIABLES ─────────────────────────────────────────────────────
async function loadVariablesConfig() {
  const d = await apiGet("/api/variables");
  if (!d?.config) return;
  const c = d.config;
  if (document.getElementById("var-api-key"))   document.getElementById("var-api-key").value   = c.weather_api_key || "";
  if (document.getElementById("var-city"))       document.getElementById("var-city").value       = c.weather_city || "";
  if (document.getElementById("var-units"))      document.getElementById("var-units").value      = c.weather_units || "imperial";
  if (document.getElementById("var-rss-url"))    document.getElementById("var-rss-url").value    = c.rss_url || "";
  if (document.getElementById("var-update"))     document.getElementById("var-update").value     = c.update_interval || 300;
  updateVariablesDisplay(d.values);
}

async function saveVariablesConfig() {
  const cfg = {
    weather_api_key:  document.getElementById("var-api-key")?.value || "",
    weather_city:     document.getElementById("var-city")?.value || "",
    weather_units:    document.getElementById("var-units")?.value || "imperial",
    rss_url:          document.getElementById("var-rss-url")?.value || "",
    update_interval:  parseInt(document.getElementById("var-update")?.value || "300"),
  };
  const d = await apiPost("/api/variables/config", cfg);
  if (d?.success) { showToast("Variables config saved","ok"); refreshVariables(); }
}

async function refreshVariables() {
  const d = await apiGet("/api/variables");
  if (d?.values) updateVariablesDisplay(d.values);
}

function updateVariablesDisplay(values) {
  const grid = document.getElementById("var-grid");
  if (!grid || !values) return;
  grid.innerHTML = Object.entries(values)
    .filter(([k]) => !k.startsWith("rss_"))
    .map(([k,v]) => `<div class="var-row"><span class="var-token">{${k}}</span><span class="var-val">${v}</span></div>`)
    .join("");
}

async function previewVarText() {
  const text = document.getElementById("var-test-text")?.value;
  if (!text) return;
  const d = await apiPost("/api/variables/preview",{text});
  const out = document.getElementById("var-test-out");
  if (out) out.textContent = d?.substituted || "";
}

// ── Shows ─────────────────────────────────────────────────────────
async function saveShow() {
  const name = document.getElementById("show-name")?.value?.trim();
  if (!name) { showToast("Enter a show name","error"); return; }
  const d = await apiPost("/api/shows/save",{name});
  if (d?.success) { showToast(`Show '${name}' saved`,"ok"); loadShowsList(); }
}

async function loadShowsList() {
  const d    = await apiGet("/api/shows");
  const wrap = document.getElementById("shows-list-wrap");
  if (!wrap) return;
  if (!d?.shows?.length) { wrap.innerHTML='<div class="empty-state">No saved shows</div>'; return; }
  wrap.innerHTML = d.shows.map(s => `
    <div class="show-item">
      <span class="show-name">${s.name}</span>
      <span class="show-meta">${s.saved?.slice(0,10)||"—"}</span>
      <span class="show-cues">${s.cues} CUES</span>
      <button class="row-btn" onclick="loadShow('${s.name}')">LOAD</button>
      <button class="row-btn del-btn" onclick="deleteShow('${s.name}')">DEL</button>
    </div>`).join("");
}

async function loadShow(name) {
  const d = await apiPost("/api/shows/load",{name});
  if (d?.success) showToast(`Show '${name}' loaded`,"ok");
  else showToast(d?.error||"Load failed","error");
}
async function deleteShow(name) {
  await apiDelete(`/api/shows/${name}`); showToast(`'${name}' deleted`); loadShowsList();
}

// ── Toast ─────────────────────────────────────────────────────────
function showToast(msg, type="") {
  const c  = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className   = "toast" + (type?" "+type:"");
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(()=>el.remove(), 3000);
}

// Alias for backward compat
function toast(msg,type) { showToast(msg,type); }
