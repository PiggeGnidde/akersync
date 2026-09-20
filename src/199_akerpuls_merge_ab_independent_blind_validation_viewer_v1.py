#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build independent blind validation viewer for S2026/Hprior tiers A vs B.

Population:
  A_CONFIRMED_HIGH   = S2026>P90 and Hprior>P75
  B_SAT_HIGH_H_MID   = S2026>P90 and P25<Hprior<=P75

Exactly 50 deterministic hash-sampled pairs from each tier AFTER excluding all
100 pair_keys used in the first frozen blind audit. The first audit's human
labels are not used for sampling or rendering.

Browser blindness:
  tier, pair_key, field ids, S2026/Hprior scores, M0 status hidden.
Only four frozen 2026 Sentinel-2 RGB panels and the old shared 2025 boundary.

No fusion, threshold tuning, automatic merge, cross-block merge, or geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"

RANKING=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_sh_gated_ranking_v1\MERGE_SH_GATED_RANKING_V1.parquet")
EXPECTED_RANKING_SHA="288a07042eaa80256541e6c25c14acd9a4b0fc0767822db540f831f0ae668e10"
RANKING_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_sh_gated_ranking_freeze_v1\AKERPULS_MERGE_SH_GATED_RANKING_FREEZE_V1.json")
EXPECTED_RANKING_FREEZE_SHA="2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"

FIRST_REVEALED_JOIN=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_v1\MERGE_AUDIT_REVEALED_JOIN.csv")
EXPECTED_FIRST_JOIN_SHA="bce010ece5982599231117e83fb301f3391b78b00e5d6e39abc700588b63e284"

M0_GPKG=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1\m0_satellite_merge_boundaries.gpkg")
M0_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json")
EXPECTED_M0_FREEZE_SHA="fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"

D1_DIR=Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1")
VRT_INDEX=D1_DIR/"d1s3j_vrt_outputs.csv"
EXPECTED_VRT_INDEX_SHA="0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979"

DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_viewer_v1")
STATUS="PASS_TO_INDEPENDENT_BLIND_AB_VALIDATION"
SAMPLE_PER_TIER=50
EXPECTED_SAMPLE=100
EXPECTED_FIRST_AUDIT=100
TIERS=["A_CONFIRMED_HIGH","B_SAT_HIGH_H_MID"]
SAMPLE_SALT="akerpuls-merge-ab-independent-validation-v1|2026-09-20|2f98d504|exclude-first100"
ORDER_SALT="akerpuls-merge-ab-independent-order-v1|2026-09-20|2f98d504|exclude-first100"

LABELS=["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"]
PREDECLARED_ANALYSIS={
    "primary_endpoint":"broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE among assessable",
    "secondary_endpoint":"strict_positive = TYDLIG_MERGE among assessable",
    "primary_contrast":"A_CONFIRMED_HIGH vs B_SAT_HIGH_H_MID",
    "tests":["two-sided Fisher exact","risk difference","Wilson 95% CI by tier"],
    "exclude":"EJ_BEDÖMBAR",
    "TVEKSAM_is_nonpositive":True,
    "no_operational_threshold_preselected":True,
    "no_fusion_weight_preselected":True,
}


def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def htxt(x:str)->str:
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


def git_guard()->str:
    branch=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if branch!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {branch}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def load_render_module():
    p=ROOT/"src"/"191_akerpuls_merge_blind_disagreement_audit_viewer_v1b.py"
    spec=importlib.util.spec_from_file_location("render191",p)
    m=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def verify_inputs():
    if not RANKING.is_file() or sha(RANKING)!=EXPECTED_RANKING_SHA:
        raise RuntimeError("Frozen ranking parquet missing or changed")
    if not RANKING_FREEZE.is_file() or sha(RANKING_FREEZE)!=EXPECTED_RANKING_FREEZE_SHA:
        raise RuntimeError("Ranking freeze missing or changed")
    if not FIRST_REVEALED_JOIN.is_file() or sha(FIRST_REVEALED_JOIN)!=EXPECTED_FIRST_JOIN_SHA:
        raise RuntimeError("First-audit revealed join missing or changed")
    if not M0_FREEZE.is_file() or sha(M0_FREEZE)!=EXPECTED_M0_FREEZE_SHA:
        raise RuntimeError("M0 freeze missing or changed")
    m0f=json.loads(M0_FREEZE.read_text(encoding="utf-8-sig"))
    gpkg_sha=m0f.get("source_hashes",{}).get("source_boundaries_gpkg_sha256")
    if not gpkg_sha or not M0_GPKG.is_file() or sha(M0_GPKG)!=gpkg_sha:
        raise RuntimeError("M0 shared-boundary GPKG missing or changed")
    if not VRT_INDEX.is_file() or sha(VRT_INDEX)!=EXPECTED_VRT_INDEX_SHA:
        raise RuntimeError("D1 VRT index missing or changed")
    rows=pd.read_csv(VRT_INDEX,encoding="utf-8-sig")
    vrt_paths={}
    for snap in ["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]:
        r=rows.loc[rows["snapshot"].astype(str)==snap]
        if len(r)!=1: raise RuntimeError(f"Expected one VRT row for {snap}")
        p=Path(str(r.iloc[0]["path"]))
        if not p.is_file() or sha(p)!=str(r.iloc[0]["sha256"]):
            raise RuntimeError(f"VRT changed for {snap}")
        vrt_paths[snap]=p
    return gpkg_sha,vrt_paths


def make_html(items,key_sha:str)->str:
    payload=json.dumps(items,ensure_ascii=False,separators=(",",":")).replace("</","<\\/")
    labs=json.dumps(LABELS,ensure_ascii=False)
    template=r'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – oberoende blind merge-validering</title><style>
:root{font-family:Arial,sans-serif;color:#171717;background:#f5f5f5}body{margin:0}.top{position:sticky;top:0;z-index:3;background:#fff;border-bottom:1px solid #ccc;padding:10px 14px}.main{max-width:1600px;margin:12px auto;padding:0 12px 30px}.card{background:#fff;border:1px solid #ccc;border-radius:7px;padding:10px}.auditimg{display:block;width:100%;height:auto;background:#ddd}.labels{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.labels button,.nav button,#exportBtn{padding:9px 12px;border:1px solid #888;border-radius:5px;background:#fff;cursor:pointer}.labels button.sel{outline:3px solid #111;font-weight:bold}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.note{width:100%;min-height:55px;box-sizing:border-box}.muted{color:#555;font-size:13px}.warn{font-weight:bold}.progress{font-variant-numeric:tabular-nums}</style></head><body>
<div class="top"><div class="row"><b>ÅkerPuls – oberoende blind merge-validering</b><span id="pos" class="progress"></span><span id="done" class="progress"></span></div>
<div class="muted">Cyan = gemensam officiell 2025-gräns. Tier, scores, fält-ID och tidigare audit är dolda.</div></div>
<div class="main"><div class="card"><img id="img" class="auditimg"><p><b>Bedömning:</b> Tyder 2026-bilderna på att de två 2025-skiftena nu fungerar som ett och samma skifte så att den cyan gränsen bör tas bort?</p>
<div class="labels" id="labels"></div><textarea id="note" class="note" placeholder="Frivillig kort kommentar"></textarea>
<div class="row nav"><button id="prev">← Föregående</button><button id="next">Nästa →</button><button id="exportBtn">Exportera validation CSV</button><span class="muted">1–5 = etikett, ←/→ = navigera.</span></div>
<p class="muted warn">Samma gröda/färg på båda sidor räcker inte i sig för merge. Leta efter evidens att den gamla brukningsgränsen faktiskt inte längre fungerar som separat 2026-gräns över säsongen.</p>
<p class="muted warn">Öppna inte AB_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv före export och freeze av etiketterna.</p></div></div>
<script>
const ITEMS=__ITEMS__, LABELS=__LABELS__, RANKFREEZE='__RANKFREEZE__', KEYSHA='__KEYSHA__';
const STORE='akerpuls_merge_ab_validation_v1_'+RANKFREEZE.slice(0,12)+'_'+KEYSHA.slice(0,12);let state=JSON.parse(localStorage.getItem(STORE)||'{}'),idx=0;
function save(){localStorage.setItem(STORE,JSON.stringify(state));}function cur(){return ITEMS[idx];}
function render(){const it=cur(),r=state[it.blind_index]||{};document.getElementById('img').src=it.image;document.getElementById('pos').textContent='Par '+(idx+1)+'/'+ITEMS.length+' · blind #'+String(it.blind_index).padStart(3,'0');document.getElementById('note').value=r.note||'';const box=document.getElementById('labels');box.innerHTML='';LABELS.forEach(function(lab){const b=document.createElement('button');b.textContent=lab;if(r.merge_label===lab)b.classList.add('sel');b.onclick=function(){const rr=state[it.blind_index]||{};rr.merge_label=lab;rr.note=document.getElementById('note').value;state[it.blind_index]=rr;save();render();};box.appendChild(b);});const n=ITEMS.filter(function(x){return state[x.blind_index]&&state[x.blind_index].merge_label;}).length;document.getElementById('done').textContent='Bedömda '+n+'/'+ITEMS.length;}
document.getElementById('note').addEventListener('input',function(e){const it=cur(),r=state[it.blind_index]||{};r.note=e.target.value;state[it.blind_index]=r;save();});document.getElementById('prev').onclick=function(){idx=Math.max(0,idx-1);render();};document.getElementById('next').onclick=function(){idx=Math.min(ITEMS.length-1,idx+1);render();};
document.addEventListener('keydown',function(e){if(document.activeElement===document.getElementById('note'))return;if(e.key>='1'&&e.key<='5'){const it=cur(),r=state[it.blind_index]||{};r.merge_label=LABELS[Number(e.key)-1];state[it.blind_index]=r;save();render();return;}if(e.key==='ArrowRight'){idx=Math.min(ITEMS.length-1,idx+1);render();}else if(e.key==='ArrowLeft'){idx=Math.max(0,idx-1);render();}});
function q(s){return '"'+String(s||'').replaceAll('"','""')+'"';}
document.getElementById('exportBtn').onclick=function(){const missing=ITEMS.filter(function(x){return !(state[x.blind_index]&&state[x.blind_index].merge_label);});if(missing.length&&!confirm(String(missing.length)+' par saknar etikett. Exportera ändå?'))return;const rows=[['sh_gated_ranking_freeze_sha256','blind_key_sha256','blind_index','merge_label','note']];ITEMS.forEach(function(it){const r=state[it.blind_index]||{};rows.push([RANKFREEZE,KEYSHA,it.blind_index,r.merge_label||'',r.note||'']);});const csv='\ufeff'+rows.map(function(r){return r.map(q).join(',');}).join('\r\n')+'\r\n';const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='merge_ab_independent_validation_labels.csv';a.click();setTimeout(function(){URL.revokeObjectURL(a.href);},1000);};render();
</script></body></html>'''
    return template.replace("__ITEMS__",payload).replace("__LABELS__",labs).replace("__RANKFREEZE__",EXPECTED_RANKING_FREEZE_SHA).replace("__KEYSHA__",key_sha)


def main()->int:
    import geopandas as gpd

    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()
    head=git_guard(); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Output already exists: {out}")
    gpkg_sha,vrt_paths=verify_inputs()

    print("AKERPULS MERGE A/B INDEPENDENT BLIND VALIDATION VIEWER V1")
    print(f"GIT_HEAD={head}")
    print(f"SH_GATED_RANKING_FREEZE_SHA256={EXPECTED_RANKING_FREEZE_SHA}")
    print("PROGRESS=LOAD_FROZEN_RANKING_AND_EXCLUDE_FIRST_AUDIT")

    cols=["pair_key","field_a","field_b","m0_status","satellite_merge_score","satellite_score_percentile","p_samecrop","hprior_percentile","sh_tier"]
    d=pd.read_parquet(RANKING,columns=cols)
    first=pd.read_csv(FIRST_REVEALED_JOIN,encoding="utf-8-sig",usecols=["pair_key"],dtype=str)
    if len(first)!=EXPECTED_FIRST_AUDIT or first["pair_key"].nunique()!=EXPECTED_FIRST_AUDIT:
        raise RuntimeError("First audit exclusion set is not exactly 100 unique pairs")
    excluded=set(first["pair_key"].astype(str))

    eligible=d.loc[d["sh_tier"].isin(TIERS) & ~d["pair_key"].astype(str).isin(excluded)].copy()
    counts=eligible["sh_tier"].value_counts().to_dict()
    print("ELIGIBLE_AFTER_EXCLUSION="+" | ".join(f"{t}:{int(counts.get(t,0))}" for t in TIERS))
    if any(int(counts.get(t,0))<SAMPLE_PER_TIER for t in TIERS):
        raise RuntimeError("Insufficient eligible A/B pairs after exclusion")

    samples=[]
    for tier in TIERS:
        g=eligible.loc[eligible["sh_tier"]==tier].copy()
        g["sample_hash"]=[htxt(f"{SAMPLE_SALT}|{tier}|{pk}") for pk in g["pair_key"].astype(str)]
        samples.append(g.sort_values(["sample_hash","pair_key"],kind="mergesort").head(SAMPLE_PER_TIER))
    sample=pd.concat(samples,ignore_index=True)
    if len(sample)!=EXPECTED_SAMPLE or sample["pair_key"].nunique()!=EXPECTED_SAMPLE:
        raise RuntimeError("Validation sample is not exactly 100 unique pairs")
    if sample["pair_key"].astype(str).isin(excluded).any():
        raise RuntimeError("First-audit overlap detected")
    sample["blind_hash"]=[htxt(f"{ORDER_SALT}|{pk}") for pk in sample["pair_key"].astype(str)]
    sample=sample.sort_values(["blind_hash","pair_key"],kind="mergesort").reset_index(drop=True)
    sample["blind_index"]=np.arange(1,EXPECTED_SAMPLE+1,dtype=int)

    sample_population_sha=htxt("\n".join(sorted(sample["pair_key"].astype(str)))+"\n")
    exclusion_sha=htxt("\n".join(sorted(excluded))+"\n")

    print("PROGRESS=LOAD_SHARED_BOUNDARY_GEOMETRY")
    g=gpd.read_file(M0_GPKG)
    g["pair_key"]=g["field_a"].astype(str)+"||"+g["field_b"].astype(str)
    if g["pair_key"].duplicated().any(): raise RuntimeError("Boundary pair keys not unique")
    geom=g.set_index("pair_key").geometry
    if not set(sample["pair_key"]).issubset(set(geom.index)):
        raise RuntimeError("Sample pair missing boundary geometry")

    out.mkdir(parents=True,exist_ok=False)
    imgdir=out/"images"; imgdir.mkdir()

    key_cols=["blind_index","pair_key","sh_tier","sample_hash","blind_hash","m0_status","satellite_merge_score","satellite_score_percentile","p_samecrop","hprior_percentile"]
    key=out/"AB_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv"
    sample[key_cols].to_csv(key,index=False,encoding="utf-8-sig")
    key_sha=sha(key)

    renderer=load_render_module()
    items=[]; image_hashes={}; validity_rows=[]
    print("PROGRESS=RENDER_100_X_4_VALIDATION_SHEETS")
    for i,r in enumerate(sample.itertuples(index=False),1):
        bi=int(r.blind_index); name=f"validation_{bi:03d}.jpg"; dest=imgdir/name
        valid=renderer.render_pair(geom.loc[str(r.pair_key)],vrt_paths,dest,bi)
        image_hashes[name]=sha(dest)
        validity_rows.append({"blind_index":bi,**valid})
        items.append({"blind_index":bi,"image":f"images/{name}"})
        if i==1 or i%10==0 or i==EXPECTED_SAMPLE:
            print(f"VALIDATION_RENDERED={i}/{EXPECTED_SAMPLE}")

    html=out/"index.html"
    html.write_text(make_html(items,key_sha),encoding="utf-8")
    validity=out/"validation_pair_validity.json"
    validity.write_text(json.dumps(validity_rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    manifest={
      "schema_version":"akerpuls-merge-ab-independent-blind-validation-viewer-v1",
      "status":STATUS,
      "generated_utc":datetime.now(timezone.utc).isoformat(),
      "git_head":head,
      "parents":{
        "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
        "ranking_parquet_sha256":EXPECTED_RANKING_SHA,
        "first_audit_revealed_join_sha256":EXPECTED_FIRST_JOIN_SHA,
        "m0_freeze_sha256":EXPECTED_M0_FREEZE_SHA,
        "m0_shared_boundary_gpkg_sha256":gpkg_sha,
        "vrt_index_sha256":EXPECTED_VRT_INDEX_SHA,
      },
      "sampling":{
        "tiers":TIERS,
        "per_tier":SAMPLE_PER_TIER,
        "rows":EXPECTED_SAMPLE,
        "eligible_after_exclusion":{t:int(counts.get(t,0)) for t in TIERS},
        "first_audit_pairs_excluded":EXPECTED_FIRST_AUDIT,
        "first_audit_exclusion_set_sha256":exclusion_sha,
        "sample_population_sha256":sample_population_sha,
        "sample_salt":SAMPLE_SALT,
        "blind_order_salt":ORDER_SALT,
        "human_labels_used_for_sampling":False,
      },
      "blind_key_sha256":key_sha,
      "predeclared_analysis":PREDECLARED_ANALYSIS,
      "labels":LABELS,
      "blindness":{
        "tier_visible":False,
        "scores_visible":False,
        "pair_id_visible":False,
        "field_ids_visible":False,
        "m0_status_visible":False,
        "blind_key_must_remain_closed_until_labels_exported_and_frozen":True,
      },
      "policy":{
        "block_boundary_hard_wall":True,
        "cross_block_merge_allowed":False,
        "automatic_merge":False,
        "geometry_mutated":False,
      },
      "guards":{
        "fusion_executed":False,
        "fusion_weight_selected":False,
        "thresholds_tuned":False,
        "automatic_merge":False,
        "geometry_mutated":False,
      },
      "html_sha256":sha(html),
      "validity_sha256":sha(validity),
      "image_hashes":image_hashes,
      "next":"FREEZE_VIEWER_THEN_COMPLETE_100_BLIND_LABELS",
    }
    mp=out/"AB_INDEPENDENT_VALIDATION_VIEWER_MANIFEST_V1.json"
    mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print(f"STATUS={STATUS}")
    print("SAMPLE=A:50 | B:50")
    print("ELIGIBLE_AFTER_EXCLUSION="+" | ".join(f"{t}:{int(counts.get(t,0))}" for t in TIERS))
    print(f"FIRST_AUDIT_EXCLUDED={EXPECTED_FIRST_AUDIT}")
    print(f"FIRST_AUDIT_EXCLUSION_SET_SHA256={exclusion_sha}")
    print(f"SAMPLE_POPULATION_SHA256={sample_population_sha}")
    print(f"BLIND_KEY_SHA256={key_sha}")
    print("TIER_VISIBLE=FALSE SCORES_VISIBLE=FALSE PAIR_ID_VISIBLE=FALSE FIELD_IDS_VISIBLE=FALSE")
    print("BLOCK_BOUNDARY_HARD_WALL=TRUE CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("DO_NOT_OPEN_AB_VALIDATION_BLIND_KEY_BEFORE_LABEL_FREEZE=TRUE")
    print(f"OUTPUT={html}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
