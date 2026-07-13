/**
 * editor.js — ContentEditor.
 *
 * One form that edits one spec, with a live preview beside it. The same
 * component backs the Compose tab, the playlist step editor and the overlay
 * editor, so there is exactly one place that knows what knobs a piece of
 * content has — adding a knob makes it appear everywhere at once.
 *
 * Preview goes through /api/preview, which runs the real renderer. It never
 * touches the panel, so you can build an entire show with nothing plugged in.
 */

let FONTS = [];
let ANIMS = [];
let VARS  = {};

async function loadEditorData() {
  const [f, a, v] = await Promise.all([
    get("/api/fonts"), get("/api/animations"), get("/api/variables/values"),
  ]);
  FONTS = f?.fonts || [];
  ANIMS = a?.animations || [];
  VARS  = v || {};
}

const MOTIONS = [
  ["static",       "Static"],
  ["scroll_left",  "Scroll ←"],
  ["scroll_right", "Scroll →"],
  ["scroll_up",    "Scroll ↑"],
  ["scroll_down",  "Scroll ↓"],
];

const TRANSITIONS = [
  ["",               "None"],
  ["wipe_right",     "Wipe right"],
  ["wipe_left",      "Wipe left"],
  ["wipe_down",      "Wipe down"],
  ["wipe_up",        "Wipe up"],
  ["curtain_open",   "Curtain open"],
  ["curtain_close",  "Curtain close"],
  ["diagonal_wipe",  "Diagonal"],
  ["flash",          "Flash"],
  ["blinds",         "Blinds"],
];

function defaultSpec(kind = "text") {
  if (kind === "animation") return {kind: "animation", animation: "bounce_balls", params: {}};
  if (kind === "image")     return {kind: "image", frames: []};
  if (kind === "clear")     return {kind: "clear"};
  if (kind === "fill")      return {kind: "fill"};
  return {
    kind: "text", text: "", font: "px5x7", size: 14,
    align: "center", valign: "middle", dx: 0, dy: 0,
    tracking: 1, leading: 1, bold: false,
    motion: "static", speed: 30, gap: 84, blink: 0,
  };
}


class ContentEditor {
  /**
   * @param {HTMLElement} root  container to render into
   * @param {object} opts  { onChange, compact }
   */
  constructor(root, opts = {}) {
    this.root    = root;
    this.opts    = opts;
    this.spec    = defaultSpec("text");
    this.preview = null;
    this.dc      = null;
    this._refresh = debounce(() => this._doPreview(), 220);
  }

  setSpec(spec) {
    this.spec = Object.assign(defaultSpec(spec?.kind || "text"), spec || {});
    this.render();
  }

  getSpec() {
    return JSON.parse(JSON.stringify(this.spec));
  }

  _set(key, val) {
    this.spec[key] = val;
    this.opts.onChange?.(this.spec);
    this._refresh();
  }

  // ── preview ─────────────────────────────────────────────────────
  async _doPreview() {
    if (!this.dc) return;
    const d = await post("/api/preview", {spec: this.spec, max_frames: 300});
    if (d?.success) this.preview.load(d.frames);
  }

  // ── render ──────────────────────────────────────────────────────
  render() {
    const s = this.spec;
    this.root.innerHTML = `
      <div class="ed">
        <div class="ed-form">
          <div class="ed-kinds" id="ed-kinds"></div>
          <div id="ed-fields"></div>
        </div>
        <div class="ed-preview">
          <div class="ed-prev-label">LIVE PREVIEW</div>
          <canvas id="ed-canvas"></canvas>
          <div class="ed-prev-meta" id="ed-prev-meta"></div>
        </div>
      </div>`;

    // Kind switcher
    const kinds = [["text", "Text"], ["animation", "Animation"],
                   ["image", "Image"], ["clear", "Clear"], ["fill", "Fill"]];
    const kw = this.root.querySelector("#ed-kinds");
    kinds.forEach(([k, label]) => {
      const b = document.createElement("button");
      b.className = "ed-kind" + (s.kind === k ? " active" : "");
      b.textContent = label;
      b.onclick = () => {
        this.spec = defaultSpec(k);
        this.opts.onChange?.(this.spec);
        this.render();
      };
      kw.appendChild(b);
    });

    const fields = this.root.querySelector("#ed-fields");
    if (s.kind === "text")           this._textFields(fields);
    else if (s.kind === "animation") this._animFields(fields);
    else if (s.kind === "image")     this._imageFields(fields);
    else fields.innerHTML =
      `<div class="ed-note">${s.kind === "clear"
        ? "Blanks every dot." : "Flips every dot on."}</div>`;

    const canvas = this.root.querySelector("#ed-canvas");
    this.dc      = new DotCanvas(canvas, {dot: 3, gap: 1});
    this.preview = new PreviewPlayer(this.dc);
    this._doPreview();
  }

  // ── text ────────────────────────────────────────────────────────
  _textFields(el) {
    const s = this.spec;
    const scrolling = s.motion !== "static";

    el.innerHTML = `
      <label class="fl">MESSAGE</label>
      <textarea id="e-text" class="fi" rows="2"
        placeholder="Type a message… use {time} {date} {temp} {rss}">${esc(s.text)}</textarea>
      <div class="var-chips" id="e-chips"></div>
      <div class="var-preview" id="e-sub"></div>

      <div class="fg">
        <div class="ff">
          <label class="fl">FONT</label>
          <select id="e-font" class="fi">
            ${FONTS.map(f => `<option value="${f.key}" ${f.key === s.font ? "selected" : ""}>${esc(f.name)}</option>`).join("")}
          </select>
        </div>
        <div class="ff">
          <label class="fl">SIZE <span class="rv" id="v-size">${s.size}px</span></label>
          <input type="range" id="e-size" min="5" max="42" step="1" value="${s.size}">
        </div>
        <div class="ff">
          <label class="fl">H ALIGN</label>
          <select id="e-align" class="fi">
            ${["left", "center", "right"].map(a =>
              `<option value="${a}" ${a === s.align ? "selected" : ""}>${a}</option>`).join("")}
          </select>
        </div>
        <div class="ff">
          <label class="fl">V ALIGN</label>
          <select id="e-valign" class="fi">
            ${["top", "middle", "bottom"].map(a =>
              `<option value="${a}" ${a === s.valign ? "selected" : ""}>${a}</option>`).join("")}
          </select>
        </div>
      </div>

      <div class="fg">
        <div class="ff">
          <label class="fl">MOTION</label>
          <select id="e-motion" class="fi">
            ${MOTIONS.map(([m, label]) =>
              `<option value="${m}" ${m === s.motion ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </div>
        <div class="ff ${scrolling ? "" : "ff-off"}">
          <label class="fl">SPEED <span class="rv" id="v-speed">${s.speed} px/s</span></label>
          <input type="range" id="e-speed" min="5" max="120" step="1"
                 value="${s.speed}" ${scrolling ? "" : "disabled"}>
        </div>
        <div class="ff ${scrolling ? "" : "ff-off"}">
          <label class="fl">LOOP GAP <span class="rv" id="v-gap">${s.gap}px</span></label>
          <input type="range" id="e-gap" min="0" max="200" step="4"
                 value="${s.gap}" ${scrolling ? "" : "disabled"}>
        </div>
        <div class="ff ${scrolling ? "ff-off" : ""}">
          <label class="fl">BLINK <span class="rv" id="v-blink">${s.blink ? s.blink + " Hz" : "off"}</span></label>
          <input type="range" id="e-blink" min="0" max="5" step="0.5"
                 value="${s.blink}" ${scrolling ? "disabled" : ""}>
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
          <div class="ff">
            <label class="cb-row">
              <input type="checkbox" id="e-bold" ${s.bold ? "checked" : ""}> BOLD
            </label>
          </div>
        </div>
      </details>`;

    // Variable chips — click to insert at the cursor.
    const chips = el.querySelector("#e-chips");
    Object.keys(VARS).filter(k => !k.startsWith("rss_")).forEach(k => {
      const c = document.createElement("button");
      c.className = "chip";
      c.textContent = "{" + k + "}";
      c.title = String(VARS[k]);
      c.onclick = () => this._insert("{" + k + "}");
      chips.appendChild(c);
    });

    const ta = el.querySelector("#e-text");
    ta.addEventListener("input", () => {
      this._set("text", ta.value);
      this._substitute(ta.value);
    });
    this._substitute(s.text);

    const bind = (id, key, cast = v => v, fmt = null) => {
      const inp = el.querySelector("#e-" + id);
      if (!inp) return;
      const out = el.querySelector("#v-" + id);
      const ev  = inp.type === "range" ? "input" : "change";
      inp.addEventListener(ev, () => {
        const val = inp.type === "checkbox" ? inp.checked : cast(inp.value);
        if (out) out.textContent = fmt ? fmt(val) : val;
        this._set(key, val);
        // Motion flips which controls are meaningful — re-render to reflect it.
        if (key === "motion") this.render();
      });
    };

    bind("font",     "font");
    bind("size",     "size",     Number, v => v + "px");
    bind("align",    "align");
    bind("valign",   "valign");
    bind("motion",   "motion");
    bind("speed",    "speed",    Number, v => v + " px/s");
    bind("gap",      "gap",      Number, v => v + "px");
    bind("blink",    "blink",    Number, v => v ? v + " Hz" : "off");
    bind("dx",       "dx",       Number);
    bind("dy",       "dy",       Number);
    bind("tracking", "tracking", Number);
    bind("leading",  "leading",  Number);
    bind("bold",     "bold");
  }

  _insert(token) {
    const ta = this.root.querySelector("#e-text");
    if (!ta) return;
    const a = ta.selectionStart ?? ta.value.length;
    const b = ta.selectionEnd   ?? ta.value.length;
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
    const s   = this.spec;
    const cur = ANIMS.find(a => a.id === s.animation) || ANIMS[0];
    if (cur && s.animation !== cur.id) s.animation = cur.id;

    const cats = {};
    ANIMS.forEach(a => (cats[a.category] ||= []).push(a));

    el.innerHTML = `
      <label class="fl">ANIMATION</label>
      <div class="anim-picker" id="e-anim-picker"></div>
      <div id="e-anim-params"></div>`;

    const picker = el.querySelector("#e-anim-picker");
    Object.entries(cats).forEach(([cat, list]) => {
      const g = document.createElement("div");
      g.className = "anim-cat";
      g.innerHTML = `<div class="anim-cat-label">${esc(cat)}</div>`;
      const grid = document.createElement("div");
      grid.className = "anim-grid";
      list.forEach(a => {
        const b = document.createElement("button");
        b.className = "anim-card" + (a.id === s.animation ? " active" : "");
        b.textContent = a.name;
        b.onclick = () => {
          this.spec.animation = a.id;
          this.spec.params = {};       // defaults come from the registry
          this.opts.onChange?.(this.spec);
          this._animFields(el);
          this._doPreview();
        };
        grid.appendChild(b);
      });
      g.appendChild(grid);
      picker.appendChild(g);
    });

    const pd = el.querySelector("#e-anim-params");
    if (!cur) return;
    pd.innerHTML = `<div class="fg">` + (cur.params || []).map(p => {
      const val = s.params?.[p.id] ?? p.default;
      if (p.type === "range") {
        return `<div class="ff">
          <label class="fl">${esc(p.label)} <span class="rv" id="pv-${p.id}">${val}</span></label>
          <input type="range" id="pp-${p.id}" min="${p.min}" max="${p.max}"
                 step="${p.step}" value="${val}">
        </div>`;
      }
      return `<div class="ff">
        <label class="fl">${esc(p.label)}</label>
        <input type="text" class="fi" id="pp-${p.id}" value="${esc(val)}">
      </div>`;
    }).join("") + `</div>`;

    (cur.params || []).forEach(p => {
      const inp = el.querySelector("#pp-" + p.id);
      const out = el.querySelector("#pv-" + p.id);
      if (!inp) return;
      inp.addEventListener("input", () => {
        const v = p.type === "range" ? parseFloat(inp.value) : inp.value;
        if (out) out.textContent = v;
        this.spec.params = {...(this.spec.params || {}), [p.id]: v};
        this.opts.onChange?.(this.spec);
        this._refresh();
      });
    });
  }

  // ── image ───────────────────────────────────────────────────────
  _imageFields(el) {
    const s = this.spec;
    const n = (s.frames || []).length;
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
            <option value="none">None</option>
            <option value="floyd">Floyd–Steinberg</option>
            <option value="bayer">Bayer</option>
          </select>
        </div>
        <div class="ff">
          <label class="fl">SCALE</label>
          <select id="e-scale" class="fi">
            <option value="fit">Fit</option>
            <option value="fill">Fill (crop)</option>
            <option value="stretch">Stretch</option>
          </select>
        </div>
        <div class="ff">
          <label class="cb-row"><input type="checkbox" id="e-inv"> INVERT</label>
        </div>
      </div>
      <div class="btn-row">
        <button class="btn btn-outline btn-sm" id="e-img-go">PROCESS</button>
        <span class="ed-note" id="e-img-info">${n ? n + " frame(s) loaded" : "No image loaded"}</span>
      </div>`;

    el.querySelector("#e-thr").addEventListener("input", e => {
      el.querySelector("#v-thr").textContent = e.target.value;
    });

    el.querySelector("#e-img-go").onclick = async () => {
      const f = el.querySelector("#e-img").files[0];
      if (!f) { toast("Choose a file first", "err"); return; }
      const form = new FormData();
      form.append("file", f);
      form.append("threshold", el.querySelector("#e-thr").value);
      form.append("dither",    el.querySelector("#e-dither").value);
      form.append("scale",     el.querySelector("#e-scale").value);
      form.append("invert",    el.querySelector("#e-inv").checked ? "true" : "false");
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
  }
}
