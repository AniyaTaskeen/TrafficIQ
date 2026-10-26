"use strict";
const LANES = ["North", "East", "South", "West"];
const COLORS = ["#38d5e7", "#6494fa", "#3bd3ae", "#af96ff"];
const $ = id => document.getElementById(id);
const text = (id, value) => { if ($(id)) $(id).textContent = value; };
function toast(message, error = false) {
  const el = document.createElement("div"); el.className = "toast" + (error ? " error" : "");
  el.textContent = message; $("toastRegion").append(el); setTimeout(() => el.remove(), 6500);
}
async function api(url, options = {}) {
  let response;
  try { response = await fetch(url, options); } catch (_) { throw new Error("Cannot reach TrafficIQ. Check that the Flask server is running."); }
  let data; try { data = await response.json(); } catch (_) { throw new Error("The server returned an unexpected response. Please try again."); }
  if (!response.ok) throw new Error(data.error || "The request failed.");
  return data;
}
const post = (url, body) => api(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
function element(tag, className, content) { const el = document.createElement(tag); if(className) el.className=className; if(content !== undefined) el.textContent=content; return el; }
function tableRow(values) { const tr=element("tr"); values.forEach(v=>tr.append(element("td",null,v))); return tr; }
function renderDecisions(result) {
  const container = $("decisionList"); if(!container || !result) return;
  container.replaceChildren();
  result.plan.forEach(p=>{const item=element("div","decision-item");const heading=element("div","decision-title");heading.append(element("span",null,p.lane+" approach"),element("span",null,p.green+"s green"));item.append(heading,element("p",null,p.explanation));container.append(item);});
  const alerts=$("congestionAlerts"); if(alerts){alerts.replaceChildren();result.plan.filter(p=>p.density==="High").forEach(p=>alerts.append(element("div","congestion-alert",`Heavy traffic · ${p.lane}: ${p.live} vehicles. Consider reviewing this approach.`)));}
  LANES.forEach(l=>text("mapCount-"+l, result.detections[l].count+" vehicles"));
}
function renderActivity(items) {
  const container=$("activityList"); if(!container) return; container.replaceChildren();
  if(!items.length){container.append(element("p","empty-inline","No activity yet. Add a traffic image to get started."));return;}
  items.slice(0,6).forEach(a=>{const row=element("div","activity-item"),body=element("div");body.append(element("p",null,a.message),element("small",null,a.created_at));row.append(element("span"),body);container.append(row);});
}
let signalSnapshot=null, signalRequest=false, signalStale=false;
function renderController(s) {
  signalSnapshot=s;
  text("simulationState",s.state.toUpperCase());text("activeSignal",s.active_lane||"All red");
  text("trafficStatus",s.state==="stopped"?"Simulation stopped":`${s.state} · ${s.phase}`);
  text("phaseLabel",s.active_lane?`${s.active_lane.toUpperCase()} ${s.phase.toUpperCase()}`:"ALL RED");
  text("phaseTimer",s.state==="stopped"?"—":s.remaining+"s");text("phaseCaption",s.state==="stopped"?"Ready when you are":s.state==="paused"?"Simulation paused":"Clearing traffic safely");
  text("nextLane",s.next_lane);text("cycleLength",s.cycle?s.cycle+"s":"—");
  LANES.forEach(l=>{if($("sig-"+l))$("sig-"+l).className="traffic-light state-"+s.signals[l];if($("map-"+l))$("map-"+l).classList.toggle("active",s.active_lane===l);if($("flow-"+l))$("flow-"+l).classList.toggle("active",s.active_lane===l&&s.phase==="green");});
  if($("startSim")){ $("startSim").disabled=!s.run_id||s.state==="running";$("startSim").textContent=s.state==="paused"?"▶ Resume":"▶ Start";$("pauseSim").disabled=s.state!=="running";$("resetSim").disabled=!s.run_id;$("simSpeed").disabled=!s.run_id;$("simSpeed").value=s.speed; }
}
async function refreshController() {
  if(!$("startSim")||signalRequest)return;signalRequest=true;
  try{const s=await api("/api/controller");renderController(s);if(signalStale){signalStale=false;toast("Controller connection restored.");}window.dispatchEvent(new CustomEvent("controllerupdate",{detail:s}));}
  catch(e){if(!signalStale){toast(e.message,true);signalStale=true;}text("simulationState","OFFLINE");text("activeSignal","Offline");text("trafficStatus","Connection lost");text("phaseTimer","—");text("phaseLabel","OFFLINE");text("phaseCaption","Connection lost");["startSim","pauseSim","resetSim","simSpeed"].forEach(id=>{if($(id))$(id).disabled=true;});LANES.forEach(l=>{if($("sig-"+l))$("sig-"+l).className="traffic-light";$("map-"+l)?.classList.remove("active");$("flow-"+l)?.classList.remove("active");});}
  finally{signalRequest=false;}
}
async function control(action, speed) {
  try{renderController(await post("/api/controller",{action,speed}));}catch(e){toast(e.message,true);}
}
if($("startSim")){
  $("startSim").onclick=()=>control(signalSnapshot?.state==="paused"?"resume":"start");$("pauseSim").onclick=()=>control("pause");$("resetSim").onclick=()=>control("reset");$("simSpeed").onchange=e=>control("speed",Number(e.target.value));
  refreshController();setInterval(refreshController,250);
}
document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>$(b.dataset.close).close());
text("topDate",new Date().toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"}));
api("/api/health").then(h=>{const status=$("engineStatus");status.replaceChildren(element("span","status-dot"),document.createTextNode(h.detector_installed?"YOLO engine ready":"Detection setup needed"));if(!h.detector_installed)status.title=h.message;}).catch(()=>text("engineStatus","Server unavailable"));
