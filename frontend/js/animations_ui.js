/**
 * animations_ui.js
 * Handles the animations tab — categorised grid + per-animation parameter panel
 */

let allAnimations  = [];
let selectedAnim   = null;

async function loadAnimations() {
  const d = await apiGet("/api/animations");
  if (!d?.animations) return;
  allAnimations = d.animations;
  renderAnimationGrid();
}

function renderAnimationGrid() {
  const container = document.getElementById("anim-container");
  if (!container) return;

  const categories = {};
  allAnimations.forEach(a => {
    if (!categories[a.category]) categories[a.category] = [];
    categories[a.category].push(a);
  });

  const catLabels = {
    geometric: "GEOMETRIC",
    physics:   "PHYSICS",
    text:      "TEXT EFFECTS",
    cellular:  "CELLULAR",
    data:      "DATA",
  };

  container.innerHTML = "";
  Object.entries(catLabels).forEach(([cat, label]) => {
    const anims = categories[cat];
    if (!anims) return;

    const section = document.createElement("div");
    section.className = "anim-section";
    section.innerHTML = `<div class="anim-cat-label">${label}</div>`;

    const grid = document.createElement("div");
    grid.className = "anim-grid";

    anims.forEach(a => {
      const card = document.createElement("div");
      card.className  = "anim-card";
      card.dataset.id = a.id;
      card.innerHTML  = `<span class="anim-name">${a.name}</span>`;
      card.addEventListener("click", () => selectAnimation(a, card));
      grid.appendChild(card);
    });

    section.appendChild(grid);
    container.appendChild(section);
  });
}

function selectAnimation(anim, card) {
  selectedAnim = anim;
  document.querySelectorAll(".anim-card").forEach(c => c.classList.remove("active"));
  card.classList.add("active");
  renderParamPanel(anim);
}

function renderParamPanel(anim) {
  const panel = document.getElementById("anim-params");
  if (!panel) return;

  panel.innerHTML = `<div class="param-title">${anim.name.toUpperCase()}</div>`;

  if (!anim.params?.length) {
    panel.innerHTML += `<div class="param-empty">No parameters</div>`;
  } else {
    anim.params.forEach(p => {
      const row = document.createElement("div");
      row.className = "param-row";

      if (p.type === "range") {
        row.innerHTML = `
          <label class="param-label">${p.label}</label>
          <div class="param-range-wrap">
            <input type="range" class="param-range" id="p-${p.id}"
              min="${p.min}" max="${p.max}" step="${p.step}" value="${p.default}">
            <span class="param-val" id="pv-${p.id}">${p.default}</span>
          </div>
        `;
        setTimeout(() => {
          const inp = document.getElementById(`p-${p.id}`);
          const val = document.getElementById(`pv-${p.id}`);
          if (inp && val) {
            inp.addEventListener("input", () => { val.textContent = inp.value; });
          }
        }, 0);
      } else if (p.type === "text") {
        row.innerHTML = `
          <label class="param-label">${p.label}</label>
          <input type="text" class="param-text" id="p-${p.id}" value="${p.default}">
        `;
      }

      panel.appendChild(row);
    });
  }

  const btnRow = document.createElement("div");
  btnRow.className = "param-actions";
  btnRow.innerHTML = `<button class="btn-primary full" onclick="runSelectedAnimation()">▶ RUN ${anim.name.toUpperCase()}</button>`;
  panel.appendChild(btnRow);
}

async function runSelectedAnimation() {
  if (!selectedAnim) { toast("Select an animation first", "error"); return; }

  const options = {};
  (selectedAnim.params || []).forEach(p => {
    const el = document.getElementById(`p-${p.id}`);
    if (!el) return;
    if (p.type === "range") {
      options[p.id] = parseFloat(el.value);
    } else {
      options[p.id] = el.value;
    }
  });

  const d = await apiPost("/api/animations/run", {
    name: selectedAnim.id,
    options
  });
  if (d?.success) toast(`Running: ${selectedAnim.name}`);
  else            toast(d?.error || "Failed", "error");
}
