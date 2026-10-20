/**
 * setup.js — The Setup tab: hardware, data sources, live effects, shows, fonts.
 *
 * Everything here is "set once, then forget", which is why it lives behind
 * collapsible sections instead of taking up tabs of its own.
 */

// ── Hardware ──────────────────────────────────────────────────────
let HW = null;          // {buses, bus_map, write_mode, max_fps, status}
let PORTS = [];
const BUS_COLORS = ["#0a0a0a", "#b5532a", "#2d6a8f", "#5d7a33"];
const BAUDS = [9600, 19200, 38400, 57600];

async function loadHardware() {
  const [h, p] = await Promise.all([get("/api/hardware"), get("/api/ports")]);
  if (!h) return;
  PORTS = p || [];
  HW = {
    buses: h.buses.map(b => ({...b})),
    bus_map: h.status.bus_map.map(r => [...r]),
    layout: h.status.layout,
    write_mode: h.write_mode,
    max_fps: h.max_fps,
    max_buses: h.max_buses,
  };
  renderHardware(h.status);
}

function renderHardware(st) {
  const el = document.getElementById("hw");
  if (!el || !HW) return;
  const portOpts = cur => {
    const list = PORTS.map(p => p.port);
    if (cur && !list.includes(cur)) list.unshift(cur);
    return `<option value="">— choose —</option>` + list.map(p =>
      `<option value="${esc(p)}" ${p === cur ? "selected" : ""}>${esc(p.split("/").pop())}</option>`).join("");
  };
  const count = i => HW.bus_map.flat().filter(b => b === i).length;
  const fullFps = i => {
    const n = count(i); const b = HW.buses[i];
    return n ? (b.baud / 10 / (n * 32 + (HW.write_mode === "synced" ? 3 : 0))) : 0;
  };
  const worst = Math.min(...HW.buses.map((_, i) => fullFps(i) || Infinity));

  el.innerHTML = `
    <div class="sh-sm">USB ADAPTERS</div>
    <div class="bus-list">
      ${HW.buses.map((b, i) => {
        const s = st?.buses?.[i];
        return `<div class="bus-row">
          <span class="bus-chip" style="background:${BUS_COLORS[i]}">${i + 1}</span>
          <select class="fi" data-bus="${i}" data-k="port">${portOpts(b.port)}</select>
          <select class="fi tiny" data-bus="${i}" data-k="baud">${BAUDS.map(r =>
            `<option ${r === b.baud ? "selected" : ""}>${r}</option>`).join("")}</select>
          <span class="bus-stat ${s?.connected ? "ok" : "bad"}">${s?.connected ? "● connected" : "○ " + esc(s?.error || "not connected")}</span>
          <span class="bus-stat">${count(i)} controllers · ${fullFps(i) ? fullFps(i).toFixed(1) + " fps full-screen" : "unused"}</span>
          ${i > 0 ? `<button class="ic danger" onclick="hwRemoveBus(${i})" title="Remove adapter">✕</button>` : ""}
        </div>`;
      }).join("")}
    </div>
    <div class="btn-row" style="margin-top:6px">
      ${HW.buses.length < HW.max_buses ? `<button class="btn btn-outline btn-sm" onclick="hwAddBus()">+ ADD ADAPTER</button>` : ""}
      <button class="btn btn-outline btn-sm" onclick="loadHardware()">↻ RESCAN PORTS</button>
    </div>

    ${HW.buses.length > 1 ? `
    <div class="sh-sm">WHICH ADAPTER EACH CONTROLLER IS WIRED TO <span class="sh-note">click a controller to change it</span></div>
    <div class="bus-map" style="grid-template-columns:repeat(${HW.layout[0]?.length || 3},1fr)">
      ${HW.layout.map((row, r) => row.map((addr, c) => {
        const b = HW.bus_map[r][c];
        return `<button class="bus-cell" style="border-color:${BUS_COLORS[b]}" onclick="hwCycle(${r},${c})">
          <span class="bus-chip" style="background:${BUS_COLORS[b]}">${b + 1}</span> addr ${addr}</button>`;
      }).join("")).join("")}
    </div>
    <div class="btn-row">
      <span class="fl inline">QUICK:</span>
      <button class="btn btn-outline btn-sm" onclick="hwPreset('cols')">ONE PER COLUMN</button>
      <button class="btn btn-outline btn-sm" onclick="hwPreset('rows')">SPLIT TOP-TO-BOTTOM</button>
      <button class="btn btn-outline btn-sm" onclick="hwPreset('one')">ALL ON ADAPTER 1</button>
    </div>` : `<div class="ed-note">Add a second or third USB-RS485 adapter to split the controllers
      across several wires. Full-screen animation speeds up by the same factor.</div>`}

    <div class="sh-sm">SPEED</div>
    <div class="fg">
      <div class="ff">
        <label class="fl">WRITE MODE</label>
        <select class="fi" id="hw-mode">
          <option value="immediate" ${HW.write_mode === "immediate" ? "selected" : ""}>Immediate — each controller flips as it arrives (V8 behaviour)</option>
          <option value="synced" ${HW.write_mode === "synced" ? "selected" : ""}>Synced — whole panel flips at once (no tearing)</option>
        </select>
      </div>
      <div class="ff">
        <label class="fl">MAX PANEL FPS <span class="rv" id="hw-fps-v">${HW.max_fps}</span></label>
        <input type="range" id="hw-fps" min="5" max="30" step="1" value="${HW.max_fps}">
      </div>
    </div>
    <div class="ed-note">
      Only controllers whose dots changed are sent, so text and small animations run near the
      max fps even on one adapter. Full-screen changes are limited by the slowest adapter:
      <b>${isFinite(worst) ? worst.toFixed(1) : "—"} fps</b> with this setup. Frames the wire can't
      carry are skipped, never queued — the wall can't fall behind.
      If Synced mode leaves the panel blank, these controllers don't support it — switch back.
    </div>

    <div class="btn-row">
      <button class="btn btn-solid btn-sm" onclick="hwSave()">SAVE &amp; RECONNECT</button>
      <a href="/wizard.html" class="btn btn-outline btn-sm">PANEL ADDRESS WIZARD</a>
    </div>
    <div class="sys-info" id="hw-live"></div>`;

  el.querySelectorAll("select[data-bus]").forEach(s => s.onchange = () => {
    const b = HW.buses[+s.dataset.bus];
    b[s.dataset.k] = s.dataset.k === "baud" ? +s.value : s.value;
    renderHardware(st);
  });
  el.querySelector("#hw-mode").onchange = e => { HW.write_mode = e.target.value; renderHardware(st); };
  el.querySelector("#hw-fps").oninput = e => {
    HW.max_fps = +e.target.value;
    el.querySelector("#hw-fps-v").textContent = e.target.value;
  };
}

function hwLive(d) {
  const el = document.getElementById("hw-live");
  if (!el || !d) return;
  el.innerHTML = [
    `Panel now:   ${d.fps} fps · ${d.modules_per_frame} controllers changed per frame`,
    `Skipped:     ${d.skipped} stale frames dropped (instead of queued)`,
    `Sent:        ${d.frames} frames · ${d.buses.map(b => `adapter ${b.index + 1}: ${(b.bytes_sent / 1024).toFixed(0)} KB`).join(" · ")}`,
  ].map(s => `<div>${esc(s)}</div>`).join("");
}

function hwAddBus() {
  HW.buses.push({port: "", baud: 57600});
  hwPreset("cols");
}

function hwRemoveBus(i) {
  HW.buses.splice(i, 1);
  HW.bus_map = HW.bus_map.map(r => r.map(b => b === i ? 0 : b > i ? b - 1 : b));
  renderHardware();
}

function hwCycle(r, c) {
  HW.bus_map[r][c] = (HW.bus_map[r][c] + 1) % HW.buses.length;
  renderHardware();
}

function hwPreset(kind) {
  const n = HW.buses.length, rows = HW.layout.length, cols = HW.layout[0]?.length || 1;
  HW.bus_map = HW.layout.map((row, r) => row.map((_, c) =>
    kind === "one" ? 0 :
    kind === "cols" ? Math.floor(c * n / cols) :
    Math.floor(r * n / rows)));
  renderHardware();
}

async function hwSave() {
  const d = await post("/api/hardware", {
    buses: HW.buses, bus_map: HW.bus_map, write_mode: HW.write_mode, max_fps: HW.max_fps,
  });
  if (d?.success) { toast("Hardware saved — reconnecting", "ok"); setTimeout(loadHardware, 800); }
  else toast(d?.error || "Save failed", "err");
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
  const name = type;
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
// Each source row expands to show its live {tokens}, so there's no separate
// tokens page to keep in sync.
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

  const [d] = await Promise.all([get("/api/sources"), loadEditorData()]);
  const list = document.getElementById("src-list");
  if (!list || !d) return;

  const tokens = `<details class="tok-all"><summary>CURRENT TOKEN VALUES</summary>
    <div class="var-grid">${TOKEN_GROUPS.map(g => `
      <div class="tok-group">
        <div class="tok-group-head ${g.ok === false ? "err" : ""}">${esc(g.group)}</div>
        ${(g.tokens || []).map(t => `<div class="var-row"><span class="var-tok">{${esc(t.token)}}</span>
          <span class="var-val">${esc(t.value)}</span></div>`).join("")}
      </div>`).join("")}</div></details>`;

  if (!d.sources.length) {
    list.innerHTML = '<div class="ed-note">No data sources yet. Add one below — its {tokens} '
      + 'then appear in every text editor.</div>' + tokens;
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
  }).join("") + tokens;
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
