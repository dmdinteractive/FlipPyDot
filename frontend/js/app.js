/**
 * app.js — FlipDot Console V7
 * All API calls use window.location.origin — works from any device on the network.
 */

const API = window.location.origin;

// ── Canvas ────────────────────────────────────────────────────────
const DW = 84, DH = 42, DOT = 4, GAP = 1;
let canvas, ctx, lastFt = Date.now(), fCount = 0;

function initCanvas() {
  canvas = document.getElementById("display-canvas");
  if (!canvas) return;
  ctx = canvas.getContext("2d");
  const step = DOT + GAP;
  canvas.width  = DW * step + GAP;
  canvas.height = DH * step + GAP;
  drawBuf(Array.from({length: DH}, () => Array(DW).fill(0)));
}

function drawBuf(buf) {
  if (!ctx) return;
  const step = DOT + GAP;
  ctx.fillStyle = "#0a0a0a";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Panel dividers
  ctx.strokeStyle = "#1a1a14";
  ctx.lineWidth   = 1;
  for (let c = 1; c < 3; c++) {
    const x = c * 28 * step;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
  }
  for (let r = 1; r < 6; r++) {
    const y = r * 7 * step;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  }

  for (let row = 0; row < DH; row++) {
    for (let col = 0; col < DW; col++) {
      const on = buf[row] && buf[row][col];
      const x  = col * step + GAP;
      const y  = row * step + GAP;
      if (on) {
        ctx.shadowColor = "rgba(240,238,228,0.4)";
        ctx.shadowBlur  = 2;
        ctx.fillStyle   = "#f0eee8";
      } else {
        ctx.shadowBlur  = 0;
        ctx.fillStyle   = "#111110";
      }
      ctx.fillRect(x, y, DOT, DOT);
    }
  }
  ctx.shadowBlur = 0;

  // FPS counter
  fCount++;
  const now = Date.now();
  if (now - lastFt >= 1000) {
    const fps = fCount;
    fCount = 0; lastFt = now;
    const el = document.getElementById("canvas-fps");
    if (el) el.textContent = fps + " fps";
  }
}

// ── API helpers ───────────────────────────────────────────────────
async function post(url, body = {}) {
  try {
    const r = await fetch(API + url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    return await r.json();
  } catch (e) {
    toast("Server unreachable", "err");
    return null;
  }
}

async function get(url) {
  try {
    const r = await fetch(API + url);
    return await r.json();
  } catch {
    return null;
  }
}

async function del(url) {
  try {
    await fetch(API + url, {method: "DELETE"});
  } catch {}
}

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initCanvas();
  setupTabs();
  scanPorts();
  loadAnimations();
  initFxParams();
  loadVarsConfig();
  updateClock();
  setInterval(updateClock, 1000);
  setInterval(pollStatus, 1500);
  setInterval(pollBuffer, 600);
  // Slider labels
  [
    ["img-threshold", "img-thr-v", 0],
    ["img-brightness", "img-br-v", 1],
    ["img-contrast",   "img-con-v", 1],
  ].forEach(([id, vid, dp]) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", () => {
      const v = document.getElementById(vid);
      if (v) v.textContent = parseFloat(el.value).toFixed(dp);
    });
  });
});

// ── Tabs ──────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".pane").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const pane = document.getElementById("pane-" + btn.dataset.tab);
      if (pane) pane.classList.add("active");
      if (btn.dataset.tab === "settings") loadShowList();
      if (btn.dataset.tab === "variables") refreshVarGrid();
    });
  });
}

// ── Clock ─────────────────────────────────────────────────────────
function updateClock() {
  const t = new Date().toTimeString().slice(0, 8);
  const el = document.getElementById("hdr-clock");
  if (el) el.textContent = t;
  const sb = document.getElementById("sb-time");
  if (sb) sb.textContent = new Date().toLocaleString();
}

// ── Polling ───────────────────────────────────────────────────────
async function pollStatus() {
  const d = await get("/api/status");
  if (!d) return;
  updateConnUI(d);
  updateSchedUI(d.scheduler);
  updateAnimUI(d.cur_anim);
  updateSysInfo(d);
}

async function pollBuffer() {
  const d = await get("/api/buffer");
  if (d && d.buffer) drawBuf(d.buffer);
}

// ── Connection UI ─────────────────────────────────────────────────
function updateConnUI(d) {
  const dot   = document.getElementById("conn-dot");
  const label = document.getElementById("conn-label");
  const ind   = document.getElementById("conn-indicator");
  const sb    = document.getElementById("sb-conn");
  const dims  = document.getElementById("canvas-dims");

  if (d.connected) {
    dot?.classList.add("on");
    ind?.classList.add("ok");
    if (label) label.textContent = d.port?.split("/").pop() || "ONLINE";
    if (sb)    { sb.textContent = "SERIAL: " + (d.port?.split("/").pop() || "OK"); sb.className = "sb-ok"; }
  } else {
    dot?.classList.remove("on");
    ind?.classList.remove("ok");
    if (label) label.textContent = d.error ? "ERROR" : "OFFLINE";
    if (sb)    { sb.textContent = "SERIAL: OFFLINE"; sb.className = "sb-err"; }
  }
  if (dims && d.width) dims.textContent = d.width + "×" + d.height;
}

async function toggleConnect() {
  const d = await get("/api/status");
  if (d && d.connected) {
    await post("/api/disconnect");
    toast("Disconnected");
  } else {
    const port = document.getElementById("port-select")?.value;
    if (!port) { toast("Select a port first", "err"); return; }
    const r = await post("/api/connect", {port});
    toast(r?.success ? "Connected: " + port : (r?.error || "Failed"), r?.success ? "ok" : "err");
  }
}

async function scanPorts() {
  const sel = document.getElementById("port-select");
  if (!sel) return;
  sel.innerHTML = "<option>Scanning…</option>";
  const d = await get("/api/ports");
  if (!d || !d.length) { sel.innerHTML = "<option value=''>No ports found</option>"; return; }
  sel.innerHTML = "";
  d.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.port;
    opt.textContent = p.port.split("/").pop() + " — " + p.description;
    sel.appendChild(opt);
  });
}

// ── Text ──────────────────────────────────────────────────────────
async function sendText() {
  const text   = document.getElementById("txt-msg")?.value?.trim();
  if (!text) { toast("Enter a message", "err"); return; }
  const fsize  = parseInt(document.getElementById("txt-size")?.value  || "14");
  const x      = parseInt(document.getElementById("txt-x")?.value     || "0");
  const y      = parseInt(document.getElementById("txt-y")?.value     || "0");
  const scroll = document.getElementById("txt-scroll")?.value === "true";
  const d = await post("/api/display/text", {text, font_size: fsize, x, y, scroll});
  if (d?.success) toast(scroll ? "Scrolling…" : "Text sent", "ok");
}

async function previewVars() {
  const text = document.getElementById("txt-msg")?.value;
  if (!text) return;
  const d = await post("/api/variables/preview", {text});
  const el = document.getElementById("txt-preview");
  if (el && d) el.textContent = "→ " + d.substituted;
}

// ── Scheduler ─────────────────────────────────────────────────────
function updateSchedUI(sched) {
  if (!sched) return;
  const btn   = document.getElementById("sched-toggle-btn");
  const badge = document.getElementById("sched-status-badge");
  const sb    = document.getElementById("sb-sched");

  if (sched.running) {
    if (btn)   { btn.textContent = "⏹ STOP SCHEDULER"; btn.className = "btn btn-outline"; }
    if (badge) badge.textContent = "RUNNING";
    if (sb)    sb.textContent = "SCHEDULER: RUNNING";
  } else {
    if (btn)   { btn.textContent = "▶ START SCHEDULER"; btn.className = "btn btn-solid"; }
    if (badge) badge.textContent = "";
    if (sb)    sb.textContent = "SCHEDULER: OFF";
  }
  renderSchedTable(sched.items || []);
}

function updateSchedMode() {
  const mode = document.getElementById("sf-mode")?.value;
  const intWrap = document.getElementById("sf-interval-wrap");
  if (intWrap) intWrap.style.display = mode === "once" ? "none" : "block";
}

function updateSchedType() {
  const type = document.getElementById("sf-type")?.value;
  const wrap = document.getElementById("sf-text-wrap");
  const lbl  = wrap?.querySelector(".fl");
  if (!wrap) return;
  if (type === "clear" || type === "fill") {
    wrap.style.display = "none";
  } else {
    wrap.style.display = "block";
    if (lbl) lbl.textContent = type === "animation" ? "ANIMATION NAME" : "MESSAGE (supports {time} {date} {temp} {rss})";
  }
}

async function addScheduleItem() {
  const type  = document.getElementById("sf-type").value;
  const raw   = document.getElementById("sf-content").value.trim();
  const label = document.getElementById("sf-label").value.trim() || raw;

  let content_type = type;
  let content = {};

  if (type === "scroll") {
    content_type = "text";
    content = {text: raw, font_size: 14, scroll: true};
  } else if (type === "text") {
    content = {text: raw, font_size: 14, scroll: false};
  } else if (type === "animation") {
    content = {animation_id: raw};
  }

  const d = await post("/api/scheduler", {
    label,
    content_type,
    content,
    mode:     document.getElementById("sf-mode").value,
    duration: parseFloat(document.getElementById("sf-dur").value    || "8"),
    interval: parseFloat(document.getElementById("sf-interval").value || "60"),
    priority: parseInt(document.getElementById("sf-priority").value   || "0"),
  });

  if (d?.success) {
    toast("Scheduled: " + label, "ok");
    document.getElementById("sf-label").value   = "";
    document.getElementById("sf-content").value = "";
  }
}

function renderSchedTable(items) {
  const tbody = document.getElementById("sched-tbody");
  const empty = document.getElementById("sched-empty");
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";
  const key = items.map(i => i.id + i.enabled + i.last_run).join("|");
  if (tbody._k === key) return;
  tbody._k = key;

  tbody.innerHTML = items.map(item => {
    const c   = item.content || {};
    const cs  = c.text || c.animation_id || item.content_type;
    const lr  = item.last_run
      ? new Date(item.last_run * 1000).toLocaleTimeString() : "never";
    const en  = item.enabled !== false;
    return `<tr class="${en ? "sched-running" : ""}">
      <td>${item.label || "—"}</td>
      <td>${item.mode}</td>
      <td>${item.content_type}</td>
      <td title="${cs}" style="max-width:140px;overflow:hidden;text-overflow:ellipsis">${cs}</td>
      <td>${item.duration}s</td>
      <td>${item.mode === "once" ? "—" : item.interval + "s"}</td>
      <td>
        <button class="btn btn-outline btn-sm"
          onclick="toggleSchedItem('${item.id}', ${!en})">${en ? "ON" : "OFF"}</button>
      </td>
      <td>
        <button class="btn btn-outline btn-sm btn-danger"
          onclick="del('/api/scheduler/${item.id}')">✕</button>
      </td>
    </tr>`;
  }).join("");
}

async function toggleSchedItem(id, enabled) {
  await fetch(API + "/api/scheduler/" + id, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({enabled}),
  });
}

async function toggleScheduler() {
  const d = await get("/api/status");
  await post(d?.scheduler?.running ? "/api/scheduler/stop" : "/api/scheduler/start");
  toast(d?.scheduler?.running ? "Scheduler stopped" : "Scheduler started", "ok");
}

// ── Animations ────────────────────────────────────────────────────
let allAnims = [], selAnim = null;

async function loadAnimations() {
  const d = await get("/api/animations");
  if (!d?.animations) return;
  allAnims = d.animations;
  renderAnimGrid();
}

function renderAnimGrid() {
  const container = document.getElementById("anim-list");
  if (!container) return;
  const cats = {};
  allAnims.forEach(a => {
    if (!cats[a.category]) cats[a.category] = [];
    cats[a.category].push(a);
  });
  const labels = {geometric:"GEOMETRIC", physics:"PHYSICS", text:"TEXT", cellular:"CELLULAR", data:"DATA"};
  container.innerHTML = "";
  Object.entries(labels).forEach(([cat, label]) => {
    const anims = cats[cat];
    if (!anims) return;
    const lbl = document.createElement("div");
    lbl.className   = "anim-cat-label";
    lbl.textContent = label;
    container.appendChild(lbl);
    const grid = document.createElement("div");
    grid.className = "anim-grid";
    anims.forEach(a => {
      const card = document.createElement("div");
      card.className  = "anim-card";
      card.dataset.id = a.id;
      card.innerHTML  = `<span class="anim-name">${a.name}</span>`;
      card.addEventListener("click", () => selectAnim(a, card));
      grid.appendChild(card);
    });
    container.appendChild(grid);
  });
}

function selectAnim(anim, card) {
  selAnim = anim;
  document.querySelectorAll(".anim-card").forEach(c => c.classList.remove("active"));
  card.classList.add("active");
  renderParamPanel(anim);
}

function renderParamPanel(anim) {
  const panel = document.getElementById("anim-params");
  if (!panel) return;
  panel.innerHTML = `<div class="param-title">${anim.name.toUpperCase()}</div>`;
  (anim.params || []).forEach(p => {
    const row = document.createElement("div");
    row.className = "param-row";
    if (p.type === "range") {
      row.innerHTML = `
        <label class="fl">${p.label}</label>
        <div class="range-wrap">
          <input type="range" id="ap-${p.id}" min="${p.min}" max="${p.max}" step="${p.step}" value="${p.default}">
          <span class="range-val" id="av-${p.id}">${p.default}</span>
        </div>`;
      setTimeout(() => {
        const inp = document.getElementById(`ap-${p.id}`);
        const val = document.getElementById(`av-${p.id}`);
        if (inp && val) inp.addEventListener("input", () => { val.textContent = inp.value; });
      }, 0);
    } else if (p.type === "text") {
      row.innerHTML = `<label class="fl">${p.label}</label>
        <input type="text" class="fi" id="ap-${p.id}" value="${p.default}">`;
    }
    panel.appendChild(row);
  });
  const btn = document.createElement("button");
  btn.className   = "btn btn-solid";
  btn.textContent = "▶ RUN " + anim.name.toUpperCase();
  btn.onclick     = runSelectedAnim;
  panel.appendChild(btn);
}

async function runSelectedAnim() {
  if (!selAnim) { toast("Select an animation", "err"); return; }
  const opts = {};
  (selAnim.params || []).forEach(p => {
    const el = document.getElementById(`ap-${p.id}`);
    if (el) opts[p.id] = p.type === "range" ? parseFloat(el.value) : el.value;
  });
  const d = await post("/api/animations/run", {name: selAnim.id, options: opts});
  if (d?.success) toast(selAnim.name + " running", "ok");
}

function updateAnimUI(curAnim) {
  const sb = document.getElementById("sb-anim");
  if (sb) sb.textContent = "ANIM: " + (curAnim || "—");
}

// ── Image ─────────────────────────────────────────────────────────
let _imgFrames = [];

async function uploadImage() {
  const input = document.getElementById("img-file");
  if (!input?.files[0]) { toast("Choose a file first", "err"); return; }
  const form = new FormData();
  form.append("file",       input.files[0]);
  form.append("threshold",  document.getElementById("img-threshold")?.value || "128");
  form.append("brightness", document.getElementById("img-brightness")?.value || "1.0");
  form.append("contrast",   document.getElementById("img-contrast")?.value   || "1.0");
  form.append("dither",     document.getElementById("img-dither")?.value     || "none");
  form.append("scale",      document.getElementById("img-scale")?.value      || "fit");
  form.append("invert",     document.getElementById("img-invert")?.checked ? "true" : "false");
  toast("Processing…");
  try {
    const r = await fetch(API + "/api/image/upload", {method: "POST", body: form});
    const d = await r.json();
    if (d.success) {
      _imgFrames = d.frames;
      renderImgPreview(d.frames[0].bitmap);
      const info = document.getElementById("img-info");
      if (info) info.textContent = d.frame_count + " frame" + (d.frame_count > 1 ? "s" : "") + (d.animated ? " — animated GIF" : "");
      const btn = document.getElementById("img-send-btn");
      if (btn) btn.disabled = false;
      toast("Processed: " + d.frame_count + " frame(s)", "ok");
    } else {
      toast(d.error || "Processing failed", "err");
    }
  } catch (e) { toast("Upload failed", "err"); }
}

function renderImgPreview(bitmap) {
  const canvas = document.getElementById("img-preview-canvas");
  if (!canvas || !bitmap) return;
  const step = DOT + GAP;
  canvas.width  = DW * step + GAP;
  canvas.height = DH * step + GAP;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#0a0a0a";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let row = 0; row < DH; row++) {
    for (let col = 0; col < DW; col++) {
      ctx.fillStyle = bitmap[row] && bitmap[row][col] ? "#f0eee8" : "#111110";
      ctx.fillRect(col * step + GAP, row * step + GAP, DOT, DOT);
    }
  }
  const el = document.getElementById("img-preview-canvas");
  if (el) el.style.width = "336px";
}

async function sendImage() {
  if (!_imgFrames.length) { toast("Upload an image first", "err"); return; }
  const loop = parseInt(document.getElementById("img-loop")?.value || "1");
  const d    = await post("/api/image/display", {frames: _imgFrames, loop});
  if (d?.success) toast("Sending " + d.frames + " frame(s)", "ok");
}

// ── Variables ─────────────────────────────────────────────────────
async function loadVarsConfig() {
  const d = await get("/api/variables");
  if (!d?.config) return;
  const c = d.config;
  const set = (id, key) => {
    const el = document.getElementById(id);
    if (el && c[key] !== undefined) el.value = c[key];
  };
  set("var-key",      "weather_api_key");
  set("var-city",     "weather_city");
  set("var-units",    "weather_units");
  set("var-rss",      "rss_url");
  set("var-interval", "update_interval");
  if (d.values) updateVarGrid(d.values);
}

async function saveVars() {
  const cfg = {
    weather_api_key:  document.getElementById("var-key")?.value      || "",
    weather_city:     document.getElementById("var-city")?.value     || "",
    weather_units:    document.getElementById("var-units")?.value    || "imperial",
    rss_url:          document.getElementById("var-rss")?.value      || "",
    update_interval:  parseInt(document.getElementById("var-interval")?.value || "300"),
  };
  const d = await post("/api/variables/config", cfg);
  if (d?.success) { toast("Variables saved", "ok"); refreshVars(); }
}

async function refreshVars() {
  const d = await get("/api/variables/values");
  if (d) updateVarGrid(d);
}

async function refreshVarGrid() {
  const d = await get("/api/variables/values");
  if (d) updateVarGrid(d);
}

function updateVarGrid(values) {
  const grid = document.getElementById("var-grid");
  if (!grid || !values) return;
  grid.innerHTML = Object.entries(values)
    .filter(([k]) => !k.startsWith("rss_"))
    .map(([k, v]) => `
      <div style="display:flex;gap:0.75rem;padding:5px 8px;background:var(--surface);font-family:var(--f-mono);font-size:0.65rem">
        <span style="color:var(--text);min-width:110px;flex-shrink:0">{${k}}</span>
        <span style="color:var(--mid)">${v}</span>
      </div>`)
    .join("");
}

async function testVar() {
  const text = document.getElementById("var-test")?.value;
  if (!text) return;
  const d = await post("/api/variables/preview", {text});
  const out = document.getElementById("var-test-out");
  if (out && d) out.textContent = "→ " + d.substituted;
}

// ── Effects ───────────────────────────────────────────────────────
const FX_PARAMS = {
  flicker:  [{id:"rate",    label:"Rate",    min:0.01, max:0.3,  step:0.01, default:0.05}],
  pulse:    [{id:"speed",   label:"Speed",   min:0.1,  max:5.0,  step:0.1,  default:0.5}],
  chase:    [{id:"speed",   label:"Speed",   min:0.5,  max:5.0,  step:0.5,  default:1.0}],
  scanline: [{id:"speed",   label:"Speed",   min:0.2,  max:3.0,  step:0.2,  default:0.5}],
  noise:    [{id:"density", label:"Density", min:0.01, max:0.3,  step:0.01, default:0.05}],
};

function initFxParams() { updateFxParams(); }

function updateFxParams() {
  const type   = document.getElementById("fx-type")?.value || "flicker";
  const params = FX_PARAMS[type] || [];
  const div    = document.getElementById("fx-params");
  if (!div) return;
  div.innerHTML = params.map(p => `
    <div class="param-row" style="margin-top:8px">
      <label class="fl">${p.label}</label>
      <div class="range-wrap">
        <input type="range" id="fxp-${p.id}" min="${p.min}" max="${p.max}" step="${p.step}" value="${p.default}">
        <span class="range-val" id="fxv-${p.id}">${p.default}</span>
      </div>
    </div>`).join("");
  params.forEach(p => {
    const inp = document.getElementById(`fxp-${p.id}`);
    const val = document.getElementById(`fxv-${p.id}`);
    if (inp && val) inp.addEventListener("input", () => { val.textContent = inp.value; });
  });
}

async function addEffect() {
  const type   = document.getElementById("fx-type")?.value || "flicker";
  const name   = document.getElementById("fx-name")?.value || "fx1";
  const params = FX_PARAMS[type] || [];
  const opts   = {};
  params.forEach(p => {
    const el = document.getElementById(`fxp-${p.id}`);
    if (el) opts[p.id] = parseFloat(el.value);
  });
  await post("/api/effects", {name, type, params: opts});
  toast("Effect added: " + name, "ok");
  loadFxList();
}

async function loadFxList() {
  const d    = await get("/api/effects");
  const list = document.getElementById("fx-list");
  if (!list || !d) return;
  const active = d.effects || {};
  if (!Object.keys(active).length) {
    list.innerHTML = '<div class="empty" style="text-align:left;padding:0">No active effects</div>';
    return;
  }
  list.innerHTML = Object.entries(active).map(([name, cfg]) => `
    <div class="fx-item">
      <span>${name}</span>
      <span style="color:var(--dim)">${cfg.type}</span>
      <button class="btn btn-outline btn-sm btn-danger"
        onclick="del('/api/effects/${name}').then(loadFxList)">✕</button>
    </div>`).join("");
}

// ── Shows ─────────────────────────────────────────────────────────
async function saveShow() {
  const name = document.getElementById("show-name")?.value?.trim();
  if (!name) { toast("Enter a show name", "err"); return; }
  const d = await post("/api/shows/save", {name});
  if (d?.success) { toast("Show saved: " + name, "ok"); loadShowList(); }
}

async function loadShowList() {
  const d    = await get("/api/shows");
  const list = document.getElementById("show-list");
  if (!list) return;
  if (!d?.shows?.length) {
    list.innerHTML = '<div class="empty" style="text-align:left;padding:0">No saved shows</div>';
    return;
  }
  list.innerHTML = d.shows.map(s => `
    <div style="display:flex;align-items:center;gap:0.5rem;padding:5px 0;border-bottom:1px solid var(--surface2);font-family:var(--f-mono);font-size:0.65rem">
      <span style="flex:1;color:var(--text)">${s.name}</span>
      <span style="color:var(--dim)">${s.saved?.slice(0, 10) || ""}</span>
      <button class="btn btn-outline btn-sm" onclick="loadShow('${s.name}')">LOAD</button>
      <button class="btn btn-outline btn-sm btn-danger" onclick="del('/api/shows/${s.name}').then(loadShowList)">✕</button>
    </div>`).join("");
}

async function loadShow(name) {
  const d = await post("/api/shows/load", {name});
  if (d?.success) toast("Show loaded: " + name, "ok");
  else toast(d?.error || "Load failed", "err");
}

// ── System info ───────────────────────────────────────────────────
function updateSysInfo(d) {
  const el = document.getElementById("sys-info");
  if (!el) return;
  el.innerHTML = [
    "Port:      " + d.port,
    "Baud:      " + d.baud_rate,
    "Display:   " + d.width + "×" + d.height,
    "Scheduler: " + (d.scheduler?.running ? "RUNNING (" + (d.scheduler?.items?.length || 0) + " items)" : "OFF"),
    "Updated:   " + (d.timestamp?.slice(11, 19) || "—"),
  ].map(s => `<div>${s}</div>`).join("");
}

// ── Toast ─────────────────────────────────────────────────────────
function toast(msg, type = "") {
  const c  = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className   = "toast" + (type ? " " + type : "");
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}
