/**
 * main.js — Flipdot Controller UI Logic
 */

const API = "http://localhost:5000";
let isConnected = false;

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  scanPorts();
  // loadAnimations called from animations_ui.js
  loadSchedule();
  startPolling();
});

// ── Tabs ──────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab)?.classList.add("active");
    });
  });
}

// ── API helpers ───────────────────────────────────────────────────
async function apiPost(url, body = {}) {
  try {
    const res = await fetch(API + url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (e) {
    toast("Server unreachable", "error");
    return null;
  }
}

async function apiGet(url) {
  try {
    const res = await fetch(API + url);
    return await res.json();
  } catch { return null; }
}

// ── Polling ───────────────────────────────────────────────────────
function startPolling() {
  pollStatus();
  pollBuffer();
  setInterval(pollStatus, 2000);
  setInterval(pollBuffer, 600);
}

async function pollStatus() {
  const d = await apiGet("/api/status");
  if (!d) return;
  isConnected = d.connected;

  const dot  = document.getElementById("status-dot");
  const txt  = document.getElementById("status-text");
  const btn  = document.getElementById("btn-connect");

  if (d.connected) {
    dot.className = "status-indicator online";
    txt.textContent = d.port?.split("/").pop() || "ONLINE";
    btn.textContent = "DISCONNECT";
    btn.className   = "btn-connect connected";
  } else {
    dot.className = "status-indicator";
    txt.textContent = "OFFLINE";
    btn.textContent = "CONNECT";
    btn.className   = "btn-connect";
  }

  if (d.width && d.height) {
    document.getElementById("hdr-dims").textContent    = `${d.width} × ${d.height}`;
    document.getElementById("hdr-panels").textContent  = `18 CONTROLLERS`;
  }
}

async function pollBuffer() {
  const d = await apiGet("/api/buffer");
  if (d?.buffer) updateBuffer(d.buffer);
}

// ── Connection ────────────────────────────────────────────────────
async function toggleConnect() {
  if (isConnected) {
    await apiPost("/api/disconnect");
    toast("Disconnected");
  } else {
    const port = document.getElementById("port-select")?.value;
    if (!port) { toast("Select a port first", "error"); return; }
    const d = await apiPost("/api/connect", { port });
    if (d?.success) toast("Connected to " + port);
    else            toast("Connection failed", "error");
  }
}

async function scanPorts() {
  const sel = document.getElementById("port-select");
  if (!sel) return;
  sel.innerHTML = "<option>Scanning…</option>";
  const data = await apiGet("/api/ports");
  if (!data?.length) {
    sel.innerHTML = "<option value=''>No ports found</option>";
    return;
  }
  sel.innerHTML = "";
  data.forEach(p => {
    const opt       = document.createElement("option");
    opt.value       = p.port;
    opt.textContent = p.port.split("/").pop() + "  —  " + p.description;
    sel.appendChild(opt);
  });
}

// ── Text ──────────────────────────────────────────────────────────
async function sendText() {
  const text      = document.getElementById("text-input")?.value?.trim();
  const font_size = parseInt(document.getElementById("font-size")?.value || "14");
  const x         = parseInt(document.getElementById("text-x")?.value || "0");
  const y         = parseInt(document.getElementById("text-y")?.value || "0");
  const scroll    = document.getElementById("text-scroll")?.checked;
  const clear     = document.getElementById("text-clear")?.checked;
  if (!text) { toast("Enter a message first", "error"); return; }
  const d = await apiPost("/api/display/text", { text, font_size, x, y, scroll, clear });
  if (d?.success) toast(scroll ? "Scrolling…" : "Text sent");
}

// ── Animations ────────────────────────────────────────────────────
async function loadAnimations() {
  const grid = document.getElementById("anim-grid");
  if (!grid) return;
  const d = await apiGet("/api/animations");
  if (!d?.animations) return;
  grid.innerHTML = "";
  d.animations.forEach(a => {
    const card = document.createElement("div");
    card.className    = "anim-card";
    card.dataset.id   = a.id;
    card.innerHTML    = `<span class="anim-name">${a.name}</span><span class="anim-id">${a.id.replace(/_/g," ").toUpperCase()}</span>`;
    card.addEventListener("click", () => runAnim(a.id, card));
    grid.appendChild(card);
  });
}

async function runAnim(id, card) {
  document.querySelectorAll(".anim-card").forEach(c => c.classList.remove("active"));
  card?.classList.add("active");
  const d = await apiPost("/api/animations/run", { name: id });
  if (d?.success) toast("Running: " + id);
}

// ── Schedule ──────────────────────────────────────────────────────
async function loadSchedule() {
  const d = await apiGet("/api/schedule");
  if (!d) return;
  renderSchedule(d.items || []);
}

function renderSchedule(items) {
  const list = document.getElementById("sched-list");
  if (!list) return;
  if (!items.length) {
    list.innerHTML = '<div class="empty-state">Queue is empty</div>';
    return;
  }
  list.innerHTML = items.map(item => `
    <div class="sched-item" id="si-${item.id}">
      <span class="sched-badge">${item.type.toUpperCase()}</span>
      <span class="sched-content">${item.content}</span>
      <span class="sched-meta">${item.repeat ? "↻ " + item.interval + "s" : item.duration + "s"}</span>
      <button class="sched-del" onclick="removeScheduleItem('${item.id}')">✕</button>
    </div>
  `).join("");
}

async function addScheduleItem() {
  const type     = document.getElementById("sched-type")?.value;
  const content  = document.getElementById("sched-content")?.value?.trim();
  const duration = parseFloat(document.getElementById("sched-dur")?.value || "5");
  const repeat   = document.getElementById("sched-repeat")?.checked;
  const interval = parseFloat(document.getElementById("sched-interval")?.value || "60");
  const startEl  = document.getElementById("sched-start")?.value;
  if (!content) { toast("Enter content first", "error"); return; }
  const d = await apiPost("/api/schedule", {
    type, content, duration, repeat, interval,
    start_time: startEl ? new Date(startEl).toISOString() : null,
  });
  if (d?.success) {
    toast("Added to queue");
    document.getElementById("sched-content").value = "";
    loadSchedule();
  }
}

async function removeScheduleItem(id) {
  await fetch(`${API}/api/schedule/${id}`, { method: "DELETE" });
  document.getElementById("si-" + id)?.remove();
  const list = document.getElementById("sched-list");
  if (list && !list.querySelector(".sched-item")) {
    list.innerHTML = '<div class="empty-state">Queue is empty</div>';
  }
  toast("Removed");
}

async function startScheduler() {
  await apiPost("/api/schedule/start");
  toast("Scheduler running");
}

async function stopScheduler() {
  await apiPost("/api/schedule/stop");
  toast("Scheduler paused");
}

// ── Toast ─────────────────────────────────────────────────────────
function toast(msg, type = "ok") {
  const c  = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className   = "toast" + (type === "error" ? " error" : "");
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}
