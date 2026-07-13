/**
 * app.js — Boot, tabs, polling, and the non-sequencer panes.
 */

let monitor    = null;     // DotCanvas for the big program monitor
let composeEd  = null;     // ContentEditor on the Compose tab
let fCount = 0, lastFt = Date.now();

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  monitor = new DotCanvas(document.getElementById("display-canvas"),
                          {dot: 4, gap: 1, dividers: true});
  monitor.blank();

  setupTabs();
  await loadEditorData();

  composeEd = new ContentEditor(document.getElementById("compose-editor"), {});
  composeEd.setSpec(defaultSpec("text"));

  scanPorts();
  loadFontList();
  loadSources();
  refreshSeq();

  tickClock();
  setInterval(tickClock, 1000);
  setInterval(pollStatus, 1500);
  setInterval(pollBuffer, 500);

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeDrawer();
  });
});

function setupTabs() {
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  const initial = location.hash.slice(1);
  if (initial) showTab(initial);
}

function showTab(tab) {
  const btn = document.querySelector(`.tab[data-tab="${tab}"]`);
  if (!btn) return;
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".pane").forEach(p => p.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("pane-" + tab)?.classList.add("active");
  history.replaceState(null, "", "#" + tab);

  if (tab === "settings")  { loadShowList(); loadFontList(); }
  if (tab === "sources")   loadSources();
  if (tab === "variables") refreshVarGrid();
  if (tab === "effects")   loadFxList();
}

function tickClock() {
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
  applySeqStatus(d.sequencer);

  const sb = document.getElementById("sb-play");
  if (sb) sb.textContent = "PLAYING: " + (d.player?.playing
    ? (d.player.label || d.player.kind || "—") : "—");
  const si = document.getElementById("sys-info");
  if (si) si.innerHTML = [
    "Port:      " + d.port,
    "Baud:      " + d.baud_rate,
    "Display:   " + d.width + "×" + d.height,
    "Sequencer: " + (d.sequencer?.running
      ? `RUNNING (${d.sequencer.steps.length} steps, ${d.sequencer.overlays.length} overlays)`
      : "STOPPED"),
    "Effects:   " + (Object.keys(d.effects?.effects || {}).join(", ") || "none"),
  ].map(s => `<div>${esc(s)}</div>`).join("");
}

async function pollBuffer() {
  const d = await get("/api/buffer");
  if (!d?.buffer) return;
  monitor.draw(d.buffer);
  fCount++;
  const now = Date.now();
  if (now - lastFt >= 1000) {
    const el = document.getElementById("canvas-fps");
    if (el) el.textContent = fCount + " fps";
    fCount = 0; lastFt = now;
  }
}

// ── Connection ────────────────────────────────────────────────────
function updateConnUI(d) {
  const dot   = document.getElementById("conn-dot");
  const label = document.getElementById("conn-label");
  const sb    = document.getElementById("sb-conn");
  const dims  = document.getElementById("canvas-dims");

  if (d.connected) {
    dot?.classList.add("on");
    if (label) label.textContent = d.port?.split("/").pop() || "ONLINE";
    if (sb) { sb.textContent = "SERIAL: " + (d.port?.split("/").pop() || "OK");
              sb.className = "sb-ok"; }
  } else {
    dot?.classList.remove("on");
    if (label) label.textContent = d.error ? "ERROR" : "OFFLINE";
    if (sb) { sb.textContent = "SERIAL: OFFLINE — preview still works";
              sb.className = "sb-err"; }
  }
  if (dims && d.width) dims.textContent = d.width + "×" + d.height;
}

async function toggleConnect() {
  const d = await get("/api/status");
  if (d?.connected) {
    await post("/api/disconnect");
    toast("Disconnected");
    return;
  }
  const port = document.getElementById("port-select")?.value;
  if (!port) { toast("Select a port first", "err"); return; }
  const r = await post("/api/connect", {port});
  toast(r?.success ? "Connected: " + port : (r?.error || "Failed"),
        r?.success ? "ok" : "err");
}

async function scanPorts() {
  const sel = document.getElementById("port-select");
  if (!sel) return;
  sel.innerHTML = "<option>Scanning…</option>";
  const d = await get("/api/ports");
  if (!d?.length) { sel.innerHTML = "<option value=''>No ports found</option>"; return; }
  sel.innerHTML = d.map(p =>
    `<option value="${esc(p.port)}">${esc(p.port.split("/").pop())} — ${esc(p.description)}</option>`
  ).join("");
}

// ── Compose ───────────────────────────────────────────────────────
async function composeSend() {
  const spec = composeEd.getSpec();
  const r = await post("/api/play", {spec});
  if (r?.success) toast("Sent to panel", "ok");
}

async function composeAddStep() {
  const spec = composeEd.getSpec();
  const r = await post("/api/sequencer/steps", {
    content: spec,
    duration: parseFloat(document.getElementById("compose-dur")?.value || "8"),
    label: "",
  });
  if (r?.success) {
    toast("Added to playlist", "ok");
    refreshSeq();
  }
}

// ── Tokens ────────────────────────────────────────────────────────
async function refreshVarGrid() {
  await loadEditorData();
  const grid = document.getElementById("var-grid");
  if (!grid) return;
  grid.innerHTML = TOKEN_GROUPS.map(g => `
    <div class="tok-group">
      <div class="tok-group-head ${g.ok === false ? "err" : ""}">
        ${esc(g.group)}
        ${g.ok === false ? `<span class="src-err">✕ ${esc(g.error || "failed")}</span>` : ""}
      </div>
      ${(g.tokens || []).map(t => `
        <div class="var-row">
          <span class="var-tok">{${esc(t.token)}}</span>
          <span class="var-val">${esc(t.value)}</span>
        </div>`).join("") || '<div class="ed-note">No values yet.</div>'}
    </div>`).join("");
}

async function testToken() {
  const text = document.getElementById("var-test")?.value;
  if (!text) return;
  const d = await post("/api/variables/preview", {text});
  const out = document.getElementById("var-test-out");
  if (out && d) out.textContent = "→ " + d.substituted;
}

// ── Effects ───────────────────────────────────────────────────────
let FX_REG = {};

async function loadFxList() {
  const d = await get("/api/effects");
  if (!d) return;
  FX_REG = d.registry || {};

  const sel = document.getElementById("fx-type");
  if (sel && !sel.options.length) {
    sel.innerHTML = Object.entries(FX_REG)
      .map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("");
    sel.onchange = renderFxParams;
    renderFxParams();
  }

  const list = document.getElementById("fx-list");
  const active = d.effects || {};
  if (!list) return;
  if (!Object.keys(active).length) {
    list.innerHTML = '<div class="empty" style="text-align:left;padding:0">No active effects</div>';
    return;
  }
  list.innerHTML = Object.entries(active).map(([name, cfg]) => `
    <div class="fx-item">
      <span>${esc(name)}</span>
      <span style="color:var(--dim)">${esc(cfg.type)}</span>
      <button class="ic danger" onclick="delFx('${esc(name)}')">✕</button>
    </div>`).join("");
}

function renderFxParams() {
  const type = document.getElementById("fx-type").value;
  const ps   = FX_REG[type]?.params || [];
  const div  = document.getElementById("fx-params");
  div.innerHTML = ps.length ? `<div class="fg">` + ps.map(p => `
    <div class="ff">
      <label class="fl">${esc(p.label)} <span class="rv" id="fv-${p.id}">${p.default}</span></label>
      <input type="range" id="fp-${p.id}" min="${p.min}" max="${p.max}"
             step="${p.step}" value="${p.default}">
    </div>`).join("") + `</div>`
    : `<div class="ed-note">No parameters.</div>`;
  ps.forEach(p => {
    const i = document.getElementById("fp-" + p.id);
    const o = document.getElementById("fv-" + p.id);
    i?.addEventListener("input", () => { o.textContent = i.value; });
  });
}

async function addFx() {
  const type = document.getElementById("fx-type").value;
  const name = document.getElementById("fx-name").value.trim() || type;
  const params = {};
  (FX_REG[type]?.params || []).forEach(p => {
    params[p.id] = parseFloat(document.getElementById("fp-" + p.id).value);
  });
  const r = await post("/api/effects", {name, type, params});
  if (r?.success) { toast("Effect added: " + name, "ok"); loadFxList(); }
}

async function delFx(name) { await del("/api/effects/" + name); loadFxList(); }
async function clearFx()   { await post("/api/effects/clear"); loadFxList(); }

// ── Fonts ─────────────────────────────────────────────────────────
async function loadFontList() {
  const d = await get("/api/fonts");
  const list = document.getElementById("font-list");
  if (!list || !d) return;
  list.innerHTML = d.fonts.map(f => `
    <div class="font-row">
      <span class="font-name">${esc(f.name)}</span>
      <span class="font-kind">${esc(f.kind)}</span>
      <span class="font-sizes">${f.sizes?.length
        ? "crisp at " + f.sizes.join(", ") + "px" : "any size"}</span>
      ${f.kind === "ttf"
        ? `<button class="ic danger" onclick="delFont('${esc(f.key)}')">✕</button>`
        : `<span class="font-lock" title="Built in">·</span>`}
    </div>`).join("");
}

async function uploadFont() {
  const inp = document.getElementById("font-file");
  if (!inp?.files[0]) { toast("Choose a .ttf or .otf", "err"); return; }
  const form = new FormData();
  form.append("file", inp.files[0]);
  try {
    const r = await fetch(API + "/api/fonts/upload", {method: "POST", body: form});
    const d = await r.json();
    if (!d.success) { toast(d.error || "Upload failed", "err"); return; }
    toast("Font added: " + d.key, "ok");
    await loadEditorData();
    loadFontList();
  } catch { toast("Upload failed", "err"); }
}

async function delFont(key) {
  await del("/api/fonts/" + key);
  await loadEditorData();
  loadFontList();
}

// ── Shows ─────────────────────────────────────────────────────────
async function saveShow() {
  const name = document.getElementById("show-name").value.trim();
  if (!name) { toast("Enter a show name", "err"); return; }
  const d = await post("/api/shows/save", {name});
  if (d?.success) { toast("Show saved: " + name, "ok"); loadShowList(); }
}

async function loadShowList() {
  const d = await get("/api/shows");
  const list = document.getElementById("show-list");
  if (!list) return;
  if (!d?.shows?.length) {
    list.innerHTML = '<div class="empty" style="text-align:left;padding:0">No saved shows</div>';
    return;
  }
  list.innerHTML = d.shows.map(s => `
    <div class="show-row">
      <span class="show-name">${esc(s.name)}</span>
      <span class="show-meta">${s.steps} steps · ${s.overlays} overlays
        ${s.version < 8 ? '<b class="v7">V7 — will migrate</b>' : ""}</span>
      <span class="show-date">${esc((s.saved || "").slice(0, 10))}</span>
      <button class="btn btn-outline btn-sm" onclick="loadShow('${esc(s.name)}')">LOAD</button>
      <button class="ic danger" onclick="delShow('${esc(s.name)}')">✕</button>
    </div>`).join("");
}

async function loadShow(name) {
  const d = await post("/api/shows/load", {name});
  if (d?.success) { toast("Loaded: " + name, "ok"); refreshSeq(); }
  else toast(d?.error || "Load failed", "err");
}

async function delShow(name) { await del("/api/shows/" + name); loadShowList(); }

// ── Data sources ──────────────────────────────────────────────────
let SRC_TYPES = [];

async function loadSources() {
  if (!SRC_TYPES.length) {
    const t = await get("/api/sources/types");
    SRC_TYPES = t?.types || [];
    const sel = document.getElementById("src-type");
    if (sel) {
      sel.innerHTML = SRC_TYPES.map(t =>
        `<option value="${t.type}">${esc(t.label)}</option>`).join("");
      sel.onchange = renderSourceForm;
      renderSourceForm();
    }
  }

  const d = await get("/api/sources");
  const list = document.getElementById("src-list");
  if (!list || !d) return;

  if (!d.sources.length) {
    list.innerHTML = '<div class="empty" style="text-align:left;padding:0">'
      + 'No data sources yet. Add one above, then its {tokens} appear in every editor.</div>';
    return;
  }

  list.innerHTML = d.sources.map(s => {
    const st = d.status[s.id] || {};
    const meta = st.ok === false
      ? `<span class="src-err">✕ ${esc(st.error || "failed")}</span>`
      : st.ok
        ? `<span class="src-ok">✓ ${st.count} item(s) · ${esc((st.last_update || "").slice(11, 19))}</span>`
        : `<span class="src-pending">… fetching</span>`;
    const t = SRC_TYPES.find(t => t.type === s.type);
    return `
      <div class="src-row ${s.enabled ? "" : "off"}">
        <span class="src-name">{${esc(s.name)}_…}</span>
        <span class="src-type">${esc(t?.label || s.type)}</span>
        <span class="src-meta">${meta}</span>
        <button class="ic" onclick="toggleSource('${s.id}', ${!s.enabled})"
          title="${s.enabled ? "Disable" : "Enable"}">${s.enabled ? "◉" : "○"}</button>
        <button class="ic danger" onclick="delSource('${s.id}')" title="Delete">✕</button>
      </div>`;
  }).join("");
}

function renderSourceForm() {
  const type = document.getElementById("src-type")?.value;
  const t = SRC_TYPES.find(x => x.type === type);
  const host = document.getElementById("src-form");
  if (!t || !host) return;

  host.innerHTML = `
    <div class="ed-note" style="margin-bottom:8px">${esc(t.help)}</div>
    <div class="fg">
      <div class="ff">
        <label class="fl">NAME (token prefix)</label>
        <input type="text" class="fi" id="src-name" value="${esc(t.type.replace("usgs_", "").replace("_", ""))}">
      </div>
      ${t.list ? `
        <div class="ff">
          <label class="fl">ROTATE EVERY (s)</label>
          <input type="number" class="fi" id="src-rotate" value="10" min="1">
        </div>` : ""}
      <div class="ff">
        <label class="fl">REFRESH EVERY (s)</label>
        <input type="number" class="fi" id="src-interval" value="${t.interval}" min="1">
      </div>
    </div>
    ${t.config.length ? `<div class="fg">${t.config.map(c => sourceField(c)).join("")}</div>` : ""}
    ${t.tokens.length ? `
      <div class="sh-sm">PROVIDES</div>
      <div class="var-chips">${t.tokens.map(tk =>
        `<span class="chip" title="${esc(tk.help)}">{NAME_${esc(tk.suffix)}}</span>`).join("")}</div>` : ""}
    <div class="src-test" id="src-test"></div>`;
}

function sourceField(c) {
  const id = "srcf-" + c.id;
  if (c.type === "select") {
    return `<div class="ff"><label class="fl">${esc(c.label)}</label>
      <select class="fi" id="${id}">${c.options.map(o =>
        `<option value="${esc(o.value)}" ${o.value === c.default ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
      </select></div>`;
  }
  if (c.type === "number") {
    return `<div class="ff"><label class="fl">${esc(c.label)}</label>
      <input type="number" class="fi" id="${id}" value="${c.default}"></div>`;
  }
  if (c.type === "datetime") {
    return `<div class="ff"><label class="fl">${esc(c.label)}</label>
      <input type="datetime-local" class="fi" id="${id}"></div>`;
  }
  if (c.type === "json" || c.type === "fields") {
    const ph = c.type === "fields"
      ? '{"price": "bpi.USD.rate"}' : '{"Authorization": "Bearer …"}';
    return `<div class="ff-wide"><label class="fl">${esc(c.label)}</label>
      <input type="text" class="fi" id="${id}" placeholder='${ph}'></div>`;
  }
  return `<div class="ff-wide"><label class="fl">${esc(c.label)}</label>
    <input type="text" class="fi" id="${id}" value="${esc(c.default ?? "")}"></div>`;
}

function collectSourceConfig() {
  const type = document.getElementById("src-type").value;
  const t = SRC_TYPES.find(x => x.type === type);
  const cfg = {};
  (t.config || []).forEach(c => {
    const el = document.getElementById("srcf-" + c.id);
    if (!el) return;
    if (c.type === "number") cfg[c.id] = parseFloat(el.value || 0);
    else if (c.type === "json" || c.type === "fields") {
      try { cfg[c.id] = el.value.trim() ? JSON.parse(el.value) : {}; }
      catch { throw new Error(`${c.label} must be valid JSON`); }
    } else cfg[c.id] = el.value;
  });
  return {type, config: cfg};
}

async function testSource() {
  const out = document.getElementById("src-test");
  let payload;
  try { payload = collectSourceConfig(); }
  catch (e) { out.innerHTML = `<span class="src-err">✕ ${esc(e.message)}</span>`; return; }
  payload.name = document.getElementById("src-name").value.trim() || payload.type;

  out.innerHTML = '<span class="src-pending">… fetching</span>';
  const d = await post("/api/sources/test", payload);
  if (!d?.success) {
    out.innerHTML = `<span class="src-err">✕ ${esc(d?.error || "failed")}</span>`;
    return;
  }
  out.innerHTML = `<span class="src-ok">✓ ${d.count} item(s)</span>
    <div class="src-sample">${Object.entries(d.tokens).map(([k, v]) =>
      `<div><span class="var-tok">{${esc(k)}}</span><span class="var-val">${esc(v)}</span></div>`).join("")}</div>`;
}

async function addSource() {
  let payload;
  try { payload = collectSourceConfig(); }
  catch (e) { toast(e.message, "err"); return; }
  payload.name = document.getElementById("src-name").value.trim() || payload.type;
  payload.interval = parseFloat(document.getElementById("src-interval").value || 300);
  const rot = document.getElementById("src-rotate");
  if (rot) payload.rotate_every = parseFloat(rot.value || 10);

  const d = await post("/api/sources", payload);
  if (d?.success) {
    toast("Source added: " + payload.name, "ok");
    await loadSources();
    setTimeout(loadEditorData, 1500);   // let it fetch, then refresh the chips
  } else {
    toast(d?.error || "Failed", "err");
  }
}

async function toggleSource(id, enabled) {
  await put("/api/sources/" + id, {enabled});
  loadSources();
}

async function delSource(id) {
  await del("/api/sources/" + id);
  await loadSources();
  loadEditorData();
}

async function refreshSources() {
  await post("/api/sources/refresh");
  toast("Refreshing all sources…");
  setTimeout(() => { loadSources(); loadEditorData(); }, 2000);
}
