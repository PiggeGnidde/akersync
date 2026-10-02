/* AKERFRO_ACCESS_WEB_UI_V0B */
(function(){
"use strict";
const cfg=window.AKERFRO_ACCESS_WEB_CONFIG||{};
const FILE=cfg.geojson||"data/akerfro_bestmatch/skane_screening.geojson";
const RANKINGS=cfg.rankings||[];
let screeningMode=false,screeningData=null,screeningLayer=null,screeningLoad=null,pinnedFieldId=null;
let savedShowFields=true,savedShowBlocks=true,firstScreenFit=true;

function rankLabel(col){
 const row=RANKINGS.find(function(x){return x[1]===col});
 return row?row[0]:col;
}
function loadScreening(){
 if(screeningData)return Promise.resolve(screeningData);
 if(screeningLoad)return screeningLoad;
 screeningLoad=fetch(FILE,{cache:"no-cache"}).then(function(r){
  if(!r.ok)throw new Error("Skåne-screening HTTP "+r.status);
  return r.json();
 }).then(function(data){
  if(!data||data.type!=="FeatureCollection"||!Array.isArray(data.features))throw new Error("Ogiltig Skåne-screening");
  screeningData=data;return data;
 }).finally(function(){screeningLoad=null});
 return screeningLoad;
}
function currentRank(){const el=document.getElementById("akfxRanking");return el?el.value:(RANKINGS[0]||[])[1]}
function currentTop(){const el=document.getElementById("akfxTopN");return el?Number(el.value):800}
function onlyA(){return false}
function rankColor(rank,topn){
 const t=Math.min(1,Math.max(0,(Number(rank)-1)/Math.max(1,topn-1)));
 const hue=115-85*t;
 return "hsl("+hue+",75%,45%)";
}
function activeFeature(p){
 const r=Number(p[currentRank()]);
 const inTop=Number.isFinite(r)&&r<=currentTop()&&(!onlyA()||p.artkandidat_class==="A_STRONG_CANDIDATE");
 return inTop||(pinnedFieldId!==null&&p.field_id===pinnedFieldId);
}
function rankLines(p){
 return RANKINGS.map(function(r){
  const v=p[r[1]]==null?"–":p[r[1]];
  return "<span>"+esc(r[0])+"</span><b>"+esc(v)+"</b>";
 }).join("");
}
function routeText(p){
 if(valid(p.field_to_bjuv_road_km))return fmt(p.field_to_bjuv_road_km,1)+" km";
 return "saknas";
}
function panel(p){
 const fallback=p.bjuv_proximity_d5_source==="C10_STRAIGHTLINE_FALLBACK";
 return '<div class="akfx-hero">'+
  '<div class="akfx-title">'+esc(p.municipality)+' · '+esc(p.field_id)+'</div>'+
  '<div class="akfx-sub">'+fmt(p.field_area_ha,1)+' ha · '+esc(p.artkandidat_class)+'</div>'+
  '<div class="akfx-grid">'+
   '<span>ÄrtMatch</span><b>'+fmt(p.artmatch_score,1)+'</b>'+
   '<span>Väglogistik</span><b>'+fmt(p.road_access_score,1)+'</b>'+
   '<span>AreaLogistik · väg</span><b>'+fmt(p.road_area_logistics_score,1)+'</b>'+
   '<span>BestMatch v0b · balanserad</span><b>'+fmt(p.bestmatch_d5_balanced_score,1)+'</b>'+
   '<span>Till närmaste körbara väg</span><b>'+fmt(p.nearest_drivable_osm_m,1)+' m</b>'+
   '<span>Till statligt/kommunalt väghållen väg</span><b>'+fmt(p.nearest_statlig_kommunal_nvdb_m,1)+' m</b>'+
   '<span>Vägavstånd till Bjuv</span><b>'+routeText(p)+'</b>'+
   '<span>Fågelväg till Bjuv</span><b>'+fmt(p.distance_bjuv_km,1)+' km</b>'+
   '<span>Rotation</span><b>'+esc(p.rotation_status)+'</b>'+
   '<span>Förfruktssignal</span><b>'+esc(p.predecessor_prior)+'</b>'+
   '<span>Historiskt konservärtsfält</span><b>'+(p.historical_conservart_positive?"Ja":"Nej")+'</b>'+
  '</div>'+
  '<div class="akfx-ranks"><div class="akfx-grid">'+rankLines(p)+'</div></div>'+
  '<div class="akfx-note">'+
   (fallback?'Vägavstånd till Bjuv saknas för detta fält; D5 använder den frysta fågelvägsproxyn som explicit fallback. ':'')+
   'Screening för urval av kandidater. Inte odlingsgaranti, kontraktsbedömning eller certifierad lastbilsnavigation.'+
  '</div></div>';
}
function openPanel(p){
 ui.identity.textContent="ÅkerFrö · hela Skåne";
 ui.drawerBody.innerHTML=panel(p);
 ui.drawer.classList.add("open");
 ui.drawer.setAttribute("aria-hidden","false");
 ui.legend.classList.add("drawer-open");
 if(matchMedia("(max-width:700px)").matches)setCollapsed(true);
}
function renderScreening(){
 if(!screeningMode||!screeningData)return;
 if(screeningLayer){map.removeLayer(screeningLayer);screeningLayer=null}
 const rank=currentRank(),topn=currentTop(),aOnly=onlyA();
 let count=0,ha=0,aCount=0,fallbacks=0;
 screeningLayer=L.geoJSON(screeningData,{
  filter:function(f){return activeFeature(f.properties||{})},
  style:function(f){
   const p=f.properties||{},r=Number(p[rank]),pin=p.field_id===pinnedFieldId;
   const c=Number.isFinite(r)?rankColor(r,topn):"#b8bcb6";
   return{color:pin?"#111":"#f5f5ef",weight:pin?3.2:.7,opacity:1,fillColor:c,fillOpacity:pin?.88:.76,dashArray:pin?"6 4":null};
  },
  onEachFeature:function(f,l){
   const p=f.properties||{},r=Number(p[rank]);
   const inTop=Number.isFinite(r)&&r<=topn&&(!aOnly||p.artkandidat_class==="A_STRONG_CANDIDATE");
   if(inTop){
    count++;ha+=Number(p.field_area_ha)||0;
    if(p.artkandidat_class==="A_STRONG_CANDIDATE")aCount++;
    if(p.bjuv_proximity_d5_source==="C10_STRAIGHTLINE_FALLBACK")fallbacks++;
   }
   l.bindTooltip(function(){return "#"+esc(p[rank])+" · "+esc(p.municipality)+" · "+fmt(p.field_area_ha,1)+" ha";},{sticky:true,direction:"top"});
   l.on("click",function(){
    pinnedFieldId=p.field_id;
    openPanel(p);
    renderScreening();
   });
  }
 }).addTo(map);
 const stat=document.getElementById("akfxStats");
 if(stat)stat.innerHTML='<b>'+count.toLocaleString("sv-SE")+'</b> fält · <b>'+ha.toFixed(0)+'</b> ha · A '+aCount.toLocaleString("sv-SE")+
  (fallbacks?' · Bjuv-fallback '+fallbacks.toLocaleString("sv-SE"):'');
 setStatus("Hela Skåne · "+rankLabel(rank)+" · topp "+topn);
 if(firstScreenFit&&screeningLayer.getBounds().isValid()){
  map.fitBounds(screeningLayer.getBounds(),{padding:[18,18]});
  firstScreenFit=false;
 }
}
function enterScreening(){
 loadScreening().then(function(){
  screeningMode=true;firstScreenFit=true;
  const box=document.getElementById("akerfroControls");if(box)box.classList.add("akf-screening-mode");
  const controls=document.getElementById("akfSkaneControls");if(controls)controls.classList.add("show");
  const button=document.getElementById("akfSkaneButton");if(button)button.textContent="↩ Kommunvy";
  savedShowFields=ui.showFields.checked;savedShowBlocks=ui.showBlocks.checked;
  if(fieldLayer&&map.hasLayer(fieldLayer))map.removeLayer(fieldLayer);
  if(blockLayer&&map.hasLayer(blockLayer))map.removeLayer(blockLayer);
  renderScreening();
 }).catch(function(error){console.error(error);toast("Skåne-screeningen kunde inte laddas.")});
}
function exitScreening(silent){
 if(!screeningMode)return;
 screeningMode=false;pinnedFieldId=null;
 if(screeningLayer){map.removeLayer(screeningLayer);screeningLayer=null}
 const box=document.getElementById("akerfroControls");if(box)box.classList.remove("akf-screening-mode");
 const controls=document.getElementById("akfSkaneControls");if(controls)controls.classList.remove("show");
 const button=document.getElementById("akfSkaneButton");if(button)button.textContent="🗺 Hela Skåne";
 ui.showFields.checked=savedShowFields;ui.showBlocks.checked=savedShowBlocks;
 if(savedShowBlocks&&blockLayer)blockLayer.addTo(map);
 if(savedShowFields&&fieldLayer)fieldLayer.addTo(map);
 if(!silent)setStatus("Kommunvy · "+ui.municipality.value);
}
function toggleScreening(){screeningMode?exitScreening(false):enterScreening()}

const baseSetLayerAkfx=setLayer;
setLayer=function(name){
 if(screeningMode&&name!=="fro")exitScreening(true);
 return baseSetLayerAkfx(name);
};
const baseLoadMunicipalityAkfx=loadMunicipality;
loadMunicipality=async function(name){
 if(screeningMode)exitScreening(true);
 return await baseLoadMunicipalityAkfx(name);
};

const button=document.getElementById("akfSkaneButton");
if(button)button.addEventListener("click",toggleScreening);
["akfxRanking","akfxTopN"].forEach(function(id){
 const el=document.getElementById(id);if(el)el.addEventListener("change",renderScreening);
});
const zoom=document.getElementById("akfxZoom");
if(zoom)zoom.addEventListener("click",function(){if(screeningLayer&&screeningLayer.getBounds().isValid())map.fitBounds(screeningLayer.getBounds(),{padding:[18,18]})});
})();