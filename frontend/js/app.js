/**
 * app.js — Flipdot Console V6 Application Logic
 * Exploratorium aesthetic + 4 workspaces
 */

const API=window.location.origin;
let socket=null,isConnected=false,editingCueId=null,_imageFrames=[];

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded",()=>{
  setupWorkspaces();
  setupProgTabs();
  scanPorts();
  loadAnimations();
  connectWS();
  updateClock();
  setInterval(updateClock,1000);
  loadShowsList();
  loadVariablesConfig();
  buildPanelHealthGrid();
  buildFxParams();
  loadPlaylist();
  loadAssets();
  setInterval(refreshVariablesMonitor,5000);
});

// ── Workspaces ────────────────────────────────────────────────────
function setupWorkspaces(){
  document.querySelectorAll(".ws-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      document.querySelectorAll(".ws-btn").forEach(b=>b.classList.remove("active"));
      document.querySelectorAll(".workspace").forEach(w=>w.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("ws-"+btn.dataset.ws)?.classList.add("active");
      if(btn.dataset.ws==="monitor") refreshMonitor();
      if(btn.dataset.ws==="setup")   loadShowsList();
    });
  });
}

function setupProgTabs(){
  document.querySelectorAll(".prog-tab").forEach(btn=>{
    btn.addEventListener("click",()=>{
      document.querySelectorAll(".prog-tab").forEach(b=>b.classList.remove("active"));
      document.querySelectorAll(".prog-pane").forEach(p=>p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("ptab-"+btn.dataset.ptab)?.classList.add("active");
      if(btn.dataset.ptab==="assets") loadAssets();
      if(btn.dataset.ptab==="pixel")  setupPixelEditor();
    });
  });
}

// ── Clock ─────────────────────────────────────────────────────────
function updateClock(){
  const t=new Date().toTimeString().slice(0,8);
  const el=document.getElementById("hdr-clock");
  if(el) el.textContent=t;
  const sb=document.getElementById("sb-time");
  if(sb) sb.textContent=new Date().toLocaleString();
}

// ── API ───────────────────────────────────────────────────────────
async function apiPost(url,body={}){
  try{const r=await fetch(API+url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});return await r.json();}
  catch(e){toast("Server unreachable","error");return null;}
}
async function apiGet(url){
  try{return await(await fetch(API+url)).json();}
  catch{return null;}
}
async function apiDelete(url){
  try{await fetch(API+url,{method:"DELETE"});}catch{}
}

// ── WebSocket ─────────────────────────────────────────────────────
function connectWS(){
  if(typeof io==="undefined"){startPollFallback();return;}
  socket=io(API,{transports:["websocket","polling"]});
  socket.on("connect",()=>toast("Real-time connected","ok"));
  socket.on("status",d=>{updateConnUI(d);updateCueUI(d.cue_engine);updateSchedUI(d.scheduler);updatePlUI(d.playlist);});
  socket.on("buffer",d=>{if(d.buffer)updateBuffer(d.buffer);});
}
function startPollFallback(){
  setInterval(async()=>{const d=await apiGet("/api/status");if(d){updateConnUI(d);updateCueUI(d.cue_engine);updateSchedUI(d.scheduler);}},2000);
  setInterval(async()=>{const d=await apiGet("/api/buffer");if(d?.buffer)updateBuffer(d.buffer);},600);
}

function wsGo()     {socket?socket.emit("go",{}):apiPost("/api/transport/go");}
function wsBack()   {socket?socket.emit("back",{}):apiPost("/api/transport/back");}
function wsRelease(){socket?socket.emit("release",{}):apiPost("/api/transport/release");}
function wsHold()   {socket?socket.emit("hold",{}):apiPost("/api/transport/hold");}

// ── Connection UI ─────────────────────────────────────────────────
function updateConnUI(d){
  isConnected=d.connected;
  const dot=document.getElementById("hdr-dot"),st=document.getElementById("hdr-status"),sb=document.getElementById("sb-conn");
  if(d.connected){
    dot?.classList.add("online");
    if(st) st.textContent=d.port?.split("/").pop()||"ONLINE";
    if(sb){sb.textContent=`SERIAL: ${d.port?.split("/").pop()} ✓`;sb.className="sb-ok";}
  } else {
    dot?.classList.remove("online");
    if(st) st.textContent="OFFLINE";
    if(sb){sb.textContent="SERIAL: OFFLINE";sb.className="sb-err";}
  }
}

async function toggleConnect(){
  if(isConnected){await apiPost("/api/disconnect");toast("Disconnected");}
  else{
    const port=(document.getElementById("port-select")||document.getElementById("setup-port"))?.value;
    if(!port){toast("Select a port first","error");return;}
    const d=await apiPost("/api/connect",{port});
    toast(d?.success?"Connected: "+port:"Connection failed",d?.success?"ok":"error");
  }
}

async function scanPorts(){
  const sel=document.getElementById("port-select");
  if(!sel) return;
  sel.innerHTML="<option>Scanning…</option>";
  const d=await apiGet("/api/ports");
  if(!d?.length){sel.innerHTML="<option value=''>No ports found</option>";return;}
  sel.innerHTML="";
  d.forEach(p=>{const o=document.createElement("option");o.value=p.port;o.textContent=p.port.split("/").pop()+" — "+p.description;sel.appendChild(o);});
}

async function scanPortsSetup(){
  const sel=document.getElementById("setup-port");
  if(!sel) return;
  const d=await apiGet("/api/ports");
  if(!d?.length){sel.innerHTML="<option value=''>No ports</option>";return;}
  sel.innerHTML="";
  d.forEach(p=>{const o=document.createElement("option");o.value=p.port;o.textContent=p.port.split("/").pop()+" — "+p.description;sel.appendChild(o);});
}

// ── Cue UI ────────────────────────────────────────────────────────
function updateCueUI(eng){
  if(!eng) return;
  const cur=eng.current_cue,nxt=eng.next_cue;
  document.getElementById("t-num").textContent=cur?cur.number:"—";
  document.getElementById("t-name").textContent=cur?cur.label:"NO CUE ACTIVE";
  document.getElementById("t-elapsed").textContent=(eng.elapsed||0).toFixed(1);
  const stEl=document.getElementById("t-state");
  if(stEl){stEl.textContent=eng.state;stEl.className="t-state "+eng.state;}
  document.getElementById("pgm-num") &&(document.getElementById("pgm-num").textContent=cur?cur.number:"—");
  document.getElementById("pgm-label")&&(document.getElementById("pgm-label").textContent=cur?cur.label:"NO CUE");
  document.getElementById("pvw-num") &&(document.getElementById("pvw-num").textContent=nxt?nxt.number:"—");
  document.getElementById("pvw-label")&&(document.getElementById("pvw-label").textContent=nxt?nxt.label:"—");
  const sb=document.getElementById("sb-cue");
  if(sb) sb.textContent=`CUE: ${eng.state}${cur?` [${cur.number}]`:""}`;
  document.querySelectorAll(".cue-table tr[data-cue-id]").forEach(r=>r.classList.toggle("active",cur&&r.dataset.cueId===cur.id));
  if(eng.cues) renderCueTable(eng.cues);
}

function renderCueTable(cues){
  const tbody=document.getElementById("cue-tbody"),empty=document.getElementById("cue-empty");
  if(!tbody) return;
  if(!cues.length){tbody.innerHTML="";if(empty)empty.style.display="block";return;}
  if(empty) empty.style.display="none";
  const key=cues.map(c=>c.id+c.label+c.duration).join("|");
  if(tbody._k===key) return;
  tbody._k=key;
  tbody.innerHTML=cues.map(cue=>{
    const ct=cue.content_type||"clear",c=cue.content||{};
    const cs=ct==="text"?(c.text||"—"):ct==="animation"?(c.animation_id||"—"):ct==="image"?"[IMG]":ct;
    return`<tr data-cue-id="${cue.id}">
      <td class="col-num">${cue.number}</td>
      <td title="${cue.label}">${cue.label}</td>
      <td><span class="type-pill ${ct}">${ct.toUpperCase()}</span></td>
      <td title="${cs}">${cs}</td>
      <td>${cue.pre_wait}s</td>
      <td>${cue.duration<0?"HOLD":cue.duration+"s"}</td>
      <td>${cue.auto_follow?"AUTO":"—"}</td>
      <td class="col-actions">
        <button class="row-btn go-btn" onclick="fireJump('${cue.id}')">GO</button>
        <button class="row-btn" onclick="openCueEditor('${cue.id}')">EDIT</button>
        <button class="row-btn del-btn" onclick="deleteCue('${cue.id}')">DEL</button>
      </td></tr>`;
  }).join("");
}

function addCue(){openCueEditor(null);}
function openCueEditor(id){
  editingCueId=id;
  const ed=document.getElementById("cue-editor");
  if(!ed) return;
  ed.style.display="block";
  if(id){
    apiGet("/api/cues").then(d=>{
      const cue=d?.cues?.find(c=>c.id===id);if(!cue) return;
      document.getElementById("ed-cue-num").textContent=cue.number;
      document.getElementById("ed-number").value=cue.number;
      document.getElementById("ed-label").value=cue.label;
      document.getElementById("ed-type").value=cue.content_type;
      document.getElementById("ed-prewait").value=cue.pre_wait;
      document.getElementById("ed-duration").value=cue.duration;
      document.getElementById("ed-fade").value=cue.fade_in;
      document.getElementById("ed-auto").value=cue.auto_follow?"true":"false";
      const c=cue.content||{};
      if(cue.content_type==="text"){
        document.getElementById("ed-text").value=c.text||"";
        document.getElementById("ed-fontsize").value=c.font_size||14;
        document.getElementById("ed-scroll").value=c.scroll?"true":"false";
      } else if(cue.content_type==="animation"){
        const sel=document.getElementById("ed-anim");if(sel)sel.value=c.animation_id||"";
      }
      updateEditorType();
    });
  } else {
    document.getElementById("ed-cue-num").textContent="NEW";
    ["ed-number","ed-label","ed-text"].forEach(i=>{const el=document.getElementById(i);if(el)el.value="";});
    document.getElementById("ed-type").value="clear";
    document.getElementById("ed-prewait").value=0;
    document.getElementById("ed-duration").value=5;
    document.getElementById("ed-fade").value=0;
    document.getElementById("ed-auto").value="false";
    updateEditorType();
  }
  ed.scrollIntoView({behavior:"smooth",block:"end"});
}

function updateEditorType(){
  const type=document.getElementById("ed-type")?.value;
  const s=(id,v)=>{const el=document.getElementById(id);if(el)el.style.display=v?"block":"none";};
  s("ed-text-f",type==="text");s("ed-fsize-f",type==="text");s("ed-scroll-f",type==="text");s("ed-anim-f",type==="animation");
}

async function saveCueEdit(){
  const type=document.getElementById("ed-type").value;
  const number=parseFloat(document.getElementById("ed-number").value)||undefined;
  const label=document.getElementById("ed-label").value||`Cue ${number||""}`;
  const prewait=parseFloat(document.getElementById("ed-prewait").value)||0;
  const duration=parseFloat(document.getElementById("ed-duration").value)||5;
  const fade=parseFloat(document.getElementById("ed-fade").value)||0;
  const auto=document.getElementById("ed-auto").value==="true";
  let content={};
  if(type==="text") content={text:document.getElementById("ed-text").value,font_size:parseInt(document.getElementById("ed-fontsize").value),scroll:document.getElementById("ed-scroll").value==="true"};
  else if(type==="animation") content={animation_id:document.getElementById("ed-anim").value};
  const payload={number,label,content_type:type,content,pre_wait:prewait,duration,fade_in:fade,auto_follow:auto};
  let d;
  if(editingCueId){
    d=await fetch(`${API}/api/cues/${editingCueId}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}).then(r=>r.json());
    if(d.success) toast("Cue updated","ok");
  } else {
    d=await apiPost("/api/cues",payload);
    if(d?.success) toast(`Cue ${d.cue?.number} added`,"ok");
  }
  cancelCueEdit();
}

function cancelCueEdit(){editingCueId=null;const ed=document.getElementById("cue-editor");if(ed)ed.style.display="none";}
async function deleteCue(id){await apiDelete(`/api/cues/${id}`);toast("Cue deleted");}
async function fireJump(id){await apiPost("/api/transport/jump",{cue:id});toast("Jumped","ok");}
async function fireCueDirect(){await saveCueEdit();}

// ── Scheduler ─────────────────────────────────────────────────────
function updateSchedUI(sched){
  if(!sched) return;
  const btn=document.getElementById("sched-toggle-btn");
  const sb=document.getElementById("sb-sched");
  if(sched.running){
    if(btn){btn.textContent="⏸ STOP";btn.className="btn btn-primary btn-sm";}
    if(sb) sb.textContent="SCHED: RUNNING";
  } else {
    if(btn){btn.textContent="▶ START";btn.className="btn btn-outline btn-sm";}
    if(sb) sb.textContent="SCHED: OFF";
  }
  renderSchedList(sched.items||[]);
}

function updateSchedMode(){
  const mode=document.getElementById("sf-mode")?.value;
  const el=document.getElementById("sf-int-wrap");
  if(el) el.style.display=mode==="once"?"none":"block";
}

async function submitScheduleItem(){
  const mode=document.getElementById("sf-mode").value;
  const ctype=document.getElementById("sf-ctype").value;
  const raw=document.getElementById("sf-content").value.trim();
  const label=document.getElementById("sf-label").value.trim()||raw;
  let content={};
  if(ctype==="text") content={text:raw,font_size:14};
  else if(ctype==="animation") content={animation_id:raw};
  const d=await apiPost("/api/scheduler",{
    label,content_type:ctype,content,mode,
    duration:parseFloat(document.getElementById("sf-dur")?.value||"5"),
    interval:parseFloat(document.getElementById("sf-interval")?.value||"60"),
  });
  if(d?.success){toast("Scheduled","ok");document.getElementById("sf-content").value="";}
}

function renderSchedList(items){
  const list=document.getElementById("sched-list");
  if(!list) return;
  if(!items.length){list.innerHTML="<div style='font-family:var(--f-mono);font-size:0.65rem;color:var(--text-dim);padding:0.5rem'>No scheduled items</div>";return;}
  list.innerHTML=items.map(item=>{
    const c=item.content||{};const cs=c.text||c.animation_id||item.content_type;
    return`<div style="display:flex;align-items:center;gap:0.5rem;padding:5px 0;border-bottom:1px solid var(--surface-2);font-family:var(--f-mono);font-size:0.65rem">
      <span style="flex:1;color:var(--text)">${item.label||cs}</span>
      <span style="color:var(--text-dim)">${item.mode}</span>
      <span style="color:var(--text-dim)">${item.duration}s</span>
      <button class="btn btn-outline btn-sm btn-danger" onclick="apiDelete('/api/scheduler/${item.id}').then(()=>apiGet('/api/scheduler').then(d=>renderSchedList(d?.items||[])))">✕</button>
    </div>`;
  }).join("");
}

async function toggleScheduler(){
  const d=await apiGet("/api/status");
  await apiPost(d?.scheduler?.running?"/api/scheduler/stop":"/api/scheduler/start");
  toast(d?.scheduler?.running?"Scheduler stopped":"Scheduler started","ok");
}

// ── Text ──────────────────────────────────────────────────────────
async function sendText(){
  const text=document.getElementById("txt-msg")?.value?.trim();
  if(!text){toast("Enter a message","error");return;}
  const d=await apiPost("/api/display/text",{
    text,font_size:parseInt(document.getElementById("txt-size")?.value||"14"),
    x:parseInt(document.getElementById("txt-x")?.value||"0"),
    y:parseInt(document.getElementById("txt-y")?.value||"0"),
    scroll:document.getElementById("txt-scroll")?.value==="true",clear:true
  });
  if(d?.success) toast(document.getElementById("txt-scroll")?.value==="true"?"Scrolling…":"Text sent","ok");
}

async function previewVarText(){
  const text=document.getElementById("txt-msg")?.value;
  if(!text) return;
  const d=await apiPost("/api/variables/preview",{text});
  const out=document.getElementById("txt-preview");
  if(out) out.textContent="→ "+(d?.substituted||"");
}

// ── Image ─────────────────────────────────────────────────────────
async function uploadImage(){
  const input=document.getElementById("img-file");
  if(!input?.files[0]){toast("Choose a file first","error");return;}
  const form=new FormData();
  form.append("file",input.files[0]);
  form.append("threshold",document.getElementById("img-threshold")?.value||"128");
  form.append("brightness",document.getElementById("img-brightness")?.value||"1.0");
  form.append("contrast",document.getElementById("img-contrast")?.value||"1.0");
  form.append("dither",document.getElementById("img-dither")?.value||"none");
  form.append("scale",document.getElementById("img-scale")?.value||"fit");
  form.append("invert",document.getElementById("img-invert")?.checked?"true":"false");
  toast("Processing…","warn");
  try{
    const r=await fetch(`${API}/api/image/upload`,{method:"POST",body:form});
    const d=await r.json();
    if(d.success){
      _imageFrames=d.frames;
      renderImagePreview(d.frames[0].bitmap);
      const info=document.getElementById("img-info");
      if(info) info.textContent=`${d.frame_count} frame${d.frame_count>1?"s":""}  ${d.animated?"— animated":""}`; 
      toast(`Processed: ${d.frame_count} frame(s)`,"ok");
    } else toast(d.error||"Failed","error");
  } catch(e){toast("Upload failed","error");}
}

function renderImagePreview(bitmap){
  const canvas=document.getElementById("img-preview-canvas");
  if(!canvas||!bitmap) return;
  const DW=84,DH=42,DOT=4,GAP=1,step=DOT+GAP;
  canvas.width=DW*step+GAP;canvas.height=DH*step+GAP;
  const ctx=canvas.getContext("2d");
  ctx.fillStyle="#0a0a0a";ctx.fillRect(0,0,canvas.width,canvas.height);
  for(let r=0;r<DH;r++) for(let c=0;c<DW;c++){
    ctx.fillStyle=bitmap[r]&&bitmap[r][c]?"#f0eee8":"#161614";
    ctx.fillRect(c*step+GAP,r*step+GAP,DOT,DOT);
  }
}

async function sendImageToDisplay(){
  if(!_imageFrames.length){toast("Upload an image first","error");return;}
  const d=await apiPost("/api/image/display",{frames:_imageFrames,loop:parseInt(document.getElementById("img-loop")?.value||"1")});
  if(d?.success) toast(`Sending ${d.frames} frame(s)`,"ok");
}

async function addImageToCue(){
  if(!_imageFrames.length){toast("Upload an image first","error");return;}
  const label=document.getElementById("img-cue-label")?.value||"Image cue";
  const d=await apiPost("/api/cues",{label,content_type:"image",content:{frames:_imageFrames,loop:parseInt(document.getElementById("img-loop")?.value||"1")},duration:parseFloat(document.getElementById("img-dur")?.value||"10")});
  if(d?.success) toast(`Cue '${label}' added`,"ok");
}

// ── Pixel Editor ──────────────────────────────────────────────────
const PE={canvas:null,ctx:null,W:84,H:42,DOT:6,GAP:1,buf:null,tool:"pencil",drawing:false,drawVal:1,_ready:false};

function setupPixelEditor(){
  if(PE._ready) return;
  PE.canvas=document.getElementById("pe-canvas");
  if(!PE.canvas) return;
  PE.ctx=PE.canvas.getContext("2d");
  const step=PE.DOT+PE.GAP;
  PE.canvas.width=PE.W*step+PE.GAP;
  PE.canvas.height=PE.H*step+PE.GAP;
  PE.buf=Array.from({length:PE.H},()=>Array(PE.W).fill(0));
  peRender();
  PE.canvas.addEventListener("mousedown",e=>{PE.drawing=true;peApply(e);});
  PE.canvas.addEventListener("mousemove",e=>{if(PE.drawing)peApply(e);});
  PE.canvas.addEventListener("mouseup",()=>PE.drawing=false);
  PE.canvas.addEventListener("mouseleave",()=>PE.drawing=false);
  PE._ready=true;
}

function peDot(e){
  const rect=PE.canvas.getBoundingClientRect(),step=PE.DOT+PE.GAP;
  const sx=PE.canvas.width/rect.width,sy=PE.canvas.height/rect.height;
  return{col:Math.floor((e.clientX-rect.left)*sx/step),row:Math.floor((e.clientY-rect.top)*sy/step)};
}

function peApply(e){
  const{col,row}=peDot(e);
  if(col<0||col>=PE.W||row<0||row>=PE.H) return;
  if(e.type==="mousedown") PE.drawVal=PE.tool==="eraser"?0:(PE.buf[row][col]===1?0:1);
  if(PE.tool==="fill") peBucket(col,row,PE.buf[row][col],1-PE.buf[row][col]);
  else PE.buf[row][col]=PE.drawVal;
  peRender();
}

function peBucket(x,y,t,r){
  if(t===r) return;
  const s=[[x,y]];
  while(s.length){
    const[cx,cy]=s.pop();
    if(cx<0||cx>=PE.W||cy<0||cy>=PE.H||PE.buf[cy][cx]!==t) continue;
    PE.buf[cy][cx]=r;
    s.push([cx+1,cy],[cx-1,cy],[cx,cy+1],[cx,cy-1]);
  }
}

function peRender(){
  if(!PE.ctx) return;
  const step=PE.DOT+PE.GAP;
  PE.ctx.fillStyle="#0a0a0a";PE.ctx.fillRect(0,0,PE.canvas.width,PE.canvas.height);
  for(let r=0;r<PE.H;r++) for(let c=0;c<PE.W;c++){
    PE.ctx.fillStyle=PE.buf[r][c]?"#f0eee8":"#161614";
    PE.ctx.fillRect(c*step+PE.GAP,r*step+PE.GAP,PE.DOT,PE.DOT);
  }
}

function peSetTool(tool){
  PE.tool=tool;
  document.querySelectorAll(".pe-tool").forEach(b=>b.classList.toggle("active",b.dataset.tool===tool));
}

function peClear(){PE.buf=Array.from({length:PE.H},()=>Array(PE.W).fill(0));peRender();}
function peFillAll(){PE.buf=Array.from({length:PE.H},()=>Array(PE.W).fill(1));peRender();}
function peInvert(){PE.buf=PE.buf.map(r=>r.map(v=>1-v));peRender();}
async function pePush(){const d=await apiPost("/api/pixel/push",{buffer:PE.buf});if(d?.success)toast("Pushed to display","ok");}
async function peSyncFromDisplay(){
  const d=await apiGet("/api/buffer");
  if(d?.buffer){PE.buf=d.buffer.map(r=>r.map(v=>v?1:0));peRender();toast("Copied from display","ok");}
}
async function peAddToCue(){
  const label=document.getElementById("pe-cue-label")?.value||"Pixel cue";
  const dur=parseFloat(document.getElementById("pe-dur")?.value||"5");
  const d=await apiPost("/api/cues",{label,content_type:"image",content:{frames:[{bitmap:PE.buf,duration:0}],loop:1},duration:dur});
  if(d?.success) toast(`Cue '${label}' added`,"ok");
}

// ── Playlist ──────────────────────────────────────────────────────
function updatePlUI(pl){
  if(!pl) return;
  const sb=document.getElementById("sb-pl");
  if(sb) sb.textContent=`PLAYLIST: ${pl.running?"RUNNING ("+pl.mode+")":"OFF"}`;
  renderPlaylist(pl);
}

async function loadPlaylist(){
  const d=await apiGet("/api/playlist");
  if(d) renderPlaylist(d);
}

function renderPlaylist(pl){
  const list=document.getElementById("pl-list");
  if(!list) return;
  if(!pl.items?.length){list.innerHTML="<div style='font-family:var(--f-mono);font-size:0.65rem;color:var(--text-dim);padding:1rem;text-align:center'>Playlist empty</div>";return;}
  list.innerHTML=pl.items.map(item=>`
    <div class="pl-item${pl.current_item?.id===item.id?" playing":""}">
      <span class="pl-label">${item.label||"—"}</span>
      <span class="pl-type">${item.content_type}</span>
      <span class="pl-dur">${item.duration}s</span>
      <span class="pl-weight">×${item.weight}</span>
      <span style="font-family:var(--f-mono);font-size:0.55rem;color:var(--text-dim)">${item.play_count} plays</span>
      <button class="btn btn-outline btn-sm" onclick="apiPost('/api/playlist/move',{id:'${item.id}',direction:'up'}).then(loadPlaylist)">↑</button>
      <button class="btn btn-outline btn-sm" onclick="apiPost('/api/playlist/move',{id:'${item.id}',direction:'down'}).then(loadPlaylist)">↓</button>
      <button class="btn btn-outline btn-sm btn-danger" onclick="apiDelete('/api/playlist/${item.id}').then(loadPlaylist)">✕</button>
    </div>`).join("");
}

async function addPlaylistItem(){
  const type=document.getElementById("pl-type").value;
  const raw=document.getElementById("pl-content").value.trim();
  const label=document.getElementById("pl-label").value.trim()||raw;
  let content={};
  if(type==="text") content={text:raw,font_size:14};
  else if(type==="animation") content={animation_id:raw};
  const d=await apiPost("/api/playlist",{
    label,content_type:type,content,
    duration:parseFloat(document.getElementById("pl-dur")?.value||"5"),
    weight:parseFloat(document.getElementById("pl-weight")?.value||"1"),
  });
  if(d?.success){toast("Added to playlist","ok");loadPlaylist();}
}

async function startPlaylist(){
  const mode=document.getElementById("pl-mode").value;
  await apiPost("/api/playlist/start",{mode});
  toast("Playlist started: "+mode,"ok");
}

// ── Assets ────────────────────────────────────────────────────────
async function loadAssets(){
  const type=document.getElementById("asset-type-filter")?.value||"";
  const d=await apiGet("/api/assets"+(type?`?type=${type}`:""));
  renderAssets(d?.assets||[]);
}

async function searchAssets(){
  const q=document.getElementById("asset-search")?.value||"";
  if(!q){loadAssets();return;}
  const d=await apiGet(`/api/assets/search?q=${encodeURIComponent(q)}`);
  renderAssets(d?.assets||[]);
}

function renderAssets(assets){
  const grid=document.getElementById("asset-grid");
  if(!grid) return;
  if(!assets.length){grid.innerHTML="<div style='font-family:var(--f-mono);font-size:0.65rem;color:var(--text-dim);padding:1rem'>No assets</div>";return;}
  grid.innerHTML=assets.map(a=>`
    <div class="asset-card" onclick="loadAsset('${a.id}')">
      <div class="asset-name">${a.name}</div>
      <div class="asset-type">${a.type}</div>
      <div class="asset-tags">${(a.tags||[]).map(t=>`<span class="asset-tag">${t}</span>`).join("")}</div>
    </div>`).join("");
}

async function loadAsset(id){
  const a=await apiGet(`/api/assets/${id}`);
  if(!a) return;
  if(a.type==="text_preset"&&a.data?.text){
    const el=document.getElementById("txt-msg");
    if(el) el.value=a.data.text;
    toast("Asset loaded into text editor","ok");
  } else if(a.type==="animation"&&a.data?.animation_id){
    await apiPost("/api/animations/run",{name:a.data.animation_id,options:a.data.params||{}});
    toast("Playing: "+a.name,"ok");
  }
}

async function saveCurrentAsAsset(){
  const name=prompt("Asset name:");
  if(!name) return;
  const d=await apiGet("/api/buffer");
  if(!d?.buffer) return;
  await apiPost("/api/assets",{name,type:"image",data:{frames:[{bitmap:d.buffer,duration:0}]},tags:["display"]});
  toast("Saved as asset: "+name,"ok");
  loadAssets();
}

// ── Variables ─────────────────────────────────────────────────────
async function loadVariablesConfig(){
  const d=await apiGet("/api/variables");
  if(!d?.config) return;
  const c=d.config;
  ["var-api-key","var-city","var-units","var-rss-url","var-update"].forEach(id=>{
    const el=document.getElementById(id);
    if(!el) return;
    const key=id.replace("var-","").replace(/-/g,"_").replace("api_key","weather_api_key").replace("rss_url","rss_url").replace("update","update_interval").replace("city","weather_city").replace("units","weather_units");
    if(c[key]!==undefined) el.value=c[key];
  });
  updateVariablesDisplay(d.values);
}

async function saveVariablesConfig(){
  const cfg={
    weather_api_key:document.getElementById("var-api-key")?.value||"",
    weather_city:document.getElementById("var-city")?.value||"",
    weather_units:document.getElementById("var-units")?.value||"imperial",
    rss_url:document.getElementById("var-rss-url")?.value||"",
    update_interval:parseInt(document.getElementById("var-update")?.value||"300"),
  };
  const d=await apiPost("/api/variables/config",cfg);
  if(d?.success){toast("Variables saved","ok");refreshVariables();}
}

async function refreshVariables(){
  const d=await apiGet("/api/variables");
  if(d?.values) updateVariablesDisplay(d.values);
}

async function refreshVariablesMonitor(){
  const d=await apiGet("/api/variables/values");
  if(d) updateVariablesDisplay(d);
}

function updateVariablesDisplay(values){
  const grid=document.getElementById("var-grid");
  if(!grid||!values) return;
  grid.innerHTML=Object.entries(values).filter(([k])=>!k.startsWith("rss_"))
    .map(([k,v])=>`<div class="var-row"><span class="var-token">{${k}}</span><span class="var-val">${v}</span></div>`).join("");
}

async function previewVarText(){
  const text=document.getElementById("txt-msg")?.value;
  if(!text) return;
  const d=await apiPost("/api/variables/preview",{text});
  const out=document.getElementById("txt-preview");
  if(out) out.textContent="→ "+(d?.substituted||"");
}

async function previewVarSetup(){
  const text=document.getElementById("var-test")?.value;
  if(!text) return;
  const d=await apiPost("/api/variables/preview",{text});
  const out=document.getElementById("var-test-out");
  if(out) out.textContent="→ "+(d?.substituted||"");
}

// ── Effects ───────────────────────────────────────────────────────
const FX_REGISTRY={
  flicker:[{id:"rate",label:"Rate",min:0.01,max:0.3,step:0.01,default:0.05}],
  pulse:  [{id:"speed",label:"Speed",min:0.1,max:5,step:0.1,default:0.5}],
  chase:  [{id:"speed",label:"Speed",min:0.5,max:5,step:0.5,default:1}],
  scanline:[{id:"speed",label:"Speed",min:0.2,max:3,step:0.2,default:0.5}],
  noise:  [{id:"density",label:"Density",min:0.01,max:0.3,step:0.01,default:0.05}],
};

function buildFxParams(){
  const type=document.getElementById("fx-type")?.value||"flicker";
  updateFxParams(type);
}

function updateFxParams(){
  const type=document.getElementById("fx-type")?.value||"flicker";
  const div=document.getElementById("fx-params");
  if(!div) return;
  const params=FX_REGISTRY[type]||[];
  div.innerHTML=params.map(p=>`
    <div style="margin-bottom:6px">
      <label class="field-label">${p.label}</label>
      <div class="range-wrap">
        <input type="range" id="fx-p-${p.id}" min="${p.min}" max="${p.max}" step="${p.step}" value="${p.default}">
        <span class="range-val" id="fx-v-${p.id}">${p.default}</span>
      </div>
    </div>`).join("");
  params.forEach(p=>{
    const inp=document.getElementById(`fx-p-${p.id}`);
    const val=document.getElementById(`fx-v-${p.id}`);
    if(inp&&val) inp.addEventListener("input",()=>val.textContent=inp.value);
  });
}

async function addEffect(){
  const type=document.getElementById("fx-type")?.value||"flicker";
  const name=document.getElementById("fx-name")?.value||"fx1";
  const params=FX_REGISTRY[type]||[];
  const opts={};
  params.forEach(p=>{const el=document.getElementById(`fx-p-${p.id}`);if(el)opts[p.id]=parseFloat(el.value);});
  await apiPost("/api/effects",{name,type,params:opts});
  toast(`Effect '${name}' added`,"ok");
  loadFxList();
}

async function loadFxList(){
  const d=await apiGet("/api/effects");
  const list=document.getElementById("fx-list");
  if(!list||!d) return;
  const active=d.effects||{};
  if(!Object.keys(active).length){list.innerHTML="<div style='font-family:var(--f-mono);font-size:0.65rem;color:var(--text-dim)'>No active effects</div>";return;}
  list.innerHTML=Object.entries(active).map(([name,cfg])=>`
    <div class="effect-row">
      <span class="effect-name">${name}</span>
      <span class="effect-type">${cfg.type}</span>
      <button class="btn btn-outline btn-sm btn-danger" onclick="apiDelete('/api/effects/${name}').then(loadFxList)">✕</button>
    </div>`).join("");
}

// ── Shows ─────────────────────────────────────────────────────────
async function saveShow(){
  const name=document.getElementById("show-name")?.value?.trim();
  if(!name){toast("Enter a show name","error");return;}
  const d=await apiPost("/api/shows/save",{name});
  if(d?.success){toast(`Show '${name}' saved`,"ok");loadShowsList();}
}

async function loadShowsList(){
  const d=await apiGet("/api/shows");
  const list=document.getElementById("shows-list");
  if(!list) return;
  if(!d?.shows?.length){list.innerHTML="<div style='font-family:var(--f-mono);font-size:0.65rem;color:var(--text-dim)'>No saved shows</div>";return;}
  list.innerHTML=d.shows.map(s=>`
    <div style="display:flex;align-items:center;gap:0.5rem;padding:5px 0;border-bottom:1px solid var(--surface-2);font-family:var(--f-mono);font-size:0.65rem">
      <span style="flex:1;color:var(--text)">${s.name}</span>
      <span style="color:var(--text-dim)">${s.cues} cues</span>
      <button class="btn btn-outline btn-sm" onclick="loadShow('${s.name}')">LOAD</button>
      <button class="btn btn-outline btn-sm btn-danger" onclick="apiDelete('/api/shows/${s.name}').then(loadShowsList)">✕</button>
    </div>`).join("");
  // Also update webhook cue list
  const wcues=document.getElementById("webhook-cues");
  if(wcues){
    const cd=await apiGet("/api/cues");
    if(cd?.cues?.length) wcues.innerHTML=cd.cues.map(c=>`<div>POST /api/webhook/${encodeURIComponent(c.label)}</div>`).join("");
  }
}

async function loadShow(name){
  const d=await apiPost("/api/shows/load",{name});
  if(d?.success) toast(`Show '${name}' loaded`,"ok");
  else toast(d?.error||"Failed","error");
}

// ── Monitor ───────────────────────────────────────────────────────
function buildPanelHealthGrid(){
  const grid=document.getElementById("panel-health-grid");
  if(!grid) return;
  grid.innerHTML="";
  for(let row=1;row<=3;row++) for(let col=1;col<=3;col++){
    const cell=document.createElement("div");
    cell.className="panel-cell";
    cell.id=`panel-${col}-${row}`;
    cell.innerHTML=`<span class="p-addr">${col}×${row}</span>TOP<br>BOTTOM`;
    grid.appendChild(cell);
  }
}

async function refreshMonitor(){
  const d=await apiGet("/api/status");
  if(!d) return;
  const stats=document.getElementById("mon-stats");
  if(stats) stats.innerHTML=[
    `Connected: ${d.connected?"YES":"NO"}`,
    `Port: ${d.port}`,
    `Display: ${d.width}×${d.height}`,
    `Cue Engine: ${d.cue_engine?.state||"—"}`,
    `Scheduler: ${d.scheduler?.running?"RUNNING":"OFF"}`,
    `Playlist: ${d.playlist?.running?"RUNNING ("+d.playlist.mode+")":"OFF"}`,
    `Effects: ${Object.keys(d.effects?.effects||{}).join(", ")||"None"}`,
    `Timestamp: ${d.timestamp?.slice(11,19)||"—"}`,
  ].map(s=>`<div>${s}</div>`).join("");
  refreshVariablesMonitor();
}

// ── Toast ─────────────────────────────────────────────────────────
function toast(msg,type=""){
  const c=document.getElementById("toasts");
  const el=document.createElement("div");
  el.className="toast"+(type?" "+type:"");
  el.textContent=msg;
  c.appendChild(el);
  setTimeout(()=>el.remove(),3000);
}
