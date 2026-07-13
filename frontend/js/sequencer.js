/**
 * sequencer.js — Playlist + overlay UI.
 *
 * The playlist is the main event: an ordered list of steps you can drag to
 * reorder, each with its own duration and its own fully-specified content.
 * Overlays are the time-triggered things that cut in and then hand control
 * back.
 *
 * Editing a step opens a drawer holding a ContentEditor, so a scheduled item
 * gets exactly the same knobs (and the same live preview) as something you
 * send by hand. In V7 a scheduled item was a single untyped string.
 */

let SEQ      = {steps: [], overlays: [], running: false, loop: true, current: null};
let editing  = null;      // {type: "step"|"overlay", id, isNew}
let stepEd   = null;      // ContentEditor instance inside the drawer
let dragId   = null;

// ── Poll-driven render ────────────────────────────────────────────
function applySeqStatus(s) {
  if (!s) return;
  const changed =
    JSON.stringify(s.steps.map(x => [x.id, x.label, x.enabled, x.duration, x.transition, x.content?.kind])) !==
    JSON.stringify(SEQ.steps.map(x => [x.id, x.label, x.enabled, x.duration, x.transition, x.content?.kind])) ||
    JSON.stringify(s.overlays) !== JSON.stringify(SEQ.overlays);

  const cursorMoved = s.current !== SEQ.current || s.running !== SEQ.running;
  SEQ = s;

  if (changed) { renderPlaylist(); renderOverlays(); }
  else if (cursorMoved) markCurrent();
  renderTransport();
}

function renderTransport() {
  const btn = document.getElementById("seq-play");
  if (btn) {
    btn.textContent = SEQ.running ? "⏸ PAUSE" : "▶ PLAY";
    btn.className   = "btn " + (SEQ.running ? "btn-outline" : "btn-solid");
  }
  const badge = document.getElementById("seq-badge");
  if (badge) {
    const n = SEQ.steps.filter(s => s.enabled).length;
    badge.textContent = SEQ.running
      ? `RUNNING — step ${(SEQ.index ?? 0) + 1}/${n}`
      : `${n} step${n === 1 ? "" : "s"}`;
  }
  const lp = document.getElementById("seq-loop");
  if (lp) lp.checked = !!SEQ.loop;
}

function markCurrent() {
  document.querySelectorAll(".step-row").forEach(r => {
    r.classList.toggle("current", r.dataset.id === SEQ.current && SEQ.running);
  });
}

// ── Playlist ──────────────────────────────────────────────────────
function summarize(c) {
  if (!c) return "—";
  if (c.kind === "text") {
    const m = c.motion && c.motion !== "static" ? " ⇄" : "";
    return (c.text || "(empty)").slice(0, 40) + m;
  }
  if (c.kind === "animation") return (c.animation || "").replace(/_/g, " ");
  if (c.kind === "image")     return `image — ${(c.frames || []).length} frame(s)`;
  return c.kind;
}

function renderPlaylist() {
  const wrap  = document.getElementById("playlist");
  const empty = document.getElementById("playlist-empty");
  if (!wrap) return;

  if (!SEQ.steps.length) {
    wrap.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";

  wrap.innerHTML = SEQ.steps.map((s, i) => `
    <div class="step-row ${s.enabled ? "" : "off"} ${s.id === SEQ.current && SEQ.running ? "current" : ""}"
         draggable="true" data-id="${s.id}">
      <span class="step-grip" title="Drag to reorder">⠿</span>
      <span class="step-num">${i + 1}</span>
      <span class="step-kind k-${s.content?.kind || "text"}">${s.content?.kind || "text"}</span>
      <span class="step-label">${esc(s.label || summarize(s.content))}</span>
      <span class="step-sum">${esc(summarize(s.content))}</span>
      <span class="step-dur">${s.duration}s</span>
      <span class="step-trans">${s.transition?.animation
        ? esc(s.transition.animation.replace(/_/g, " ")) : "—"}</span>
      <span class="step-acts">
        <button class="ic" title="Preview on panel" data-act="prev" data-id="${s.id}">▶</button>
        <button class="ic" title="Edit"      data-act="edit" data-id="${s.id}">✎</button>
        <button class="ic" title="Duplicate" data-act="dupe" data-id="${s.id}">⧉</button>
        <button class="ic" title="${s.enabled ? "Disable" : "Enable"}"
                data-act="tog" data-id="${s.id}">${s.enabled ? "◉" : "○"}</button>
        <button class="ic danger" title="Delete" data-act="del" data-id="${s.id}">✕</button>
      </span>
    </div>`).join("");

  wrap.querySelectorAll(".ic").forEach(b => {
    b.onclick = e => {
      e.stopPropagation();
      stepAction(b.dataset.act, b.dataset.id);
    };
  });
  wrap.querySelectorAll(".step-row").forEach(r => {
    r.ondblclick   = () => openEditor("step", r.dataset.id);
    r.ondragstart  = e => { dragId = r.dataset.id; r.classList.add("dragging");
                            e.dataTransfer.effectAllowed = "move"; };
    r.ondragend    = () => { r.classList.remove("dragging");
                             wrap.querySelectorAll(".step-row").forEach(x =>
                               x.classList.remove("drop-before", "drop-after")); };
    r.ondragover   = e => {
      e.preventDefault();
      if (r.dataset.id === dragId) return;
      const mid = r.getBoundingClientRect().top + r.offsetHeight / 2;
      r.classList.toggle("drop-before", e.clientY < mid);
      r.classList.toggle("drop-after",  e.clientY >= mid);
    };
    r.ondragleave  = () => r.classList.remove("drop-before", "drop-after");
    r.ondrop       = e => {
      e.preventDefault();
      r.classList.remove("drop-before", "drop-after");
      if (!dragId || r.dataset.id === dragId) return;
      const ids = SEQ.steps.map(s => s.id).filter(id => id !== dragId);
      const at  = ids.indexOf(r.dataset.id);
      const mid = r.getBoundingClientRect().top + r.offsetHeight / 2;
      ids.splice(e.clientY < mid ? at : at + 1, 0, dragId);
      dragId = null;
      post("/api/sequencer/reorder", {ids}).then(refreshSeq);
    };
  });
}

async function stepAction(act, id) {
  if (act === "edit") return openEditor("step", id);
  if (act === "del") {
    await del("/api/sequencer/steps/" + id);
    toast("Step deleted");
  } else if (act === "dupe") {
    await post(`/api/sequencer/steps/${id}/duplicate`);
    toast("Step duplicated", "ok");
  } else if (act === "tog") {
    const s = SEQ.steps.find(x => x.id === id);
    await put("/api/sequencer/steps/" + id, {enabled: !s.enabled});
  } else if (act === "prev") {
    await post(`/api/sequencer/steps/${id}/preview`);
    toast("Playing step on panel", "ok");
  }
  refreshSeq();
}

// ── Overlays ──────────────────────────────────────────────────────
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function describeTrigger(t) {
  if (!t) return "—";
  if (t.type === "interval") {
    const s = Number(t.every || 0);
    return s >= 3600 ? `every ${(s / 3600).toFixed(1)}h`
         : s >= 60   ? `every ${Math.round(s / 60)} min`
         :             `every ${s}s`;
  }
  if (t.type === "daily")  return `daily at ${t.at}`;
  if (t.type === "weekly") {
    const d = (t.days || []).map(i => DAYS[i]).join(" ");
    return `${d || "no days"} at ${t.at}`;
  }
  if (t.type === "once")   return `once at ${String(t.at || "").replace("T", " ")}`;
  return t.type;
}

function renderOverlays() {
  const wrap  = document.getElementById("overlays");
  const empty = document.getElementById("overlays-empty");
  if (!wrap) return;

  if (!SEQ.overlays.length) {
    wrap.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";

  wrap.innerHTML = SEQ.overlays.map(o => `
    <div class="ov-row ${o.enabled ? "" : "off"}" data-id="${o.id}">
      <span class="ov-mark">✦</span>
      <span class="step-label">${esc(o.label || summarize(o.content))}</span>
      <span class="ov-trig">${esc(describeTrigger(o.trigger))}</span>
      <span class="step-sum">${esc(summarize(o.content))}</span>
      <span class="step-dur">${o.duration}s</span>
      <span class="ov-prio" title="Priority">P${o.priority}</span>
      <span class="step-acts">
        <button class="ic" data-act="edit" data-id="${o.id}" title="Edit">✎</button>
        <button class="ic" data-act="tog"  data-id="${o.id}"
                title="${o.enabled ? "Disable" : "Enable"}">${o.enabled ? "◉" : "○"}</button>
        <button class="ic danger" data-act="del" data-id="${o.id}" title="Delete">✕</button>
      </span>
    </div>`).join("");

  wrap.querySelectorAll(".ic").forEach(b => {
    b.onclick = async () => {
      const id = b.dataset.id;
      if (b.dataset.act === "edit") return openEditor("overlay", id);
      if (b.dataset.act === "del") {
        await del("/api/sequencer/overlays/" + id);
        toast("Overlay deleted");
      } else {
        const o = SEQ.overlays.find(x => x.id === id);
        await put("/api/sequencer/overlays/" + id, {enabled: !o.enabled});
      }
      refreshSeq();
    };
  });
  wrap.querySelectorAll(".ov-row").forEach(r => {
    r.ondblclick = () => openEditor("overlay", r.dataset.id);
  });
}

// ── Editor drawer ─────────────────────────────────────────────────
function openEditor(type, id) {
  const isNew = !id;
  const src   = type === "step"
    ? SEQ.steps.find(s => s.id === id)
    : SEQ.overlays.find(o => o.id === id);

  const model = src ? JSON.parse(JSON.stringify(src)) : (
    type === "step"
      ? {label: "", duration: 8, enabled: true, transition: null,
         content: defaultSpec("text")}
      : {label: "", duration: 8, enabled: true, priority: 0,
         trigger: {type: "daily", at: "17:00", days: [0, 1, 2, 3, 4], every: 1800},
         content: defaultSpec("text")}
  );
  editing = {type, id, isNew, model};

  const drawer = document.getElementById("drawer");
  document.getElementById("drawer-title").textContent =
    (isNew ? "NEW " : "EDIT ") + (type === "step" ? "PLAYLIST STEP" : "OVERLAY");

  document.getElementById("drawer-meta").innerHTML = `
    <div class="fg">
      <div class="ff">
        <label class="fl">LABEL</label>
        <input type="text" id="d-label" class="fi" value="${esc(model.label)}"
               placeholder="Optional name">
      </div>
      <div class="ff">
        <label class="fl">DURATION (s)</label>
        <input type="number" id="d-dur" class="fi" min="0.5" step="0.5"
               value="${model.duration}">
      </div>
      ${type === "step" ? `
        <div class="ff">
          <label class="fl">TRANSITION IN</label>
          <select id="d-trans" class="fi">
            ${TRANSITIONS.map(([v, l]) =>
              `<option value="${v}" ${v === (model.transition?.animation || "")
                ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </div>
      ` : `
        <div class="ff">
          <label class="fl">PRIORITY</label>
          <input type="number" id="d-prio" class="fi" min="0" max="10"
                 value="${model.priority ?? 0}">
        </div>
      `}
    </div>
    ${type === "overlay" ? triggerFields(model.trigger) : ""}`;

  if (type === "overlay") wireTrigger();

  const host = document.getElementById("drawer-content");
  stepEd?.destroy();
  stepEd = new ContentEditor(host, {onChange: spec => { editing.model.content = spec; }});
  stepEd.setSpec(model.content);

  drawer.classList.add("open");
  document.body.classList.add("drawer-open");
}

function triggerFields(t) {
  t = t || {type: "daily", at: "17:00", days: [], every: 1800};
  const type = t.type || "daily";
  return `
    <div class="sh-sm">TRIGGER</div>
    <div class="fg">
      <div class="ff">
        <label class="fl">WHEN</label>
        <select id="d-trig-type" class="fi">
          ${[["daily", "Daily at a time"], ["weekly", "Weekly on days"],
             ["interval", "Every N minutes"], ["once", "Once at a date/time"]]
            .map(([v, l]) => `<option value="${v}" ${v === type ? "selected" : ""}>${l}</option>`)
            .join("")}
        </select>
      </div>
      <div class="ff" id="d-trig-at" style="display:${["daily", "weekly"].includes(type) ? "block" : "none"}">
        <label class="fl">AT</label>
        <input type="time" id="d-at" class="fi" value="${esc(t.at || "17:00")}">
      </div>
      <div class="ff" id="d-trig-every" style="display:${type === "interval" ? "block" : "none"}">
        <label class="fl">EVERY (minutes)</label>
        <input type="number" id="d-every" class="fi" min="1" step="1"
               value="${Math.max(1, Math.round((t.every || 1800) / 60))}">
      </div>
      <div class="ff" id="d-trig-once" style="display:${type === "once" ? "block" : "none"}">
        <label class="fl">DATE &amp; TIME</label>
        <input type="datetime-local" id="d-once" class="fi"
               value="${esc(type === "once" ? (t.at || "") : "")}">
      </div>
    </div>
    <div id="d-trig-days" style="display:${type === "weekly" ? "block" : "none"}">
      <label class="fl">DAYS</label>
      <div class="days">
        ${DAYS.map((d, i) => `
          <label class="day ${(t.days || []).includes(i) ? "on" : ""}">
            <input type="checkbox" data-day="${i}" ${(t.days || []).includes(i) ? "checked" : ""}>
            ${d}
          </label>`).join("")}
      </div>
    </div>`;
}

function wireTrigger() {
  const sel = document.getElementById("d-trig-type");
  const upd = () => {
    const v = sel.value;
    document.getElementById("d-trig-at").style.display    = ["daily", "weekly"].includes(v) ? "block" : "none";
    document.getElementById("d-trig-every").style.display = v === "interval" ? "block" : "none";
    document.getElementById("d-trig-once").style.display  = v === "once" ? "block" : "none";
    document.getElementById("d-trig-days").style.display  = v === "weekly" ? "block" : "none";
  };
  sel.onchange = upd;
  document.querySelectorAll(".day input").forEach(cb => {
    cb.onchange = () => cb.closest(".day").classList.toggle("on", cb.checked);
  });
}

function collectTrigger() {
  const type = document.getElementById("d-trig-type").value;
  if (type === "interval") {
    return {type, every: Math.max(60,
      parseFloat(document.getElementById("d-every").value || "30") * 60)};
  }
  if (type === "once") {
    return {type, at: document.getElementById("d-once").value};
  }
  const t = {type, at: document.getElementById("d-at").value || "17:00"};
  if (type === "weekly") {
    t.days = [...document.querySelectorAll(".day input")]
      .filter(cb => cb.checked).map(cb => Number(cb.dataset.day));
  }
  return t;
}

function closeDrawer() {
  document.getElementById("drawer").classList.remove("open");
  document.body.classList.remove("drawer-open");
  stepEd?.destroy();
  stepEd  = null;
  editing = null;
}

async function saveDrawer() {
  if (!editing) return;
  const {type, id, isNew} = editing;

  const payload = {
    label:    document.getElementById("d-label").value.trim(),
    duration: parseFloat(document.getElementById("d-dur").value || "8"),
    content:  stepEd.getSpec(),
    enabled:  editing.model.enabled !== false,
  };

  if (type === "step") {
    const tr = document.getElementById("d-trans").value;
    payload.transition = tr ? {animation: tr} : null;
  } else {
    payload.priority = parseInt(document.getElementById("d-prio").value || "0");
    payload.trigger  = collectTrigger();
  }

  const base = type === "step" ? "/api/sequencer/steps" : "/api/sequencer/overlays";
  const r = isNew ? await post(base, payload) : await put(`${base}/${id}`, payload);

  if (r?.success) {
    toast((isNew ? "Added " : "Saved ") + type, "ok");
    closeDrawer();
    refreshSeq();
  } else {
    toast(r?.error || "Save failed", "err");
  }
}

// ── Transport ─────────────────────────────────────────────────────
async function seqToggle() {
  await post(SEQ.running ? "/api/sequencer/stop" : "/api/sequencer/start");
  refreshSeq();
}
async function seqNext()  { await post("/api/sequencer/next");  refreshSeq(); }
async function seqPrev()  { await post("/api/sequencer/prev");  refreshSeq(); }
async function seqLoop(e) { await post("/api/sequencer/loop", {loop: e.target.checked}); }

async function refreshSeq() {
  applySeqStatus(await get("/api/sequencer"));
}
