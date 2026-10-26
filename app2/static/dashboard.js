"use strict";
let detections={}, latestSession=null, busy=false, cameraStream=null, cameraLane=null, sessionDirty=false;
let currentSettings={medium_threshold:10,high_threshold:20};
function density(count){return count>=currentSettings.high_threshold?"High":count>=currentSettings.medium_threshold?"Medium":"Low";}
function readyState(){
  const ready=LANES.filter(l=>detections[l]).length;text("readyCount",`${ready} / 4 ready`);
  $("analyzeBtn").disabled=busy||ready!==4||!sessionDirty;
  text("analyzeBtn",busy?"Processing…":ready===4&&!sessionDirty?"Timings up to date":"Calculate timings →");
  text("analyzeHint",busy?"Processing actual image data…":ready===4?(sessionDirty?"All directions ready. Calculate a new adaptive plan.":"Your signal plan is ready. Start the intersection simulation."):"Add all four images to calculate adaptive timings.");
  document.querySelectorAll("[data-upload],[data-camera],[data-file]").forEach(b=>b.disabled=busy);
}
function renderDetection(lane,d){
  $("slot-"+lane).querySelector(".upload-empty").hidden=true;
  const img=$("preview-"+lane);img.src=d.annotated_url;img.hidden=false;$("imageLabel-"+lane).hidden=false;
  text("count-"+lane,d.count);text("uploadLabel-"+lane,"Replace image");
  const level=density(d.count);text("density-"+lane,level);$("density-"+lane).className="badge density "+level;
  const plural={car:"cars",motorcycle:"motorcycles",bus:"buses",truck:"trucks"};
  text("categories-"+lane,Object.entries(d.categories).map(([k,v])=>`${v} ${v===1?k:plural[k]}`).join(" · "));
  document.querySelector(`[data-compare="${lane}"]`).disabled=false;
}
function applySession(result){
  latestSession=result;detections={...result.detections};sessionDirty=false;
  currentSettings=result.settings;LANES.forEach(l=>renderDetection(l,detections[l]));
  text("totalVehicles",result.total);text("busiestLane",result.busiest);text("quietestLane",result.quietest);
  text("busiestDetail",detections[result.busiest].count+" detected vehicles");text("quietestDetail",detections[result.quietest].count+" detected vehicles");
  result.plan.forEach(p=>text("green-"+p.lane,p.green+" s"));renderDecisions(result);
  text("sessionNote",`Session #${result.run_id} · ${result.created_at} · ${result.mode} timings. Counts stay unchanged until a new image is analyzed.`);
  readyState();refreshController();
}
async function saveSession(){
  const ids=Object.fromEntries(LANES.map(l=>[l,detections[l]?.id]));
  const result=await post("/api/analyze",{detections:ids});applySession(result);toast(`Session saved · ${result.total} vehicles. Signal plan ready.`);
  renderActivity((await api("/api/dashboard")).activity);
}
async function analyzeImages(){
  if(busy||LANES.some(l=>!detections[l]))return;busy=true;readyState();
  try{await saveSession();}catch(e){toast(e.message,true);}finally{busy=false;readyState();}
}
async function uploadImage(lane,file){
  if(!file||busy)return;
  if(!/^image\/(jpeg|png|webp)$/.test(file.type)){toast("Choose a JPEG, PNG, or WebP image.",true);return;}
  if(file.size>12*1024*1024){toast("Image is too large. Maximum: 12 MB.",true);return;}
  busy=true;readyState();$("error-"+lane).hidden=true;$("loader-"+lane).hidden=false;
  // Preview candidate while keeping the previous confirmed detection on error.
  const previewUrl=URL.createObjectURL(file),img=$("preview-"+lane);img.src=previewUrl;img.hidden=false;$("slot-"+lane).querySelector(".upload-empty").hidden=true;
  const form=new FormData();form.append("image",file);
  try{
    const d=await api("/api/detect/"+lane,{method:"POST",body:form});detections[lane]=d;sessionDirty=true;renderDetection(lane,d);
    LANES.forEach(l=>text("green-"+l,"Pending"));text("sessionNote","Images have changed. The controller still uses the last saved session until a new plan is calculated.");
    text("totalVehicles",Object.values(detections).reduce((sum,x)=>sum+x.count,0));
    text("busiestLane","Pending");text("quietestLane","Pending");text("busiestDetail","Recalculating plan");text("quietestDetail","Recalculating plan");
    toast(`${lane} image: ${d.count} vehicles detected.`);
    if(LANES.every(l=>detections[l]))await saveSession();
    else renderActivity((await api("/api/dashboard")).activity);
  }catch(e){
    text("error-"+lane,e.message);$("error-"+lane).hidden=false;toast(e.message,true);
    if(detections[lane])renderDetection(lane,detections[lane]);else{img.hidden=true;$("slot-"+lane).querySelector(".upload-empty").hidden=false;}
  }finally{URL.revokeObjectURL(previewUrl);busy=false;$("loader-"+lane).hidden=true;$("file-"+lane).value="";readyState();}
}
document.querySelectorAll("[data-upload]").forEach(b=>b.onclick=()=>$("file-"+b.dataset.upload).click());
document.querySelectorAll("[data-file]").forEach(f=>f.onchange=()=>uploadImage(f.dataset.file,f.files[0]));
document.querySelectorAll(".lane-card").forEach(card=>{card.ondragover=e=>{e.preventDefault();if(!busy)card.classList.add("dragging");};card.ondragleave=()=>card.classList.remove("dragging");card.ondrop=e=>{e.preventDefault();card.classList.remove("dragging");uploadImage(card.dataset.lane,e.dataTransfer.files[0]);};});
document.querySelectorAll("[data-compare]").forEach(b=>b.onclick=()=>{
  const lane=b.dataset.compare,d=detections[lane];if(!d)return;
  text("compareTitle",lane+" approach");$("compareOriginal").src=d.original_url;$("compareAnnotated").src=d.annotated_url;
  text("compareDetails",`${d.count} vehicles · ${Math.round(d.confidence*100)}% confidence threshold · ${d.model} · ${d.created_at}`);$("compareDialog").showModal();
});
$("analyzeBtn").onclick=analyzeImages;
function closeCamera(){if(cameraStream)cameraStream.getTracks().forEach(t=>t.stop());cameraStream=null;$("cameraVideo").srcObject=null;$("captureBtn").disabled=true;if($("cameraDialog").open)$("cameraDialog").close();}
async function openCamera(lane){
  cameraLane=lane;closeCamera();text("cameraTitle",`Capture ${lane} traffic image`);
  if(!navigator.mediaDevices?.getUserMedia){toast("Use your device's image picker to capture a photo.");$("cameraFallback").click();return;}
  $("cameraDialog").showModal();
  try{const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"},width:{ideal:1920}},audio:false});
    if(!$("cameraDialog").open){stream.getTracks().forEach(t=>t.stop());return;}cameraStream=stream;$("cameraVideo").srcObject=stream;await $("cameraVideo").play();$("captureBtn").disabled=false;
  }catch(e){closeCamera();toast(e.name==="NotAllowedError"?"Camera access was denied. Allow camera permission or upload an image.":"No usable camera found. Upload an image or use your device camera picker.",true);$("cameraFallback").click();}
}
document.querySelectorAll("[data-camera]").forEach(b=>b.onclick=()=>openCamera(b.dataset.camera));
$("cameraClose").onclick=closeCamera;$("cameraDialog").addEventListener("close",closeCamera);window.addEventListener("pagehide",closeCamera);
$("cameraFallback").onchange=e=>{uploadImage(cameraLane,e.target.files[0]);e.target.value="";};
$("captureBtn").onclick=()=>{const v=$("cameraVideo");if(!v.videoWidth)return;const canvas=document.createElement("canvas");canvas.width=v.videoWidth;canvas.height=v.videoHeight;canvas.getContext("2d").drawImage(v,0,0);const lane=cameraLane;canvas.toBlob(blob=>{closeCamera();if(blob)uploadImage(lane,new File([blob],"camera.jpg",{type:"image/jpeg"}));},"image/jpeg",.92);};
let activityTick=0;
window.addEventListener("controllerupdate",async e=>{
  // Other tabs can change the current plan. Never silently discard pending images.
  if(!busy&&!sessionDirty&&e.detail.run_id&&(e.detail.run_id!==latestSession?.run_id||e.detail.revision!==latestSession?.revision)){try{const data=await api("/api/dashboard");if(data.latest)applySession(data.latest);}catch(_){} }
  if(++activityTick%24===0){try{renderActivity((await api("/api/dashboard")).activity);}catch(_){} }
});
(async()=>{try{const data=await api("/api/dashboard");currentSettings=data.settings;if(data.latest)applySession(data.latest);
  for(const lane of LANES){const d=data.draft?.[lane];if(d&&d.id!==detections[lane]?.id){detections[lane]=d;sessionDirty=true;renderDetection(lane,d);}}
  if(sessionDirty){LANES.forEach(l=>text("green-"+l,"Pending"));text("sessionNote","Pending lane images restored. Calculate timings when all four are ready. The controller uses the last saved session.");text("totalVehicles",Object.values(detections).reduce((sum,d)=>sum+d.count,0));}
  renderActivity(data.activity);renderController(data.controller);}catch(e){toast(e.message,true);}finally{readyState();}})();
