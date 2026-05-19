/**
 * preview.js — Dual monitor renderer for V5 console
 * Program monitor (full brightness) + Preview monitor (dimmed)
 */

const DW = 84, DH = 42;
const DOT = 4, GAP = 1;

let pgmCanvas, pgmCtx, pvwCanvas, pvwCtx;
let pgmBuf = Array.from({length: DH}, () => Array(DW).fill(0));
let lastFt = Date.now(), fCount = 0, fps = 0;

function initPreview() {
  pgmCanvas = document.getElementById("pgm-canvas");
  pvwCanvas = document.getElementById("pvw-canvas");
  if (!pgmCanvas || !pvwCanvas) return;

  pgmCtx = pgmCanvas.getContext("2d");
  pvwCtx = pvwCanvas.getContext("2d");

  const step = DOT + GAP;
  pgmCanvas.width  = pvwCanvas.width  = DW * step + GAP;
  pgmCanvas.height = pvwCanvas.height = DH * step + GAP;

  drawCanvas(pgmCtx, pgmBuf, true);
  drawCanvas(pvwCtx, pgmBuf, false);
}

function drawCanvas(ctx, buf, isPgm) {
  const step = DOT + GAP;
  ctx.fillStyle = "#050505";
  ctx.fillRect(0, 0, DW * step + GAP, DH * step + GAP);

  // Panel dividers
  ctx.strokeStyle = isPgm ? "#1a1a14" : "#111108";
  ctx.lineWidth = 1;
  for (let c = 1; c < 3; c++) {
    const x = c * 28 * step;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, DH * step + GAP); ctx.stroke();
  }
  for (let r = 1; r < 6; r++) {
    const y = r * 7 * step;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(DW * step + GAP, y); ctx.stroke();
  }

  ctx.shadowBlur = 0;
  for (let row = 0; row < DH; row++) {
    for (let col = 0; col < DW; col++) {
      const on = buf[row] && buf[row][col];
      const x  = col * step + GAP;
      const y  = row * step + GAP;
      if (on) {
        if (isPgm) {
          ctx.shadowColor = "rgba(232,232,224,0.6)";
          ctx.shadowBlur  = 2;
          ctx.fillStyle   = "#e8e8e0";
        } else {
          ctx.shadowBlur  = 0;
          ctx.fillStyle   = "#555550";
        }
      } else {
        ctx.shadowBlur  = 0;
        ctx.fillStyle   = isPgm ? "#111110" : "#0a0a08";
      }
      ctx.fillRect(x, y, DOT, DOT);
    }
  }
  ctx.shadowBlur = 0;

  // FPS (program only)
  if (isPgm) {
    fCount++;
    const now = Date.now();
    if (now - lastFt >= 1000) {
      fps = fCount; fCount = 0; lastFt = now;
      const el = document.getElementById("pgm-fps");
      if (el) el.textContent = fps + " fps";
    }
  }
}

function updateBuffer(buf) {
  pgmBuf = buf;
  if (pgmCtx) drawCanvas(pgmCtx, buf, true);
  if (pvwCtx) drawCanvas(pvwCtx, buf, false);
}

document.addEventListener("DOMContentLoaded", initPreview);
