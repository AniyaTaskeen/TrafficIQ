"use strict";
const charts={};
function chart(id,type,labels,datasets,extra={}){
  if(charts[id])charts[id].destroy();
  const scales=type==="doughnut"?{}:{x:{grid:{color:"#26364a55"},ticks:{color:"#8095b0",font:{size:10}}},y:{beginAtZero:true,grid:{color:"#26364a66"},ticks:{color:"#8095b0",precision:0,font:{size:9}}}};
  charts[id]=new Chart($(id),{type,data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,animation:{duration:350},scales,plugins:{legend:{display:type==="line"||type==="doughnut",position:"bottom",labels:{color:"#a6b8d0",padding:20,boxWidth:9,font:{size:10}}},tooltip:{backgroundColor:"#1a2b42",padding:12}},...extra}});
}
async function refreshAnalytics(){
  const btn=$("refreshAnalytics");btn.disabled=true;btn.textContent="↻ Refreshing…";
  try{
    const data=await api("/api/analytics"),r=data.latest;$("analyticsEmpty").hidden=!!r;
    text("analyticsTotal",r?.total??"—");text("analyticsBusiest",r?.busiest??"—");text("analyticsGreen",r?r.average_green+"s":"—");text("analyticsSessions",data.sessions);
    text("analyticsTimestamp",r?`Session #${r.run_id} · ${r.created_at} · ${r.mode}`:"Awaiting analysis");
    $("analyticsRows").replaceChildren(...(r?r.plan.map(p=>tableRow([p.lane,p.live,p.categories.car,p.categories.motorcycle,p.categories.bus,p.categories.truck,p.density,p.green+" s"])):[tableRow(["No image sessions yet. Analyze four lane images to begin."])]));
    if(typeof Chart==="undefined")throw new Error("Chart.js could not load. Refresh the page or check static/vendor/chart.umd.js.");
    const plan=r?.plan||[],counts=plan.map(p=>p.live),greens=plan.map(p=>p.green);
    chart("countsChart","bar",LANES,[{label:"Detected vehicles",data:counts,backgroundColor:COLORS.map(c=>c+"bb"),borderColor:COLORS,borderWidth:1,borderRadius:6,maxBarThickness:65}]);
    chart("greensChart","bar",LANES,[{label:"Green seconds",data:greens,backgroundColor:COLORS.map(c=>c+"88"),borderColor:COLORS,borderWidth:1,borderRadius:6,maxBarThickness:65}]);
    chart("typesChart","doughnut",["Cars","Motorcycles","Buses","Trucks"],[{data:r?[r.categories.car,r.categories.motorcycle,r.categories.bus,r.categories.truck]:[],backgroundColor:COLORS,borderColor:"#111b2a",borderWidth:5,hoverOffset:7}],{cutout:"73%"});
    if(r)text("densityCaption",`Medium ≥ ${r.settings.medium_threshold} · High ≥ ${r.settings.high_threshold} detected vehicles`);
    chart("densityChart","bar",LANES,[{label:"Detected vehicles",data:counts,backgroundColor:plan.map(p=>p.density==="High"?"#fa7684":p.density==="Medium"?"#f4c36d":"#3bd3ae"),borderRadius:5,maxBarThickness:65}]);
    chart("historyChart","line",data.history.map(h=>"#"+h.run_id),LANES.map((l,i)=>({label:l,data:data.history.map(h=>h.counts[l]),borderColor:COLORS[i],backgroundColor:COLORS[i],borderWidth:2,pointRadius:4,tension:.2})));
    // Empty-state text covers zero-detection and no-session charts without invented values.
    for(const id of ["countsChart","greensChart","typesChart","densityChart","historyChart"]){
      const wrap=$(id).parentElement;let empty=wrap.querySelector(".chart-empty");if(empty)empty.remove();
      if(!r||(id==="typesChart"&&r.total===0)){empty=element("div","chart-empty",r?"No vehicles detected in this session":"Awaiting your first image analysis");wrap.append(empty);}
    }
  }catch(e){toast(e.message,true);}finally{btn.disabled=false;btn.textContent="↻ Refresh";}
}
$("refreshAnalytics").onclick=refreshAnalytics;refreshAnalytics();
