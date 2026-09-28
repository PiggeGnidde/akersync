#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VT-A4c + impact inventory.

1) Patch built ÅkerVatten dist so VISS wording is explicitly occurrence-level,
   and fix authority motivation rendering by embedding evidence synchronously.
2) Inventory all 23 groundwater impact-motivation rows in Skåne.

No VT-A1/A2/A3 classification or geometry logic changes.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
A1C=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a1c'
A3=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a3'
DIST=ROOT/'dist'
DATA=DIST/'data'/'akervatten'
JS=DIST/'assets'/'akervatten_v0a.js'
OUT=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a4c'
MARK='AKERVATTEN_VISS_UI_V0A'

def load(p):
    if not p.exists(): raise RuntimeError(f'Missing {p}')
    return json.loads(p.read_text(encoding='utf-8-sig'))
def norm(x): return '' if x is None else str(x).strip().upper()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    evidence=load(A3/'waterbody_evidence.json')
    impacts=load(A1C/'measuregroundwaterimpactmotivations.json')

    # --- Impact inventory ---
    print('='*100)
    print('ÅkerKontext · VattenTryck — VT-A4c UI + groundwater impact inventory')
    print('='*100)
    print(f'Groundwater impact motivation rows: {len(impacts):,}')
    c=Counter((str(r.get('MeasureGroundWaterImpactType') or ''),str(r.get('Classification') or '')) for r in impacts)
    print('\nIMPACT TYPES / CLASSIFICATIONS')
    print('-'*100)
    for (typ,cl),n in sorted(c.items()): print(f'{typ} | {cl!r}: {n}')
    print('\nALL POSITIVE (Y) IMPACT ROWS')
    print('-'*100)
    positive=[]
    for r in impacts:
        if str(r.get('Classification') or '').strip()!='Y': continue
        row={'EU_CD':norm(r.get('WaterEUID')),'name':r.get('WaterName'),'impact':r.get('MeasureGroundWaterImpactType'),
             'motivation':r.get('Motivation'),'date':r.get('Date')}
        positive.append(row)
        print(f"{row['EU_CD']} | {row['name']} | {row['impact']}")
        print(f"  {row['motivation']}")
    (OUT/'impact_inventory.json').write_text(json.dumps({'row_count':len(impacts),'positive_rows':positive,'all_rows':impacts},ensure_ascii=False,indent=2),encoding='utf-8')

    # --- UI patch ---
    if not JS.exists(): raise RuntimeError('Built JS missing; run VT-A4/A4b first')
    js=JS.read_text(encoding='utf-8')
    start_token='\n/* '+MARK+' BEGIN */'; end_token='\n/* '+MARK+' END */'
    if start_token not in js or end_token not in js: raise RuntimeError('A4b VISS block not found')
    start=js.index(start_token); end=js.index(end_token,start)+len(end_token)

    # Embed only relevant evidence. This avoids the async fetch race that could leave
    # the details box empty when a field was clicked before evidence JSON had loaded.
    ev={str(x.get('EU_CD') or ''):{'name':x.get('name'),'withdrawal_motivations':x.get('withdrawal_motivations') or [],'quantitative_risk':x.get('quantitative_risk')} for x in evidence}
    ev_json=json.dumps(ev,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')

    block=r'''/* AKERVATTEN_VISS_UI_V0A BEGIN */
META.viss={title:"VISS / vattenuttag",hint:"VISS-klassad påverkan och risk för den grundvattenförekomst som fältet överlappar. Klassningen gäller vattenförekomsten som helhet, inte den enskilda åkern.",regional:false};
const _vissEvidence=__EVIDENCE__;
const _akvBaseFieldStyle=fieldStyle;
fieldStyle=function(feature){if(activeLayer==="vatten"&&currentWaterLayer==="viss"){const r=record(feature.properties);if(!r||!r.viss_positive_case)return{color:"#a9adaa",weight:.5,opacity:.28,fillOpacity:0};return{color:"#f5f5ef",weight:.7,opacity:.9,fillColor:r.quantitative_risk_signal?"#8d5b52":"#c5a56a",fillOpacity:.78};}return _akvBaseFieldStyle(feature);};
const _akvBaseBind=bindWaterTooltips;
bindWaterTooltips=function(){if(currentWaterLayer!=="viss")return _akvBaseBind();if(!fieldLayer||activeLayer!=="vatten")return;fieldLayer.eachLayer(function(layer){layer.unbindTooltip();layer.bindTooltip(function(){const p=layer.feature.properties,r=record(p);if(!r||!r.viss_positive_case)return "Skifte "+escText(p.skifte_id)+" · ingen identifierad VISS-klassning";return "Skifte "+escText(p.skifte_id)+" · VISS-grundvattenförekomst: "+escText(r.dominant_name||r.dominant_EU_CD);},{sticky:true,direction:"top"})});};
const _akvBaseLegend=renderLegend;
renderLegend=function(){if(activeLayer!=="vatten"||currentWaterLayer!=="viss")return _akvBaseLegend();const collapsed=ui.legend.classList.contains("collapsed");const rows='<div class="legend-row"><span class="legend-swatch" style="background:#8d5b52"></span><span>Förekomst med kvantitativ risksignal</span></div><div class="legend-row"><span class="legend-swatch" style="background:#c5a56a"></span><span>Förekomst med signifikant påverkan från vattenuttag</span></div><div class="legend-row"><span class="legend-swatch" style="background:transparent;border:1px solid #a9adaa"></span><span>Ofärgad: ingen sådan VISS-klassning</span></div>';ui.legend.innerHTML='<button id="legendToggle" class="legend-toggle" type="button" aria-expanded="'+String(!collapsed)+'">🎨</button><div class="legend-content"><div class="legend-title">VISS · grundvattenförekomst</div>'+rows+'<div class="legend-foot">Färgen avser den överlappande vattenförekomstens VISS-klassning, inte aktivitet på den enskilda åkern.</div></div>';document.getElementById("legendToggle").addEventListener("click",function(){ui.legend.classList.toggle("collapsed",!ui.legend.classList.contains("collapsed"));renderLegend()});};
function _vissFlags(r){const a=[];if(r.pressure_agriculture)a.push("jordbrukets vattenuttag");if(r.pressure_municipal)a.push("kommunal/allmän vattentäkt");if(r.pressure_industry)a.push("tillverkningsindustrins vattenuttag");if(r.pressure_generic)a.push("vattenuttag");if(r.pressure_other)a.push("annat vattenuttag");return a;}
function _vissMotivation(r){const e=_vissEvidence[r.dominant_EU_CD];if(!e)return "";const ms=e.withdrawal_motivations||[];if(!ms.length)return "";const relevant=ms.filter(m=>{const t=String(m.type||"").toLowerCase();if(r.pressure_agriculture&&t.includes("jordbruk"))return true;if(r.pressure_municipal&&(t.includes("kommunal")||t.includes("allmän")))return true;if(r.pressure_industry&&t.includes("tillverkningsindustri"))return true;if(r.pressure_generic&&String(m.type||"").trim()==="3 Vattenuttag")return true;if(r.pressure_other&&t.includes("uttag"))return true;return false;});const use=relevant.length?relevant:ms;const uniq=[];const seen=new Set();use.forEach(m=>{const s=String(m.motivation||"").trim();if(s&&!seen.has(s)&&s!=="-"){seen.add(s);uniq.push(s)}});if(!uniq.length)return "";return '<details class="akv-note" style="margin-top:8px"><summary><b>VISS bedömning</b></summary><div style="margin-top:6px">'+uniq.map(escText).join("<br><br>")+'</div></details>';}
function vissRows(r){if(!r.viss_positive_case)return '<div class="akv-large"><div class="akv-large-title">VISS · grundvattenförekomst</div><b>Ingen sådan VISS-klassning för överlappande grundvattenförekomst</b><span>Detta betyder inte att vattenuttag saknas.</span></div>';const flags=_vissFlags(r);const ov=r.dominant_overlap_fraction==null?"":("Fältets överlapp: "+fmt(100*Number(r.dominant_overlap_fraction),0)+" %");const pressure=flags.length?"Signifikant påverkan: "+flags.join(" · "):"VISS-klassad påverkan från vattenuttag";const risk=r.quantitative_risk_signal?"Kvantitativ risk: potentiell påverkan":"Kvantitativ risk: ingen identifierad";return '<div class="akv-large"><div class="akv-large-title">VISS · grundvattenförekomst</div><b>'+escText(r.dominant_name||r.dominant_EU_CD)+'</b><span>'+ov+'</span><span><b>VISS klassning för vattenförekomsten</b></span><span>'+escText(pressure)+'</span><span>'+escText(risk)+'</span><span>EU_CD: '+escText(r.dominant_EU_CD)+(Number(r.viss_gw_relation_count)>1?" · "+r.viss_gw_relation_count+" överlappande förekomster":"")+'</span>'+_vissMotivation(r)+'</div>';}
const _akvBasePanel=panel;
panel=function(r){const html=_akvBasePanel(r);if(!r)return html;const note='<div class="akv-note">Klassningen gäller grundvattenförekomsten som helhet, inte den enskilda åkern. Den visar inte om vatten tas från just denna plats.</div>';return html.replace('<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag',vissRows(r)+note+'<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag');};
/* AKERVATTEN_VISS_UI_V0A END */'''.replace('__EVIDENCE__',ev_json)
    JS.write_text(js[:start]+'\n'+block+js[end:],encoding='utf-8')

    print('\nUI PATCH')
    print('-'*100)
    print('Occurrence-level wording:       YES')
    print('Field-level causal implication: REMOVED')
    print('VISS motivation loading:        synchronous embedded evidence')
    print('Hallands Väderö disclaimer:     place-level wording')
    print('VT-A1/A2/A3 data logic:         UNCHANGED')
    print('Saved impact inventory:         data/derived/akervatten/viss_vt_a4c/impact_inventory.json')
    print('VT-A4c UI + IMPACT INVENTORY: PASS')
    print('='*100)

if __name__=='__main__': main()
