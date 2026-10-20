/**
 * editor.js — ContentEditor.
 *
 * One form that edits one spec, with a live preview beside it. The same
 * component backs the Create tab, the playlist step editor and the overlay
 * editor, so every place that makes content gets the same knobs.
 *
 * Text is built in three plain-English steps — how it ARRIVES, what it does
 * WHILE UP, and how it LEAVES — plus an optional moving background. Recipes
 * set all of those at once for staff who just want something that looks good.
 *
 * Preview goes through /api/preview, which runs the real renderer at the
 * panel's frame rate. It never touches the panel.
 */

let FONTS = [];
let ANIMS = [];
let TOKEN_GROUPS = [];

async function loadEditorData() {
  const [f, a, t] = await Promise.all([
    get("/api/fonts"), get("/api/animations"), get("/api/variables/tokens"),
  ]);
  FONTS = f?.fonts || [];
  ANIMS = a?.animations || [];
  TOKEN_GROUPS = t?.groups || [];
}

function allTokens() { return TOKEN_GROUPS.flatMap(g => g.tokens || []); }

// Used by the dashboard zone editor (layout.js) — zones keep the classic set.
const MOTIONS = [
  ["static", "Static"],
  ["scroll_left", "Scroll ← (loop)"], ["scroll_right", "Scroll → (loop)"],
  ["scroll_up", "Scroll ↑ (loop)"],   ["scroll_down", "Scroll ↓ (loop)"],
  ["scroll_in_left", "Scroll ← & stop"], ["scroll_in_right", "Scroll → & stop"],
  ["scroll_in_up", "Scroll ↑ & stop"],   ["scroll_in_down", "Scroll ↓ & stop"],
];
const isMoving  = m => m !== "static";
const isLooping = m => m.startsWith("scroll_") && !m.startsWith("scroll_in_");
const canBlink  = m => m === "static" || m.startsWith("scroll_in_");

const TRANSITIONS = [
  ["", "None"], ["wipe_right", "Wipe right"], ["wipe_left", "Wipe left"],
  ["wipe_down", "Wipe down"], ["wipe_up", "Wipe up"],
  ["curtain_open", "Curtain open"], ["curtain_close", "Curtain close"],
  ["diagonal_wipe", "Diagonal"], ["flash", "Flash"], ["blinds", "Blinds"],
];

// ── Text animation vocabulary ─────────────────────────────────────
// ARRIVE: "slide_*" map onto the classic scroll_in motions; the rest are
// letter-by-letter intros rendered by backend/textfx.py.
const ARRIVE = [
  ["",            "Just appear"],
  ["flap",        "Split-flap"],
  ["decode",      "Decode"],
  ["type",        "Typewriter"],
  ["drop",        "Drop & bounce"],
  ["rise",        "Rise up"],
  ["dissolve",    "Dissolve in"],
  ["gather",      "Swarm together"],
  ["wipe",        "Wipe on"],
  ["slide_left",  "Slide in ←"],
  ["slide_right", "Slide in →"],
  ["slide_up",    "Slide in ↑"],
  ["slide_down",  "Slide in ↓"],
];
const WHILE = [
  ["",             "Hold still"],
  ["wave",         "Wave"],
  ["sparkle",      "Sparkle"],
  ["jitter",       "Jitter"],
  ["bounce",       "Bounce around"],
  ["marquee",      "Marquee lights"],
  ["blink",        "Blink"],
  ["scroll_left",  "Ticker ← (loops)"],
  ["scroll_right", "Ticker → (loops)"],
  ["scroll_up",    "Credits ↑ (loops)"],
  ["scroll_down",  "Scroll ↓ (loops)"],
];
const LEAVE = [
  ["",         "Stay to the end"],
  ["dissolve", "Dissolve out"],
  ["explode",  "Explode"],
  ["fall",     "Fall away"],
  ["flap",     "Split-flap out"],
  ["type",     "Backspace"],
  ["wipe",     "Wipe off"],
];
const BLENDS = [
  ["outline", "Text cut out of it"],
  ["mask",    "Visual inside the letters"],
  ["xor",     "Inverted where they overlap"],
  ["over",    "Just layered"],
];

const RECIPES = [
  {name: "Split-flap board", set: {arrive: "flap", while: "", leave: "flap", bg: ""}},
  {name: "Hacker decode",    set: {arrive: "decode", while: "sparkle", leave: "dissolve", bg: ""}},
  {name: "Typewriter",       set: {arrive: "type", while: "", leave: "type", bg: ""}},
  {name: "Bouncy",           set: {arrive: "drop", while: "wave", leave: "fall", bg: ""}},
  {name: "Big reveal",       set: {arrive: "gather", while: "", leave: "explode", bg: ""}},
  {name: "News ticker",      set: {arrive: "", while: "scroll_left", leave: "", bg: ""}},
  {name: "Over plasma",      set: {arrive: "dissolve", while: "", leave: "dissolve", bg: "plasma", bg_blend: "outline"}},
  {name: "Starfield title",  set: {arrive: "rise", while: "", leave: "fall", bg: "starfield", bg_blend: "outline"}},
];

function defaultSpec(kind = "text") {
  if (kind === "layout")    return {kind: "layout", zones: []};
  if (kind === "animation") return {kind: "animation", animation: "plasma", params: {}};
  if (kind === "image")     return {kind: "image", frames: []};
  if (kind === "clear")     return {kind: "clear"};
  if (kind === "fill")      return {kind: "fill"};
  return {
    kind: "text", text: "", font: "px5x7", size: 14,
    align: "center", valign: "middle", dx: 0, dy: 0,
    tracking: 1, leading: 1, bold: false,
    motion: "static", speed: 30, gap: 84, blink: 0, blink_duty: 0.5,
    intro: "", idle: "", outro: "", fx_speed: 1, bg: "", bg_params: {}, bg_blend: "outline",
  };
}

/** Read the three-step view out of a spec (handles V8 specs too). */
function textSteps(s) {
  const m = s.motion || "static";
  let arrive = s.intro || "";
  if (m.startsWith("scroll_in_")) arrive = "slide_" + m.slice(10);
  let wh = s.idle || "";
  if (isLooping(m)) wh = m;
  else if (!wh && Number(s.blink) > 0) wh = "blink";
  return {arrive, while: wh, leave: s.outro || ""};
}

/** Write the three-step view back into spec fields. */
function applySteps(s, st) {
  s.intro = ""; s.idle = ""; s.outro = st.leave || "";
  s.motion = "static";
  if (st.arrive?.startsWith("slide_")) s.motion = "scroll_in_" + st.arrive.slice(6);
  else s.intro = st.arrive || "";
  if (st.while?.startsWith("scroll_")) {
    s.motion = st.while; s.intro = ""; s.outro = "";
  } else if (st.while === "blink") {
    s.blink = s.blink > 0 ? s.blink : 1;
  } else {
    s.idle = st.while || "";
  }
  if (st.while !== "blink") s.blink = 0;
  return s;
}

const opt = (list, cur) => list.map(([v, l]) =>
  `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`).join("");


class ContentEditor {
  /**
   * @param {HTMLElement} root
   * @param {object} opts  { onChange(spec), getDuration() -> seconds }
   */
  constructor(root, opts = {}) {
    this.root = root;
    this.opts = opts;
    this.spec = defaultSpec("text");
    this.preview = null;
    this.dc = null;
    this._refresh = debounce(() => this._doPreview(), 220);
  }

  setSpec(spec) {
    this.spec = Object.assign(defaultSpec(spec?.kind || "text"), spec || {});
    this.render();
  }

  getSpec() { return JSON.parse(JSON.stringify(this.spec)); }

  refresh() { this._refresh(); }

  _changed() {
    this.opts.onChange?.(this.spec);
    this._refresh();
  }

  _set(key, val) { this.spec[key] = val; this._changed(); }

  // ── preview ─────────────────────────────────────────────────────
  async _doPreview() {
    if (!this.dc) return;
    const duration = this.opts.getDuration?.() || 8;
    const d = await post("/api/preview", {spec: this.spec, duration, max_frames: 400});
    if (!d?.success) return;
    this.preview.load(d.frames, d.width, d.height);

    const meta = this.root.querySelector("#ed-prev-meta");
    if (!meta) return;
    const m = d.measure || {};
    if (m.hint) {
      meta.className = "ed-prev-meta warn";
      meta.textContent = "⚠ " + m.hint;
    } else {
      meta.className = "ed-prev-meta";
      meta.textContent = d.static ? `${d.width}×${d.height} · still`
        : `${d.width}×${d.height} · previewing ${duration}s, as the panel plays it`;
    }
  }

  // ── render ──────────────────────────────────────────────────────
  render() {
    const s = this.spec;
    this.preview?.stop();

    if (s.kind === "layout") {
      this.root.innerHTML = `<div class="ed-kinds" id="ed-kinds"></div><div id="ed-layout"></div>`;
      this._renderKinds(this.root.querySelector("#ed-kinds"));
      this.layout?.destroy();
      this.layout = new LayoutEditor(this.root.querySelector("#ed-layout"), {
        spec: s,
        onChange: spec => { this.spec = spec; this.opts.onChange?.(spec); },
      });
      this.layout.setSpec(s);
      return;
    }

    this.root.innerHTML = `
      <div class="ed">
        <div class="ed-form">
          <div class="ed-kinds" id="ed-kinds"></div>
          <div id="ed-fields"></div>
        </div>
        <div class="ed-preview">
          <div class="ed-prev-label">PREVIEW</div>
          <canvas id="ed-canvas"></canvas>
          <div class="ed-prev-meta" id="ed-prev-meta"></div>
        </div>
      </div>`;
    this._renderKinds(this.root.querySelector("#ed-kinds"));

    const fields = this.root.querySelector("#ed-fields");
    if (s.kind === "text")           this._textFields(fields);
    else if (s.kind === "animation") this._animFields(fields);
    else if (s.kind === "image")     this._imageFields(fields);
    else fields.innerHTML = `<div class="ed-note">${s.kind === "clear"
      ? "Flips every dot off." : "Flips every dot on."}</div>`;

    this.dc = new DotCanvas(this.root.querySelector("#ed-canvas"), {dot: 4, gap: 1});
    this.preview = new PreviewPlayer(this.dc);
    this._doPreview();
  }

  _renderKinds(kw) {
    const kinds = [["text", "Text"], ["animation", "Animation"], ["image", "Image / GIF"],
                   ["layout", "Dashboard"], ["clear", "Blank"]];
    kw.innerHTML = kinds.map(([k, l]) =>
      `<button class="ed-kind ${this.spec.kind === k ? "active" : ""}" data-k="${k}">${l}</button>`).join("");
    kw.querySelectorAll("button").forEach(b => b.onclick = () => {
      this.spec = defaultSpec(b.dataset.k);
      this.opts.onChange?.(this.spec);
      this.render();
    });
  }

  // ── text ────────────────────────────────────────────────────────
  _textFields(el) {
    const s = this.spec;
    const st = textSteps(s);
    const ticker = st.while.startsWith("scroll_");
    const letterFx = !!(s.intro || s.idle || s.outro);
    const visuals = ANIMS.filter(a => a.category === "generative");

    el.innerHTML = `
      <label class="fl">MESSAGE</label>
      <textarea id="e-text" class="fi" rows="2"
        placeholder="Type a message… Enter for a new line">${esc(s.text)}</textarea>
      <details class="ed-tokens"><summary>＋ live data {tokens}</summary>
        <div class="var-chips" id="e-chips"></div></details>
      <div class="var-preview" id="e-sub"></div>

      <div class="recipes">
        <span class="fl">RECIPES</span>
        ${RECIPES.map((r, i) => `<button class="chip recipe" data-i="${i}">${esc(r.name)}</button>`).join("")}
      </div>

      <div class="step-grid">
        <div class="ff">
          <label class="fl">① ARRIVE</label>
          <select id="e-arrive" class="fi" ${ticker ? "disabled" : ""}>${opt(ARRIVE, st.arrive)}</select>
        </div>
        <div class="ff">
          <label class="fl">② WHILE UP</label>
          <select id="e-while" class="fi">${opt(WHILE, st.while)}</select>
        </div>
        <div class="ff">
          <label class="fl">③ LEAVE</label>
          <select id="e-leave" class="fi" ${ticker ? "disabled" : ""}>${opt(LEAVE, st.leave)}</select>
        </div>
      </div>
      ${ticker ? `<div class="ed-note">A ticker loops for the whole step, so it has no arrive/leave.</div>` : ""}

      <div class="fg">
        <div class="ff">
          <label class="fl">FONT</label>
          <select id="e-font" class="fi">${FONTS.map(f =>
            `<option value="${f.key}" ${f.key === s.font ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</select>
        </div>
        <div class="ff">
          <label class="fl">SIZE <span class="rv" id="v-size">${s.size}px</span></label>
          <input type="range" id="e-size" min="5" max="42" step="1" value="${s.size}">
        </div>
        <div class="ff">
          <label class="fl">${ticker || s.motion.startsWith("scroll_in_") ? "SCROLL SPEED" : "ANIMATION SPEED"}
            <span class="rv" id="v-spd">${ticker || s.motion.startsWith("scroll_in_")
              ? s.speed + " px/s" : (s.fx_speed ?? 1) + "×"}</span></label>
          ${ticker || s.motion.startsWith("scroll_in_")
            ? `<input type="range" id="e-speed" min="5" max="120" step="1" value="${s.speed}">`
            : `<input type="range" id="e-fxs" min="0.25" max="3" step="0.25" value="${s.fx_speed ?? 1}">`}
        </div>
        <div class="ff">
          <label class="fl">POSITION</label>
          <div class="seg" id="e-pos">
            ${[["left", "◧"], ["center", "▣"], ["right", "◨"]].map(([v, l]) =>
              `<button class="${s.align === v ? "on" : ""}" data-a="${v}" title="${v}">${l}</button>`).join("")}
            ${[["top", "⬒"], ["middle", "▣"], ["bottom", "⬓"]].map(([v, l]) =>
              `<button class="${s.valign === v ? "on" : ""}" data-v="${v}" title="${v}">${l}</button>`).join("")}
          </div>
        </div>
      </div>

      <div class="fg">
        <div class="ff">
          <label class="fl">MOVING BACKGROUND</label>
          <select id="e-bg" class="fi">
            <option value="">None</option>
            ${visuals.map(a => `<option value="${a.id}" ${a.id === s.bg ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
          </select>
        </div>
        <div class="ff ${s.bg ? "" : "ff-off"}">
          <label class="fl">TEXT ON BACKGROUND</label>
          <select id="e-blend" class="fi" ${s.bg ? "" : "disabled"}>${opt(BLENDS, s.bg_blend || "outline")}</select>
        </div>
        <div class="ff">
          <label class="cb-row"><input type="checkbox" id="e-bold" ${s.bold ? "checked" : ""}> BOLD</label>
        </div>
      </div>

      <details class="ed-adv">
        <summary>FINE TUNING</summary>
        <div class="fg">
          <div class="ff">
            <label class="fl">NUDGE X <span class="rv" id="v-dx">${s.dx}</span></label>
            <input type="range" id="e-dx" min="-42" max="42" step="1" value="${s.dx}">
          </div>
          <div class="ff">
            <label class="fl">NUDGE Y <span class="rv" id="v-dy">${s.dy}</span></label>
            <input type="range" id="e-dy" min="-21" max="21" step="1" value="${s.dy}">
          </div>
          <div class="ff">
            <label class="fl">LETTER SPACING <span class="rv" id="v-tracking">${s.tracking}</span></label>
            <input type="range" id="e-tracking" min="0" max="8" step="1" value="${s.tracking}">
          </div>
          <div class="ff">
            <label class="fl">LINE SPACING <span class="rv" id="v-leading">${s.leading}</span></label>
            <input type="range" id="e-leading" min="0" max="10" step="1" value="${s.leading}">
          </div>
          ${st.while === "blink" ? `
          <div class="ff">
            <label class="fl">BLINK RATE <span class="rv" id="v-blink">${s.blink} Hz</span></label>
            <input type="range" id="e-blink" min="0.5" max="5" step="0.5" value="${s.blink || 1}">
          </div>
          <div class="ff">
            <label class="fl">BLINK ON-TIME <span class="rv" id="v-duty">${Math.round((s.blink_duty ?? .5) * 100)}%</span></label>
            <input type="range" id="e-duty" min="0.1" max="0.9" step="0.05" value="${s.blink_duty ?? .5}">
          </div>` : ""}
          ${ticker ? `
          <div class="ff">
            <label class="fl">GAP BETWEEN LOOPS <span class="rv" id="v-gap">${s.gap}px</span></label>
            <input type="range" id="e-gap" min="0" max="200" step="4" value="${s.gap}">
          </div>` : ""}
        </div>
      </details>`;

    // tokens
    const chips = el.querySelector("#e-chips");
    TOKEN_GROUPS.forEach(g => {
      if (!g.tokens?.length) return;
      chips.insertAdjacentHTML("beforeend",
        `<span class="chip-group ${g.ok === false ? "err" : ""}">${esc(g.group)}</span>`);
      g.tokens.forEach(t => {
        const c = document.createElement("button");
        c.className = "chip"; c.textContent = "{" + t.token + "}"; c.title = "now: " + t.value;
        c.onclick = () => this._insert("{" + t.token + "}");
        chips.appendChild(c);
      });
    });
    if (!chips.children.length) chips.innerHTML = `<span class="ed-note">No data sources yet — add one in Setup.</span>`;

    const ta = el.querySelector("#e-text");
    ta.addEventListener("input", () => { this._set("text", ta.value); this._substitute(ta.value); });
    this._substitute(s.text);

    // three steps
    const steps = () => ({
      arrive: el.querySelector("#e-arrive").value,
      while:  el.querySelector("#e-while").value,
      leave:  el.querySelector("#e-leave").value,
    });
    ["arrive", "while", "leave"].forEach(k => el.querySelector("#e-" + k).onchange = () => {
      applySteps(this.spec, steps());
      this._changed();
      this.render();                       // available knobs depend on the choice
    });

    el.querySelectorAll(".recipe").forEach(b => b.onclick = () => {
      const r = RECIPES[+b.dataset.i].set;
      applySteps(this.spec, r);
      this.spec.bg = r.bg || "";
      if (r.bg_blend) this.spec.bg_blend = r.bg_blend;
      if (r.bg && this.spec.size < 14) { this.spec.size = 14; this.spec.bold = true; }
      this._changed();
      this.render();
    });

    el.querySelectorAll("#e-pos button").forEach(b => b.onclick = () => {
      if (b.dataset.a) this.spec.align = b.dataset.a;
      if (b.dataset.v) this.spec.valign = b.dataset.v;
      this._changed();
      el.querySelectorAll("#e-pos button").forEach(x => x.classList.toggle("on",
        x.dataset.a ? x.dataset.a === this.spec.align : x.dataset.v === this.spec.valign));
    });

    const bind = (id, key, cast = v => v, fmt = null, rerender = false) => {
      const inp = el.querySelector("#e-" + id);
      if (!inp) return;
      const out = el.querySelector("#v-" + id);
      inp.addEventListener(inp.type === "range" ? "input" : "change", () => {
        const val = inp.type === "checkbox" ? inp.checked : cast(inp.value);
        if (out) out.textContent = fmt ? fmt(val) : val;
        this._set(key, val);
        if (rerender) this.render();
      });
    };
    bind("font", "font");
    bind("size", "size", Number, v => v + "px");
    bind("speed", "speed", Number, v => v + " px/s");
    bind("fxs", "fx_speed", Number, v => v + "×");
    el.querySelector("#e-fxs")?.addEventListener("input", e =>
      el.querySelector("#v-spd").textContent = e.target.value + "×");
    el.querySelector("#e-speed")?.addEventListener("input", e =>
      el.querySelector("#v-spd").textContent = e.target.value + " px/s");
    bind("bg", "bg", v => v, null, true);
    bind("blend", "bg_blend");
    bind("bold", "bold");
    bind("dx", "dx", Number);
    bind("dy", "dy", Number);
    bind("tracking", "tracking", Number);
    bind("leading", "leading", Number);
    bind("blink", "blink", Number, v => v + " Hz");
    bind("duty", "blink_duty", Number, v => Math.round(v * 100) + "%");
    bind("gap", "gap", Number, v => v + "px");
  }

  _insert(token) {
    const ta = this.root.querySelector("#e-text");
    if (!ta) return;
    const a = ta.selectionStart ?? ta.value.length, b = ta.selectionEnd ?? ta.value.length;
    ta.value = ta.value.slice(0, a) + token + ta.value.slice(b);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = a + token.length;
    this._set("text", ta.value);
    this._substitute(ta.value);
  }

  async _substitute(text) {
    const out = this.root.querySelector("#e-sub");
    if (!out) return;
    if (!text || !text.includes("{")) { out.textContent = ""; return; }
    const d = await post("/api/variables/preview", {text});
    if (d) out.textContent = "→ " + d.substituted;
  }

  // ── animation ───────────────────────────────────────────────────
  _animFields(el) {
    const s = this.spec;
    const cur = ANIMS.find(a => a.id === s.animation) || ANIMS[0];
    if (cur && s.animation !== cur.id) s.animation = cur.id;

    const order = ["generative", "physics", "cellular", "geometric", "data", "text"];
    const cats = {};
    ANIMS.forEach(a => (cats[a.category] ||= []).push(a));
    const names = {generative: "Visuals — run until the step ends", physics: "Physics",
                   cellular: "Cellular", geometric: "Wipes & shapes", data: "Data-ish", text: "Text"};

    el.innerHTML = `
      <div class="anim-picker">${Object.keys(cats).sort((a, b) =>
        (order.indexOf(a) + 99) % 99 - (order.indexOf(b) + 99) % 99).map(cat => `
        <div class="anim-cat">
          <div class="anim-cat-label">${esc(names[cat] || cat)}</div>
          <div class="anim-grid">${cats[cat].map(a =>
            `<button class="anim-card ${a.id === s.animation ? "active" : ""}" data-id="${a.id}">${esc(a.name)}</button>`).join("")}
          </div>
        </div>`).join("")}
      </div>
      <div id="e-anim-params"></div>`;

    el.querySelectorAll(".anim-card").forEach(b => b.onclick = () => {
      this.spec.animation = b.dataset.id;
      this.spec.params = {};
      this.opts.onChange?.(this.spec);
      this._animFields(el);
      this._doPreview();
    });

    const pd = el.querySelector("#e-anim-params");
    if (!cur) return;
    pd.innerHTML = `<div class="fg">` + (cur.params || []).map(p => {
      const val = s.params?.[p.id] ?? p.default;
      return p.type === "range"
        ? `<div class="ff"><label class="fl">${esc(p.label)} <span class="rv" id="pv-${p.id}">${val}</span></label>
             <input type="range" id="pp-${p.id}" min="${p.min}" max="${p.max}" step="${p.step}" value="${val}"></div>`
        : `<div class="ff"><label class="fl">${esc(p.label)}</label>
             <input type="text" class="fi" id="pp-${p.id}" value="${esc(val)}"></div>`;
    }).join("") + `</div>`;

    (cur.params || []).forEach(p => {
      const inp = el.querySelector("#pp-" + p.id);
      const out = el.querySelector("#pv-" + p.id);
      inp?.addEventListener("input", () => {
        const v = p.type === "range" ? parseFloat(inp.value) : inp.value;
        if (out) out.textContent = v;
        this.spec.params = {...(this.spec.params || {}), [p.id]: v};
        this._changed();
      });
    });
  }

  // ── image ───────────────────────────────────────────────────────
  _imageFields(el) {
    const n = (this.spec.frames || []).length;
    el.innerHTML = `
      <label class="fl">IMAGE / GIF</label>
      <input type="file" id="e-img" accept="image/*" class="fi" style="padding:3px">
      <div class="fg" style="margin-top:8px">
        <div class="ff">
          <label class="fl">THRESHOLD <span class="rv" id="v-thr">128</span></label>
          <input type="range" id="e-thr" min="0" max="255" value="128">
        </div>
        <div class="ff">
          <label class="fl">DITHER</label>
          <select id="e-dither" class="fi">
            <option value="none">None</option><option value="floyd">Floyd–Steinberg</option>
            <option value="bayer">Bayer</option>
          </select>
        </div>
        <div class="ff">
          <label class="fl">SCALE</label>
          <select id="e-scale" class="fi">
            <option value="fit">Fit</option><option value="fill">Fill (crop)</option>
            <option value="stretch">Stretch</option>
          </select>
        </div>
        <div class="ff"><label class="cb-row"><input type="checkbox" id="e-inv"> INVERT</label></div>
      </div>
      <div class="btn-row">
        <button class="btn btn-outline btn-sm" id="e-img-go">PROCESS</button>
        <span class="ed-note" id="e-img-info">${n ? n + " frame(s) loaded" : "No image loaded"}</span>
      </div>`;

    el.querySelector("#e-thr").addEventListener("input", e =>
      el.querySelector("#v-thr").textContent = e.target.value);

    el.querySelector("#e-img-go").onclick = async () => {
      const f = el.querySelector("#e-img").files[0];
      if (!f) { toast("Choose a file first", "err"); return; }
      const form = new FormData();
      form.append("file", f);
      form.append("threshold", el.querySelector("#e-thr").value);
      form.append("dither", el.querySelector("#e-dither").value);
      form.append("scale", el.querySelector("#e-scale").value);
      form.append("invert", el.querySelector("#e-inv").checked ? "true" : "false");
      toast("Processing…");
      try {
        const r = await fetch(API + "/api/image/upload", {method: "POST", body: form});
        const d = await r.json();
        if (!d.success) { toast(d.error || "Failed", "err"); return; }
        this.spec.frames = d.frames;
        this.opts.onChange?.(this.spec);
        el.querySelector("#e-img-info").textContent =
          d.frame_count + " frame(s)" + (d.animated ? " — animated" : "");
        this._doPreview();
        toast("Processed " + d.frame_count + " frame(s)", "ok");
      } catch { toast("Upload failed", "err"); }
    };
  }

  destroy() {
    this.preview?.stop();
    this.layout?.destroy();
  }
}
