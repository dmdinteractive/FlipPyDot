/**
 * animations_ui.js — V6 Exploratorium style
 */
let allAnimations=[],selectedAnim=null;

async function loadAnimations(){
  const d=await apiGet("/api/animations");
  if(!d?.animations) return;
  allAnimations=d.animations;
  renderAnimationGrid();
}

function renderAnimationGrid(){
  const container=document.getElementById("anim-container");
  if(!container) return;
  const cats={};
  allAnimations.forEach(a=>{if(!cats[a.category])cats[a.category]=[];cats[a.category].push(a);});
  const labels={geometric:"GEOMETRIC",physics:"PHYSICS",text:"TEXT",cellular:"CELLULAR",data:"DATA"};
  container.innerHTML="";
  Object.entries(labels).forEach(([cat,label])=>{
    const anims=cats[cat];
    if(!anims) return;
    const sec=document.createElement("div");
    sec.className="anim-section";
    sec.innerHTML=`<div class="anim-cat-hd">${label}</div>`;
    const grid=document.createElement("div");
    grid.className="anim-grid";
    anims.forEach(a=>{
      const card=document.createElement("div");
      card.className="anim-card";
      card.dataset.id=a.id;
      card.innerHTML=`<span class="anim-name">${a.name}</span>`;
      card.addEventListener("click",()=>selectAnim(a,card));
      grid.appendChild(card);
    });
    sec.appendChild(grid);
    container.appendChild(sec);
  });
  // Also populate animation select in cue editor
  const sel=document.getElementById("ed-anim");
  if(sel){
    sel.innerHTML="";
    allAnimations.forEach(a=>{const opt=document.createElement("option");opt.value=a.id;opt.textContent=a.name;sel.appendChild(opt);});
  }
}

function selectAnim(anim,card){
  selectedAnim=anim;
  document.querySelectorAll(".anim-card").forEach(c=>c.classList.remove("active"));
  card.classList.add("active");
  renderParamPanel(anim);
}

function renderParamPanel(anim){
  const panel=document.getElementById("anim-params");
  if(!panel) return;
  panel.innerHTML=`<div style="font-family:var(--f-mono);font-size:0.6rem;letter-spacing:0.12em;color:var(--text);padding-bottom:0.5rem;border-bottom:1px solid var(--border);margin-bottom:0.75rem">${anim.name.toUpperCase()}</div>`;
  (anim.params||[]).forEach(p=>{
    const row=document.createElement("div");
    row.style.marginBottom="0.75rem";
    if(p.type==="range"){
      row.innerHTML=`<label class="field-label">${p.label}</label><div class="range-wrap"><input type="range" id="p-${p.id}" min="${p.min}" max="${p.max}" step="${p.step}" value="${p.default}"><span class="range-val" id="pv-${p.id}">${p.default}</span></div>`;
      setTimeout(()=>{const inp=document.getElementById(`p-${p.id}`);const val=document.getElementById(`pv-${p.id}`);if(inp&&val)inp.addEventListener("input",()=>{val.textContent=inp.value;});},0);
    } else if(p.type==="text"){
      row.innerHTML=`<label class="field-label">${p.label}</label><input type="text" class="field-input" id="p-${p.id}" value="${p.default}">`;
    }
    panel.appendChild(row);
  });
  const btn=document.createElement("button");
  btn.className="btn btn-primary";
  btn.textContent="▶ RUN "+anim.name.toUpperCase();
  btn.onclick=runSelectedAnim;
  panel.appendChild(btn);
}

async function runSelectedAnim(){
  if(!selectedAnim){toast("Select an animation first","error");return;}
  const opts={};
  (selectedAnim.params||[]).forEach(p=>{
    const el=document.getElementById(`p-${p.id}`);
    if(el) opts[p.id]=p.type==="range"?parseFloat(el.value):el.value;
  });
  const d=await apiPost("/api/animations/run",{name:selectedAnim.id,options:opts});
  if(d?.success) toast(`${selectedAnim.name} running`,"ok");
  else toast(d?.error||"Failed","error");
}
