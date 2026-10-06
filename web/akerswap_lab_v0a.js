/* AKERSWAP_VIRTUAL_FARMERS_LAB_V0H */
(function(){
"use strict";

var STORE="akerswap_virtual_farmers_v0b";
var HUB_STORE="akerswap_virtual_hubs_v0c";
var LEGACY_STORE="akerswap_virtual_farmers_select_v0a";
var COLOR_A="#1769aa", COLOR_B="#d97706", COLOR_SWAP="#6a3d9a";
var mode=null, hubMode=null, picks=new Map(), swapOverlay=null, hubOverlay=null;
var manualHubs={A:null,B:null};

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
function loadHubs(){
  try{
    var h=JSON.parse(localStorage.getItem(HUB_STORE)||"{}");
    ["A","B"].forEach(function(f){
      var x=h[f];
      if(x&&finite(x.lat)!==null&&finite(x.lon)!==null)manualHubs[f]={lat:Number(x.lat),lon:Number(x.lon)};
    });
  }catch(e){console.warn(e);}
}
function saveHubs(){localStorage.setItem(HUB_STORE,JSON.stringify(manualHubs));}

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
    var manifest=(typeof MANIFEST!=="undefined")?MANIFEST:null;
    var meta=manifest&&manifest.municipalities?manifest.municipalities[k]:null;
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
  var aBeforeKm=haversine(a,hA), aAfterKm=haversine(a,hB);
  var bBeforeKm=haversine(b,hB), bAfterKm=haversine(b,hA);
  var before=a.area_ha*aBeforeKm+b.area_ha*bBeforeKm;
  var after =a.area_ha*aAfterKm+b.area_ha*bAfterKm;
  var gain=before-after;

  // Farmer A gives field a and receives field b.
  // Farmer B gives field b and receives field a.
  var farmerAGain=a.area_ha*aBeforeKm-b.area_ha*bAfterKm;
  var farmerBGain=b.area_ha*bBeforeKm-a.area_ha*aAfterKm;

  if(gain<=1e-9)return null;
  var changed=a.area_ha+b.area_ha;
  return {
    a:a,b:b,gain:gain,changed:changed,eff:gain/changed,areaRel:rel,ds:ds,dd:dd,
    farmerAGain:farmerAGain,farmerBGain:farmerBGain,
    bilateralWin:farmerAGain>=-1e-9 && farmerBGain>=-1e-9,
    aBeforeKm:aBeforeKm,aAfterKm:aAfterKm,bBeforeKm:bBeforeKm,bAfterKm:bAfterKm,
    before:before,after:after
  };
}
function makeCandidates(listA,listB,hA,hB){
  var allPositive=[], winwin=[];
  listA.forEach(function(a){listB.forEach(function(b){
    var x=coreCandidate(a,b,hA,hB);
    if(!x)return;
    allPositive.push(x);
    if(x.bilateralWin)winwin.push(x);
  });});
  return {allPositive:allPositive,winwin:winwin};
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

function renderHubMarkers(){
  if(!hubOverlay)hubOverlay=L.layerGroup().addTo(map);
  hubOverlay.clearLayers();
  ["A","B"].forEach(function(f){
    var h=manualHubs[f];
    if(!h)return;
    var color=f==="A"?COLOR_A:COLOR_B;
    L.circleMarker([h.lat,h.lon],{radius:9,color:color,weight:3,fillColor:"#fff",fillOpacity:1})
      .bindTooltip("Gård / maskinstation "+f,{permanent:true,direction:"top"})
      .addTo(hubOverlay);
  });
}
function render(){
  var a=rows("A"),b=rows("B");
  var ca=document.getElementById("aksCountA"),cb=document.getElementById("aksCountB");
  if(ca)ca.textContent=a.length+" skiften · "+fmt1(totalArea(a))+" ha";
  if(cb)cb.textContent=b.length+" skiften · "+fmt1(totalArea(b))+" ha";
  document.querySelectorAll(".aks-mode").forEach(function(x){
    x.classList.toggle("active",x.dataset.farm===mode);
  });
  document.querySelectorAll(".aks-hub-mode").forEach(function(x){
    x.classList.toggle("active",x.dataset.farm===hubMode);
    var f=x.dataset.farm;
    x.textContent=(manualHubs[f]?"✓ ":"📍 ")+"Gård "+f;
  });
  var ha=document.getElementById("aksHubA"),hb=document.getElementById("aksHubB");
  if(ha)ha.textContent=manualHubs.A?"manuell driftpunkt":"fallback: centroid";
  if(hb)hb.textContent=manualHubs.B?"manuell driftpunkt":"fallback: centroid";
  var st=document.getElementById("aksStatus");
  if(st){
    if(hubMode)st.textContent="Placera Gård "+hubMode+": klicka valfri punkt på kartan.";
    else if(mode)st.textContent="Klickläge: Bonde "+mode+". Klicka skiften för att lägga till/ta bort.";
    else st.textContent="Klickläge av. Vanligt skiftesklick öppnar ÅkerPass-panelen.";
  }
  try{if(fieldLayer)fieldLayer.setStyle(fieldStyle);}catch(e){}
  renderHubMarkers();
}
function setMode(farm){hubMode=null;mode=(mode===farm)?null:farm;render();}
function setHubMode(farm){mode=null;hubMode=(hubMode===farm)?null:farm;render();}
function setManualHub(farm,latlng){
  manualHubs[farm]={lat:Number(latlng.lat),lon:Number(latlng.lng)};
  hubMode=null;saveHubs();clearResult(false);render();
  if(typeof toast==="function")toast("Gård "+farm+" satt.");
}

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
  picks.clear();mode=null;hubMode=null;manualHubs={A:null,B:null};
  save();saveHubs();clearResult(false);render();
  if(typeof toast==="function")toast("ÅkerSwap-val och gårdspunkter rensade.");
}

function drawResult(result){
  clearResult(false);
  swapOverlay=L.layerGroup().addTo(map);
  if(result.sourceA!=="MANUAL"){
    L.circleMarker([result.hA.lat,result.hA.lon],{radius:8,color:COLOR_A,weight:3,fillColor:"#fff",fillOpacity:1})
      .bindTooltip("Infererad hubb A",{permanent:true,direction:"top"}).addTo(swapOverlay);
  }
  if(result.sourceB!=="MANUAL"){
    L.circleMarker([result.hB.lat,result.hB.lon],{radius:8,color:COLOR_B,weight:3,fillColor:"#fff",fillOpacity:1})
      .bindTooltip("Infererad hubb B",{permanent:true,direction:"top"}).addTo(swapOverlay);
  }
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
  var sourceA=manualHubs.A?"MANUAL":"AREA_WEIGHTED_CENTROID_PROXY";
  var sourceB=manualHubs.B?"MANUAL":"AREA_WEIGHTED_CENTROID_PROXY";
  var hA=manualHubs.A||weightedHub(a),hB=manualHubs.B||weightedHub(b);
  var base=baseline(a,b,hA,hB);
  var candidateSets=makeCandidates(a,b,hA,hB);
  var cands=candidateSets.winwin;
  var rejectedOneSided=candidateSets.allPositive.length-cands.length;
  var total=totalArea(a)+totalArea(b);
  var full=greedy(cands,total,null,false);
  var s5=greedy(cands,total,0.05,true);
  var s10=greedy(cands,total,0.10,true);
  var s20=greedy(cands,total,0.20,true);
  var result={hA:hA,hB:hB,sourceA:sourceA,sourceB:sourceB,base:base,cands:cands,rejectedOneSided:rejectedOneSided,full:full,s5:s5,s10:s10,s20:s20,total:total};
  drawResult(result);

  var gainPct=base>0?full.gain/base:0;
  var changedPct=total>0?full.changed/total:0;
  var ignored=(rawA.length-a.length)+(rawB.length-b.length);
  var tr=full.selected.slice(0,10).map(function(x,i){
    var areaDiffPct=100*x.areaRel;
    var gainPerHa=x.changed>0?x.gain/x.changed:0;
    return '<tr class="aks-swap-row" data-swap="'+i+'">'+
      '<td><b>'+(i+1)+'</b></td>'+
      '<td><b>Bonde A</b><small>'+fmt1(x.aBeforeKm)+' → '+fmt1(x.bAfterKm)+' km</small><small>ger A '+htmlEsc(x.a.skifte_id)+' ('+fmt1(x.a.area_ha)+' ha)<br>får B '+htmlEsc(x.b.skifte_id)+' ('+fmt1(x.b.area_ha)+' ha)</small></td>'+
      '<td><b>Bonde B</b><small>'+fmt1(x.bBeforeKm)+' → '+fmt1(x.aAfterKm)+' km</small><small>ger B '+htmlEsc(x.b.skifte_id)+' ('+fmt1(x.b.area_ha)+' ha)<br>får A '+htmlEsc(x.a.skifte_id)+' ('+fmt1(x.a.area_ha)+' ha)</small></td>'+
      '<td class="aks-gain"><b>'+fmt1(x.gain)+'</b><small>'+fmt1(gainPerHa)+' /ha</small><small>A +'+fmt1(x.farmerAGain)+' · B +'+fmt1(x.farmerBGain)+'</small></td>'+
      '<td><small>ΔA '+fmt1(areaDiffPct)+' %<br>ΔScore '+fmt1(x.ds)+'<br>ΔDrift '+fmt1(x.dd)+'</small></td>'+
    '</tr>';
  }).join("");

  var body=document.getElementById("aksResult");
  body.innerHTML=
    '<div class="aks-kpis">'+
      '<div><b>'+pct(gainPct)+'</b><span>full greedy gain</span></div>'+
      '<div><b>'+full.selected.length+'</b><span>föreslagna byten</span></div>'+
      '<div><b>'+pct(changedPct)+'</b><span>areal berörd</span></div>'+
    '</div>'+
    '<div class="aks-small">Driftpunkt A: '+(sourceA==="MANUAL"?"manuell gård/maskinstation":"areaviktad centroid")+
      ' · B: '+(sourceB==="MANUAL"?"manuell gård/maskinstation":"areaviktad centroid")+
      '. Avstånd = fågelvägsproxy från skiftescentrum till driftpunkt. CORE: areal ±20 %, ÅkerScore ±10, ÅkerDrift ±10. Baseline '+fmt1(base)+' ha·km. Positiva kandidatpar '+cands.length+'.'+(ignored?" "+ignored+" valda skiften saknar komplett analysdata och ignoreras.":"")+'</div>'+
    '<div class="aks-budget"><b>Hur mycket mark behöver bytas?</b><br>'+
      'Byt upp till 5 % av marken → få '+(full.gain?pct(s5.gain/full.gain):"–")+' av möjlig körbesparing<br>'+
      'Byt upp till 10 % → få '+(full.gain?pct(s10.gain/full.gain):"–")+'<br>'+
      'Byt upp till 20 % → få '+(full.gain?pct(s20.gain/full.gain):"–")+
      '<br><span class="aks-budget-note">Poängen: några få väl valda skiften kan ge nästan hela nyttan.</span></div>'+
    (tr?'<div class="aks-table-note"><b>Förklaring:</b> varje bonde visar sitt eget avstånd före → efter bytet. Under står vilket fält bonden ger bort och vilket den får. Total gain = sparad ha·km; A/B under gain är respektive bondes egen vinst.</div><div class="aks-table-wrap"><table class="aks-table"><thead><tr><th>#</th><th>Bonde A · före→efter</th><th>Bonde B · före→efter</th><th>gain ha·km</th><th>match</th></tr></thead><tbody>'+tr+'</tbody></table></div>':
        '<div class="aks-small">Inga positiva CORE-swappar hittades för de två virtuella portföljerna.</div>')+
    '<button id="aksCopyResult" class="action aks-wide" type="button">Kopiera resultat</button>';

  document.getElementById("aksCopyResult").addEventListener("click",function(){
    var out=[
      "AKERSWAP_VIRTUAL_FARMERS_RESULT_V0F",
      "A_FIELDS="+a.length,
      "A_AREA_HA="+totalArea(a).toFixed(2),
      "B_FIELDS="+b.length,
      "B_AREA_HA="+totalArea(b).toFixed(2),
      "BASELINE_AREA_KM="+base.toFixed(2),
      "CORE_POSITIVE_TOTAL_PAIRS="+candidateSets.allPositive.length,
      "CORE_WINWIN_CANDIDATE_PAIRS="+cands.length,
      "CORE_REJECTED_ONE_SIDED_PAIRS="+rejectedOneSided,
      "FULL_SWAPS="+full.selected.length,
      "FULL_GAIN_PCT="+(100*gainPct).toFixed(1),
      "FULL_CHANGED_AREA_PCT="+(100*changedPct).toFixed(1),
      "CAPTURE_5PCT="+(full.gain?(100*s5.gain/full.gain).toFixed(1):"NA"),
      "CAPTURE_10PCT="+(full.gain?(100*s10.gain/full.gain).toFixed(1):"NA"),
      "CAPTURE_20PCT="+(full.gain?(100*s20.gain/full.gain).toFixed(1):"NA"),
      "HUB_A_MODEL="+sourceA,
      "HUB_A_LAT="+hA.lat.toFixed(6),
      "HUB_A_LON="+hA.lon.toFixed(6),
      "HUB_B_MODEL="+sourceB,
      "HUB_B_LAT="+hB.lat.toFixed(6),
      "HUB_B_LON="+hB.lon.toFixed(6),
      "",
      "[TOP_SWAPS]",
      full.selected.slice(0,10).map(function(x,i){
        return "SWAP"+(i+1)+"=A:"+x.a.fid+" <-> B:"+x.b.fid+
          " | gain_ha_km="+x.gain.toFixed(2)+
          " | gain_per_changed_ha="+(x.changed?x.gain/x.changed:0).toFixed(2)+
          " | farmerA_gain_ha_km="+x.farmerAGain.toFixed(2)+
          " | farmerB_gain_ha_km="+x.farmerBGain.toFixed(2)+
          " | areaA="+x.a.area_ha.toFixed(2)+
          " | areaB="+x.b.area_ha.toFixed(2)+
          " | area_diff_pct="+(100*x.areaRel).toFixed(1)+
          " | farmerA_km="+x.aBeforeKm.toFixed(2)+"->"+x.bAfterKm.toFixed(2)+
          " | farmerB_km="+x.bBeforeKm.toFixed(2)+"->"+x.aAfterKm.toFixed(2)+
          " | outgoing_field_A_to_B_km="+x.aBeforeKm.toFixed(2)+"->"+x.aAfterKm.toFixed(2)+
          " | outgoing_field_B_to_A_km="+x.bBeforeKm.toFixed(2)+"->"+x.bAfterKm.toFixed(2)+
          " | pair_before_ha_km="+x.before.toFixed(2)+
          " | pair_after_ha_km="+x.after.toFixed(2)+
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
    '<div class="aks-grid aks-hub-grid">'+
      '<button class="action aks-hub-mode" data-farm="A" type="button">📍 Gård A</button>'+
      '<button class="action aks-hub-mode" data-farm="B" type="button">📍 Gård B</button>'+
    '</div>'+
    '<div class="aks-hub-status"><span id="aksHubA"></span><span id="aksHubB"></span></div>'+
    '<div id="aksStatus" class="status"></div>'+
    '<div class="aks-grid">'+
      '<button id="aksRun" class="action aks-run" type="button">⇄ Kör ÅkerSwap</button>'+
      '<button id="aksClear" class="action" type="button">Rensa</button>'+
    '</div>'+
    '<button id="aksCopy" class="action aks-wide" type="button">Kopiera A/B</button>'+
    '<div id="aksResult"></div>';
  body.appendChild(box);
  box.querySelectorAll(".aks-mode").forEach(function(x){x.addEventListener("click",function(){setMode(x.dataset.farm);});});
  box.querySelectorAll(".aks-hub-mode").forEach(function(x){x.addEventListener("click",function(){setHubMode(x.dataset.farm);});});
  document.getElementById("aksRun").addEventListener("click",runSwap);
  document.getElementById("aksClear").addEventListener("click",clearAll);
  document.getElementById("aksCopy").addEventListener("click",copySelection);
}
load();loadHubs();

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
    if(hubMode)return;
    if(mode){toggle(feature,layer);return;}
    return baseSelectField(feature,layer,writeUrl===undefined?true:writeUrl);
  };
}
map.on("click",function(e){
  if(!hubMode)return;
  var farm=hubMode;
  setManualHub(farm,e.latlng);
});
mount();render();hydrateLegacySelections();
})();