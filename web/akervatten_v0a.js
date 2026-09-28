/* AKERVATTEN_WEB_UI_V0A */
(function(){
"use strict";
const cfg=window.AKERVATTEN_WEB_CONFIG||{};
const FILES=cfg.files||{};
const REGIONAL=cfg.regional||{};
const cache={},loads={},decoded={};
let currentMunicipality="",currentData=null,currentWaterLayer="mark_torka";
let regionalLayer=null,regionalToken=0;
const SCORE_COLORS={
 mark_torka:["#edf2e5","#ddd9a6","#d9b56c","#bd7b4e","#7e423b"],
 mark_vata:["#f0eee4","#d9e6df","#a9d0c7","#6aa7ad","#356a86"],
 small_gw:["#f0eee4","#dce8df","#b8d5c2","#80ad98","#487a70"],
 gw_drought:["#f1eee5","#e5d8b5","#d4b076","#ad765b","#78454c"],
 sw_drought:["#f0eee5","#dcd9c1","#b9b7a1","#7d8591","#505a70"]
};
const BANDS=["Mycket låg","Låg","Måttlig","Hög","Mycket hög"];
const META={
 mark_torka:{title:"MarkTorka",hint:"Relativ strukturell torkkänslighet i själva åkern · sand + topografiskt våthetsindex.",regional:false},
 mark_vata:{title:"MarkVäta",hint:"Relativ strukturell våthetsbenägenhet · lera/TWI samt separat organisk-jord-signal.",regional:false},
 small_gw:{title:"Små grundvattenmagasin",hint:"Översiktlig relativ SGU-indikator för lokal tillgång i små magasin. Inte brunnskapacitet.",regional:false},
 gw_drought:{title:"GrundvattenTorka · historik",hint:"Historisk torkkänslighet i SGU-HYPE-området. Polygonen är regional, inte en fältegenskap.",regional:"groundwater_history"},
 large_gw:{title:"Stora grundvattenmagasin",hint:"SGU:s magasinsdelområden och kartlagda kapacitetsklasser. Ingen 0–100-score och inget tillståndsbesked.",regional:"large_groundwater"},
 sw_drought:{title:"YtvattenTorka · historik",hint:"Historisk lågflödeskänslighet i S-HYPE-avrinningsområdet. Polygonen är regional.",regional:"surfacewater_history"}
};

function decode(data,fieldId){
 const c=decoded[data.municipality]||(decoded[data.municipality]={});
 if(c[fieldId])return c[fieldId];
 const raw=(data.fields||{})[fieldId];if(!raw)return null;
 const row={};
 data.columns.forEach(function(name,i){const d=(data.dictionaries||{})[name],v=raw[i];row[name]=d?d[v]:v});
 c[fieldId]=row;return row;
}
function record(p){if(!currentData||currentMunicipality!==p.kommun)return null;return decode(currentData,p.id)}
function loadSidecar(name){
 if(cache[name]){currentMunicipality=name;currentData=cache[name];return Promise.resolve(currentData)}
 if(loads[name])return loads[name];
 const file=FILES[name];if(!file)return Promise.reject(new Error("ÅkerVatten-sidecar saknas"));
 loads[name]=fetch(file,{cache:"no-cache"}).then(function(r){if(!r.ok)throw new Error("ÅkerVatten HTTP "+r.status);return r.json()}).then(function(data){
  if(data.schema_version!=="akervatten-web-field-v0a"||data.municipality!==name||!data.fields||Object.keys(data.fields).length!==data.field_count)throw new Error("Ogiltig ÅkerVatten-payload");
  cache[name]=data;currentMunicipality=name;currentData=data;return data;
 }).finally(function(){delete loads[name]});
 return loads[name];
}
function scoreOf(r,name){return r&&r[name]!=null&&Number.isFinite(Number(r[name]))?Number(r[name]):null}
function band(v){if(v==null)return "saknas";return BANDS[Math.max(0,Math.min(4,Math.floor(v===100?4:v/20)))]}
function scoreColor(name,v){
 if(v==null)return "#c3c7c3";
 const colors=SCORE_COLORS[name]||SCORE_COLORS.mark_torka;
 return colors[Math.max(0,Math.min(4,Math.floor(v===100?4:v/20)))];
}
function escText(v){return esc(v==null?"":String(v))}
function scoreText(v){return v==null?"saknas":fmt(v,0)+" · "+band(v)}
function capColor(p){
 const lo=Number(p.withdrawal_lower_lps),hi=Number(p.withdrawal_upper_lps);
 if(!Number.isFinite(lo)&&!Number.isFinite(hi))return "#aeb3b0";
 const ref=Number.isFinite(hi)?hi:lo;
 if(ref<=.2)return "#e5e1d4";
 if(ref<=1)return "#c7d7cf";
 if(ref<=5)return "#95b9aa";
 if(ref<=25)return "#638f84";
 return "#395f63";
}
function isRegional(){return !!META[currentWaterLayer].regional}

const baseFieldStyle=fieldStyle;
const baseRenderLegend=renderLegend;
const baseRenderHint=renderHint;
const baseSetLayer=setLayer;
const baseLoadMunicipality=loadMunicipality;

fieldStyle=function(feature){
 if(activeLayer!=="vatten")return baseFieldStyle(feature);
 if(isRegional())return{color:"#ffffff",weight:.65,opacity:.58,fillColor:"#ffffff",fillOpacity:.012};
 const r=record(feature.properties),v=scoreOf(r,currentWaterLayer);
 if(v==null)return{color:"#a9adaa",weight:.5,opacity:.32,fillColor:"#bfc3bf",fillOpacity:.05};
 return{color:"#f5f5ef",weight:.65,opacity:.85,fillColor:scoreColor(currentWaterLayer,v),fillOpacity:.76};
};

function bindWaterTooltips(){
 if(!fieldLayer||activeLayer!=="vatten")return;
 fieldLayer.eachLayer(function(layer){
  layer.unbindTooltip();
  layer.bindTooltip(function(){
   const p=layer.feature.properties,r=record(p);
   if(!r)return "Skifte "+escText(p.skifte_id)+" · ÅkerVatten data saknas";
   if(currentWaterLayer==="large_gw"){
    const cls=r.large_capacity_class||"kapacitetsklass saknas";
    return "Skifte "+escText(p.skifte_id)+" · "+escText(cls);
   }
   const v=scoreOf(r,currentWaterLayer);
   return "Skifte "+escText(p.skifte_id)+" · "+META[currentWaterLayer].title+" "+(v==null?"saknas":fmt(v,0));
  },{sticky:true,direction:"top"});
 });
}
function ensurePane(){
 if(!map.getPane("akvRegionPane")){
  const pane=map.createPane("akvRegionPane");
  pane.style.zIndex="330";
  pane.style.pointerEvents="none";
 }
}
function removeRegional(){
 regionalToken++;
 if(regionalLayer){map.removeLayer(regionalLayer);regionalLayer=null}
}
function regionStyle(feature){
 const p=feature.properties||{};
 if(currentWaterLayer==="large_gw")return{color:"#455b5d",weight:.8,opacity:.7,fillColor:capColor(p),fillOpacity:.52};
 const v=Number(p.score);
 return{color:"#ffffff",weight:.8,opacity:.72,fillColor:scoreColor(currentWaterLayer,Number.isFinite(v)?v:null),fillOpacity:.58};
}
function showRegional(){
 removeRegional();
 const key=META[currentWaterLayer].regional;if(!key)return Promise.resolve();
 const url=REGIONAL[key];if(!url)return Promise.reject(new Error("Regional ÅkerVatten-fil saknas: "+key));
 ensurePane();
 const token=++regionalToken;
 return fetch(url,{cache:"no-cache"}).then(function(r){if(!r.ok)throw new Error("Regional ÅkerVatten HTTP "+r.status);return r.json()}).then(function(data){
  if(token!==regionalToken||activeLayer!=="vatten"||META[currentWaterLayer].regional!==key)return;
  regionalLayer=L.geoJSON(data,{pane:"akvRegionPane",interactive:false,style:regionStyle}).addTo(map);
 });
}
function refreshWater(){
 if(activeLayer!=="vatten")return;
 if(fieldLayer){
  fieldLayer.setStyle(fieldStyle);
  bindWaterTooltips();
  if(selectedFieldLayer)selectedFieldLayer.setStyle(Object.assign({},fieldStyle(selectedFieldLayer.feature),{color:"#d7263d",weight:3,opacity:1}));
 }
 showRegional().catch(function(error){console.error(error);toast("Regionalt ÅkerVatten-lager kunde inte laddas.")});
 renderLegend();renderHint();
 const hint=document.getElementById("akvSubHint");if(hint)hint.textContent=META[currentWaterLayer].hint;
}
function legendRowsScore(){
 const colors=SCORE_COLORS[currentWaterLayer];
 return BANDS.map(function(b,i){return '<div class="legend-row"><span class="legend-swatch" style="background:'+colors[i]+'"></span><span>'+b+'</span></div>'}).join("");
}
function legendRowsCapacity(){
 const rows=[
  ["#e5e1d4","≤0,2 l/s"],
  ["#c7d7cf","0,2–1 l/s"],
  ["#95b9aa","1–5 l/s"],
  ["#638f84","5–25 l/s"],
  ["#395f63",">25 l/s"],
  ["#aeb3b0","Okänd/ej bedömd"]
 ];
 return rows.map(function(x){return '<div class="legend-row"><span class="legend-swatch" style="background:'+x[0]+'"></span><span>'+x[1]+'</span></div>'}).join("");
}
renderLegend=function(){
 if(activeLayer!=="vatten")return baseRenderLegend();
 const collapsed=ui.legend.classList.contains("collapsed");
 const rows=currentWaterLayer==="large_gw"?legendRowsCapacity():legendRowsScore();
 const foot=currentWaterLayer==="large_gw"
  ?"Visuell storleksklass i l/s; klickpanelen visar SGU:s exakta källklass. Inte tillstånd eller garanterad brunnskapacitet."
  :"Relativ skala inom Skåne. 0–100 är inte sannolikhet och inte juridisk bedömning.";
 ui.legend.innerHTML='<button id="legendToggle" class="legend-toggle" type="button" aria-expanded="'+String(!collapsed)+'">🎨</button><div class="legend-content"><div class="legend-title">'+META[currentWaterLayer].title+'</div>'+rows+'<div class="legend-foot">'+foot+'</div></div>';
 document.getElementById("legendToggle").addEventListener("click",function(){ui.legend.classList.toggle("collapsed",!ui.legend.classList.contains("collapsed"));renderLegend()});
};
renderHint=function(){
 if(activeLayer!=="vatten")return baseRenderHint();
 ui.hint.textContent=META[currentWaterLayer].hint;
};
setLayer=function(name){
 const box=document.getElementById("akervattenControls");
 if(box)box.classList.toggle("show",name==="vatten");
 if(name!=="vatten"){
  removeRegional();
  baseSetLayer(name);
  return;
 }
 const fro=document.getElementById("akerfroControls");if(fro)fro.classList.remove("show");
 activeLayer="vatten";
 document.querySelectorAll("[data-layer]").forEach(function(button){button.classList.toggle("active",button.dataset.layer===name)});
 const municipality=ui.municipality.value;
 if(municipality&&FILES[municipality])loadSidecar(municipality).then(refreshWater).catch(function(error){console.error(error);toast("ÅkerVatten-data kunde inte laddas.")});else refreshWater();
};
loadMunicipality=async function(name){
 if(activeLayer==="vatten"){try{await loadSidecar(name)}catch(error){console.error(error);toast("ÅkerVatten-data kunde inte laddas.")}}
 const result=await baseLoadMunicipality(name);
 if(activeLayer==="vatten")refreshWater();
 return result;
};

function capRange(r){
 if(!r||!r.large_capacity_class)return "Ingen kartlagd klass";
 const lo=Number(r.large_capacity_lower_lps),hi=Number(r.large_capacity_upper_lps);
 let equiv="";
 if(Number.isFinite(lo)||Number.isFinite(hi)){
  if(Number.isFinite(lo)&&Number.isFinite(hi))equiv=" · "+fmt(lo,2)+"–"+fmt(hi,2)+" l/s";
  else if(Number.isFinite(lo))equiv=" · ≥"+fmt(lo,2)+" l/s";
  else equiv=" · ≤"+fmt(hi,2)+" l/s";
 }
 return escText(r.large_capacity_class)+equiv;
}
function scoreRow(label,r,key,sub){
 const v=scoreOf(r,key);
 return '<div class="akv-row"><div><b>'+label+'</b><span>'+sub+'</span></div><strong>'+(v==null?"saknas":fmt(v,0))+'</strong><em>'+band(v)+'</em></div>';
}
function panel(r){
 if(!r)return '<div class="akv-note">ÅkerVatten-data saknas för fältet.</div>';
 const large=r.large_relation==="DIRECT_MAGAZINE"
  ?'<div class="akv-large"><div class="akv-large-title">Stora grundvattenmagasin</div><b>'+capRange(r)+'</b><span>'+(r.large_position?escText(r.large_position):"Position saknas")+'</span><span>'+(r.large_rock?escText(r.large_rock):"Bergart/jordart saknas")+'</span><span>'+(r.large_magazine_names?escText(r.large_magazine_names):"Magasinsnamn saknas")+'</span></div>'
  :'<div class="akv-large"><div class="akv-large-title">Stora grundvattenmagasin</div><b>'+(r.large_relation==="RECHARGE_AREA_ONLY"?"Endast tillrinningsområde":"Ingen direkt kartlagd magasinträff")+'</b></div>';
 return '<div class="akv-card">'+
  '<div class="akv-card-head"><div><b>ÅkerVatten</b><span>Separata beslutsunderlag · ingen totalscore</span></div><span class="akv-legal">Vattenrätt: ej bedömd</span></div>'+
  scoreRow("MarkTorka",r,"mark_torka","Åkerns mark/topografi")+
  scoreRow("MarkVäta",r,"mark_vata","Åkerns mark/topografi")+
  scoreRow("Små magasin",r,"small_gw","Översiktlig lokal SGU-indikator")+
  scoreRow("GrundvattenTorka",r,"gw_drought","Historiskt SGU-HYPE-område")+
  scoreRow("YtvattenTorka",r,"sw_drought","Historiskt S-HYPE-område")+
  large+
  '<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag är inte en juridisk bedömning. Kapacitetsklass innebär inte tillstånd, hållbart uttag eller garanterad brunnskapacitet.</div>'+
  '</div>';
}
window.akervattenSection=function(p){
 const current=record(p);
 if(current)return '<details class="akv-panel"'+(activeLayer==="vatten"?" open":"")+'><summary>ÅkerVatten</summary><div class="akv-shell">'+panel(current)+'</div></details>';
 return '<details class="akv-panel" data-municipality="'+encodeURIComponent(p.kommun)+'" data-field="'+encodeURIComponent(p.id)+'"><summary>ÅkerVatten</summary><div class="akv-shell"><div class="akv-note">Öppna för att ladda vattenunderlag.</div></div></details>';
};
document.addEventListener("toggle",function(event){
 const el=event.target;
 if(!el.classList||!el.classList.contains("akv-panel")||!el.open||el.dataset.loaded==="1"||!el.dataset.municipality)return;
 const body=el.querySelector(".akv-shell"),name=decodeURIComponent(el.dataset.municipality||""),fieldId=decodeURIComponent(el.dataset.field||"");
 body.innerHTML='<div class="akv-note">Laddar ÅkerVatten…</div>';
 loadSidecar(name).then(function(data){body.innerHTML=panel(decode(data,fieldId));el.dataset.loaded="1"}).catch(function(error){console.error(error);body.innerHTML='<div class="akv-note">ÅkerVatten kunde inte laddas.</div>'});
},true);

function selectSub(name){
 if(!META[name])return;
 currentWaterLayer=name;
 document.querySelectorAll(".akv-sub").forEach(function(b){b.classList.toggle("active",b.dataset.akvLayer===name)});
 if(activeLayer==="vatten")refreshWater();
}
document.querySelectorAll(".akv-sub").forEach(function(button){button.addEventListener("click",function(){selectSub(button.dataset.akvLayer)})});

const params=new URLSearchParams(location.search);
const requestedSub=params.get("vatten");
if(requestedSub&&META[requestedSub])selectSub(requestedSub);
if(params.get("lager")==="vatten")setLayer("vatten");
})();