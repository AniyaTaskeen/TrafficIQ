"use strict";
let planResult=null,loadingPlan=false;
function renderPlan(result,settings){
  planResult=result;if(!result)return;
  renderDecisions(result);text("modeBadge",result.mode.toUpperCase());$("timingMode").value=result.mode;
  text("planSummary",`Session #${result.run_id} · ${result.cycle}s full cycle`);
  $("planRows").replaceChildren(...result.plan.map(p=>tableRow([p.lane,p.live,p.share+"%",p.density,p.green+" s",result.yellow+" s",result.all_red+" s"])));
  result.plan.forEach(p=>{const input=$("manual-"+p.lane);input.value=p.green;input.min=settings.min_green;input.max=settings.max_green;});
  $("applyTimings").disabled=false;setManual();
}
function setManual(){LANES.forEach(l=>$("manual-"+l).disabled=$("timingMode").value!=="manual");}
$("timingMode").onchange=setManual;
$("timingForm").onsubmit=async e=>{e.preventDefault();if(!planResult)return;$("applyTimings").disabled=true;
  try{const mode=$("timingMode").value,greens=Object.fromEntries(LANES.map(l=>[l,Number($("manual-"+l).value)]));const result=await post("/api/timings",{mode,greens,run_id:planResult.run_id});renderPlan(result,result.settings);await refreshController();toast("Timings applied. Simulation reset to all red.");}catch(e){toast(e.message,true);}finally{$("applyTimings").disabled=false;}
};
async function loadPlan(){if(loadingPlan)return;loadingPlan=true;try{const d=await api("/api/dashboard");renderPlan(d.latest,d.settings);}catch(e){toast(e.message,true);}finally{loadingPlan=false;}}
window.addEventListener("controllerupdate",e=>{if(e.detail.run_id!==planResult?.run_id||e.detail.revision!==planResult?.revision)loadPlan();});loadPlan();
