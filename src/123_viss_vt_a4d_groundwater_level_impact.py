#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VT-A4d: add VISS groundwater-level impact to field fingerprint/UI.

Final pre-freeze refinement. Only the water-quantity relevant VISS impact
'Förändrade grundvattennivåer' is added. Chemical impacts remain inventoried
but are intentionally excluded from VattenTryck.

No composite score. No legal/permit inference. Existing VT-A1/A2 geometry and
pressure/risk classifications are unchanged.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
A1C=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a1c'
A3=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a3'
DIST=ROOT/'dist'; DATA=DIST/'data'/'akervatten'; JS=DIST/'assets'/'akervatten_v0a.js'
MARK='AKERVATTEN_VISS_UI_V0A'

def load(p):
    if not p.exists(): raise RuntimeError(f'Missing {p}')
    return json.loads(p.read_text(encoding='utf-8-sig'))
def norm(x): return '' if x is None else str(x).strip().upper()

def main():
    impacts=load(A1C/'measuregroundwaterimpactmotivations.json')
    evidence=load(A3/'waterbody_evidence.json')
    level={}
    for r in impacts:
        if str(r.get('Classification') or '').strip()=='Y' and str(r.get('MeasureGroundWaterImpactType') or '').strip()=='Förändrade grundvattennivåer':
            e=norm(r.get('WaterEUID')); level[e]={'motivation':str(r.get('Motivation') or '').strip(),'date':str(r.get('Date') or '')}
    print('='*96); print('ÅkerKontext · VattenTryck — VT-A4d groundwater-level impact'); print('='*96)
    print(f'Positive groundwater-level impact water bodies: {len(level)}')
    for e,x in level.items(): print(f'  {e}: {x["motivation"]}')
    if len(level)!=1 or 'SE625674-131386' not in level: raise RuntimeError('Expected exactly Bjärehalvön as positive groundwater-level impact')

    # Patch sidecars so impact becomes a durable field-level fingerprint attribute.
    files=sorted(DATA.glob('fields_*.json'))
    if not files: raise RuntimeError('No field sidecars; run VT-A4 first')
    n=hit=0
    for p in files:
        rows=load(p); changed=False
        for r in rows:
            e=str(r.get('dominant_EU_CD') or '')
            x=level.get(e)
            r['groundwater_level_impact']=bool(x)
            r['groundwater_level_impact_motivation']=x['motivation'] if x else ''
            n+=1; hit+=bool(x); changed=True
        if changed: p.write_text(json.dumps(rows,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')

    # Embed withdrawal evidence plus level-impact evidence synchronously.
    ev={str(x.get('EU_CD') or ''):{'name':x.get('name'),'withdrawal_motivations':x.get('withdrawal_motivations') or [],'quantitative_risk':x.get('quantitative_risk'),'groundwater_level_impact':level.get(str(x.get('EU_CD') or ''))} for x in evidence}
    ev_json=json.dumps(ev,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    js=JS.read_text(encoding='utf-8'); st='\n/* '+MARK+' BEGIN */'; en='\n/* '+MARK+' END */'
    if st not in js or en not in js: raise RuntimeError('VISS UI block missing; run VT-A4c first')
    a=js.index(st); b=js.index(en,a)+len(en)
    block=r'''/* AKERVATTEN_VISS_UI_V0A BEGIN */
META.viss={title:"VISS / vattenuttag",hint:"VISS-klassad påverkan och risk för den grundvattenförekomst som fältet överlappar. Klassningen gäller vattenförekomsten som helhet, inte den enskilda åkern.",regional:false};
const _vissEvidence=__EVIDENCE__;
const _akvBaseFieldStyle=fieldStyle;fieldStyle=function(feature){if(activeLayer==="vatten"&&currentWaterLayer==="viss"){const r=record(feature.properties);if(!r||!r.viss_positive_case)return{color:"#a9adaa",weight:.5,opacity:.28,fillOpacity:0};return{color:"#f5f5ef",weight:.7,opacity:.9,fillColor:r.quantitative_risk_signal?"#8d5b52":"#c5a56a",fillOpacity:.78};}return _akvBaseFieldStyle(feature);};
const _akvBaseBind=bindWaterTooltips;bindWaterTooltips=function(){if(currentWaterLayer!=="viss")return _akvBaseBind();if(!fieldLayer||activeLayer!=="vatten")return;fieldLayer.eachLayer(function(layer){layer.unbindTooltip();layer.bindTooltip(function(){const p=layer.feature.properties,r=record(p);if(!r||!r.viss_positive_case)return "Skifte "+escText(p.skifte_id)+" · ingen identifierad VISS-klassning";return "Skifte "+escText(p.skifte_id)+" · VISS-grundvattenförekomst: "+escText(r.dominant_name||r.dominant_EU_CD);},{sticky:true,direction:"top"})});};
const _akvBaseLegend=renderLegend;renderLegend=function(){if(activeLayer!=="vatten"||currentWaterLayer!=="viss")return _akvBaseLegend();const collapsed=ui.legend.classList.contains("collapsed");const rows='<div class="legend-row"><span class="legend-swatch" style="background:#8d5b52"></span><span>Förekomst med kvantitativ risksignal</span></div><div class="legend-row"><span class="legend-swatch" style="background:#c5a56a"></span><span>Förekomst med signifikant påverkan från vattenuttag</span></div><div class="legend-row"><span class="legend-swatch" style="background:transparent;border:1px solid #a9adaa"></span><span>Ofärgad: ingen sådan VISS-klassning</span></div>';ui.legend.innerHTML='<button id="legendToggle" class="legend-toggle" type="button" aria-expanded="'+String(!collapsed)+'">🎨</button><div class="legend-content"><div class="legend-title">VISS · grundvattenförekomst</div>'+rows+'<div class="legend-foot">Färgen avser den överlappande vattenförekomstens VISS-klassning, inte aktivitet på den enskilda åkern.</div></div>';document.getElementById("legendToggle").addEventListener("click",function(){ui.legend.classList.toggle("collapsed",!ui.legend.classList.contains("collapsed"));renderLegend()});};
function _vissFlags(r){const a=[];if(r.pressure_agriculture)a.push("jordbrukets vattenuttag");if(r.pressure_municipal)a.push("kommunal/allmän vattentäkt");if(r.pressure_industry)a.push("tillverkningsindustrins vattenuttag");if(r.pressure_generic)a.push("vattenuttag");if(r.pressure_other)a.push("annat vattenuttag");return a;}
function _vissMotivation(r){const e=_vissEvidence[r.dominant_EU_CD];if(!e)return "";const ms=e.withdrawal_motivations||[];const relevant=ms.filter(m=>{const t=String(m.type||"").toLowerCase();return (r.pressure_agriculture&&t.includes("jordbruk"))||(r.pressure_municipal&&(t.includes("kommunal")||t.includes("allmän")))||(r.pressure_industry&&t.includes("tillverkningsindustri"))||(r.pressure_generic&&String(m.type||"").trim()==="3 Vattenuttag")||(r.pressure_other&&t.includes("uttag"));});const use=relevant.length?relevant:ms,uniq=[],seen=new Set();use.forEach(m=>{const s=String(m.motivation||"").trim();if(s&&s!=="-"&&!seen.has(s)){seen.add(s);uniq.push(s)}});if(!uniq.length)return "";return '<details class="akv-note" style="margin-top:8px"><summary><b>VISS bedömning · vattenuttag</b></summary><div style="margin-top:6px">'+uniq.map(escText).join("<br><br>")+'</div></details>';}
function _levelImpact(r){if(!r.groundwater_level_impact)return "";const m=String(r.groundwater_level_impact_motivation||"").trim();return '<span><b>Påverkan på grundvattennivåer: identifierad</b></span>'+(m?'<details class="akv-note" style="margin-top:8px"><summary><b>VISS bedömning · grundvattennivåer</b></summary><div style="margin-top:6px">'+escText(m)+'</div></details>':'');}
function vissRows(r){if(!r.viss_positive_case)return '<div class="akv-large"><div class="akv-large-title">VISS · grundvattenförekomst</div><b>Ingen sådan VISS-klassning för överlappande grundvattenförekomst</b><span>Detta betyder inte att vattenuttag saknas.</span></div>';const flags=_vissFlags(r),ov=r.dominant_overlap_fraction==null?"":("Fältets överlapp: "+fmt(100*Number(r.dominant_overlap_fraction),0)+" %"),pressure=flags.length?"Signifikant påverkan: "+flags.join(" · "):"VISS-klassad påverkan från vattenuttag",risk=r.quantitative_risk_signal?"Kvantitativ risk: potentiell påverkan":"Kvantitativ risk: ingen identifierad";return '<div class="akv-large"><div class="akv-large-title">VISS · grundvattenförekomst</div><b>'+escText(r.dominant_name||r.dominant_EU_CD)+'</b><span>'+ov+'</span><span><b>VISS klassning för vattenförekomsten</b></span><span>'+escText(pressure)+'</span>'+_levelImpact(r)+'<span>'+escText(risk)+'</span><span>EU_CD: '+escText(r.dominant_EU_CD)+(Number(r.viss_gw_relation_count)>1?" · "+r.viss_gw_relation_count+" överlappande förekomster":"")+'</span>'+_vissMotivation(r)+'</div>';}
const _akvBasePanel=panel;panel=function(r){const html=_akvBasePanel(r);if(!r)return html;const note='<div class="akv-note">Klassningen gäller grundvattenförekomsten som helhet, inte den enskilda åkern. Den visar inte om vatten tas från just denna plats.</div>';return html.replace('<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag',vissRows(r)+note+'<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag');};
/* AKERVATTEN_VISS_UI_V0A END */'''.replace('__EVIDENCE__',ev_json)
    JS.write_text(js[:a]+'\n'+block+js[b:],encoding='utf-8')
    print(f'Field sidecar rows updated:              {n:,}')
    print(f'Fields with level-impact flag:           {hit:,}')
    print('Chemical impacts added to VattenTryck:   NO')
    print('Composite score created:                 NO')
    print('Legal/permit inference created:          NO')
    print('VT-A4d FINAL PRE-FREEZE PATCH: PASS'); print('='*96)
if __name__=='__main__': main()
