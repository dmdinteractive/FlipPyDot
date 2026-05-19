/**
 * preview.js — Live 84x42 dot grid canvas renderer
 */

const DW = 84, DH = 42;
const DOT_SIZE = 5, DOT_GAP = 1;

let canvas, ctx;
let buf = Array.from({length: DH}, () => Array(DW).fill(0));
let lastFrameTime = Date.now(), frameCount = 0, fps = 0;

function initPreview() {
  canvas = document.getElementById("preview");
  ctx    = canvas.getContext("2d");
  const step  = DOT_SIZE + DOT_GAP;
  canvas.width  = DW * step + DOT_GAP;
  canvas.height = DH * step + DOT_GAP;
  drawFrame();
}

function drawFrame() {
  const step = DOT_SIZE + DOT_GAP;
  ctx.fillStyle = "#0a0a0a";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Panel dividers (3 cols x 6 rows of controllers)
  ctx.strokeStyle = "#1a1a18";
  ctx.lineWidth = 1;
  for (let c = 1; c < 3; c++) {
    const x = c * 28 * step;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
  }
  for (let r = 1; r < 6; r++) {
    const y = r * 7 * step;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  }

  // Dots
  ctx.shadowBlur = 0;
  for (let row = 0; row < DH; row++) {
    for (let col = 0; col < DW; col++) {
      const on = buf[row] && buf[row][col];
      const x  = col * step + DOT_GAP;
      const y  = row * step + DOT_GAP;
      if (on) {
        ctx.shadowColor = "#f5f4f0";
        ctx.shadowBlur  = 3;
        ctx.fillStyle   = "#f5f4f0";
      } else {
        ctx.shadowBlur  = 0;
        ctx.fillStyle   = "#161614";
      }
      ctx.beginPath();
      ctx.arc(x + DOT_SIZE/2, y + DOT_SIZE/2, DOT_SIZE/2, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.shadowBlur = 0;

  // FPS
  frameCount++;
  const now = Date.now();
  if (now - lastFrameTime >= 1000) {
    fps = frameCount; frameCount = 0; lastFrameTime = now;
    const el = document.getElementById("fps-counter");
    if (el) el.textContent = `${fps} fps`;
  }
}

function updateBuffer(newBuf) {
  buf = newBuf;
  drawFrame();
}

document.addEventListener("DOMContentLoaded", initPreview);
