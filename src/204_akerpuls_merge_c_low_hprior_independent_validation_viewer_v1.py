#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Targeted independent validation of low-Hprior veto within S2026>P90.

Uses ALL previously unseen C-tier pairs:
  C_SAT_HIGH_H_LOW = S2026>P90 and Hprior<=P25.

Each remaining C pair is deterministically matched 1:1 to one previously unseen
A/B control on nearest frozen S2026 percentile. All pairs from BOTH previous
human audits are excluded before matching.

Blind browser shows only four frozen 2026 Sentinel RGB panels + old 2025 shared
boundary. Arm/tier, pair ids and scores remain hidden until labels are frozen.

Primary endpoint (predeclared):
  broad positive = TYDLIG_MERGE + MÖJLIG_MERGE.
Primary paired test:
  exact two-sided McNemar, CONTROL_NONLOW_HPRIOR vs C_LOW_HPRIOR.
Matched pair is excluded from paired endpoint if either member is EJ_BEDÖMBAR.

No fusion, no threshold tuning, no automatic merge, no cross-block merge,
no geometry mutation.
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
EXPECTED_RANKING_FREEZE_SHA="2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"

FIRST_JOIN=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_v1\MERGE_AUDIT_REVEALED_JOIN.csv")
EXPECTED_FIRST_JOIN_SHA="bce010ece5982599231117e83fb301f3391b78b00e5d6e39abc700588b63e284"
SECOND_JOIN=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_validation_reveal_v1\MERGE_AB_INDEPENDENT_VALIDATION_REVEALED_JOIN.csv")
EXPECTED_SECOND_JOIN_SHA="ef17c26b588428895c6e0e158b2d91edbdf4a75e50cc997aa1584fde00ec51b5"
AB_VALIDATION_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_validation_reveal_freeze_v1\AKERPULS_MERGE_AB_INDEPENDENT_VALIDATION_REVEAL_FREEZE_V1.json")
EXPECTED_AB_VALIDATION_FREEZE_SHA="333e3c9738cf56f9a3fadf37c46a7883c508ec70bd25975eb214132fb65ffc8d"

M0_GPKG=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1\m0_satellite_merge_boundaries.gpkg")
M0_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json")
EXPECTED_M0_FREEZE_SHA="fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"

VRT_INDEX=Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1\d1s3j_vrt_outputs.csv")
EXPECTED_VRT_INDEX_SHA="0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979"

DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_viewer_v1")
STATUS="PASS_TO_C_LOW_HPRIOR_INDEPENDENT_BLIND_VALIDATION"

C_TIER="C_SAT_HIGH_H_LOW"
CONTROL_TIERS=["A_CONFIRMED_HIGH","B_SAT_HIGH_H_MID"]
EXPECTED_C_TOTAL=54
EXPECTED_FIRST_AUDIT=100
EXPECTED_SECOND_AUDIT=100
EXPECTED_EXCLUDED_UNION=200
EXPECTED_REMAINING_C=29
EXPECTED_REMAINING_CONTROLS=2057
EXPECTED_MATCHES=29
EXPECTED_SAMPLE=58

MATCH_SALT="akerpuls-c-low-hprior-match-v1|2026-10-05|333e3c97"
ORDER_SALT="akerpuls-c-low-hprior-blind-order-v1|2026-10-05|333e3c97"

LABELS=["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"]
PREDECLARED_ANALYSIS={
    "primary_endpoint":"broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE",
    "secondary_endpoint":"strict_positive = TYDLIG_MERGE",
    "primary_contrast":"CONTROL_NONLOW_HPRIOR vs C_LOW_HPRIOR within S2026>P90",
    "matching":"1:1 nearest frozen S2026 percentile without replacement",
    "primary_test":"exact two-sided McNemar on matched broad-positive labels",
    "secondary_test":"exact two-sided McNemar on matched strict-positive labels",
    "paired_exclusion":"exclude matched pair if either member is EJ_BEDÖMBAR",
    "descriptive":["group rates","Wilson 95% CI","unpaired Fisher exact","risk difference"],
    "TVEKSAM_is_nonpositive":True,
    "no_threshold_tuning":True,
    "no_fusion":True,
}


def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def htxt(x:str)->str:
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


def git_guard()->str:
    b=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if b!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {b}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def load_renderer():
    p=ROOT/"src"/"191_akerpuls_merge_blind_disagreement_audit_viewer_v1b.py"
    spec=importlib.util.spec_from_file_location("render191",p)
    m=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def verify_inputs():
    for p,expected,name in [
        (RANKING,EXPECTED_RANKING_SHA,"ranking"),
        (FIRST_JOIN,EXPECTED_FIRST_JOIN_SHA,"first audit join"),
        (SECOND_JOIN,EXPECTED_SECOND_JOIN_SHA,"second audit join"),
        (AB_VALIDATION_FREEZE,EXPECTED_AB_VALIDATION_FREEZE_SHA,"A/B validation freeze"),
        (M0_FREEZE,EXPECTED_M0_FREEZE_SHA,"M0 freeze"),
        (VRT_INDEX,EXPECTED_VRT_INDEX_SHA,"VRT index"),
    ]:
        if not p.is_file() or sha(p)!=expected:
            raise RuntimeError(f"{name} missing or changed")

    m0f=json.loads(M0_FREEZE.read_text(encoding="utf-8-sig"))
    gpkg_sha=m0f.get("source_hashes",{}).get("source_boundaries_gpkg_sha256")
    if not gpkg_sha or not M0_GPKG.is_file() or sha(M0_GPKG)!=gpkg_sha:
        raise RuntimeError("M0 boundary GPKG missing or changed")

    rows=pd.read_csv(VRT_INDEX,encoding="utf-8-sig")
    vrt={}
    for snap in ["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]:
        r=rows.loc[rows["snapshot"].astype(str)==snap]
        if len(r)!=1: raise RuntimeError(f"Expected one VRT row for {snap}")
        p=Path(str(r.iloc[0]["path"]))
        if not p.is_file() or sha(p)!=str(r.iloc[0]["sha256"]):
            raise RuntimeError(f"VRT changed for {snap}")
        vrt[snap]=p
    return gpkg_sha,vrt


def choose_matches(c:pd.DataFrame,controls:pd.DataFrame)->pd.DataFrame:
    """Deterministic greedy nearest-neighbor matching on S2026 percentile."""
    remaining=controls.copy()
    result=[]
    c_order=c.sort_values(["satellite_score_percentile","pair_key"],kind="mergesort")
    for match_id,(_,cr) in enumerate(c_order.iterrows(),1):
        delta=(remaining["satellite_score_percentile"]-float(cr["satellite_score_percentile"])).abs()
        mind=float(delta.min())
        cand=remaining.loc[np.isclose(delta.to_numpy(),mind,rtol=0,atol=1e-15)].copy()
        if len(cand)>1:
            cand["_tie"]=[htxt(f"{MATCH_SALT}|{cr['pair_key']}|{pk}") for pk in cand["pair_key"].astype(str)]
            cand=cand.sort_values(["_tie","pair_key"],kind="mergesort")
        rr=cand.iloc[0]
        result.append({
            "match_id":match_id,
            "c_pair_key":str(cr["pair_key"]),
            "control_pair_key":str(rr["pair_key"]),
            "c_s2026_percentile":float(cr["satellite_score_percentile"]),
            "control_s2026_percentile":float(rr["satellite_score_percentile"]),
            "abs_s2026_percentile_delta":abs(float(cr["satellite_score_percentile"])-float(rr["satellite_score_percentile"])),
        })
        remaining=remaining.loc[remaining["pair_key"].astype(str)!=str(rr["pair_key"])].copy()
    return pd.DataFrame(result)


def make_html(items,key_sha:str)->str:
    payload=json.dumps(items,ensure_ascii=False,separators=(",",":")).replace("</","<\\/")
    labs=json.dumps(LABELS,ensure_ascii=False)
    template=r'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – blind low-Hprior validation</title><style>
:root{font-family:Arial,sans-serif;color:#171717;background:#f5f5f5}body{margin:0}.top{position:sticky;top:0;z-index:3;background:#fff;border-bottom:1px solid #ccc;padding:10px 14px}.main{max-width:1600px;margin:12px auto;padding:0 12px 30px}.card{background:#fff;border:1px solid #ccc;border-radius:7px;padding:10px}.auditimg{display:block;width:100%;height:auto;background:#ddd}.labels{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.labels button,.nav button,#exportBtn{padding:9px 12px;border:1px solid #888;border-radius:5px;background:#fff;cursor:pointer}.labels button.sel{outline:3px solid #111;font-weight:bold}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.note{width:100%;min-height:55px;box-sizing:border-box}.muted{color:#555;font-size:13px}.warn{font-weight:bold}.progress{font-variant-numeric:tabular-nums}</style></head><body>
<div class="top"><div class="row"><b>ÅkerPuls – blind low-Hprior validation</b><span id="pos"></span><span id="done"></span></div><div class="muted">Cyan = gemensam officiell 2025-gräns. Arm/tier, scores och IDs är dolda.</div></div>
<div class="main"><div class="card"><img id="img" class="auditimg"><p><b>Bedömning:</b> Tyder 2026-bilderna på att de två 2025-skiftena nu fungerar som ett och samma skifte så att den cyan gränsen bör tas bort?</p>
<div class="labels" id="labels"></div><textarea id="note" class="note" placeholder="Frivillig kort kommentar"></textarea>
<div class="row nav"><button id="prev">← Föregående</button><button id="next">Nästa →</button><button id="exportBtn">Exportera validation CSV</button><span class="muted">1–5 = etikett, ←/→ = navigera.</span></div>
<p class="muted warn">Samma gröda/färg räcker inte i sig. Bedöm om den gamla cyan brukningsgränsen faktiskt verkar ha försvunnit över säsongen.</p>
<p class="muted warn">Öppna inte C_LOW_HPRIOR_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv före label-freeze.</p></div></div>
<script>
const ITEMS=__ITEMS__,LABELS=__LABELS__,RANKFREEZE='__RANKFREEZE__',KEYSHA='__KEYSHA__';
const STORE='akerpuls_c_low_hprior_validation_v1_'+RANKFREEZE.slice(0,12)+'_'+KEYSHA.slice(0,12);let state=JSON.parse(localStorage.getItem(STORE)||'{}'),idx=0;
function save(){localStorage.setItem(STORE,JSON.stringify(state));}function cur(){return ITEMS[idx];}
function render(){const it=cur(),r=state[it.blind_index]||{};document.getElementById('img').src=it.image;document.getElementById('pos').textContent='Par '+(idx+1)+'/'+ITEMS.length+' · blind #'+String(it.blind_index).padStart(3,'0');document.getElementById('note').value=r.note||'';const box=document.getElementById('labels');box.innerHTML='';LABELS.forEach(function(lab){const b=document.createElement('button');b.textContent=lab;if(r.merge_label===lab)b.classList.add('sel');b.onclick=function(){const rr=state[it.blind_index]||{};rr.merge_label=lab;rr.note=document.getElementById('note').value;state[it.blind_index]=rr;save();render();};box.appendChild(b);});const n=ITEMS.filter(function(x){return state[x.blind_index]&&state[x.blind_index].merge_label;}).length;document.getElementById('done').textContent='Bedömda '+n+'/'+ITEMS.length;}
document.getElementById('note').addEventListener('input',function(e){const it=cur(),r=state[it.blind_index]||{};r.note=e.target.value;state[it.blind_index]=r;save();});document.getElementById('prev').onclick=function(){idx=Math.max(0,idx-1);render();};document.getElementById('next').onclick=function(){idx=Math.min(ITEMS.length-1,idx+1);render();};
document.addEventListener('keydown',function(e){if(document.activeElement===document.getElementById('note'))return;if(e.key>='1'&&e.key<='5'){const it=cur(),r=state[it.blind_index]||{};r.merge_label=LABELS[Number(e.key)-1];state[it.blind_index]=r;save();render();return;}if(e.key==='ArrowRight'){idx=Math.min(ITEMS.length-1,idx+1);render();}else if(e.key==='ArrowLeft'){idx=Math.max(0,idx-1);render();}});
function q(s){return '"'+String(s||'').replaceAll('"','""')+'"';}
document.getElementById('exportBtn').onclick=function(){const missing=ITEMS.filter(function(x){return !(state[x.blind_index]&&state[x.blind_index].merge_label);});if(missing.length&&!confirm(String(missing.length)+' par saknar etikett. Exportera ändå?'))return;const rows=[['sh_gated_ranking_freeze_sha256','blind_key_sha256','blind_index','merge_label','note']];ITEMS.forEach(function(it){const r=state[it.blind_index]||{};rows.push([RANKFREEZE,KEYSHA,it.blind_index,r.merge_label||'',r.note||'']);});const csv='\ufeff'+rows.map(function(r){return r.map(q).join(',');}).join('\r\n')+'\r\n';const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='merge_c_low_hprior_validation_labels.csv';a.click();setTimeout(function(){URL.revokeObjectURL(a.href);},1000);};render();
</script></body></html>'''
    return template.replace("__ITEMS__",payload).replace("__LABELS__",labs).replace("__RANKFREEZE__",EXPECTED_RANKING_FREEZE_SHA).replace("__KEYSHA__",key_sha)


def main()->int:
    import geopandas as gpd

    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()
    head=git_guard(); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Output already exists: {out}")
    gpkg_sha,vrt=verify_inputs()

    print("AKERPULS MERGE LOW-HPRIOR C TARGETED INDEPENDENT VALIDATION VIEWER V1")
    print(f"GIT_HEAD={head}")
    print(f"AB_VALIDATION_FREEZE_SHA256={EXPECTED_AB_VALIDATION_FREEZE_SHA}")
    print("PROGRESS=LOAD_RANKING_AND_EXCLUDE_BOTH_PRIOR_AUDITS")

    cols=["pair_key","field_a","field_b","m0_status","satellite_merge_score","satellite_score_percentile","p_samecrop","hprior_percentile","sh_tier"]
    d=pd.read_parquet(RANKING,columns=cols)
    if int((d["sh_tier"]==C_TIER).sum())!=EXPECTED_C_TOTAL:
        raise RuntimeError("Frozen C-tier total changed")

    first=pd.read_csv(FIRST_JOIN,encoding="utf-8-sig",usecols=["pair_key"],dtype=str)
    second=pd.read_csv(SECOND_JOIN,encoding="utf-8-sig",usecols=["pair_key"],dtype=str)
    if len(first)!=EXPECTED_FIRST_AUDIT or first["pair_key"].nunique()!=EXPECTED_FIRST_AUDIT:
        raise RuntimeError("First audit set changed")
    if len(second)!=EXPECTED_SECOND_AUDIT or second["pair_key"].nunique()!=EXPECTED_SECOND_AUDIT:
        raise RuntimeError("Second audit set changed")
    excluded=set(first["pair_key"].astype(str)) | set(second["pair_key"].astype(str))
    if len(excluded)!=EXPECTED_EXCLUDED_UNION:
        raise RuntimeError(f"Expected 200 unique prior-audit pairs, got {len(excluded)}")

    c=d.loc[(d["sh_tier"]==C_TIER) & ~d["pair_key"].astype(str).isin(excluded)].copy()
    controls=d.loc[d["sh_tier"].isin(CONTROL_TIERS) & ~d["pair_key"].astype(str).isin(excluded)].copy()
    if len(c)!=EXPECTED_REMAINING_C:
        raise RuntimeError(f"Expected {EXPECTED_REMAINING_C} unseen C pairs, got {len(c)}")
    if len(controls)!=EXPECTED_REMAINING_CONTROLS:
        raise RuntimeError(f"Expected {EXPECTED_REMAINING_CONTROLS} unseen A+B controls, got {len(controls)}")
    print(f"ELIGIBLE_AFTER_EXCLUSION=C:{len(c)} | CONTROL_A_PLUS_B:{len(controls)}")

    matches=choose_matches(c,controls)
    if len(matches)!=EXPECTED_MATCHES or matches["control_pair_key"].nunique()!=EXPECTED_MATCHES:
        raise RuntimeError("Matching did not produce 29 unique controls")

    lookup=d.set_index("pair_key")
    rows=[]
    for m in matches.itertuples(index=False):
        for arm,pk in [("C_LOW_HPRIOR",m.c_pair_key),("CONTROL_NONLOW_HPRIOR",m.control_pair_key)]:
            rr=lookup.loc[pk]
            rows.append({
                "match_id":int(m.match_id),
                "arm":arm,
                "pair_key":pk,
                "source_tier":str(rr["sh_tier"]),
                "field_a":str(rr["field_a"]),
                "field_b":str(rr["field_b"]),
                "m0_status":str(rr["m0_status"]),
                "satellite_merge_score":float(rr["satellite_merge_score"]),
                "satellite_score_percentile":float(rr["satellite_score_percentile"]),
                "p_samecrop":float(rr["p_samecrop"]),
                "hprior_percentile":float(rr["hprior_percentile"]),
                "match_abs_s2026_percentile_delta":float(m.abs_s2026_percentile_delta),
            })
    sample=pd.DataFrame(rows)
    if len(sample)!=EXPECTED_SAMPLE or sample["pair_key"].nunique()!=EXPECTED_SAMPLE:
        raise RuntimeError("Expected 58 unique validation pairs")
    if sample["pair_key"].astype(str).isin(excluded).any():
        raise RuntimeError("Prior-audit overlap detected")

    sample["blind_hash"]=[htxt(f"{ORDER_SALT}|{pk}") for pk in sample["pair_key"].astype(str)]
    sample=sample.sort_values(["blind_hash","pair_key"],kind="mergesort").reset_index(drop=True)
    sample["blind_index"]=np.arange(1,EXPECTED_SAMPLE+1,dtype=int)

    excluded_sha=htxt("\n".join(sorted(excluded))+"\n")
    sample_sha=htxt("\n".join(sorted(sample["pair_key"].astype(str)))+"\n")
    match_sha=htxt("\n".join(
        f"{int(r.match_id)}|{r.c_pair_key}|{r.control_pair_key}|{r.abs_s2026_percentile_delta:.12g}"
        for r in matches.itertuples(index=False)
    )+"\n")

    print(
        "MATCH_S2026_ABS_DELTA="
        f"P50:{matches['abs_s2026_percentile_delta'].median():.8f} | "
        f"P90:{matches['abs_s2026_percentile_delta'].quantile(.9):.8f} | "
        f"MAX:{matches['abs_s2026_percentile_delta'].max():.8f}"
    )

    g=gpd.read_file(M0_GPKG)
    g["pair_key"]=g["field_a"].astype(str)+"||"+g["field_b"].astype(str)
    if g["pair_key"].duplicated().any(): raise RuntimeError("Boundary pair keys not unique")
    geom=g.set_index("pair_key").geometry
    if not set(sample["pair_key"]).issubset(set(geom.index)):
        raise RuntimeError("Sample pair missing boundary geometry")

    out.mkdir(parents=True,exist_ok=False); imgdir=out/"images"; imgdir.mkdir()
    key_cols=["blind_index","match_id","arm","pair_key","source_tier","field_a","field_b","m0_status","satellite_merge_score","satellite_score_percentile","p_samecrop","hprior_percentile","match_abs_s2026_percentile_delta","blind_hash"]
    key=out/"C_LOW_HPRIOR_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv"
    sample[key_cols].to_csv(key,index=False,encoding="utf-8-sig")
    key_sha=sha(key)
    matches.to_csv(out/"MATCHING_DIAGNOSTIC_DO_NOT_OPEN_BEFORE_REVIEW.csv",index=False,encoding="utf-8-sig")

    renderer=load_renderer()
    items=[]; image_hashes={}; validity_rows=[]
    print("PROGRESS=RENDER_58_X_4_VALIDATION_SHEETS")
    for i,r in enumerate(sample.itertuples(index=False),1):
        bi=int(r.blind_index); name=f"validation_{bi:03d}.jpg"; dest=imgdir/name
        valid=renderer.render_pair(geom.loc[str(r.pair_key)],vrt,dest,bi)
        image_hashes[name]=sha(dest); validity_rows.append({"blind_index":bi,**valid})
        items.append({"blind_index":bi,"image":f"images/{name}"})
        if i==1 or i%10==0 or i==EXPECTED_SAMPLE: print(f"VALIDATION_RENDERED={i}/{EXPECTED_SAMPLE}")

    html=out/"index.html"
    html.write_text(make_html(items,key_sha),encoding="utf-8")
    validity=out/"validation_pair_validity.json"
    validity.write_text(json.dumps(validity_rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    manifest={
      "schema_version":"akerpuls-merge-c-low-hprior-independent-validation-viewer-v1",
      "status":STATUS,
      "generated_utc":datetime.now(timezone.utc).isoformat(),
      "git_head":head,
      "parents":{
        "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
        "ab_independent_validation_freeze_sha256":EXPECTED_AB_VALIDATION_FREEZE_SHA,
        "first_audit_join_sha256":EXPECTED_FIRST_JOIN_SHA,
        "second_audit_join_sha256":EXPECTED_SECOND_JOIN_SHA,
        "m0_freeze_sha256":EXPECTED_M0_FREEZE_SHA,
        "m0_boundary_gpkg_sha256":gpkg_sha,
        "vrt_index_sha256":EXPECTED_VRT_INDEX_SHA,
      },
      "sampling":{
        "all_remaining_C_used":True,
        "C_total_frozen":EXPECTED_C_TOTAL,
        "prior_audit_pairs_excluded":EXPECTED_EXCLUDED_UNION,
        "remaining_C":EXPECTED_REMAINING_C,
        "remaining_controls_A_plus_B":EXPECTED_REMAINING_CONTROLS,
        "matched_controls":EXPECTED_MATCHES,
        "rows":EXPECTED_SAMPLE,
        "exclusion_set_sha256":excluded_sha,
        "sample_population_sha256":sample_sha,
        "matching_definition":"1:1 nearest S2026 percentile without replacement; deterministic hash tie-break",
        "matching_sha256":match_sha,
        "match_delta_p50":float(matches["abs_s2026_percentile_delta"].median()),
        "match_delta_p90":float(matches["abs_s2026_percentile_delta"].quantile(.9)),
        "match_delta_max":float(matches["abs_s2026_percentile_delta"].max()),
        "human_labels_used_for_sampling":False,
      },
      "blind_key_sha256":key_sha,
      "predeclared_analysis":PREDECLARED_ANALYSIS,
      "labels":LABELS,
      "blindness":{
        "arm_visible":False,"tier_visible":False,"scores_visible":False,
        "pair_id_visible":False,"field_ids_visible":False,"match_id_visible":False,
        "blind_key_must_remain_closed_until_labels_exported_and_frozen":True,
      },
      "policy":{
        "block_boundary_hard_wall":True,
        "cross_block_merge_allowed":False,
        "automatic_merge":False,
        "geometry_mutated":False,
      },
      "guards":{
        "fusion_executed":False,"thresholds_tuned":False,
        "automatic_merge":False,"geometry_mutated":False,
      },
      "html_sha256":sha(html),
      "validity_sha256":sha(validity),
      "image_hashes":image_hashes,
      "next":"FREEZE_VIEWER_THEN_COMPLETE_58_BLIND_LABELS",
    }
    mp=out/"C_LOW_HPRIOR_VALIDATION_VIEWER_MANIFEST_V1.json"
    mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print(f"STATUS={STATUS}")
    print(f"SAMPLE=C_LOW_HPRIOR:{EXPECTED_MATCHES} | MATCHED_CONTROL:{EXPECTED_MATCHES} | TOTAL:{EXPECTED_SAMPLE}")
    print(f"PRIOR_AUDIT_PAIRS_EXCLUDED={EXPECTED_EXCLUDED_UNION}")
    print(f"EXCLUSION_SET_SHA256={excluded_sha}")
    print(f"SAMPLE_POPULATION_SHA256={sample_sha}")
    print(f"MATCHING_SHA256={match_sha}")
    print(f"BLIND_KEY_SHA256={key_sha}")
    print("ARM_VISIBLE=FALSE TIER_VISIBLE=FALSE SCORES_VISIBLE=FALSE IDS_VISIBLE=FALSE")
    print("BLOCK_BOUNDARY_HARD_WALL=TRUE CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("DO_NOT_OPEN_C_LOW_HPRIOR_BLIND_KEY_BEFORE_LABEL_FREEZE=TRUE")
    print(f"OUTPUT={html}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
