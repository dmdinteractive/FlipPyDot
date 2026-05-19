/**
 * console.js — Flipdot Console V5 Application Logic
 */
const API = window.location.origin;
let isConnected  = false;
let editingCueId = null;

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupDayButtons();
  scanPorts();
  loadAnimations();
  startPolling();
  updateClock();
  setInterval(updateClock, 1000);
  loadShowsList();
});

// ── Tabs ──────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll(".ws-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ws-tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".ws-pane").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const pane = document.getElementById("tab-" + btn.dataset.tab);
      if (pane) pane.classList.add("active");
    });
  });
}

// ── Clock ─────────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById("sys-clock");
  if (el) el.textContent = new Date().toTimeString().slice(0,8);
  const sb = document.getElementById("sb-time");
  if (sb) sb.textContent = new Date().toLocaleString();
}

// ── API helpers ───────────────────────────────────────────────────
async function apiPost(url, body = {}) {
  try {
    const r = await fetch(API + url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    return await r.json();
  } catch (e) { toast("Server unreachable", "error"); return null; }
}

async function apiGet(url) {
  try {
    const r = await fetch(API + url);
    return await r.json();
  } catch { return null; }
}

async function apiDelete(url) {
  try {
    await fetch(API + url, {method: "DELETE"});
  } catch {}
}

// ── Polling ───────────────────────────────────────────────────────
function startPolling() {
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

// ── Connection UI ─────────────────────────────────────────────────
function updateConnectionUI(d) {
  isConnected = d.connected;
  const tally = document.getElementById("tally-conn");
  const label = document.getElementById("tally-conn-label");
  const btn   = document.querySelector(".sysbar-btn[onclick='toggleConnect()']") ||
                document.querySelector(".sysbar-btn");
  const sb    = document.getElementById("sb-conn");

  if (d.connected) {
    tally?.classList.add("online");
    tally?.classList.remove("on-air");
    if (label) label.textContent = d.port?.split("/").pop() || "ONLINE";
    if (sb)    sb.textContent = `SERIAL: ${d.port?.split("/").pop()} OK`;
    sb?.classList.add("ok"); sb?.classList.remove("err");
  } else {
    tally?.classList.remove("online","on-air");
    if (label) label.textContent = "OFFLINE";
    if (sb)    sb.textContent = "SERIAL: OFFLINE";
    sb?.classList.remove("ok"); sb?.classList.add("err");
  }

  if (d.width && d.height) {
    const dims = document.getElementById("sys-dims");
    if (dims) dims.textContent = `${d.width}×${d.height}`;
  }
}

// ── Cue Engine UI ─────────────────────────────────────────────────
function updateCueEngineUI(eng) {
  if (!eng) return;

  // Transport display
  const stateEl = document.getElementById("t-state");
  const numEl   = document.getElementById("t-cur-num");
  const nameEl  = document.getElementById("t-cur-name");
  const elapsed = document.getElementById("t-elapsed");
  const tally   = document.getElementById("tally-cue");
  const label   = document.getElementById("tally-cue-label");
  const sb      = document.getElementById("sb-cue");

  const cur = eng.current_cue;
  if (numEl)  numEl.textContent  = cur ? cur.number : "—";
  if (nameEl) nameEl.textContent = cur ? cur.label  : "NO CUE ACTIVE";
  if (elapsed) elapsed.textContent = eng.elapsed?.toFixed(1) || "0.0";

  // State styling
  if (stateEl) {
    stateEl.textContent = eng.state;
    stateEl.className   = "t-state " + eng.state.toLowerCase().replace("_","-");
  }

  // Tally
  if (tally && label) {
    tally.className = "tally" + (eng.state !== "IDLE" ? " on-air" : "");
    label.textContent = eng.state;
  }

  if (sb) sb.textContent = `CUE ENGINE: ${eng.state} ${cur ? `[${cur.number} ${cur.label}]` : ""}`;

  // Program monitor metadata
  const pgmNum   = document.getElementById("pgm-cue-num");
  const pgmLabel = document.getElementById("pgm-cue-label");
  if (pgmNum)   pgmNum.textContent   = cur ? cur.number : "—";
  if (pgmLabel) pgmLabel.textContent = cur ? cur.label  : "NO CUE";

  const pvwNum   = document.getElementById("pvw-cue-num");
  const pvwLabel = document.getElementById("pvw-cue-label");
  const nxt      = eng.next_cue;
  if (pvwNum)   pvwNum.textContent   = nxt ? nxt.number : "—";
  if (pvwLabel) pvwLabel.textContent = nxt ? nxt.label  : "END OF LIST";

  // Cue table highlight
  document.querySelectorAll(".cue-table tr[data-cue-id]").forEach(row => {
    row.classList.toggle("active-cue", cur && row.dataset.cueId === cur.id);
  });

  // Render cue table if cue list changed
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
    toast("Disconnected");
  } else {
    const port = document.getElementById("port-select")?.value;
    if (!port) { toast("Select a port first", "error"); return; }
    const d = await apiPost("/api/connect", {port});
    if (d?.success) toast("Connected: " + port, "ok");
    else            toast("Connection failed", "error");
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

  if (!cues.length) {
    tbody.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";

  // Only re-render if changed
  const key = cues.map(c => c.id + c.label + c.duration).join("|");
  if (tbody._lastKey === key) return;
  tbody._lastKey = key;

  tbody.innerHTML = cues.map(cue => {
    const ct = cue.content_type || "clear";
    const cs = cue.content || {};
    const contentStr = ct === "text" ? (cs.text || "—")
                     : ct === "animation" ? (cs.animation_id || "—")
                     : ct;
    return `
      <tr data-cue-id="${cue.id}">
        <td class="col-num">${cue.number}</td>
        <td class="col-label" title="${cue.label}">${cue.label}</td>
        <td class="col-type"><span class="type-badge ${ct}">${ct.toUpperCase()}</span></td>
        <td class="col-content" title="${contentStr}">${contentStr}</td>
        <td class="col-wait">${cue.pre_wait}s</td>
        <td class="col-dur">${cue.duration < 0 ? "HOLD" : cue.duration + "s"}</td>
        <td class="col-fade">${cue.fade_in}s</td>
        <td class="col-follow">${cue.auto_follow ? "AUTO" : "—"}</td>
        <td class="col-actions">
          <button class="row-btn go-btn" onclick="fireJump('${cue.id}')">GO</button>
          <button class="row-btn" onclick="openCueEditor('${cue.id}')">EDIT</button>
          <button class="row-btn del-btn" onclick="deleteCue('${cue.id}')">DEL</button>
        </td>
      </tr>`;
  }).join("");
}

// ── Cue management ────────────────────────────────────────────────
function addCue() {
  openCueEditor(null);
}

function openCueEditor(cueId) {
  editingCueId = cueId;
  const editor = document.getElementById("cue-editor");
  if (!editor) return;
  editor.style.display = "block";

  const numEl  = document.getElementById("ed-cue-num");

  if (cueId) {
    // Load existing cue data from table
    const row = document.querySelector(`tr[data-cue-id="${cueId}"]`);
    if (!row) return;
    // Find cue in engine status — poll once
    apiGet("/api/cues").then(d => {
      const cue = d?.cues?.find(c => c.id === cueId);
      if (!cue) return;
      if (numEl) numEl.textContent = cue.number;
      document.getElementById("ed-number").value  = cue.number;
      document.getElementById("ed-label").value   = cue.label;
      document.getElementById("ed-type").value    = cue.content_type;
      document.getElementById("ed-prewait").value = cue.pre_wait;
      document.getElementById("ed-duration").value= cue.duration;
      document.getElementById("ed-fade").value    = cue.fade_in;
      document.getElementById("ed-auto").value    = cue.auto_follow ? "true" : "false";
      const c = cue.content || {};
      if (cue.content_type === "text") {
        document.getElementById("ed-text").value    = c.text || "";
        document.getElementById("ed-fontsize").value= c.font_size || 14;
        document.getElementById("ed-scroll").value  = c.scroll ? "true" : "false";
      } else if (cue.content_type === "animation") {
        const sel = document.getElementById("ed-anim");
        if (sel) sel.value = c.animation_id || "";
      }
      updateEditorType();
    });
  } else {
    if (numEl) numEl.textContent = "NEW";
    document.getElementById("ed-number").value   = "";
    document.getElementById("ed-label").value    = "";
    document.getElementById("ed-type").value     = "clear";
    document.getElementById("ed-prewait").value  = 0;
    document.getElementById("ed-duration").value = 5;
    document.getElementById("ed-fade").value     = 0;
    document.getElementById("ed-auto").value     = "false";
    updateEditorType();
  }

  editor.scrollIntoView({behavior: "smooth", block: "end"});
}

function updateEditorType() {
  const type = document.getElementById("ed-type")?.value;
  document.getElementById("ed-text-field")?.style.setProperty("display", type === "text" ? "block" : "none");
  document.getElementById("ed-fontsize-field")?.style.setProperty("display", type === "text" ? "block" : "none");
  document.getElementById("ed-scroll-field")?.style.setProperty("display", type === "text" ? "block" : "none");
  document.getElementById("ed-anim-field")?.style.setProperty("display", type === "animation" ? "block" : "none");
}

async function saveCueEdit() {
  const type     = document.getElementById("ed-type").value;
  const number   = parseFloat(document.getElementById("ed-number").value) || undefined;
  const label    = document.getElementById("ed-label").value || `Cue ${number || ""}`;
  const prewait  = parseFloat(document.getElementById("ed-prewait").value) || 0;
  const duration = parseFloat(document.getElementById("ed-duration").value) || 5;
  const fade     = parseFloat(document.getElementById("ed-fade").value) || 0;
  const auto     = document.getElementById("ed-auto").value === "true";

  let content = {};
  if (type === "text") {
    content = {
      text:      document.getElementById("ed-text").value,
      font_size: parseInt(document.getElementById("ed-fontsize").value),
      scroll:    document.getElementById("ed-scroll").value === "true",
    };
  } else if (type === "animation") {
    content = { animation_id: document.getElementById("ed-anim").value };
  }

  const payload = {
    number, label,
    content_type: type, content,
    pre_wait: prewait, duration, fade_in: fade, auto_follow: auto,
  };

  let d;
  if (editingCueId) {
    d = await fetch(`${API}/api/cues/${editingCueId}`, {
      method: "PUT",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    }).then(r => r.json());
    if (d.success) toast("Cue updated", "ok");
  } else {
    d = await apiPost("/api/cues", payload);
    if (d?.success) toast(`Cue ${d.cue?.number} added`, "ok");
  }
  cancelCueEdit();
}

function cancelCueEdit() {
  editingCueId = null;
  const editor = document.getElementById("cue-editor");
  if (editor) editor.style.display = "none";
}

async function deleteCue(id) {
  await apiDelete(`/api/cues/${id}`);
  toast("Cue deleted");
}

async function fireJump(id) {
  await apiPost("/api/transport/jump", {cue: id});
  toast("Jumped to cue", "ok");
}

async function fireCueDirect() {
  await saveCueEdit();
}

async function clearCueList() {
  const d = await apiGet("/api/cues");
  if (!d?.cues) return;
  for (const cue of d.cues) {
    await apiDelete(`/api/cues/${cue.id}`);
  }
  toast("Cue list cleared");
}

// ── Scheduler ─────────────────────────────────────────────────────
function setupDayButtons() {
  document.querySelectorAll(".day-btn").forEach(btn => {
    btn.addEventListener("click", () => btn.classList.toggle("active"));
  });
}

function updateSchedMode() {
  const mode = document.getElementById("sf-mode")?.value;
  document.getElementById("sf-interval-wrap").style.display =
    mode === "repeat" || mode === "weekly" ? "block" : "none";
  document.getElementById("sf-time-wrap").style.display =
    mode === "once" ? "block" : "none";
  document.getElementById("sf-days-wrap").style.display =
    mode === "weekly" ? "block" : "none";
}

function addScheduleItem() {
  const form = document.getElementById("sched-form");
  if (form) form.style.display = form.style.display === "none" ? "block" : "none";
}

async function submitScheduleItem() {
  const mode  = document.getElementById("sf-mode").value;
  const ctype = document.getElementById("sf-ctype").value;
  const raw   = document.getElementById("sf-content").value.trim();
  const label = document.getElementById("sf-label").value.trim() || raw;

  let content = {};
  if (ctype === "text")      content = {text: raw, font_size: 14};
  else if (ctype === "animation") content = {animation_id: raw};

  const days = [];
  document.querySelectorAll(".day-btn.active").forEach(b => days.push(parseInt(b.dataset.day)));

  const startEl = document.getElementById("sf-start")?.value;
  const st      = startEl ? new Date(startEl).toISOString() : null;

  const d = await apiPost("/api/scheduler", {
    label, content_type: ctype, content, mode,
    duration:  parseFloat(document.getElementById("sf-dur")?.value || "5"),
    interval:  parseFloat(document.getElementById("sf-interval")?.value || "60"),
    priority:  parseInt(document.getElementById("sf-priority")?.value || "0"),
    start_time: st, days,
  });
  if (d?.success) {
    toast("Scheduler item added", "ok");
    document.getElementById("sf-content").value = "";
  }
}

function renderScheduleTable(items) {
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
  if (tbody._lastKey === key) return;
  tbody._lastKey = key;

  const dayNames = ["M","T","W","T","F","S","S"];
  tbody.innerHTML = items.map(item => {
    const c = item.content || {};
    const contentStr = c.text || c.animation_id || item.content_type;
    const daysStr = item.days?.map(d => dayNames[d]).join("") || "—";
    const lastRun = item.last_run
      ? new Date(item.last_run * 1000).toLocaleTimeString()
      : "never";
    return `
      <tr>
        <td>${item.label || "—"}</td>
        <td><span class="type-badge">${item.mode.toUpperCase()}</span></td>
        <td><span class="type-badge ${item.content_type}">${item.content_type.toUpperCase()}</span></td>
        <td title="${contentStr}">${contentStr}</td>
        <td>${item.duration}s</td>
        <td>${item.mode === "once" ? "—" : item.interval + "s"}</td>
        <td>${item.priority}</td>
        <td>${lastRun}</td>
        <td>
          <button class="row-btn" onclick="toggleSchedItem('${item.id}',${!item.enabled})">
            ${item.enabled ? "ON" : "OFF"}
          </button>
        </td>
        <td>
          <button class="row-btn del-btn" onclick="deleteSchedItem('${item.id}')">DEL</button>
        </td>
      </tr>`;
  }).join("");
}

async function toggleSchedItem(id, enabled) {
  await fetch(`${API}/api/scheduler/${id}`, {
    method: "PUT",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({enabled})
  });
}

async function deleteSchedItem(id) {
  await apiDelete(`/api/scheduler/${id}`);
  toast("Item removed");
}

async function toggleScheduler() {
  const d = await apiGet("/api/status");
  if (d?.scheduler?.running) {
    await apiPost("/api/scheduler/stop");
    toast("Scheduler stopped");
  } else {
    await apiPost("/api/scheduler/start");
    toast("Scheduler started", "ok");
  }
}

// ── Text ──────────────────────────────────────────────────────────
async function sendText() {
  const text   = document.getElementById("txt-msg")?.value?.trim();
  const fsize  = document.getElementById("txt-size")?.value || "14";
  const x      = document.getElementById("txt-x")?.value || "0";
  const y      = document.getElementById("txt-y")?.value || "0";
  const scroll = document.getElementById("txt-scroll")?.value === "true";
  if (!text) { toast("Enter a message", "error"); return; }
  const d = await apiPost("/api/display/text", {
    text, font_size: parseInt(fsize),
    x: parseInt(x), y: parseInt(y), scroll, clear: true
  });
  if (d?.success) toast(scroll ? "Scrolling…" : "Text sent", "ok");
}

// ── Shows ─────────────────────────────────────────────────────────
async function saveShow() {
  const name = document.getElementById("show-name")?.value?.trim();
  if (!name) { toast("Enter a show name", "error"); return; }
  const d = await apiPost("/api/shows/save", {name});
  if (d?.success) { toast(`Show '${name}' saved`, "ok"); loadShowsList(); }
  else             toast("Save failed", "error");
}

async function loadShowsList() {
  const d = await apiGet("/api/shows");
  const wrap = document.getElementById("shows-list-wrap");
  if (!wrap) return;
  if (!d?.shows?.length) {
    wrap.innerHTML = '<div class="empty-state">No saved shows</div>';
    return;
  }
  wrap.innerHTML = d.shows.map(s => `
    <div class="show-item">
      <span class="show-name">${s.name}</span>
      <span class="show-meta">${s.saved?.slice(0,10) || "—"}</span>
      <span class="show-cues">${s.cues} CUES</span>
      <button class="row-btn" onclick="loadShow('${s.name}')">LOAD</button>
      <button class="row-btn del-btn" onclick="deleteShow('${s.name}')">DEL</button>
    </div>`).join("");
}

async function loadShow(name) {
  const d = await apiPost("/api/shows/load", {name});
  if (d?.success) { toast(`Show '${name}' loaded`, "ok"); }
  else            toast(d?.error || "Load failed", "error");
}

async function deleteShow(name) {
  await apiDelete(`/api/shows/${name}`);
  toast(`'${name}' deleted`);
  loadShowsList();
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
