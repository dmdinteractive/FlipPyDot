/**
 * app.js — Boot, tabs, the live monitor, Create and Texts.
 *
 * The monitor listens to /api/monitor (server-sent events): the server pushes
 * a frame each time the panel changes, so the browser mirrors the wall at the
 * wall's own rate instead of polling twice a second.
 */

let monitor   = null;
let composeEd = null;
let SMS = null;

document.addEventListener("DOMContentLoaded", async () => {
  monitor = new DotCanvas(document.getElementById("display-canvas"), {dot: 4, gap: 1, dividers: true});
  monitor.blank();

  setupTabs();
  await loadEditorData();

  composeEd = new ContentEditor(document.getElementById("compose-editor"), {
    getDuration: () => parseFloat(document.getElementById("compose-dur")?.value || "8"),
    onChange: spec => document.getElementById("use-sms-style").style.display =
      spec.kind === "text" ? "" : "none",
  });
  composeEd.setSpec(defaultSpec("text"));
  document.getElementById("compose-dur").addEventListener("change", () => composeEd.refresh());

  refreshSeq();
  startMonitor();
  tickClock();
  setInterval(tickClock, 1000);
  pollStatus();
  setInterval(pollStatus, 1500);

  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
});

// ── Tabs ──────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  showTab(location.hash.slice(1) || "playlist");
}

function showTab(tab) {
  const legacy = {sequencer: "playlist", compose: "create", sources: "setup",
                  variables: "setup", effects: "setup", settings: "setup"};
  tab = legacy[tab] || tab;
  const btn = document.querySelector(`.tab[data-tab="${tab}"]`);
  if (!btn) return;
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b === btn));
  document.querySelectorAll(".pane").forEach(p => p.classList.toggle("active", p.id === "pane-" + tab));
  history.replaceState(null, "", "#" + tab);

  if (tab === "texts") loadSms(true);
  if (tab === "setup") { loadHardware(); loadSources(); loadFxList(); loadShowList(); loadFontList(); }
}

function tickClock() {
  const el = document.getElementById("hdr-clock");
  if (el) el.textContent = new Date().toTimeString().slice(0, 8);
}

// ── Monitor ───────────────────────────────────────────────────────
function startMonitor() {
  if (!window.EventSource) { setInterval(pollBuffer, 500); return; }
  const es = new EventSource(API + "/api/monitor");
  es.onmessage = e => {
    const [w, h, f] = e.data.split(",");
    monitor.drawPacked(f, +w, +h);
  };
  es.onerror = () => { /* the browser reconnects on its own */ };
}

async function pollBuffer() {
  const d = await get("/api/buffer");
  if (d?.f) monitor.drawPacked(d.f, d.w, d.h);
}

// ── Status ────────────────────────────────────────────────────────
async function pollStatus() {
  const d = await get("/api/status");
  if (!d) {
    document.getElementById("conn-label").textContent = "SERVER DOWN";
    return;
  }
  const dot = document.getElementById("conn-dot");
  const lab = document.getElementById("conn-label");
  const buses = d.display?.buses || [];
  const up = buses.filter(b => b.connected).length;
  dot.classList.toggle("on", up > 0);
  lab.textContent = !up ? (d.error ? "PANEL ERROR" : "OFFLINE — PREVIEW ONLY")
    : buses.length > 1 ? `${up}/${buses.length} ADAPTERS` : (d.port || "").split("/").pop();

  const p = d.player || {};
  document.getElementById("now-playing").textContent =
    p.playing ? (String(p.label || p.kind || "—").slice(0, 28)) : "idle";
  const ds = d.display || {};
  document.getElementById("canvas-fps").textContent = (ds.fps || 0).toFixed(1) + " fps";
  document.getElementById("wire-meta").textContent = ds.frames
    ? `${ds.modules_per_frame} of ${d.width / 28 * d.height / 7} controllers per frame · ${ds.write_mode}`
    : "";

  applySeqStatus(d.sequencer);
  renderSmsMini(d.sms);
  if (document.getElementById("pane-setup").classList.contains("active")) hwLive(d.display);
  if (document.getElementById("pane-texts").classList.contains("active")) loadSms(false);
}

// ── Create ────────────────────────────────────────────────────────
function composeDur() { return parseFloat(document.getElementById("compose-dur")?.value || "8"); }

async function composeSend() {
  // Stays up until something replaces it — unless it has a "leave" effect,
  // which needs to know when the end is.
  const spec = composeEd.getSpec();
  const timed = spec.kind === "text" && !!spec.outro;
  const r = await post("/api/play", {spec, duration: timed ? composeDur() : null});
  if (r?.success) toast(timed ? `On the wall for ${composeDur()}s` : "On the wall", "ok");
}

async function composeAddStep() {
  const r = await post("/api/sequencer/steps", {content: composeEd.getSpec(), duration: composeDur(), label: ""});
  if (r?.success) { toast("Added to playlist", "ok"); refreshSeq(); }
}

async function useAsSmsStyle() {
  const s = composeEd.getSpec();
  if (s.kind !== "text") return;
  const style = {kind: "text", text: "{message}", font: s.font, align: s.align, valign: s.valign,
                 intro: s.intro, idle: s.idle, outro: s.outro, fx_speed: s.fx_speed,
                 bg: s.bg, bg_params: s.bg_params, bg_blend: s.bg_blend, bold: s.bold};
  if (s.motion?.startsWith("scroll_in_")) { style.motion = s.motion; style.speed = s.speed; }
  const d = await post("/api/sms/config", {style});
  if (d?.success) toast("Visitor texts will use this look", "ok");
}

// ── Texts ─────────────────────────────────────────────────────────
function renderSmsMini(s) {
  const el = document.getElementById("sms-mini");
  if (!el || !s) return;
  el.className = "sms-mini " + (s.enabled ? "on" : "");
  el.innerHTML = s.enabled
    ? `<b>TEXTS ON</b> · ${s.queued} waiting${s.ok === false ? ` · <span class="src-err">Twilio error</span>` : ""}`
    : `TEXTS OFF`;
}

const NICE = {
  "": "just appear", flap: "split-flap", decode: "decode", type: "typewriter", drop: "drop",
  rise: "rise", dissolve: "dissolve", gather: "swarm", wipe: "wipe", explode: "explode",
  fall: "fall away", wave: "wave", sparkle: "sparkle", jitter: "jitter", bounce: "bounce",
  marquee: "marquee",
};

async function loadSms(fillForm) {
  const d = await get("/api/sms");
  if (!d) return;
  SMS = d;
  const c = d.config;

  const num = (c.number || "").replace(/^\+1(\d{3})(\d{3})(\d{4})$/, "($1) $2-$3");
  document.getElementById("sms-hero").innerHTML = `
    <label class="switch"><input type="checkbox" id="sms-on" ${c.enabled ? "checked" : ""}
      onchange="smsToggle(this.checked)"><span></span></label>
    <div>
      <div class="sms-big">${c.enabled ? (num ? "Text " + esc(num) : "On — add the Twilio number below")
                                       : "Visitor texts are off"}</div>
      <div class="sh-note">${c.enabled
        ? `${d.queued} waiting · ${c.mode === "poll" ? "checking Twilio every " + c.poll_seconds + "s" : "webhook"}`
          + (d.ok === false ? ` · <span class="src-err">${esc(d.error || "")}</span>` : d.last_poll ? ` · last check ${esc(d.last_poll.slice(11))}` : "")
        : "Turn on to show visitors' messages on the wall."}</div>
    </div>`;

  document.getElementById("sms-log").innerHTML = (d.log || []).map(e => `
    <div class="sms-row ${e.state}">
      <span class="sms-from">${esc(e.from)}</span>
      <span class="sms-text">${esc(e.text) || "<i>(nothing drawable)</i>"}</span>
      <span class="sms-at">${esc(e.at.slice(11, 16))}</span>
      <span class="sms-state">${e.state}</span>
    </div>`).join("") || `<div class="empty" style="padding:1rem 0;text-align:left">No messages yet.</div>`;

  const st = c.style || {};
  document.getElementById("sms-style-note").innerHTML =
    `Look: arrive <b>${NICE[st.intro || ""] || st.intro}</b>, while up <b>${NICE[st.idle || ""] === "just appear" ? "still" : NICE[st.idle || ""]}</b>,
     leave <b>${st.outro ? NICE[st.outro] || st.outro : "stay"}</b>${st.bg ? `, over <b>${esc(st.bg)}</b>` : ""}.
     Size is picked automatically so each message fits; long ones scroll.
     To change the look, design a text in Create and press “Use for visitor texts”.`;

  if (!fillForm) return;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v ?? ""; };
  set("sms-when", c.when); set("sms-seconds", c.seconds); set("sms-max", c.max_length);
  set("sms-header", c.header); set("sms-number", c.number); set("sms-poll", c.poll_seconds);
  set("sms-sid", c.account_sid); set("sms-token", c.auth_token); set("sms-mode", c.mode);
  set("sms-url", c.public_url); set("sms-reply", c.reply);
}

async function smsToggle(on) {
  await post("/api/sms/config", {enabled: on});
  loadSms(false);
}

async function smsSave() {
  const v = id => document.getElementById(id).value;
  const d = await post("/api/sms/config", {
    when: v("sms-when"), seconds: +v("sms-seconds") || 8, max_length: +v("sms-max") || 160,
    header: v("sms-header"), number: v("sms-number").trim(), poll_seconds: +v("sms-poll") || 5,
    account_sid: v("sms-sid").trim(), auth_token: v("sms-token").trim(), mode: v("sms-mode"),
    public_url: v("sms-url").trim(), reply: v("sms-reply"),
  });
  if (d?.success) { toast("Saved", "ok"); loadSms(true); }
}

async function smsTest() {
  const inp = document.getElementById("sms-test");
  const d = await post("/api/sms/test", {text: inp.value || "Hello from the museum!"});
  if (d?.success) { toast("Test message queued", "ok"); inp.value = ""; }
  else toast(d?.error || "Failed", "err");
  loadSms(false);
}

async function smsSkip() { await post("/api/sms/skip"); }
