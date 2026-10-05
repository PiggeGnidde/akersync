/* AKERSWAP_VIRTUAL_FARMERS_SELECT_V0A */
(function(){
"use strict";
var STORE="akerswap_virtual_farmers_select_v0a";
var COLOR_A="#1769aa", COLOR_B="#d97706";
var mode=null, picks=new Map();

function idOf(p){return p ? String(p.block_id)+"|"+String(p.skifte_id) : "";}
function n(x){var v=Number(x);return Number.isFinite(v)?v:0;}
function esc2(x){return String(x==null?"":x).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}
function rows(farm){return Array.from(picks.values()).filter(function(x){return x.farm===farm;});}
function area(farm){return rows(farm).reduce(function(s,x){return s+n(x.area_ha);},0);}
function fmt(x){return Number(x).toLocaleString("sv-SE",{maximumFractionDigits:1});}

function load(){
  try{
    var a=JSON.parse(localStorage.getItem(STORE)||"[]");
    if(Array.isArray(a))a.forEach(function(x){if(x&&x.fid&&(x.farm==="A"||x.farm==="B"))picks.set(x.fid,x);});
  }catch(e){console.warn(e);}
}
function save(){localStorage.setItem(STORE,JSON.stringify(Array.from(picks.values())));}

function render(){
  var a=rows("A"),b=rows("B");
  var ca=document.getElementById("aksCountA"),cb=document.getElementById("aksCountB");
  if(ca)ca.textContent=a.length+" skiften · "+fmt(area("A"))+" ha";
  if(cb)cb.textContent=b.length+" skiften · "+fmt(area("B"))+" ha";
  document.querySelectorAll(".aks-mode").forEach(function(x){x.classList.toggle("active",x.dataset.farm===mode);});
  var st=document.getElementById("aksStatus");
  if(st)st.textContent=mode ? "Klickläge: Bonde "+mode+". Klicka skiften för att lägga till/ta bort." : "Klickläge av. Vanligt skiftesklick öppnar ÅkerPass-panelen.";
  try{if(fieldLayer)fieldLayer.setStyle(fieldStyle);}catch(e){}
}
function setMode(farm){mode=(mode===farm)?null:farm;render();}
function toggle(feature,layer){
  var p=feature.properties||{}, fid=idOf(p);
  if(!fid)return;
  var old=picks.get(fid);
  if(old&&old.farm===mode){
    picks.delete(fid);
  }else{
    picks.set(fid,{
      fid:fid,farm:mode,kommun:p.kommun||"",
      block_id:String(p.block_id),skifte_id:String(p.skifte_id),
      area_ha:Number.isFinite(Number(p.area_ha))?Number(p.area_ha):null,
      akerscore:Number.isFinite(Number(p.akerscore))?Number(p.akerscore):null,
      akerdrift:Number.isFinite(Number(p.akerdrift))?Number(p.akerdrift):null
    });
  }
  save();render();
}
function clearAll(){
  picks.clear();mode=null;save();render();
  if(typeof toast==="function")toast("ÅkerSwap-valen rensade.");
}
function copySelection(){
  var a=rows("A"),b=rows("B");
  var out=[
    "AKERSWAP_VIRTUAL_FARMERS_SELECT_V0A",
    "A_FIELDS="+a.length,
    "A_AREA_HA="+area("A").toFixed(2),
    "B_FIELDS="+b.length,
    "B_AREA_HA="+area("B").toFixed(2),
    "",
    "[BONDE_A]",
    a.map(function(x){return x.fid;}).join("\n"),
    "",
    "[BONDE_B]",
    b.map(function(x){return x.fid;}).join("\n")
  ].join("\n");
  navigator.clipboard.writeText(out).then(function(){
    if(typeof toast==="function")toast("Bonde A/B-val kopierade.");
  }).catch(function(){
    var ta=document.createElement("textarea");ta.value=out;document.body.appendChild(ta);ta.select();document.execCommand("copy");ta.remove();
    if(typeof toast==="function")toast("Bonde A/B-val kopierade.");
  });
}
function mount(){
  var body=document.querySelector(".control-body");
  if(!body||document.getElementById("akerswapLab"))return;
  var box=document.createElement("section");
  box.id="akerswapLab";box.className="aks-lab";
  box.innerHTML=
    '<span class="label">ÅkerSwap Lab · virtuella bönder</span>'+
    '<div class="aks-help">Aktivera A eller B och klicka skiften direkt i kartan. Klicka samma skifte igen för att ta bort det. Ett skifte kan bara tillhöra en av de virtuella bönderna.</div>'+
    '<div class="aks-grid">'+
      '<button class="action aks-mode" data-farm="A" type="button">Bonde A</button>'+
      '<button class="action aks-mode" data-farm="B" type="button">Bonde B</button>'+
    '</div>'+
    '<div class="aks-counts"><span id="aksCountA"></span><span id="aksCountB"></span></div>'+
    '<div id="aksStatus" class="status"></div>'+
    '<div class="aks-grid">'+
      '<button id="aksCopy" class="action aks-copy" type="button">Kopiera A/B</button>'+
      '<button id="aksClear" class="action" type="button">Rensa</button>'+
    '</div>';
  body.appendChild(box);
  box.querySelectorAll(".aks-mode").forEach(function(x){x.addEventListener("click",function(){setMode(x.dataset.farm);});});
  document.getElementById("aksCopy").addEventListener("click",copySelection);
  document.getElementById("aksClear").addEventListener("click",clearAll);
}
load();

if(typeof fieldStyle==="function"){
  var baseFieldStyle=fieldStyle;
  fieldStyle=function(feature){
    var s=baseFieldStyle(feature);
    var x=picks.get(idOf((feature||{}).properties||{}));
    if(x){s.color=x.farm==="A"?COLOR_A:COLOR_B;s.weight=4;s.opacity=1;}
    return s;
  };
}
if(typeof selectField==="function"){
  var baseSelectField=selectField;
  selectField=function(feature,layer,writeUrl){
    if(mode){toggle(feature,layer);return;}
    return baseSelectField(feature,layer,writeUrl===undefined?true:writeUrl);
  };
}
mount();render();
})();