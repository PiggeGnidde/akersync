#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VT-A4: add VISS as seventh ÅkerVatten information view in an existing dist.

Uses frozen VT-A3 field fingerprint. Patches only ÅkerVatten-owned field sidecars,
ÅkerVatten JS and the ÅkerVatten control block in index.html. No model is
recalculated and no composite score is created.
"""
from __future__ import annotations
import json, re, shutil
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/"dist"
A3=ROOT/"data/derived/akervatten/viss_vt_a3"
MARK="AKERVATTEN_VISS_UI_V0A"
COLS=["viss_positive_case","viss_gw_relation_count","viss_gw_eu_cd","dominant_EU_CD","dominant_name","dominant_overlap_fraction","pressure_agriculture","pressure_municipal","pressure_industry","pressure_generic","pressure_other","quantitative_risk_signal"]

def stable(o): return json.dumps(o,ensure_ascii=False,separators=(",",":"))+"\n"

def main():
    fp_path=A3/"field_viss_fingerprint.parquet"
    ev_path=A3/"waterbody_evidence.json"
    if not fp_path.exists() or not ev_path.exists(): raise RuntimeError("Run src/117_viss_vt_a3_field_fingerprint.py first")
    if not (DIST/"index.html").exists(): raise RuntimeError(f"Existing ÅkerVatten dist missing: {DIST}")
    fp=pd.read_parquet(fp_path).set_index("field_id",drop=False)
    if len(fp)!=128636: raise RuntimeError(f"Expected 128,636 fingerprint rows, got {len(fp):,}")
    evidence=json.loads(ev_path.read_text(encoding="utf-8"))
    ev={x["EU_CD"]:x for x in evidence}

    # Existing sidecars define municipality membership; enrich them in place.
    data_dir=DIST/"data/akervatten"
    files=sorted(p for p in data_dir.glob("*.json") if p.name!="skane_index.json")
    total=0; hit=0
    for p in files:
        d=json.loads(p.read_text(encoding="utf-8"))
        if d.get("schema_version")!="akervatten-web-field-v0a" or "fields" not in d: continue
        oldcols=list(d["columns"])
        # idempotent: remove an earlier VT-A4 tail if rerun.
        keep=[i for i,c in enumerate(oldcols) if c not in COLS]
        newfields={}
        for fid,row in d["fields"].items():
            base=[row[i] for i in keep]
            r=fp.loc[fid] if fid in fp.index else None
            if r is None: raise RuntimeError(f"Field {fid} from web sidecar missing in VT-A3")
            vals=[
                bool(r.viss_positive_case),int(r.viss_gw_relation_count),str(r.viss_gw_eu_cd or ""),str(r.dominant_EU_CD or ""),str(r.dominant_name or ""),
                None if pd.isna(r.dominant_overlap_fraction) else round(float(r.dominant_overlap_fraction),4),
                bool(r.pressure_agriculture),bool(r.pressure_municipal),bool(r.pressure_industry),bool(r.pressure_generic),bool(r.pressure_other),bool(r.quantitative_risk_signal)
            ]
            newfields[fid]=base+vals
            total+=1; hit+=int(bool(r.viss_positive_case))
        d["columns"]=[oldcols[i] for i in keep]+COLS
        d["fields"]=newfields
        p.write_text(stable(d),encoding="utf-8")
    if total!=128636 or hit!=16626: raise RuntimeError(f"Sidecar reconciliation failed: total={total:,}, VISS={hit:,}")

    # Evidence is tiny (16 water bodies) and belongs to ÅkerVatten-owned data.
    (data_dir/"viss_evidence.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    index=DIST/"index.html"; html=index.read_text(encoding="utf-8")
    if MARK not in html:
        anchor='<button type="button" class="akv-sub" data-akv-layer="sw_drought">Ytvatten</button>'
        if html.count(anchor)!=1: raise RuntimeError("Could not locate ÅkerVatten sublayer controls")
        html=html.replace(anchor,anchor+'\n    <button type="button" class="akv-sub" data-akv-layer="viss">VISS / uttag</button>',1)
        html=html.replace("<!-- AKERVATTEN_WEB_UI_V0A -->","<!-- AKERVATTEN_WEB_UI_V0A -->\n<!-- "+MARK+" -->",1)
        index.write_text(html,encoding="utf-8")

    js_path=DIST/"assets/akervatten_v0a.js"; js=js_path.read_text(encoding="utf-8")
    # Always start from current source asset when rerunning after a previous patch.
    if MARK in js:
        start=js.index("\n/* "+MARK+" BEGIN */")
        end=js.index("\n/* "+MARK+" END */",start)+len("\n/* "+MARK+" END */")
        js=js[:start]+js[end:]
    insertion=r'''
/* AKERVATTEN_VISS_UI_V0A BEGIN */
META.viss={title:"VISS / vattenuttag",hint:"Myndighetsklassad signifikant påverkan och kvantitativ risksignal för överlappande grundvattenförekomst. Inte uttagsvolym eller tillstånd.",regional:false};
const _akvBaseFieldStyle=fieldStyle;
fieldStyle=function(feature){
 if(activeLayer==="vatten"&&currentWaterLayer==="viss"){
  const r=record(feature.properties);
  if(!r||!r.viss_positive_case)return{color:"#a9adaa",weight:.5,opacity:.28,fillColor:"#d7d9d5",fillOpacity:.06};
  return{color:"#f5f5ef",weight:.7,opacity:.9,fillColor:r.quantitative_risk_signal?"#8d5b52":"#c5a56a",fillOpacity:.78};
 }
 return _akvBaseFieldStyle(feature);
};
const _akvBaseBind=bindWaterTooltips;
bindWaterTooltips=function(){
 if(currentWaterLayer!=="viss")return _akvBaseBind();
 if(!fieldLayer||activeLayer!=="vatten")return;
 fieldLayer.eachLayer(function(layer){layer.unbindTooltip();layer.bindTooltip(function(){const p=layer.feature.properties,r=record(p);if(!r||!r.viss_positive_case)return "Skifte "+escText(p.skifte_id)+" · ingen positiv VISS-signal";return "Skifte "+escText(p.skifte_id)+" · "+escText(r.dominant_name||r.dominant_EU_CD)+(r.quantitative_risk_signal?" · kvantitativ risksignal":"");},{sticky:true,direction:"top"})});
};
const _akvBaseLegend=renderLegend;
renderLegend=function(){
 if(activeLayer!=="vatten"||currentWaterLayer!=="viss")return _akvBaseLegend();
 const collapsed=ui.legend.classList.contains("collapsed");
 const rows='<div class="legend-row"><span class="legend-swatch" style="background:#8d5b52"></span><span>Kvantitativ risksignal</span></div><div class="legend-row"><span class="legend-swatch" style="background:#c5a56a"></span><span>Annan positiv VISS-uttagssignal</span></div><div class="legend-row"><span class="legend-swatch" style="background:#d7d9d5"></span><span>Ingen positiv signal i datamängden</span></div>';
 ui.legend.innerHTML='<button id="legendToggle" class="legend-toggle" type="button" aria-expanded="'+String(!collapsed)+'">🎨</button><div class="legend-content"><div class="legend-title">VISS / vattenuttag</div>'+rows+'<div class="legend-foot">Ingen totalscore. Frånvaro av signal bevisar inte frånvaro av uttag.</div></div>';
 document.getElementById("legendToggle").addEventListener("click",function(){ui.legend.classList.toggle("collapsed",!ui.legend.classList.contains("collapsed"));renderLegend()});
};
function vissRows(r){
 if(!r.viss_positive_case)return '<div class="akv-large"><div class="akv-large-title">VISS · vattenuttag och kvantitativ påverkan</div><b>Ingen positiv VISS-signal i denna datamängd</b><span>Detta ska inte tolkas som att vattenuttag saknas.</span></div>';
 const flags=[];if(r.pressure_agriculture)flags.push("Jordbruksuttag");if(r.pressure_municipal)flags.push("Kommunal/allmän vattentäkt");if(r.pressure_industry)flags.push("Tillverkningsindustri");if(r.pressure_generic)flags.push("Vattenuttag");if(r.pressure_other)flags.push("Annat signifikant vattenuttag");
 const ov=r.dominant_overlap_fraction==null?"":(" · överlapp "+fmt(100*Number(r.dominant_overlap_fraction),0)+" %");
 return '<div class="akv-large"><div class="akv-large-title">VISS · vattenuttag och kvantitativ påverkan</div><b>'+escText(r.dominant_name||r.dominant_EU_CD)+ov+'</b><span>'+(flags.length?escText(flags.join(" · ")):"Positiv VISS-signal")+'</span><span>'+(r.quantitative_risk_signal?"Kvantitativ risksignal: potentiell påverkan":"Ingen kvantitativ risksignal i den positiva case-definitionen")+'</span><span>EU_CD: '+escText(r.dominant_EU_CD)+(Number(r.viss_gw_relation_count)>1?" · "+r.viss_gw_relation_count+" överlappande förekomster":"")+'</span></div>';
}
const _akvBasePanel=panel;
panel=function(r){
 const html=_akvBasePanel(r);if(!r)return html;
 const note='<div class="akv-note">VISS beskriver myndighetsklassad påverkan/risk på grundvattenförekomsten. Uppgiften anger inte hur mycket vatten som tas från denna åker, om lantbrukaren tar vatten eller om uttag har tillstånd.</div>';
 return html.replace('<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag',vissRows(r)+note+'<div class="akv-note">Hydrologiskt/hydrogeologiskt underlag');
};
/* AKERVATTEN_VISS_UI_V0A END */
'''
    close="\n})();"
    if js.count(close)!=1: raise RuntimeError("Unexpected ÅkerVatten JS closure")
    js=js.replace(close,insertion+close,1)
    js_path.write_text(js,encoding="utf-8")

    print("="*88)
    print("ÅkerKontext · VattenTryck — VT-A4 web patch")
    print("="*88)
    print(f"Fields enriched:              {total:,}")
    print(f"Positive VISS fields:         {hit:,}")
    print("Seventh view:                 VISS / uttag")
    print("Composite VattenTryck score:  NOT CREATED")
    print("Legal/permit inference:       NOT CREATED")
    print(f"Output: {DIST/'index.html'}")
    print("VT-A4 WEB PATCH: PASS")
    print("="*88)

if __name__=="__main__": main()
