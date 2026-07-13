/**
 * core.js — API access, toasts, and the dot-matrix canvas.
 *
 * DotCanvas draws a bitmap as physical flipdots. PreviewPlayer animates a
 * frame list returned by /api/preview, honouring each frame's own delay — so
 * the preview in the browser runs at the same pace the panel will.
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

// ── Dot canvas ────────────────────────────────────────────────────
class DotCanvas {
  constructor(canvas, {dot = 4, gap = 1, glow = true, dividers = false} = {}) {
    this.canvas   = canvas;
    this.ctx      = canvas.getContext("2d");
    this.dot      = dot;
    this.gap      = gap;
    this.glow     = glow;
    this.dividers = dividers;
    this.w = 84;
    this.h = 42;
    this.resize(84, 42);
  }

  resize(w, h) {
    if (w === this.w && h === this.h && this.canvas.width) return;
    this.w = w;
    this.h = h;
    const step = this.dot + this.gap;
    this.canvas.width  = w * step + this.gap;
    this.canvas.height = h * step + this.gap;
  }

  draw(buf) {
    if (!buf || !buf.length) return;
    this.resize(buf[0].length, buf.length);

    const {ctx, dot, gap} = this;
    const step = dot + gap;

    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    if (this.dividers) {
      ctx.strokeStyle = "#1a1a14";
      ctx.lineWidth = 1;
      for (let c = 28; c < this.w; c += 28) {
        const x = c * step;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, this.canvas.height); ctx.stroke();
      }
      for (let r = 7; r < this.h; r += 7) {
        const y = r * step;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.canvas.width, y); ctx.stroke();
      }
    }

    for (let row = 0; row < this.h; row++) {
      const line = buf[row];
      if (!line) continue;
      for (let col = 0; col < this.w; col++) {
        if (line[col]) {
          if (this.glow) {
            ctx.shadowColor = "rgba(240,238,228,0.4)";
            ctx.shadowBlur  = 2;
          }
          ctx.fillStyle = "#f0eee8";
        } else {
          ctx.shadowBlur = 0;
          ctx.fillStyle  = "#141412";
        }
        ctx.fillRect(col * step + gap, row * step + gap, dot, dot);
      }
    }
    ctx.shadowBlur = 0;
  }

  blank() {
    this.draw(Array.from({length: this.h}, () => Array(this.w).fill(0)));
  }
}

// ── Preview player ────────────────────────────────────────────────
/**
 * Plays a frame list from /api/preview on a DotCanvas.
 *
 * Frames carry their own delay, and a frame with hold=true is one the panel
 * would sit on indefinitely — we park on it rather than racing to the next.
 */
class PreviewPlayer {
  constructor(dotCanvas) {
    this.dc     = dotCanvas;
    this.frames = [];
    this.i      = 0;
    this.timer  = null;
  }

  load(frames) {
    this.stop();
    this.frames = frames || [];
    this.i = 0;
    if (this.frames.length) this._tick();
    else this.dc.blank();
  }

  _tick() {
    if (!this.frames.length) return;
    const f = this.frames[this.i % this.frames.length];
    this.dc.draw(f.bitmap);

    // A single held frame is a still image — nothing to animate.
    if (f.hold && this.frames.length === 1) return;

    const delay = (f.hold ? 1.0 : (f.delay || 0.05)) * 1000;
    this.i = (this.i + 1) % this.frames.length;
    this.timer = setTimeout(() => this._tick(), Math.max(20, delay));
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
