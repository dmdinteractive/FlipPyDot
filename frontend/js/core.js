/**
 * core.js — API access, toasts, and the dot-matrix canvas.
 *
 * DotCanvas draws frames as physical flipdots. PreviewPlayer animates the
 * frame list returned by /api/preview at the pace the panel will play it.
 */

const API = window.location.origin;

// ── HTTP ──────────────────────────────────────────────────────────
async function get(url) {
  try {
    const r = await fetch(API + url);
    return await r.json();
  } catch { return null; }
}

async function post(url, body = {}) {
  try {
    const r = await fetch(API + url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    return await r.json();
  } catch {
    toast("Server unreachable", "err");
    return null;
  }
}

async function put(url, body = {}) {
  try {
    const r = await fetch(API + url, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    return await r.json();
  } catch { return null; }
}

async function del(url) {
  try {
    const r = await fetch(API + url, {method: "DELETE"});
    return await r.json();
  } catch { return null; }
}

// ── Toast ─────────────────────────────────────────────────────────
function toast(msg, type = "") {
  const c = document.getElementById("toasts");
  if (!c) return;
  const el = document.createElement("div");
  el.className = "toast" + (type ? " " + type : "");
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ── Frames ────────────────────────────────────────────────────────
/**
 * Frames travel as base64 of the packed bits (row-major, MSB first) —
 * about 440 bytes for the full 84x42 panel instead of ~11 KB of JSON.
 */
function unpack(b64, w, h) {
  const bin = atob(b64);
  const out = new Uint8Array(w * h);
  for (let i = 0; i < out.length; i++) {
    out[i] = (bin.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1;
  }
  return out;
}

// ── Dot canvas ────────────────────────────────────────────────────
/**
 * Draws the panel as round discs. Only dots that changed since the last
 * frame are repainted, so the monitor can follow the panel at full rate
 * without the browser breaking a sweat.
 */
class DotCanvas {
  constructor(canvas, {dot = 4, gap = 1, dividers = false} = {}) {
    this.canvas   = canvas;
    this.ctx      = canvas.getContext("2d");
    this.dot      = dot;
    this.gap      = gap;
    this.dividers = dividers;
    this.w = 0; this.h = 0;
    this.last = null;
    this._sprites();
    this.resize(84, 42);
  }

  _sprites() {
    const mk = (fill, glow) => {
      const c = document.createElement("canvas");
      const s = this.dot + this.gap;
      c.width = c.height = s;
      const x = c.getContext("2d");
      x.fillStyle = "#0a0a0a";
      x.fillRect(0, 0, s, s);
      if (glow) { x.shadowColor = "rgba(240,238,228,.45)"; x.shadowBlur = 2; }
      x.fillStyle = fill;
      x.beginPath();
      x.arc(this.gap + this.dot / 2, this.gap + this.dot / 2, this.dot / 2 + 0.25, 0, Math.PI * 2);
      x.fill();
      return c;
    };
    this.onSprite  = mk("#f0eee8", true);
    this.offSprite = mk("#1c1c19", false);
  }

  resize(w, h) {
    if (this.w === w && this.h === h) return;
    const step = this.dot + this.gap;
    this.w = w; this.h = h;
    this.canvas.width  = w * step + this.gap;
    this.canvas.height = h * step + this.gap;
    this.last = null;
  }

  /** bits: Uint8Array(w*h) or array of rows. */
  draw(bits, w = this.w, h = this.h) {
    if (!bits) return;
    if (Array.isArray(bits)) {                 // legacy row arrays
      h = bits.length; w = bits[0]?.length || 0;
      bits = Uint8Array.from(bits.flat());
    }
    this.resize(w, h);
    const {ctx} = this;
    const step = this.dot + this.gap;
    const full = !this.last;
    if (full) {
      ctx.fillStyle = "#0a0a0a";
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }
    for (let i = 0; i < w * h; i++) {
      const v = bits[i];
      if (!full && this.last[i] === v) continue;
      ctx.drawImage(v ? this.onSprite : this.offSprite, (i % w) * step, ((i / w) | 0) * step);
    }
    this.last = bits;
    if (full && this.dividers) {
      ctx.strokeStyle = "#2a2a24";
      ctx.lineWidth = 1;
      for (let c = 28; c < w; c += 28) {
        ctx.beginPath(); ctx.moveTo(c * step + .5, 0); ctx.lineTo(c * step + .5, this.canvas.height); ctx.stroke();
      }
      for (let r = 7; r < h; r += 7) {
        ctx.beginPath(); ctx.moveTo(0, r * step + .5); ctx.lineTo(this.canvas.width, r * step + .5); ctx.stroke();
      }
    }
  }

  drawPacked(b64, w = this.w, h = this.h) { this.draw(unpack(b64, w, h), w, h); }

  blank() { this.draw(new Uint8Array(this.w * this.h)); }
}

// ── Preview player ────────────────────────────────────────────────
/**
 * Plays /api/preview output: [{f: packed frame, d: seconds | null}].
 * The server already sampled it at the panel's frame rate and merged
 * repeats, so what you see here is what the wall will do, beat for beat.
 */
class PreviewPlayer {
  constructor(dotCanvas) {
    this.dc = dotCanvas;
    this.frames = [];
    this.i = 0;
    this.timer = null;
  }

  load(frames, w, h) {
    this.stop();
    this.w = w || this.dc.w; this.h = h || this.dc.h;
    this.frames = (frames || []).map(f => ({bits: unpack(f.f, this.w, this.h), d: f.d}));
    this.i = 0;
    if (this.frames.length) this._tick(); else this.dc.blank();
  }

  _tick() {
    const f = this.frames[this.i];
    this.dc.draw(f.bits, this.w, this.h);
    if (f.d == null) return;                       // hold: a still image
    this.i = (this.i + 1) % this.frames.length;
    // Pause a beat on wrap-around so a loop reads as "again" not "glitch".
    const extra = this.i === 0 && this.frames.length > 1 ? 600 : 0;
    this.timer = setTimeout(() => this._tick(), Math.max(16, f.d * 1000) + extra);
  }

  stop() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}

// ── Misc ──────────────────────────────────────────────────────────
function debounce(fn, ms = 250) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]
  ));
}
