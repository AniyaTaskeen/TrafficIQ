"use strict";
const settingKeys=["confidence","min_green","max_green","medium_threshold","high_threshold"];
$("confidence").oninput=()=>text("confidenceOutput",Math.round(Number($("confidence").value)*100)+"%");
$("settingsForm").onsubmit=async e=>{e.preventDefault();const button=$("saveSettings");button.disabled=true;button.textContent="Saving…";
  try{const data=Object.fromEntries(settingKeys.map(k=>[k,Number($(k).value)]));await post("/api/settings",data);toast("Settings saved. Automatic timings updated; simulation stopped.");}catch(e){toast(e.message,true);}finally{button.disabled=false;button.textContent="Save settings";}
};
(async()=>{try{const settings=await api("/api/settings");settingKeys.forEach(k=>$(k).value=settings[k]);$("confidence").oninput();$("saveSettings").disabled=false;}catch(e){toast(e.message,true);}})();
