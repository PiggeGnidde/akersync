/* AKERFRO_ERTOR_WEB_UI_V0A */
(function(){
"use strict";
const cfg=window.AKERFRO_WEB_CONFIG||{};
const AKF_FILES=cfg.files||{};
const AKF_TOPLIST_FILE=cfg.toplist||"data/akerfro/skane_top1000.json";
const COLORS={A_STRONG_CANDIDATE:"#17643c",B_PHYSICAL_CANDIDATE:"#72a85e",C_ROTATION_CAUTION:"#d99a3e",D_NOT_HIGH_PHYSICAL_MATCH:"#b8bcb6"};
const LABELS={A_STRONG_CANDIDATE:"A · Stark kandidat",B_PHYSICAL_CANDIDATE:"B · Fysisk kandidat",C_ROTATION_CAUTION:"C · Rotationsvarning",D_NOT_HIGH_PHYSICAL_MATCH:"D · Ej prioriterad"};
const SHORT={A_STRONG_CANDIDATE:"A",B_PHYSICAL_CANDIDATE:"B",C_ROTATION_CAUTION:"C",D_NOT_HIGH_PHYSICAL_MATCH:"D"};
const cache={},loads={},decoded={};
let currentMunicipality="",currentData=null,topCache=null;

function decode(data,fieldId){
 const c=decoded[data.municipality]||(decoded[data.municipality]={});
 if(c[fieldId])return c[fieldId];
 const raw=(data.fields||{})[fieldId];if(!raw)return null;
 const row={};
 data.columns.forEach(function(name,index){const d=(data.dictionaries||{})[name],v=raw[index];row[name]=d?d[v]:v});
 c[fieldId]=row;return row;
}
function record(p){if(!currentData||currentMunicipality!==p.kommun)return null;return decode(currentData,p.id)}
function loadSidecar(name){
 if(cache[name]){currentMunicipality=name;currentData=cache[name];return Promise.resolve(currentData)}
 if(loads[name])return loads[name];
 const file=AKF_FILES[name];if(!file)return Promise.reject(new Error("ÅkerFrö-sidecar saknas"));
 loads[name]=fetch(file,{cache:"no-cache"}).then(function(r){if(!r.ok)throw new Error("ÅkerFrö HTTP "+r.status);return r.json()}).then(function(data){
  if(data.schema_version!=="akerfro-ertor-web-v0a"||data.municipality!==name||!data.fields||Object.keys(data.fields).length!==data.field_count)throw new Error("Ogiltig ÅkerFrö-payload");
  cache[name]=data;currentMunicipality=name;currentData=data;return data;
 }).finally(function(){delete loads[name]});
 return loads[name];
}
function enabled(cls){const el=document.querySelector('.akf-class-filter[value="'+cls+'"]');return !!(el&&el.checked)}
function passes(r){
 if(!r||!enabled(r.class))return false;
 const d=document.getElementById("akfDistanceFilter"),a=document.getElementById("akfAreaFilter");
 if(d&&d.value!=="all"&&Number(r.distance_bjuv_km)>=Number(d.value))return false;
 if(a){
  const x=Number(r.area_ha);
  if(a.value==="5-12"&&!(x>=5&&x<=12))return false;
  if(a.value==="5plus"&&!(x>=5))return false;
  if(a.value==="2plus"&&!(x>=2))return false;
 }
 return true;
}
function historicalOutline(r){const el=document.getElementById("akfHistoryOutline");return !!(el&&el.checked&&r&&r.historical_positive)}
function tooltip(feature){
 const p=feature.properties,r=record(p);
 if(activeLayer==="fro"){
  if(!r)return "Skifte "+esc(p.skifte_id)+" · ÅkerFrö data saknas";
  return "Skifte "+esc(p.skifte_id)+" · "+esc(SHORT[r.class]||"–")+" · ÄrtMatch "+fmt(r.artmatch,0)+" · AreaLogistik "+fmt(r.area_logistics,0);
 }
 const label=activeLayer==="score"?"ÅkerScore":activeLayer==="value"?"ÅkerVärde":"ÅkerDrift";
 const arableLayer=activeLayer==="score"||activeLayer==="drift";
 const na=activeLayer==="value"&&p.akervarde_applicability!=="applicable"||arableLayer&&p.arable_applicability!=="applicable";
 const shown=na?(p.arable_applicability==="unknown"?"Okänd markanvändning":"Ej tillämpligt"):intFmt(fieldValue(p));
 return "Skifte "+esc(p.skifte_id)+" · "+label+" "+shown;
}
function bindTooltips(){
 if(!fieldLayer)return;
 fieldLayer.eachLayer(function(layer){
  layer.unbindTooltip();
  layer.bindTooltip(function(){return tooltip(layer.feature)},{sticky:true,direction:"top"});
 });
}
function refresh(){
 if(activeLayer==="fro"&&fieldLayer){
  fieldLayer.setStyle(fieldStyle);
  bindTooltips();
  if(selectedFieldLayer)selectedFieldLayer.setStyle(Object.assign({},fieldStyle(selectedFieldLayer.feature),{color:"#d7263d",weight:3}));
 }
 renderLegend();renderHint();
}

const baseFieldStyle=fieldStyle,baseRenderLegend=renderLegend,baseRenderHint=renderHint,baseSetLayer=setLayer,baseLoadMunicipality=loadMunicipality;

fieldStyle=function(feature){
 if(activeLayer!=="fro")return baseFieldStyle(feature);
 const r=record(feature.properties);
 if(!r)return{color:"#adb2ab",weight:.5,opacity:.35,fillColor:"#b8bcb6",fillOpacity:.08};
 const visible=passes(r),historic=historicalOutline(r);
 return{color:historic?"#6d3f8c":"#f5f5ef",weight:historic?2.3:.7,opacity:visible?1:.12,fillColor:COLORS[r.class]||"#b8bcb6",fillOpacity:visible?.78:.015};
};
renderLegend=function(){
 if(activeLayer!=="fro")return baseRenderLegend();
 const collapsed=ui.legend.classList.contains("collapsed");
 const rows=Object.keys(LABELS).map(function(k){return '<div class="legend-row"><span class="legend-swatch" style="background:'+COLORS[k]+'"></span><span>'+LABELS[k]+'</span></div>'}).join("");
 ui.legend.innerHTML='<button id="legendToggle" class="legend-toggle" type="button" aria-expanded="'+String(!collapsed)+'">🎨</button><div class="legend-content"><div class="legend-title">ÅkerFrö · konservärt 2026</div>'+rows+'<div class="legend-foot">Screening av fysisk match, rotation/förfrukt och operativ logistik. Inte odlingsgaranti eller kontraktsbedömning.</div></div>';
 document.getElementById("legendToggle").addEventListener("click",function(){ui.legend.classList.toggle("collapsed",!ui.legend.classList.contains("collapsed"));renderLegend()});
};
renderHint=function(){
 if(activeLayer!=="fro")return baseRenderHint();
 ui.hint.textContent="Konservärt 2026: A/B/C/D bygger på fryst ÄrtMatch, observerad växtföljd och separat AreaLogistik. Klicka på ett fält för förklaringen.";
};
setLayer=function(name){
 const box=document.getElementById("akerfroControls");if(box)box.classList.toggle("show",name==="fro");
 if(name!=="fro"){baseSetLayer(name);bindTooltips();return}
 activeLayer="fro";
 document.querySelectorAll("[data-layer]").forEach(function(button){button.classList.toggle("active",button.dataset.layer===name)});
 const municipality=ui.municipality.value;
 if(municipality&&AKF_FILES[municipality])loadSidecar(municipality).then(refresh).catch(function(error){console.error(error);toast("ÅkerFrö-data kunde inte laddas.")});else refresh();
};
loadMunicipality=async function(name){
 if(activeLayer==="fro"){try{await loadSidecar(name)}catch(error){console.error(error);toast("ÅkerFrö-data kunde inte laddas.")}}
 const result=await baseLoadMunicipality(name);
 bindTooltips();
 if(activeLayer==="fro")refresh();
 return result;
};

function classCss(cls){return cls==="A_STRONG_CANDIDATE"?"akf-A":cls==="B_PHYSICAL_CANDIDATE"?"akf-B":cls==="C_ROTATION_CAUTION"?"akf-C":"akf-D"}
function year(v){return v==null?"ingen observerad 2015–2025":esc(v)}
function panel(r){
 if(!r)return '<div class="akf-note">ÅkerFrö-data saknas för fältet.</div>';
 const cls=LABELS[r.class]||r.class;
 const prior=r.predecessor_prior==="POSITIVE"?"positiv historisk prior":r.predecessor_prior==="NEGATIVE"?"negativ historisk prior":r.predecessor_prior==="NEUTRAL"?"neutral historisk prior":"begränsat/okänt stöd";
 const enr=valid(r.predecessor_enrichment)?" · "+fmt(r.predecessor_enrichment,2)+"×":"";
 return '<div class="akf-hero"><div class="akf-hero-row"><div><div class="akf-class">'+esc(cls)+'</div><div class="akf-sub">Konservärt · kandidatår 2026 · prioritet #'+intFmt(r.priority_rank)+'</div></div><span class="akf-badge '+classCss(r.class)+'">'+esc(SHORT[r.class]||"–")+'</span></div>'+
 '<div class="akf-metrics"><div class="akf-metric"><span>ÄrtMatch · fysisk match</span><b>'+fmt(r.artmatch,1)+'</b></div><div class="akf-metric"><span>AreaLogistik</span><b>'+fmt(r.area_logistics,1)+'</b></div><div class="akf-metric"><span>Areal / AreaFit</span><b>'+fmt(r.area_ha,1)+' ha</b><span>AreaFit '+fmt(r.area_fit,0)+'</span></div><div class="akf-metric"><span>Bjuv / Proximity</span><b>'+fmt(r.distance_bjuv_km,0)+' km</b><span>Proximity '+fmt(r.bjuv_proximity,0)+'</span></div></div>'+
 '<div class="akf-detail"><div class="akf-detail-grid"><span>Rotation</span><b>'+esc(r.rotation_status)+'</b><span>Förfrukt 2025</span><b>'+esc(r.predecessor_crop||"saknas")+'</b><span>Förfruktssignal</span><b>'+esc(prior)+enr+'</b><span>Senaste konservärt</span><b>'+year(r.last_conservart_year)+'</b><span>Senaste annan ärt</span><b>'+year(r.last_other_pea_year)+'</b><span>Senaste åkerböna</span><b>'+year(r.last_faba_year)+'</b><span>Historiskt konservärtsfält</span><b>'+(r.historical_positive?"Ja":"Nej")+'</b></div></div>'+
 '<div class="akf-note">ÄrtMatch är fysisk/strukturell screening. Rotation/förfrukt och AreaLogistik är separata urvalslager. Resultatet är inte en avkastningsprognos, odlingsgaranti eller bedömning av kontrakt.</div></div>';
}
window.akerfroSection=function(p){
 const current=record(p);
 if(current)return '<details class="akf-panel"'+(activeLayer==="fro"?" open":"")+'><summary>ÅkerFrö · konservärt</summary><div class="akf-shell">'+panel(current)+'</div></details>';
 return '<details class="akf-panel" data-municipality="'+encodeURIComponent(p.kommun)+'" data-field="'+encodeURIComponent(p.id)+'"><summary>ÅkerFrö · konservärt</summary><div class="akf-shell"><div class="akf-note">Öppna för att ladda konservärtscreening.</div></div></details>';
};
document.addEventListener("toggle",function(event){
 const element=event.target;
 if(!element.classList||!element.classList.contains("akf-panel")||!element.open||element.dataset.loaded==="1"||!element.dataset.municipality)return;
 const body=element.querySelector(".akf-shell"),name=decodeURIComponent(element.dataset.municipality||""),fieldId=decodeURIComponent(element.dataset.field||"");
 body.innerHTML='<div class="akf-note">Laddar ÅkerFrö…</div>';
 loadSidecar(name).then(function(data){body.innerHTML=panel(decode(data,fieldId));element.dataset.loaded="1"}).catch(function(error){console.error(error);body.innerHTML='<div class="akf-note">ÅkerFrö kunde inte laddas.</div>'});
},true);

function loadTop(){
 if(topCache)return Promise.resolve(topCache);
 return fetch(AKF_TOPLIST_FILE,{cache:"no-cache"}).then(function(r){if(!r.ok)throw new Error("Topplista HTTP "+r.status);return r.json()}).then(function(data){if(data.schema_version!=="akerfro-ertor-toplist-v0a"||!Array.isArray(data.rows)||data.count!==1000)throw new Error("Ogiltig ÅkerFrö-topplista");topCache=data;return data});
}
function openToplist(){
 loadTop().then(function(data){
  ui.identity.textContent="ÅkerFrö · Top 1000";
  const rows=data.rows.map(function(row){return '<button class="akf-top-row" type="button" data-m="'+encodeURIComponent(row.municipality)+'" data-f="'+encodeURIComponent(row.field_id)+'"><span class="akf-top-rank">#'+row.rank+'</span><span class="akf-top-main"><b>'+esc(row.municipality)+' · '+esc(row.field_id)+'</b><span>'+esc(row.predecessor_crop)+' · '+fmt(row.area_ha,1)+' ha · '+fmt(row.distance_bjuv_km,0)+' km Bjuv</span></span><span class="akf-top-score"><b>'+fmt(row.area_logistics,0)+'</b>logistik<br>'+fmt(row.artmatch,0)+' match</span></button>'}).join("");
  ui.drawerBody.innerHTML='<div class="akf-top-intro">Skånes 1 000 högst prioriterade konservärtsfält enligt fryst C10-ranking: först A/B/C/D-klass, därefter AreaLogistik och sedan ÄrtMatch.</div><div class="akf-top-list">'+rows+'</div>';
  ui.drawerBody.querySelectorAll(".akf-top-row").forEach(function(button){button.addEventListener("click",function(){goTop(button.dataset.m,button.dataset.f)})});
  ui.drawer.classList.add("open");ui.drawer.setAttribute("aria-hidden","false");ui.legend.classList.add("drawer-open");if(matchMedia("(max-width:700px)").matches)setCollapsed(true);
 }).catch(function(error){console.error(error);toast("Topplistan kunde inte laddas.")});
}
async function goTop(municipalityEncoded,fieldEncoded){
 const municipality=decodeURIComponent(municipalityEncoded),fieldId=decodeURIComponent(fieldEncoded);
 ui.municipality.value=municipality;await loadMunicipality(municipality);
 let target=null;if(fieldLayer)fieldLayer.eachLayer(function(layer){if((((layer.feature||{}).properties||{}).id)===fieldId)target=layer});
 if(!target){toast("Fältet kunde inte hittas i kartlagret.");return}
 const bounds=target.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[40,40],maxZoom:17});selectField(target.feature,target);
}

document.querySelectorAll(".akf-class-filter").forEach(function(el){el.addEventListener("change",refresh)});
document.getElementById("akfDistanceFilter").addEventListener("change",refresh);
document.getElementById("akfAreaFilter").addEventListener("change",refresh);
document.getElementById("akfHistoryOutline").addEventListener("change",refresh);
document.getElementById("akfTopButton").addEventListener("click",openToplist);

const requested=new URLSearchParams(location.search).get("lager");
if(requested==="fro")setLayer("fro");
})();
