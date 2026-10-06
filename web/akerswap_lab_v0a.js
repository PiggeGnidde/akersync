/* AKERSWAP_VIRTUAL_FARMERS_LAB_V0B */
(function(){
"use strict";

var STORE="akerswap_virtual_farmers_v0b";
var LEGACY_STORE="akerswap_virtual_farmers_select_v0a";
var COLOR_A="#1769aa", COLOR_B="#d97706", COLOR_SWAP="#6a3d9a";
var mode=null, picks=new Map(), swapOverlay=null;

function idOf(p){return p ? String(p.block_id)+"|"+String(p.skifte_id) : "";}
function finite(x){var v=Number(x);return Number.isFinite(v)?v:null;}
function n(x){var v=finite(x);return v===null?0:v;}
function rows(farm){return Array.from(picks.values()).filter(function(x){return x.farm===farm;});}
function eligible(farm){return rows(farm).filter(function(x){
  return finite(x.area_ha)!==null && x.area_ha>0 &&
         finite(x.akerscore)!==null && finite(x.akerdrift)!==null &&
         finite(x.lat)!==null && finite(x.lon)!==null;
});}
function totalArea(list){return list.reduce(function(s,x){return s+n(x.area_ha);},0);}
function fmt1(x){return Number(x).toLocaleString("sv-SE",{maximumFractionDigits:1});}
function pct(x){return (100*Number(x)).toLocaleString("sv-SE",{maximumFractionDigits:1})+" %";}
function htmlEsc(x){return String(x==null?"":x).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}

function load(){
  try{
    var raw=localStorage.getItem(STORE);
    var migrated=false;
    if(!raw){
      raw=localStorage.getItem(LEGACY_STORE);
      migrated=!!raw;
    }
    var a=JSON.parse(raw||"[]");
    if(Array.isArray(a))a.forEach(function(x){
      if(x&&x.fid&&(x.farm==="A"||x.farm==="B"))picks.set(x.fid,x);
    });
    if(migrated)save();
  }catch(e){console.warn(e);}
}
function save(){localStorage.setItem(STORE,JSON.stringify(Array.from(picks.values())));}

function geometryCenter(geometry){
  if(!geometry||!geometry.coordinates)return null;
  var minLat=Infinity,maxLat=-Infinity,minLon=Infinity,maxLon=-Infinity;
  function walk(x){
    if(!Array.isArray(x))return;
    if(x.length>=2&&typeof x[0]==="number"&&typeof x[1]==="number"){
      var lon=x[0],lat=x[1];
      if(Number.isFinite(lat)&&Number.isFinite(lon)){
        minLat=Math.min(minLat,lat);maxLat=Math.max(maxLat,lat);
        minLon=Math.min(minLon,lon);maxLon=Math.max(maxLon,lon);
      }
      return;
    }
    x.forEach(walk);
  }
  walk(geometry.coordinates);
  if(!Number.isFinite(minLat)||!Number.isFinite(minLon))return null;
  return {lat:(minLat+maxLat)/2,lon:(minLon+maxLon)/2};
}
async function hydrateLegacySelections(){
  var missing=Array.from(picks.values()).filter(function(x){
    return finite(x.lat)===null||finite(x.lon)===null;
  });
  if(!missing.length)return;

  var byKommun={};
  missing.forEach(function(x){
    var k=String(x.kommun||"");
    if(!byKommun[k])byKommun[k]=new Set();
    byKommun[k].add(x.fid);
  });

  var hydrated=0;
  var jobs=Object.keys(byKommun).map(async function(k){
    var meta=window.MANIFEST&&window.MANIFEST.municipalities?window.MANIFEST.municipalities[k]:null;
    if(!meta)return;
    try{
      var response=await fetch(meta.file,{cache:"no-cache"});
      if(!response.ok)return;
      var doc=await response.json();
      var features=(doc.fields&&doc.fields.features)||[];
      features.forEach(function(feature){
        var p=(feature||{}).properties||{}, id=idOf(p);
        if(!byKommun[k].has(id))return;
        var x=picks.get(id),c=geometryCenter(feature.geometry);
        if(!x||!c)return;
        x.lat=c.lat;x.lon=c.lon;
        if(finite(x.area_ha)===null)x.area_ha=finite(p.area_ha);
        if(finite(x.akerscore)===null)x.akerscore=finite(p.akerscore);
        if(finite(x.akerdrift)===null)x.akerdrift=finite(p.akerdrift);
        hydrated++;
      });
    }catch(e){console.warn("ÅkerSwap legacy hydration",k,e);}
  });
  await Promise.all(jobs);
  save();render();
  if(hydrated&&typeof toast==="function")toast("ÅkerSwap återställde "+hydrated+" tidigare klickade skiften.");
}

function haversine(a,b){
  var R=6371, rad=Math.PI/180;
  var p1=a.lat*rad,p2=b.lat*rad,dp=(b.lat-a.lat)*rad,dl=(b.lon-a.lon)*rad;
  var h=Math.sin(dp/2)*Math.sin(dp/2)+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)*Math.sin(dl/2);
  return 2*R*Math.asin(Math.min(1,Math.sqrt(h)));
}
function weightedHub(list){
  var sw=0,lat=0,lon=0;
  list.forEach(function(x){
    var w=Math.max(n(x.area_ha),1e-9);
    sw+=w;lat+=w*x.lat;lon+=w*x.lon;
  });
  return sw>0?{lat:lat/sw,lon:lon/sw}:null;
}
function baseline(listA,listB,hA,hB){
  var s=0;
  listA.forEach(function(x){s+=x.area_ha*haversine(x,hA);});
  listB.forEach(function(x){s+=x.area_ha*haversine(x,hB);});
  return s;
}
function coreCandidate(a,b,hA,hB){
  var rel=Math.abs(a.area_ha-b.area_ha)/Math.max((a.area_ha+b.area_ha)/2,1e-9);
  var ds=Math.abs(a.akerscore-b.akerscore);
  var dd=Math.abs(a.akerdrift-b.akerdrift);
  if(rel>0.20||ds>10||dd>10)return null;
  var before=a.area_ha*haversine(a,hA)+b.area_ha*haversine(b,hB);
  var after =a.area_ha*haversine(a,hB)+b.area_ha*haversine(b,hA);
  var gain=before-after;
  if(gain<=1e-9)return null;
  var changed=a.area_ha+b.area_ha;
  return {a:a,b:b,gain:gain,changed:changed,eff:gain/changed,areaRel:rel,ds:ds,dd:dd};
}
function makeCandidates(listA,listB,hA,hB){
  var out=[];
  listA.forEach(function(a){listB.forEach(function(b){
    var x=coreCandidate(a,b,hA,hB);if(x)out.push(x);
  });});
  return out;
}
function greedy(candidates,total,budgetFrac,efficiency){
  var arr=candidates.slice().sort(function(x,y){
    return efficiency ? y.eff-x.eff : y.gain-x.gain;
  });
  var usedA=new Set(),usedB=new Set(),selected=[],gain=0,changed=0;
  var budget=budgetFrac==null?Infinity:total*budgetFrac;
  arr.forEach(function(x){
    if(usedA.has(x.a.fid)||usedB.has(x.b.fid))return;
    if(changed+x.changed>budget+1e-9)return;
    usedA.add(x.a.fid);usedB.add(x.b.fid);
    selected.push(x);gain+=x.gain;changed+=x.changed;
  });
  return {selected:selected,gain:gain,changed:changed};
}

function render(){
  var a=rows("A"),b=rows("B");
  var ca=document.getElementById("aksCountA"),cb=document.getElementById("aksCountB");
  if(ca)ca.textContent=a.length+" skiften · "+fmt1(totalArea(a))+" ha";
  if(cb)cb.textContent=b.length+" skiften · "+fmt1(totalArea(b))+" ha";
  document.querySelectorAll(".aks-mode").forEach(function(x){
    x.classList.toggle("active",x.dataset.farm===mode);
  });
  var st=document.getElementById("aksStatus");
  if(st)st.textContent=mode ?
    "Klickläge: Bonde "+mode+". Klicka skiften för att lägga till/ta bort." :
    "Klickläge av. Vanligt skiftesklick öppnar ÅkerPass-panelen.";
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
    var c=layer.getBounds().getCenter();
    picks.set(fid,{
      fid:fid,farm:mode,kommun:p.kommun||"",
      block_id:String(p.block_id),skifte_id:String(p.skifte_id),
      area_ha:finite(p.area_ha),akerscore:finite(p.akerscore),akerdrift:finite(p.akerdrift),
      lat:c.lat,lon:c.lng
    });
  }
  save();clearResult(false);render();
}
function clearResult(showToast){
  if(swapOverlay){swapOverlay.remove();swapOverlay=null;}
  var r=document.getElementById("aksResult");if(r)r.innerHTML="";
  if(showToast&&typeof toast==="function")toast("ÅkerSwap-resultatet rensat.");
}
function clearAll(){
  picks.clear();mode=null;save();clearResult(false);render();
  if(typeof toast==="function")toast("ÅkerSwap-valen rensade.");
}

function drawResult(result){
  clearResult(false);
  swapOverlay=L.layerGroup().addTo(map);
  L.circleMarker([result.hA.lat,result.hA.lon],{radius:8,color:COLOR_A,weight:3,fillColor:"#fff",fillOpacity:1})
    .bindTooltip("Infererad hubb A",{permanent:true,direction:"top"}).addTo(swapOverlay);
  L.circleMarker([result.hB.lat,result.hB.lon],{radius:8,color:COLOR_B,weight:3,fillColor:"#fff",fillOpacity:1})
    .bindTooltip("Infererad hubb B",{permanent:true,direction:"top"}).addTo(swapOverlay);
  result.full.selected.slice(0,10).forEach(function(x,i){
    L.polyline([[x.a.lat,x.a.lon],[x.b.lat,x.b.lon]],{
      color:COLOR_SWAP,weight:3,opacity:.78,dashArray:"7 5"
    }).bindTooltip("#"+(i+1)+" · "+fmt1(x.gain)+" ha·km").addTo(swapOverlay);
  });
}

function copySelection(){
  var a=rows("A"),b=rows("B");
  var out=[
    "AKERSWAP_VIRTUAL_FARMERS_SELECT_V0B",
    "A_FIELDS="+a.length,
    "A_AREA_HA="+totalArea(a).toFixed(2),
    "B_FIELDS="+b.length,
    "B_AREA_HA="+totalArea(b).toFixed(2),
    "",
    "[BONDE_A]",
    a.map(function(x){return x.fid;}).join("\n"),
    "",
    "[BONDE_B]",
    b.map(function(x){return x.fid;}).join("\n")
  ].join("\n");
  copyText(out,"Bonde A/B-val kopierade.");
}
function copyText(out,message){
  function fallback(){
    var ta=document.createElement("textarea");ta.value=out;document.body.appendChild(ta);ta.select();
    document.execCommand("copy");ta.remove();if(typeof toast==="function")toast(message);
  }
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(out).then(function(){if(typeof toast==="function")toast(message);}).catch(fallback);
  }else fallback();
}

function runSwap(){
  var rawA=rows("A"),rawB=rows("B"),a=eligible("A"),b=eligible("B");
  if(a.length<2||b.length<2){
    if(typeof toast==="function")toast("Välj minst två analysbara skiften per bonde.");
    return;
  }
  var hA=weightedHub(a),hB=weightedHub(b);
  var base=baseline(a,b,hA,hB);
  var cands=makeCandidates(a,b,hA,hB);
  var total=totalArea(a)+totalArea(b);
  var full=greedy(cands,total,null,false);
  var s5=greedy(cands,total,0.05,true);
  var s10=greedy(cands,total,0.10,true);
  var s20=greedy(cands,total,0.20,true);
  var result={hA:hA,hB:hB,base:base,cands:cands,full:full,s5:s5,s10:s10,s20:s20,total:total};
  drawResult(result);

  var gainPct=base>0?full.gain/base:0;
  var changedPct=total>0?full.changed/total:0;
  var ignored=(rawA.length-a.length)+(rawB.length-b.length);
  var tr=full.selected.slice(0,10).map(function(x,i){
    return "<tr><td>"+(i+1)+"</td><td>A "+htmlEsc(x.a.skifte_id)+"</td><td>B "+htmlEsc(x.b.skifte_id)+"</td><td>"+fmt1(x.gain)+"</td></tr>";
  }).join("");

  var body=document.getElementById("aksResult");
  body.innerHTML=
    '<div class="aks-kpis">'+
      '<div><b>'+pct(gainPct)+'</b><span>full greedy gain</span></div>'+
      '<div><b>'+full.selected.length+'</b><span>föreslagna byten</span></div>'+
      '<div><b>'+pct(changedPct)+'</b><span>areal berörd</span></div>'+
    '</div>'+
    '<div class="aks-small">Single-hub proxy = areaviktad centroid av valda skiften. CORE: areal ±20 %, ÅkerScore ±10, ÅkerDrift ±10. Baseline '+fmt1(base)+' ha·km. Positiva kandidatpar '+cands.length+'.'+(ignored?" "+ignored+" valda skiften saknar komplett analysdata och ignoreras.":"")+'</div>'+
    '<div class="aks-budget"><b>Sparse capture av full gain:</b> 5 % budget → '+(full.gain?pct(s5.gain/full.gain):"–")+
      ' · 10 % → '+(full.gain?pct(s10.gain/full.gain):"–")+
      ' · 20 % → '+(full.gain?pct(s20.gain/full.gain):"–")+'</div>'+
    (tr?'<table class="aks-table"><thead><tr><th>#</th><th>Bonde A</th><th>Bonde B</th><th>gain ha·km</th></tr></thead><tbody>'+tr+'</tbody></table>':
        '<div class="aks-small">Inga positiva CORE-swappar hittades för de två virtuella portföljerna.</div>')+
    '<button id="aksCopyResult" class="action aks-wide" type="button">Kopiera resultat</button>';

  document.getElementById("aksCopyResult").addEventListener("click",function(){
    var out=[
      "AKERSWAP_VIRTUAL_FARMERS_RESULT_V0B",
      "A_FIELDS="+a.length,
      "A_AREA_HA="+totalArea(a).toFixed(2),
      "B_FIELDS="+b.length,
      "B_AREA_HA="+totalArea(b).toFixed(2),
      "BASELINE_AREA_KM="+base.toFixed(2),
      "CORE_POSITIVE_CANDIDATE_PAIRS="+cands.length,
      "FULL_SWAPS="+full.selected.length,
      "FULL_GAIN_PCT="+(100*gainPct).toFixed(1),
      "FULL_CHANGED_AREA_PCT="+(100*changedPct).toFixed(1),
      "CAPTURE_5PCT="+(full.gain?(100*s5.gain/full.gain).toFixed(1):"NA"),
      "CAPTURE_10PCT="+(full.gain?(100*s10.gain/full.gain).toFixed(1):"NA"),
      "CAPTURE_20PCT="+(full.gain?(100*s20.gain/full.gain).toFixed(1):"NA"),
      "HUB_MODEL=AREA_WEIGHTED_CENTROID_PROXY",
      "",
      "[TOP_SWAPS]",
      full.selected.slice(0,10).map(function(x,i){
        return "SWAP"+(i+1)+"=A:"+x.a.fid+" <-> B:"+x.b.fid+
          " | gain_ha_km="+x.gain.toFixed(2)+
          " | areaA="+x.a.area_ha.toFixed(2)+
          " | areaB="+x.b.area_ha.toFixed(2)+
          " | dScore="+x.ds.toFixed(1)+
          " | dDrift="+x.dd.toFixed(1);
      }).join("\n")
    ].join("\n");
    copyText(out,"ÅkerSwap-resultatet kopierat.");
  });
}

function mount(){
  var body=document.querySelector(".control-body");
  if(!body||document.getElementById("akerswapLab"))return;
  var box=document.createElement("section");
  box.id="akerswapLab";box.className="aks-lab";
  box.innerHTML=
    '<span class="label">ÅkerSwap Lab · virtuella bönder</span>'+
    '<div class="aks-help">Aktivera A eller B och klicka skiften. Klicka samma skifte igen för att ta bort det. När båda portföljerna är klara: Kör ÅkerSwap.</div>'+
    '<div class="aks-grid">'+
      '<button class="action aks-mode" data-farm="A" type="button">Bonde A</button>'+
      '<button class="action aks-mode" data-farm="B" type="button">Bonde B</button>'+
    '</div>'+
    '<div class="aks-counts"><span id="aksCountA"></span><span id="aksCountB"></span></div>'+
    '<div id="aksStatus" class="status"></div>'+
    '<div class="aks-grid">'+
      '<button id="aksRun" class="action aks-run" type="button">⇄ Kör ÅkerSwap</button>'+
      '<button id="aksClear" class="action" type="button">Rensa</button>'+
    '</div>'+
    '<button id="aksCopy" class="action aks-wide" type="button">Kopiera A/B</button>'+
    '<div id="aksResult"></div>';
  body.appendChild(box);
  box.querySelectorAll(".aks-mode").forEach(function(x){x.addEventListener("click",function(){setMode(x.dataset.farm);});});
  document.getElementById("aksRun").addEventListener("click",runSwap);
  document.getElementById("aksClear").addEventListener("click",clearAll);
  document.getElementById("aksCopy").addEventListener("click",copySelection);
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
mount();render();hydrateLegacySelections();
})();