#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VT-A4b: clarify VISS product language and show VISS authority motivation.

Patches the already-built VT-A4 dist only. No data/model logic changes.
"""
from __future__ import annotations
import json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/"dist"
DATA=DIST/"data/akervatten"
JS=DIST/"assets/akervatten_v0a.js"
MARK="AKERVATTEN_VISS_UI_V0A"


def main():
    if not JS.exists(): raise RuntimeError("ÅkerVatten JS missing; run VT-A4 first")
    ev_path=DATA/"viss_evidence.json"
    if not ev_path.exists(): raise RuntimeError("viss_evidence.json missing; run VT-A4 first")
    evidence=json.loads(ev_path.read_text(encoding="utf-8"))
    ev={str(x.get("EU_CD") or ""):x for x in evidence}

    # Compact UI evidence file: retain exact VISS motivation text and dates by EU_CD.
    compact={}
    for euid,x in ev.items():
        compact[euid]={
            "name":x.get("name") or euid,
            "withdrawal_motivations":x.get("withdrawal_motivations") or [],
            "quantitative_risk":x.get("quantitative_risk"),
        }
    (DATA/"viss_evidence_ui.json").write_text(json.dumps(compact,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")

    js=JS.read_text(encoding="utf-8")
    start_token="\n/* "+MARK+" BEGIN */"
    end_token="\n/* "+MARK+" END */"
    if start_token not in js or end_token not in js: raise RuntimeError("VT-A4 VISS block not found in JS")
    start=js.index(start_token)
    end=js.index(end_token,start)+len(end_token)

    block=r'''
/* AKERVATTEN_VISS_UI_V0A BEGIN */
META.viss={title:"VISS / vattenuttag",hint:"VISS-klassad påverkan från vattenuttag och kvantitativ risk för överlappande grundvattenförekomst. Klassningen gäller vattenförekomsten, inte den enskilda åkern.",regional:false};
let _vissEvidence={};
fetch("data/akervatten/viss_evidence_ui.json").then(r=>r.ok?r.json():{}).then(x=>{_vissEvidence=x||{};}).catch(()=>{});
const _akvBaseFieldStyle=fieldStyle;
fieldStyle=function(feature){
 if(activeLayer==="vatten"&&currentWaterLayer==="viss"){
  const r=record(feature.properties);
  if(!r||!r.viss_positive_case)return{color:"#a9adaa",weight:.5,opacity:.28,fillOpacity:0};
  return{color:"#f5f5ef",weight:.7,opacity:.9,fillColor:r.quantitative_risk_signal?"#8d5b52":"#c5a56a",fillOpacity:.78};
 }
 return _akvBaseFieldStyle(feature);
};
const _akvBaseBind=bindWaterTooltips;
bindWaterTooltips=function(){
 if(currentWaterLayer!=="viss")return _akvBaseBind();
 if(!fieldLayer||activeLayer!=="vatten")return;
 fieldLayer.eachLayer(function(layer){layer.unbindTooltip();layer.bindTooltip(function(){const p=layer.feature.properties,r=record(p);if(!r||!r.viss_positive_case)return "Skifte "+escText(p.skifte_id)+" · ingen identifierad VISS-klassning";return "Skifte "+escText(p.skifte_id)+" · "+escText(r.dominant_name||r.dominant_EU_CD)+(r.quantitative_risk_signal?" · kvantitativ risk":" · påverkan från vattenuttag");},{sticky:true,direction:"top"})});
};
const _akvBaseLegend=renderLegend;
renderLegend=function(){
 if(activeLayer!=="vatten"||currentWaterLayer!=="viss")return _akvBaseLegend();
 const collapsed=ui.legend.classList.contains("collapsed");
 const rows='<div class="legend-row"><span class="legend-swatch" style="background:#8d5b52"></span><span>Kvantitativ risk identifierad</span></div><div class="legend-row"><span class="legend-swatch" style="background:#c5a56a"></span><span>Signifikant påverkan från vattenuttag</span></div><div class="legend-row"><span class="legend-swatch" style="background:transparent;border:1px solid #a9adaa"></span><span>Ofärgad: ingen sådan VISS-klassning</span></div>';
 ui.legend.innerHTML='<button id="legendToggle" class="legend-toggle" type="button" aria-expanded="'+String(!collapsed)+'">🎨</button><div class="legend-content"><div class="legend-title">VISS · påverkan på grundvatten</div>'+rows+'<div class="legend-foot">Ingen totalscore. Avsaknad av VISS-klassning innebär inte att vattenuttag saknas.</div></div>';
 document.getElementById("legendToggle").addEventListener("click",function(){ui.legend.classList.toggle("collapsed",!ui.legend.classList.contains("collapsed"));renderLegend()});
};
function _vissFlags(r){const a=[];if(r.pressure_agriculture)a.push("jordbrukets vattenuttag");if(r.pressure_municipal)a.push("kommunal/allmän vattentäkt");if(r.pressure_industry)a.push("tillverkningsindustrins vattenuttag");if(r.pressure_generic)a.push("vattenuttag");if(r.pressure_other)a.push("annat vattenuttag");return a;}
function _vissMotivation(r){
 const e=_vissEvidence[r.dominant_EU_CD];if(!e)return "";
 const ms=e.withdrawal_motivations||[];if(!ms.length)return "";
 const relevant=ms.filter(m=>{const t=String(m.type||"").toLowerCase();if(r.pressure_agriculture&&t.includes("jordbruk"))return true;if(r.pressure_municipal&&(t.includes("kommunal")||t.includes("allmän")))return true;if(r.pressure_industry&&t.includes("tillverkningsindustri"))return true;if(r.pressure_generic&&String(m.type||"").trim()==="3 Vattenuttag")return true;if(r.pressure_other&&t.includes("uttag"))return true;return false;});
 const use=relevant.length?relevant:ms;const uniq=[];const seen=new Set();use.forEach(m=>{const s=String(m.motivation||"").trim();if(s&&!seen.has(s)){seen.add(s);uniq.push(s)}});if(!uniq.length)return "";
 return '<details class="akv-note" style="margin-top:8px"><summary><b>VISS bedömning</b></summary><div style="margin-top:6px">'+uniq.map(escText).join("<br><br>")+'</div></details>';
}
function vissRows(r){
 if(!r.viss_positive_case)return '<div class="akv-large"><div class="akv-large-title">VISS · påverkan på grundvatten</div><b>Ingen sådan VISS-klassning för överlappande grundvattenförekomst</b><span>Detta betyder inte att vattenuttag saknas.</span></div>';
 const flags=_vissFlags(r);const ov=r.dominant_overlap_fraction==null?"":(" · överlapp "+fmt(100*Number(r.dominant_overlap_fraction),0)+" %");
 const pressure=flags.length?"Signifikant påverkan: "+flags.join(" · "):"VISS-klassad påverkan från vattenuttag";
 const risk=r.quantitative_risk_signal?"Kvantitativ risk: potentiell påverkan":"Kvantitativ risk: ingen identifierad";
 return '<div class="akv-large"><div class="akv-large-title">VISS · påverkan på grundvatten</div><b>'+escText(r.dominant_name||r.dominant_EU_CD)+ov+'</b><span>'+escText(pressure)+'</span><span>'+escText(risk)+'</span><span>EU_CD: '+escText(r.dominant_EU_CD)+(Number(r.viss_gw_relation_count)>1?" · "+r.viss_gw_relation_count+" överlappande förekomster":"")+'</span>'+_vissMotivation(r)+'</div>';
}
const _akvBasePanel=panel;
panel=function(r){
 const html=_akvBasePanel(r);if(!r)return html;
 const note='<div class="akv-note">Klassningen gäller grundvattenförekomsten, inte den enskilda åkern. Den visar inte om just denna lantbrukare tar vatten eller har tillstånd.</div>';
 return html.replace('<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag',vissRows(r)+note+'<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag');
};
/* AKERVATTEN_VISS_UI_V0A END */
'''
    JS.write_text(js[:start]+"\n"+block+js[end:],encoding="utf-8")
    print("="*88)
    print("ÅkerKontext · VattenTryck — VT-A4b UI polish")
    print("="*88)
    print("Language:                     clarified")
    print("'positive signal' wording:   removed from user-facing VISS UI")
    print("No-signal map fill:           transparent")
    print("VISS motivation:              added as expandable authority text")
    print("Data/model logic:             UNCHANGED")
    print("VT-A4b UI POLISH: PASS")
    print("="*88)

if __name__=="__main__": main()
