/**
 * layout.js — Visual zone editor.
 *
 * A layout is a set of zones drawn on one frame. You drag them around on top
 * of the live preview and resize them with corner handles; the preview
 * underneath keeps rendering real data the whole time, so you're arranging
 * against the actual clock and the actual headline, not a placeholder.
 *
 * The overlay is a plain absolutely-positioned <div> per zone, sitting on top
 * of the preview canvas and scaled by the same factor, so hit-testing is free
 * and we never have to reimplement it against canvas pixels.
 */

const ZONE_TYPES = [
  ["text", "Text"],
  ["rule", "Rule"],
  ["box",  "Box"],
];

let zoneSeq = 0;
function newZoneId() {
  return "z" + (++zoneSeq) + Math.random().toString(36).slice(2, 5);
}

function defaultZone(type, w, h) {
  if (type === "rule") return {id: newZoneId(), type: "rule", x: 0, y: Math.floor(h / 2), w, h: 1};
  if (type === "box")  return {id: newZoneId(), type: "box", x: 4, y: 4,
                               w: Math.floor(w / 2), h: Math.floor(h / 2),
                               filled: false, thickness: 1};
  return {
    id: newZoneId(), type: "text", label: "",
    x: 2, y: 2, w: Math.max(20, w - 4), h: 14,
    text: "{time_hm}", font: "px5x7", size: 14,
    align: "left", valign: "middle",
    motion: "static", speed: 30, gap: 16,
    tracking: 1, leading: 1, bold: false, dx: 0, dy: 0,
    enabled: true,
  };
}

// Starting points, so the first dashboard isn't a blank grid.
//
// These are tuned to FIT an 84x42 panel — a big clock only fits at 21px with
// tracking 0 (75px wide; at the default tracking of 1 it is 87px and gets
// clipped). Shipping a preset that trips the overflow warning on sight would
// be a poor first impression, so each of these is checked against measure().
const LAYOUT_PRESETS = {
  "Big clock + date": (w, h) => [
    {...defaultZone("text", w, h), label: "Clock", x: 2, y: 1, w: w - 4, h: 24,
     text: "{time_hm}", size: 21, tracking: 0, align: "center"},
    {...defaultZone("text", w, h), label: "Date", x: 2, y: 27, w: w - 4, h: 13,
     text: "{date}", size: 7, align: "center"},
  ],
  "Clock + news ticker": (w, h) => [
    {...defaultZone("text", w, h), label: "Clock", x: 2, y: 0, w: w - 4, h: 22,
     text: "{time_hm}", size: 21, tracking: 0, align: "center"},
    {...defaultZone("rule", w, h), y: 24},
    {...defaultZone("text", w, h), label: "Ticker", x: 0, y: 27, w, h: 14,
     text: "M{quake_mag} {quake_place|upper}", size: 7,
     motion: "scroll_left", speed: 22, gap: 14},
  ],
  "Three rows": (w, h) => [
    {...defaultZone("text", w, h), label: "Time", x: 2, y: 1, w: w - 4, h: 11,
     text: "{time_hm}  {date}", font: "px3x5", size: 5, align: "left"},
    {...defaultZone("rule", w, h), y: 13},
    {...defaultZone("text", w, h), label: "ISS", x: 2, y: 16, w: w - 4, h: 11,
     text: "ISS {iss_position}", font: "px3x5", size: 5, align: "left"},
    {...defaultZone("rule", w, h), y: 28},
    {...defaultZone("text", w, h), label: "Quakes", x: 2, y: 31, w: w - 4, h: 11,
     text: "{quake_count} QUAKES  MAX M{quake_max_mag}",
     font: "px3x5", size: 5, align: "left"},
  ],
  // Wrapped, not scrolled — a quote reads far better as a block of text.
  "Quote board": (w, h) => [
    {...defaultZone("text", w, h), label: "Quote", x: 1, y: 0, w: w - 2, h: 31,
     text: "{quote_text|upper}", font: "px3x5", size: 5, align: "left",
     valign: "middle", wrap: true, leading: 2},
    {...defaultZone("rule", w, h), y: 33},
    {...defaultZone("text", w, h), label: "Author", x: 1, y: 35, w: w - 2, h: 7,
     text: "{quote_author|upper}", font: "px3x5", size: 5, align: "right"},
  ],
};


class LayoutEditor {
  /**
   * @param {HTMLElement} root
   * @param {object} opts { spec, onChange }
   */
  constructor(root, opts = {}) {
    this.root  = root;
    this.opts  = opts;
    this.spec  = opts.spec || {kind: "layout", zones: []};
    this.sel   = null;
    this.W     = 84;
    this.H     = 42;
    this.scale = 5;            // screen px per dot
    this._refresh = debounce(() => this._doPreview(), 200);
  }

  setSpec(spec) {
    this.spec = spec && spec.kind === "layout"
      ? JSON.parse(JSON.stringify(spec))
      : {kind: "layout", zones: []};
    if (!Array.isArray(this.spec.zones)) this.spec.zones = [];
    this.sel = this.spec.zones[0]?.id || null;
    this.render();
  }

  getSpec() {
    return JSON.parse(JSON.stringify(this.spec));
  }

  _changed() {
    this.opts.onChange?.(this.spec);
    this._refresh();
  }

  zone(id) {
    return this.spec.zones.find(z => z.id === id);
  }

  // ── shell ───────────────────────────────────────────────────────
  render() {
    this.root.innerHTML = `
      <div class="lay">
        <div class="lay-stage-col">
          <div class="lay-toolbar">
            ${ZONE_TYPES.map(([t, l]) =>
              `<button class="btn btn-outline btn-sm" data-add="${t}">+ ${l}</button>`).join("")}
            <select class="fi lay-preset"><option value="">Preset…</option>
              ${Object.keys(LAYOUT_PRESETS).map(k =>
                `<option value="${esc(k)}">${esc(k)}</option>`).join("")}
            </select>
            <span class="lay-hint">drag to move · corner to resize · ⌫ to delete</span>
          </div>
          <div class="lay-stage" id="lay-stage">
            <canvas id="lay-canvas"></canvas>
            <div class="lay-zones" id="lay-zones"></div>
          </div>
          <div class="ed-prev-meta" id="lay-meta"></div>
          <div class="lay-list" id="lay-list"></div>
        </div>
        <div class="lay-props" id="lay-props"></div>
      </div>`;

    const stage = this.root.querySelector("#lay-stage");
    this.dc      = new DotCanvas(this.root.querySelector("#lay-canvas"),
                                 {dot: 4, gap: 1, glow: false});
    this.preview = new PreviewPlayer(this.dc);

    this.root.querySelectorAll("[data-add]").forEach(b => {
      b.onclick = () => {
        const z = defaultZone(b.dataset.add, this.W, this.H);
        this.spec.zones.push(z);
        this.sel = z.id;
        this._changed();
        this.renderZones();
        this.renderProps();
        this.renderList();
      };
    });

    this.root.querySelector(".lay-preset").onchange = e => {
      const p = LAYOUT_PRESETS[e.target.value];
      e.target.value = "";
      if (!p) return;
      this.spec.zones = p(this.W, this.H);
      this.sel = this.spec.zones[0]?.id || null;
      this._changed();
      this.renderZones();
      this.renderProps();
      this.renderList();
    };

    stage.addEventListener("mousedown", e => {
      if (e.target === stage || e.target.id === "lay-canvas"
          || e.target.id === "lay-zones") {
        this.sel = null;
        this.renderZones();
        this.renderProps();
        this.renderList();
      }
    });

    document.addEventListener("keydown", this._key = e => {
      if (!this.sel) return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      const z = this.zone(this.sel);
      if (!z) return;

      if (e.key === "Backspace" || e.key === "Delete") {
        e.preventDefault();
        this.removeZone(this.sel);
        return;
      }
      const step = e.shiftKey ? 5 : 1;
      const moves = {ArrowLeft: [-step, 0], ArrowRight: [step, 0],
                     ArrowUp: [0, -step], ArrowDown: [0, step]};
      if (moves[e.key]) {
        e.preventDefault();
        z.x = clamp(z.x + moves[e.key][0], -this.W, this.W);
        z.y = clamp(z.y + moves[e.key][1], -this.H, this.H);
        this._changed();
        this.renderZones();
        this.renderProps();
      }
    });

    this.renderZones();
    this.renderProps();
    this.renderList();
    this._doPreview();
  }

  destroy() {
    this.preview?.stop();
    if (this._key) document.removeEventListener("keydown", this._key);
  }

  // ── preview + zone overlay ──────────────────────────────────────
  async _doPreview() {
    const d = await post("/api/preview", {spec: this.spec, max_frames: 160});
    if (!d?.success) return;
    this.W = d.width;
    this.H = d.height;
    this.preview.load(d.frames);

    const meta = this.root.querySelector("#lay-meta");
    const m = d.measure || {};
    if (m.zones?.length) {
      meta.className = "ed-prev-meta warn";
      meta.innerHTML = m.zones.map(z =>
        `⚠ <b>${esc(z.label || z.zone)}</b> — ${esc(z.hint)}`).join("<br>");
    } else {
      meta.className = "ed-prev-meta";
      meta.textContent = `${d.width}×${d.height} · ${this.spec.zones.length} zone(s) · live`;
    }
    this.renderZones();
  }

  renderZones() {
    const host = this.root.querySelector("#lay-zones");
    if (!host) return;
    const s = this.scale;
    host.style.width  = this.W * s + "px";
    host.style.height = this.H * s + "px";

    host.innerHTML = this.spec.zones.map(z => `
      <div class="lz ${z.id === this.sel ? "sel" : ""} ${z.enabled === false ? "off" : ""}"
           data-id="${z.id}"
           style="left:${z.x * s}px; top:${z.y * s}px;
                  width:${Math.max(1, z.w) * s}px; height:${Math.max(1, z.h) * s}px">
        <span class="lz-tag">${esc(z.label || z.type)}</span>
        <span class="lz-h" data-h="se"></span>
      </div>`).join("");

    host.querySelectorAll(".lz").forEach(el => {
      el.addEventListener("mousedown", e => this._grab(e, el));
    });
  }

  _grab(e, el) {
    e.preventDefault();
    e.stopPropagation();
    const id = el.dataset.id;
    const z  = this.zone(id);
    if (!z) return;

    this.sel = id;
    this.renderZones();
    this.renderProps();
    this.renderList();

    const resizing = e.target.classList.contains("lz-h");
    const s  = this.scale;
    const x0 = e.clientX, y0 = e.clientY;
    const z0 = {x: z.x, y: z.y, w: z.w, h: z.h};

    const move = ev => {
      // Convert screen delta back into dots, so a zone always lands on a whole
      // dot — a half-dot box would be a lie, the panel can't do it.
      const dx = Math.round((ev.clientX - x0) / s);
      const dy = Math.round((ev.clientY - y0) / s);
      if (resizing) {
        z.w = clamp(z0.w + dx, 1, this.W);
        z.h = clamp(z0.h + dy, 1, this.H);
      } else {
        z.x = clamp(z0.x + dx, 0, this.W - 1);
        z.y = clamp(z0.y + dy, 0, this.H - 1);
      }
      this.renderZones();
      this._syncPropFields();
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      this._changed();
      this.renderList();
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  }

  removeZone(id) {
    this.spec.zones = this.spec.zones.filter(z => z.id !== id);
    if (this.sel === id) this.sel = this.spec.zones[0]?.id || null;
    this._changed();
    this.renderZones();
    this.renderProps();
    this.renderList();
  }

  // ── zone list ───────────────────────────────────────────────────
  renderList() {
    const el = this.root.querySelector("#lay-list");
    if (!el) return;
    if (!this.spec.zones.length) {
      el.innerHTML = `<div class="ed-note">No zones yet — add one above, or start from a preset.</div>`;
      return;
    }
    el.innerHTML = this.spec.zones.map((z, i) => `
      <div class="lz-row ${z.id === this.sel ? "sel" : ""} ${z.enabled === false ? "off" : ""}"
           data-id="${z.id}">
        <span class="lz-row-type k-${z.type}">${z.type}</span>
        <span class="lz-row-txt">${esc(z.label || (z.type === "text" ? z.text : `${z.w}×${z.h}`))}</span>
        <span class="lz-row-pos">${z.x},${z.y} · ${z.w}×${z.h}</span>
        <button class="ic" data-act="tog" title="${z.enabled === false ? "Enable" : "Disable"}">${z.enabled === false ? "○" : "◉"}</button>
        <button class="ic danger" data-act="del" title="Delete">✕</button>
      </div>`).join("");

    el.querySelectorAll(".lz-row").forEach(r => {
      r.onclick = e => {
        const act = e.target.dataset?.act;
        const id  = r.dataset.id;
        if (act === "del") return this.removeZone(id);
        if (act === "tog") {
          const z = this.zone(id);
          z.enabled = z.enabled === false;
          this._changed();
          this.renderZones();
          this.renderList();
          return;
        }
        this.sel = id;
        this.renderZones();
        this.renderProps();
        this.renderList();
      };
    });
  }

  // ── properties panel ────────────────────────────────────────────
  _syncPropFields() {
    const z = this.zone(this.sel);
    if (!z) return;
    ["x", "y", "w", "h"].forEach(k => {
      const el = this.root.querySelector("#lp-" + k);
      if (el) el.value = z[k];
    });
  }

  renderProps() {
    const host = this.root.querySelector("#lay-props");
    if (!host) return;
    const z = this.zone(this.sel);

    if (!z) {
      host.innerHTML = `<div class="param-title">ZONE</div>
        <div class="ed-note">Select a zone to edit it, or add one.</div>`;
      return;
    }

    const geom = `
      <div class="fg">
        ${["x", "y", "w", "h"].map(k => `
          <div class="ff">
            <label class="fl">${k.toUpperCase()}</label>
            <input type="number" class="fi" id="lp-${k}" value="${z[k]}">
          </div>`).join("")}
      </div>`;

    if (z.type === "rule" || z.type === "box") {
      host.innerHTML = `
        <div class="param-title">${z.type.toUpperCase()}</div>
        ${geom}
        ${z.type === "box" ? `
          <div class="fg">
            <div class="ff">
              <label class="cb-row">
                <input type="checkbox" id="lp-filled" ${z.filled ? "checked" : ""}> FILLED
              </label>
            </div>
            <div class="ff">
              <label class="fl">THICKNESS</label>
              <input type="number" class="fi" id="lp-thickness" min="1" max="6"
                     value="${z.thickness || 1}">
            </div>
          </div>` : ""}
        <button class="btn btn-outline btn-sm btn-danger" id="lp-del">DELETE ZONE</button>`;
    } else {
      host.innerHTML = `
        <div class="param-title">TEXT ZONE</div>
        <label class="fl">NAME (optional)</label>
        <input type="text" class="fi" id="lp-label" value="${esc(z.label || "")}"
               placeholder="e.g. Clock">
        <label class="fl" style="margin-top:8px">CONTENT</label>
        <textarea class="fi" id="lp-text" rows="2">${esc(z.text || "")}</textarea>
        <div class="var-chips" id="lp-chips"></div>
        <div class="var-preview" id="lp-sub"></div>
        ${geom}
        <div class="fg">
          <div class="ff">
            <label class="fl">FONT</label>
            <select class="fi" id="lp-font">
              ${FONTS.map(f => `<option value="${f.key}" ${f.key === z.font ? "selected" : ""}>${esc(f.name)}</option>`).join("")}
            </select>
          </div>
          <div class="ff">
            <label class="fl">SIZE <span class="rv" id="lv-size">${z.size}px</span></label>
            <input type="range" id="lp-size" min="5" max="42" value="${z.size}">
          </div>
          <div class="ff">
            <label class="fl">H ALIGN</label>
            <select class="fi" id="lp-align">
              ${["left", "center", "right"].map(a =>
                `<option value="${a}" ${a === z.align ? "selected" : ""}>${a}</option>`).join("")}
            </select>
          </div>
          <div class="ff">
            <label class="fl">V ALIGN</label>
            <select class="fi" id="lp-valign">
              ${["top", "middle", "bottom"].map(a =>
                `<option value="${a}" ${a === z.valign ? "selected" : ""}>${a}</option>`).join("")}
            </select>
          </div>
          <div class="ff">
            <label class="fl">MOTION</label>
            <select class="fi" id="lp-motion">
              ${MOTIONS.map(([m, l]) =>
                `<option value="${m}" ${m === z.motion ? "selected" : ""}>${l}</option>`).join("")}
            </select>
          </div>
          <div class="ff">
            <label class="fl">SPEED <span class="rv" id="lv-speed">${z.speed}</span></label>
            <input type="range" id="lp-speed" min="5" max="120" value="${z.speed}"
                   ${z.motion === "static" ? "disabled" : ""}>
          </div>
        </div>
        <details class="ed-adv">
          <summary>FINE TUNING</summary>
          <div class="fg">
            <div class="ff">
              <label class="fl">LETTER SPACING <span class="rv" id="lv-tracking">${z.tracking}</span></label>
              <input type="range" id="lp-tracking" min="0" max="8" value="${z.tracking}">
            </div>
            <div class="ff">
              <label class="fl">LINE SPACING <span class="rv" id="lv-leading">${z.leading}</span></label>
              <input type="range" id="lp-leading" min="0" max="10" value="${z.leading}">
            </div>
            <div class="ff">
              <label class="fl">LOOP GAP <span class="rv" id="lv-gap">${z.gap}</span></label>
              <input type="range" id="lp-gap" min="0" max="120" value="${z.gap}">
            </div>
            <div class="ff">
              <label class="cb-row"><input type="checkbox" id="lp-bold" ${z.bold ? "checked" : ""}> BOLD</label>
            </div>
            <div class="ff">
              <label class="cb-row"><input type="checkbox" id="lp-wrap" ${z.wrap ? "checked" : ""}> WRAP TEXT</label>
            </div>
          </div>
        </details>
        <button class="btn btn-outline btn-sm btn-danger" id="lp-del">DELETE ZONE</button>`;

      const chips = host.querySelector("#lp-chips");
      TOKEN_GROUPS.forEach(g => {
        g.tokens.slice(0, 40).forEach(t => {
          const b = document.createElement("button");
          b.className = "chip";
          b.textContent = "{" + t.token + "}";
          b.title = `${g.group} — currently: ${t.value}`;
          b.onclick = () => {
            const ta = host.querySelector("#lp-text");
            const a = ta.selectionStart ?? ta.value.length;
            ta.value = ta.value.slice(0, a) + "{" + t.token + "}" + ta.value.slice(ta.selectionEnd ?? a);
            ta.focus();
            z.text = ta.value;
            this._changed();
            this._sub(z.text);
          };
          chips.appendChild(b);
        });
      });
      this._sub(z.text);
    }

    host.querySelector("#lp-del").onclick = () => this.removeZone(z.id);

    const bind = (id, key, cast = v => v, fmt = null, rerender = false) => {
      const el = host.querySelector("#lp-" + id);
      if (!el) return;
      const out = host.querySelector("#lv-" + id);
      el.addEventListener(el.type === "range" ? "input" : "change", () => {
        z[key] = el.type === "checkbox" ? el.checked : cast(el.value);
        if (out) out.textContent = fmt ? fmt(z[key]) : z[key];
        this._changed();
        this.renderZones();
        this.renderList();
        if (rerender) this.renderProps();
      });
    };

    ["x", "y", "w", "h"].forEach(k => bind(k, k, Number));
    bind("filled", "filled");
    bind("thickness", "thickness", Number);
    bind("label", "label");
    bind("font", "font");
    bind("size", "size", Number, v => v + "px");
    bind("align", "align");
    bind("valign", "valign");
    bind("motion", "motion", v => v, null, true);
    bind("speed", "speed", Number);
    bind("tracking", "tracking", Number);
    bind("leading", "leading", Number);
    bind("gap", "gap", Number);
    bind("bold", "bold");
    bind("wrap", "wrap");

    const ta = host.querySelector("#lp-text");
    if (ta) {
      ta.addEventListener("input", () => {
        z.text = ta.value;
        this._changed();
        this.renderList();
        this._sub(ta.value);
      });
    }
  }

  async _sub(text) {
    const out = this.root.querySelector("#lp-sub");
    if (!out) return;
    if (!text || !text.includes("{")) { out.textContent = ""; return; }
    const d = await post("/api/variables/preview", {text});
    if (d) out.textContent = "→ " + d.substituted;
  }
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}
