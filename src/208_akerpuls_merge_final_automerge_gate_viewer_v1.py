#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final blind validation gate for ÅkerPuls merge-v1.

This script first freezes the completed low-Hprior C validation result, then
builds AND formally freezes the final pre-label blind viewer.

Final candidate rule is prospectively fixed before any new labels:
    S2026 percentile > 0.95
    Hprior percentile > 0.25
    same 2025 block only

All 258 previously human-reviewed pairs are excluded. Exactly 80 previously
unseen candidates are deterministic hash-sampled.

Final operational gate (all conditions required):
    broad merge rate >= 0.90 among assessable
    one-sided Wilson 95% lower bound for broad rate >= 0.85
    BEHÅLL_GRÄNS rate <= 0.05 among assessable
    EJ_BEDÖMBAR <= 8 of 80

If any condition fails, merge-v1 remains proposal-only. This is the final blind
test for the current S2026 + Hprior signal family; no post-hoc threshold chase.
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
THIRD_JOIN=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_reveal_v1\MERGE_C_LOW_HPRIOR_VALIDATION_REVEALED_JOIN.csv")
EXPECTED_THIRD_JOIN_SHA="8c5bad81bcf77bbbd831240573e3887c8169c2c2e7d84a1bd06181a75ace77c5"

C_SUMMARY=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_reveal_v1\MERGE_C_LOW_HPRIOR_VALIDATION_SUMMARY_V1.json")
EXPECTED_C_SUMMARY_SHA="c2125f76978eb9706d2072e3b8a5059db1d452653b818d2eee0611985524d36a"
C_PAIRED=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_reveal_v1\MERGE_C_LOW_HPRIOR_VALIDATION_MATCHED_PAIR_OUTCOMES.csv")
EXPECTED_C_PAIRED_SHA="e493a1b311c7879fa627b5a52ac52e954fe47c4096b76be751a8dc2167e50c35"
EXPECTED_C_LABEL_FREEZE_SHA="d8143e47bb1ab9b8056f0b93e32250caeac5397c2b483d60e167a28cef0d3899"

M0_GPKG=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1\m0_satellite_merge_boundaries.gpkg")
M0_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json")
EXPECTED_M0_FREEZE_SHA="fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
VRT_INDEX=Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1\d1s3j_vrt_outputs.csv")
EXPECTED_VRT_INDEX_SHA="0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979"

C_FREEZE_DIR=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_reveal_freeze_v1")
DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_viewer_v1")
DEFAULT_FREEZE_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_viewer_freeze_v1")

STATUS="PASS_TO_FINAL_AUTOMERGE_GATE_BLIND_VALIDATION"
FREEZE_STATUS="FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_V1"
C_FREEZE_STATUS="FROZEN_AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_REVEAL_V1"

S_GATE=0.95
H_VETO=0.25
SAMPLE_N=80
EXPECTED_PRIOR_UNION=258
SAMPLE_SALT="akerpuls-final-automerge-gate-sample-v1|2026-10-05|P95|HGT25"
ORDER_SALT="akerpuls-final-automerge-gate-order-v1|2026-10-05|P95|HGT25"

LABELS=["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"]
ACCEPTANCE={
    "broad_rate_min":0.90,
    "broad_one_sided_wilson95_lower_min":0.85,
    "behall_rate_max":0.05,
    "ej_bedomdbar_max_count":8,
    "all_conditions_required":True,
    "pass_action":"ALLOW_HIGH_CONFIDENCE_AUTOMERGE_TIER_IN_PRELIMINARY_2026_GEOMETRY",
    "fail_action":"MERGE_V1_PROPOSAL_ONLY_NO_AUTOMATIC_BOUNDARY_REMOVAL",
    "final_blind_test_for_current_signal_family":True,
    "no_posthoc_threshold_chase":True,
}


def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def htxt(s:str)->str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def git_guard()->str:
    b=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if b!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {b}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def verify_file(p:Path,expected:str,name:str):
    if not p.is_file() or sha(p)!=expected:
        raise RuntimeError(f"{name} missing or changed")


def load_renderer():
    p=ROOT/"src"/"191_akerpuls_merge_blind_disagreement_audit_viewer_v1b.py"
    spec=importlib.util.spec_from_file_location("render191",p)
    m=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def verify_static_inputs():
    for p,e,n in [
        (RANKING,EXPECTED_RANKING_SHA,"ranking"),
        (FIRST_JOIN,EXPECTED_FIRST_JOIN_SHA,"first audit join"),
        (SECOND_JOIN,EXPECTED_SECOND_JOIN_SHA,"A/B validation join"),
        (THIRD_JOIN,EXPECTED_THIRD_JOIN_SHA,"C validation join"),
        (C_SUMMARY,EXPECTED_C_SUMMARY_SHA,"C validation summary"),
        (C_PAIRED,EXPECTED_C_PAIRED_SHA,"C paired outcomes"),
        (M0_FREEZE,EXPECTED_M0_FREEZE_SHA,"M0 freeze"),
        (VRT_INDEX,EXPECTED_VRT_INDEX_SHA,"VRT index"),
    ]:
        verify_file(p,e,n)

    m0f=json.loads(M0_FREEZE.read_text(encoding="utf-8-sig"))
    gpkg_sha=m0f.get("source_hashes",{}).get("source_boundaries_gpkg_sha256")
    if not gpkg_sha or not M0_GPKG.is_file() or sha(M0_GPKG)!=gpkg_sha:
        raise RuntimeError("M0 shared-boundary GPKG missing or changed")

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


def freeze_c_result(head:str)->tuple[str,dict]:
    s=json.loads(C_SUMMARY.read_text(encoding="utf-8-sig"))
    if s.get("status")!="PASS_TO_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_REVIEW":
        raise RuntimeError("Unexpected C reveal status")
    if s.get("parents",{}).get("labels_freeze_sha256")!=EXPECTED_C_LABEL_FREEZE_SHA:
        raise RuntimeError("C label-freeze lineage changed")
    broad=s.get("primary_broad_paired",{})
    strict=s.get("secondary_strict_paired",{})
    expected_values={
        "broad_valid":25,
        "broad_control_pos_cneg":7,
        "broad_control_neg_cpos":2,
        "broad_rd":0.2,
        "broad_p":0.1796875,
        "strict_valid":25,
        "strict_control_pos_cneg":11,
        "strict_control_neg_cpos":4,
        "strict_rd":0.28,
        "strict_p":0.11846923828125,
    }
    got={
        "broad_valid":int(broad.get("matched_pairs_valid",-1)),
        "broad_control_pos_cneg":int(broad.get("discordant_CONTROL_positive_C_negative",-1)),
        "broad_control_neg_cpos":int(broad.get("discordant_CONTROL_negative_C_positive",-1)),
        "broad_rd":float(broad.get("paired_risk_difference_CONTROL_minus_C")),
        "broad_p":float(broad.get("mcnemar_exact_two_sided_p")),
        "strict_valid":int(strict.get("matched_pairs_valid",-1)),
        "strict_control_pos_cneg":int(strict.get("discordant_CONTROL_positive_C_negative",-1)),
        "strict_control_neg_cpos":int(strict.get("discordant_CONTROL_negative_C_positive",-1)),
        "strict_rd":float(strict.get("paired_risk_difference_CONTROL_minus_C")),
        "strict_p":float(strict.get("mcnemar_exact_two_sided_p")),
    }
    for k,v in expected_values.items():
        if isinstance(v,float):
            if abs(got[k]-v)>1e-12: raise RuntimeError(f"C result changed: {k}")
        elif got[k]!=v:
            raise RuntimeError(f"C result changed: {k}")

    if C_FREEZE_DIR.exists():
        raise RuntimeError(f"C result freeze output already exists: {C_FREEZE_DIR}")
    C_FREEZE_DIR.mkdir(parents=True,exist_ok=False)
    freeze={
        "schema_version":"akerpuls-merge-c-low-hprior-independent-validation-reveal-freeze-v1",
        "status":C_FREEZE_STATUS,
        "source_git_head":s.get("git_head"),
        "freeze_git_head":head,
        "parents":{
            "labels_freeze_sha256":EXPECTED_C_LABEL_FREEZE_SHA,
            "summary_sha256":EXPECTED_C_SUMMARY_SHA,
            "join_sha256":EXPECTED_THIRD_JOIN_SHA,
            "paired_outcomes_sha256":EXPECTED_C_PAIRED_SHA,
        },
        "result_lock":{
            "C_broad":s["by_arm"]["C_LOW_HPRIOR"]["broad_positive_rate"],
            "CONTROL_broad":s["by_arm"]["CONTROL_NONLOW_HPRIOR"]["broad_positive_rate"],
            "paired_broad_RD_control_minus_C":broad["paired_risk_difference_CONTROL_minus_C"],
            "paired_broad_mcnemar_p":broad["mcnemar_exact_two_sided_p"],
            "C_strict":s["by_arm"]["C_LOW_HPRIOR"]["strict_positive_rate"],
            "CONTROL_strict":s["by_arm"]["CONTROL_NONLOW_HPRIOR"]["strict_positive_rate"],
            "paired_strict_RD_control_minus_C":strict["paired_risk_difference_CONTROL_minus_C"],
            "paired_strict_mcnemar_p":strict["mcnemar_exact_two_sided_p"],
        },
        "interpretation_lock":{
            "Hprior_P75_confirmation_bonus_supported":False,
            "low_Hprior_le_P25_is_conservative_veto_for_merge_v1":True,
            "Hprior_used_as_weight_or_bonus":False,
        },
        "contract":{
            "policy_for_final_test_rule_selected":True,
            "automatic_merge_executed":False,
            "geometry_mutated":False,
            "cross_block_merge_allowed":False,
        },
        "next":"FINAL_BLIND_GATE_S2026_GT_P95_AND_HPRIOR_GT_P25",
    }
    fp=C_FREEZE_DIR/"AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_REVEAL_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha(fp)
    (C_FREEZE_DIR/"AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_REVEAL_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_REVEAL_FREEZE_V1.json\n",encoding="utf-8")
    return fsha,freeze


def make_html(items,key_sha:str)->str:
    payload=json.dumps(items,ensure_ascii=False,separators=(",",":")).replace("</","<\\/")
    labs=json.dumps(LABELS,ensure_ascii=False)
    template=r'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – final blind merge-v1 gate</title><style>
:root{font-family:Arial,sans-serif;color:#171717;background:#f5f5f5}body{margin:0}.top{position:sticky;top:0;z-index:3;background:#fff;border-bottom:1px solid #ccc;padding:10px 14px}.main{max-width:1600px;margin:12px auto;padding:0 12px 30px}.card{background:#fff;border:1px solid #ccc;border-radius:7px;padding:10px}.auditimg{display:block;width:100%;height:auto;background:#ddd}.labels{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.labels button,.nav button,#exportBtn{padding:9px 12px;border:1px solid #888;border-radius:5px;background:#fff;cursor:pointer}.labels button.sel{outline:3px solid #111;font-weight:bold}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.note{width:100%;min-height:55px;box-sizing:border-box}.muted{color:#555;font-size:13px}.warn{font-weight:bold}</style></head><body>
<div class="top"><div class="row"><b>ÅkerPuls – FINAL blind merge-v1 gate</b><span id="pos"></span><span id="done"></span></div><div class="muted">Cyan = gemensam officiell 2025-gräns. Scores, pair-ID och fält-ID är dolda.</div></div>
<div class="main"><div class="card"><img id="img" class="auditimg"><p><b>Bedömning:</b> Tyder 2026-bilderna på att de två 2025-skiftena nu fungerar som ett och samma skifte så att den cyan gränsen bör tas bort?</p>
<div class="labels" id="labels"></div><textarea id="note" class="note" placeholder="Frivillig kort kommentar"></textarea>
<div class="row nav"><button id="prev">← Föregående</button><button id="next">Nästa →</button><button id="exportBtn">Exportera FINAL validation CSV</button><span class="muted">1–5 = etikett, ←/→ = navigera.</span></div>
<p class="muted warn">Samma gröda/färg räcker inte i sig. Bedöm om den gamla cyan brukningsgränsen faktiskt verkar ha försvunnit över säsongen.</p>
<p class="muted warn">Öppna inte FINAL_AUTOMERGE_GATE_BLIND_KEY_DO_NOT_OPEN.csv före label-freeze.</p></div></div>
<script>
const ITEMS=__ITEMS__,LABELS=__LABELS__,RANKFREEZE='__RANKFREEZE__',KEYSHA='__KEYSHA__';
const STORE='akerpuls_final_automerge_gate_v1_'+RANKFREEZE.slice(0,12)+'_'+KEYSHA.slice(0,12);let state=JSON.parse(localStorage.getItem(STORE)||'{}'),idx=0;
function save(){localStorage.setItem(STORE,JSON.stringify(state));}function cur(){return ITEMS[idx];}
function render(){const it=cur(),r=state[it.blind_index]||{};document.getElementById('img').src=it.image;document.getElementById('pos').textContent='Par '+(idx+1)+'/'+ITEMS.length+' · blind #'+String(it.blind_index).padStart(3,'0');document.getElementById('note').value=r.note||'';const box=document.getElementById('labels');box.innerHTML='';LABELS.forEach(function(lab){const b=document.createElement('button');b.textContent=lab;if(r.merge_label===lab)b.classList.add('sel');b.onclick=function(){const rr=state[it.blind_index]||{};rr.merge_label=lab;rr.note=document.getElementById('note').value;state[it.blind_index]=rr;save();render();};box.appendChild(b);});const n=ITEMS.filter(function(x){return state[x.blind_index]&&state[x.blind_index].merge_label;}).length;document.getElementById('done').textContent='Bedömda '+n+'/'+ITEMS.length;}
document.getElementById('note').addEventListener('input',function(e){const it=cur(),r=state[it.blind_index]||{};r.note=e.target.value;state[it.blind_index]=r;save();});document.getElementById('prev').onclick=function(){idx=Math.max(0,idx-1);render();};document.getElementById('next').onclick=function(){idx=Math.min(ITEMS.length-1,idx+1);render();};
document.addEventListener('keydown',function(e){if(document.activeElement===document.getElementById('note'))return;if(e.key>='1'&&e.key<='5'){const it=cur(),r=state[it.blind_index]||{};r.merge_label=LABELS[Number(e.key)-1];state[it.blind_index]=r;save();render();return;}if(e.key==='ArrowRight'){idx=Math.min(ITEMS.length-1,idx+1);render();}else if(e.key==='ArrowLeft'){idx=Math.max(0,idx-1);render();}});
function q(s){return '"'+String(s||'').replaceAll('"','""')+'"';}
document.getElementById('exportBtn').onclick=function(){const missing=ITEMS.filter(function(x){return !(state[x.blind_index]&&state[x.blind_index].merge_label);});if(missing.length&&!confirm(String(missing.length)+' par saknar etikett. Exportera ändå?'))return;const rows=[['sh_gated_ranking_freeze_sha256','blind_key_sha256','blind_index','merge_label','note']];ITEMS.forEach(function(it){const r=state[it.blind_index]||{};rows.push([RANKFREEZE,KEYSHA,it.blind_index,r.merge_label||'',r.note||'']);});const csv='\ufeff'+rows.map(function(r){return r.map(q).join(',');}).join('\r\n')+'\r\n';const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='merge_final_automerge_gate_labels.csv';a.click();setTimeout(function(){URL.revokeObjectURL(a.href);},1000);};render();
</script></body></html>'''
    return template.replace("__ITEMS__",payload).replace("__LABELS__",labs).replace("__RANKFREEZE__",EXPECTED_RANKING_FREEZE_SHA).replace("__KEYSHA__",key_sha)


def main()->int:
    import geopandas as gpd

    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    ap.add_argument("--freeze-output-dir",default=str(DEFAULT_FREEZE_OUT))
    args=ap.parse_args()

    head=git_guard()
    out=Path(args.output_dir); fout=Path(args.freeze_output_dir)
    if out.exists(): raise RuntimeError(f"Viewer output already exists: {out}")
    if fout.exists(): raise RuntimeError(f"Viewer-freeze output already exists: {fout}")

    gpkg_sha,vrt=verify_static_inputs()
    c_freeze_sha,_=freeze_c_result(head)
    print(f"C_VALIDATION_REVEAL_FREEZE_SHA256={c_freeze_sha}")

    cols=["pair_key","field_a","field_b","m0_status","satellite_merge_score","satellite_score_percentile","p_samecrop","hprior_percentile","sh_tier"]
    d=pd.read_parquet(RANKING,columns=cols)

    prior=[]
    for p in (FIRST_JOIN,SECOND_JOIN,THIRD_JOIN):
        q=pd.read_csv(p,encoding="utf-8-sig",usecols=["pair_key"],dtype=str)
        prior.extend(q["pair_key"].astype(str).tolist())
    excluded=set(prior)
    if len(excluded)!=EXPECTED_PRIOR_UNION:
        raise RuntimeError(f"Expected {EXPECTED_PRIOR_UNION} unique prior-reviewed pairs, got {len(excluded)}")

    assess=d["m0_status"].isin(["MERGE_CANDIDATE","KEEP_BOUNDARY"])
    eligible=d.loc[
        assess
        & (d["satellite_score_percentile"]>S_GATE)
        & (d["hprior_percentile"]>H_VETO)
        & ~d["pair_key"].astype(str).isin(excluded)
    ].copy()
    if len(eligible)<SAMPLE_N:
        raise RuntimeError(f"Only {len(eligible)} eligible unseen P95/H>25 pairs; need {SAMPLE_N}")

    eligible["sample_hash"]=[htxt(f"{SAMPLE_SALT}|{pk}") for pk in eligible["pair_key"].astype(str)]
    sample=eligible.sort_values(["sample_hash","pair_key"],kind="mergesort").head(SAMPLE_N).copy()
    if len(sample)!=SAMPLE_N or sample["pair_key"].nunique()!=SAMPLE_N:
        raise RuntimeError("Final sample is not exactly 80 unique pairs")

    sample["blind_hash"]=[htxt(f"{ORDER_SALT}|{pk}") for pk in sample["pair_key"].astype(str)]
    sample=sample.sort_values(["blind_hash","pair_key"],kind="mergesort").reset_index(drop=True)
    sample["blind_index"]=np.arange(1,SAMPLE_N+1,dtype=int)

    exclusion_sha=htxt("\n".join(sorted(excluded))+"\n")
    population_sha=htxt("\n".join(sorted(sample["pair_key"].astype(str)))+"\n")

    g=gpd.read_file(M0_GPKG)
    g["pair_key"]=g["field_a"].astype(str)+"||"+g["field_b"].astype(str)
    if g["pair_key"].duplicated().any(): raise RuntimeError("Boundary pair keys not unique")
    geom=g.set_index("pair_key").geometry
    if not set(sample["pair_key"]).issubset(set(geom.index)):
        raise RuntimeError("Final sample pair missing shared-boundary geometry")

    out.mkdir(parents=True,exist_ok=False)
    imgdir=out/"images"; imgdir.mkdir()

    key_cols=["blind_index","pair_key","field_a","field_b","m0_status","satellite_merge_score","satellite_score_percentile","p_samecrop","hprior_percentile","sample_hash","blind_hash"]
    key=out/"FINAL_AUTOMERGE_GATE_BLIND_KEY_DO_NOT_OPEN.csv"
    sample[key_cols].to_csv(key,index=False,encoding="utf-8-sig")
    key_sha=sha(key)

    renderer=load_renderer()
    items=[]; image_hashes={}; validity_rows=[]
    print("PROGRESS=RENDER_80_X_4_FINAL_GATE_SHEETS")
    for i,r in enumerate(sample.itertuples(index=False),1):
        bi=int(r.blind_index); name=f"validation_{bi:03d}.jpg"; dest=imgdir/name
        valid=renderer.render_pair(geom.loc[str(r.pair_key)],vrt,dest,bi)
        image_hashes[name]=sha(dest)
        validity_rows.append({"blind_index":bi,**valid})
        items.append({"blind_index":bi,"image":f"images/{name}"})
        if i==1 or i%10==0 or i==SAMPLE_N:
            print(f"FINAL_GATE_RENDERED={i}/{SAMPLE_N}")

    html=out/"index.html"
    html.write_text(make_html(items,key_sha),encoding="utf-8")
    validity=out/"validation_pair_validity.json"
    validity.write_text(json.dumps(validity_rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    manifest={
        "schema_version":"akerpuls-merge-final-automerge-gate-viewer-v1",
        "status":STATUS,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "git_head":head,
        "parents":{
            "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
            "c_validation_reveal_freeze_sha256":c_freeze_sha,
            "first_audit_join_sha256":EXPECTED_FIRST_JOIN_SHA,
            "ab_validation_join_sha256":EXPECTED_SECOND_JOIN_SHA,
            "c_validation_join_sha256":EXPECTED_THIRD_JOIN_SHA,
            "m0_freeze_sha256":EXPECTED_M0_FREEZE_SHA,
            "m0_boundary_gpkg_sha256":gpkg_sha,
            "vrt_index_sha256":EXPECTED_VRT_INDEX_SHA,
        },
        "candidate_rule":{
            "same_2025_block_only":True,
            "S2026_percentile_gt":S_GATE,
            "Hprior_percentile_gt":H_VETO,
            "rule_selected_before_final_labels":True,
        },
        "sampling":{
            "eligible_unseen":int(len(eligible)),
            "prior_human_reviewed_pairs_excluded":EXPECTED_PRIOR_UNION,
            "exclusion_set_sha256":exclusion_sha,
            "sample_rows":SAMPLE_N,
            "sample_population_sha256":population_sha,
            "sample_salt":SAMPLE_SALT,
            "blind_order_salt":ORDER_SALT,
            "human_labels_used_for_sampling":False,
        },
        "blind_key_sha256":key_sha,
        "labels":LABELS,
        "predeclared_final_gate":{
            "primary_endpoint":"broad = TYDLIG_MERGE + MÖJLIG_MERGE among assessable",
            "secondary_endpoint":"strict = TYDLIG_MERGE among assessable",
            "EJ_BEDÖMBAR_excluded_from_rates":True,
            "TVEKSAM_is_nonpositive":True,
            "acceptance":ACCEPTANCE,
            "decision_is_final_for_merge_v1_current_signal_family":True,
        },
        "blindness":{
            "scores_visible":False,
            "pair_id_visible":False,
            "field_ids_visible":False,
            "blind_key_must_remain_closed_until_labels_exported_and_frozen":True,
        },
        "policy":{
            "block_boundary_hard_wall":True,
            "cross_block_merge_allowed":False,
            "automatic_merge":False,
            "geometry_mutated":False,
        },
        "html_sha256":sha(html),
        "validity_sha256":sha(validity),
        "image_hashes":image_hashes,
        "next":"LABEL_80_BLIND_FINAL_GATE_PAIRS_THEN_FREEZE_LABELS_BEFORE_REVEAL",
    }
    mp=out/"FINAL_AUTOMERGE_GATE_VIEWER_MANIFEST_V1.json"
    mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    source_manifest_sha=sha(mp)

    # Formal pre-label freeze is created in the same deterministic run.
    fout.mkdir(parents=True,exist_ok=False)
    viewer_freeze={
        "schema_version":"akerpuls-merge-final-automerge-gate-viewer-freeze-v1",
        "status":FREEZE_STATUS,
        "source_git_head":head,
        "source_manifest_sha256":source_manifest_sha,
        "sample_population_sha256":population_sha,
        "blind_key_sha256":key_sha,
        "candidate_rule":manifest["candidate_rule"],
        "predeclared_final_gate":manifest["predeclared_final_gate"],
        "rendered_images_verified":len(image_hashes),
        "html_sha256":sha(html),
        "validity_sha256":sha(validity),
        "contract":{
            "sample_frozen_before_human_labels":True,
            "acceptance_rule_frozen_before_human_labels":True,
            "blind_key_contents_revealed":False,
            "human_labels_created":False,
            "automatic_merge":False,
            "geometry_mutated":False,
            "cross_block_merge_allowed":False,
        },
        "next":"COMPLETE_80_FINAL_BLIND_LABELS_THEN_FREEZE_LABELS_BEFORE_REVEAL",
    }
    fp=fout/"AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_FREEZE_V1.json"
    fp.write_text(json.dumps(viewer_freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    freeze_sha=sha(fp)
    (fout/"AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_FREEZE_V1.sha256").write_text(
        freeze_sha+"  AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_FREEZE_V1.json\n",encoding="utf-8")

    # Re-verify all rendered bytes after freeze file exists.
    if len(image_hashes)!=SAMPLE_N: raise RuntimeError("Expected 80 rendered image hashes")
    for name,e in image_hashes.items():
        if sha(imgdir/name)!=e: raise RuntimeError(f"Rendered image changed: {name}")
    if sha(key)!=key_sha: raise RuntimeError("Blind key changed after render")

    print(f"STATUS={STATUS}")
    print(f"VIEWER_FREEZE_STATUS={FREEZE_STATUS}")
    print(f"C_VALIDATION_REVEAL_FREEZE_SHA256={c_freeze_sha}")
    print(f"FINAL_GATE_RULE=S2026_GT_P95_AND_HPRIOR_GT_P25")
    print(f"PRIOR_REVIEWED_EXCLUDED={EXPECTED_PRIOR_UNION}")
    print(f"ELIGIBLE_UNSEEN={len(eligible)}")
    print(f"SAMPLE=80")
    print(f"EXCLUSION_SET_SHA256={exclusion_sha}")
    print(f"SAMPLE_POPULATION_SHA256={population_sha}")
    print(f"BLIND_KEY_SHA256={key_sha}")
    print(f"SOURCE_MANIFEST_SHA256={source_manifest_sha}")
    print(f"FINAL_GATE_VIEWER_FREEZE_SHA256={freeze_sha}")
    print("ACCEPT_BROAD_RATE_MIN=0.90")
    print("ACCEPT_BROAD_ONE_SIDED_WILSON95_LOWER_MIN=0.85")
    print("ACCEPT_BEHALL_RATE_MAX=0.05")
    print("ACCEPT_EJ_BEDOMBAR_MAX_COUNT=8")
    print("FINAL_BLIND_TEST_FOR_CURRENT_SIGNAL_FAMILY=TRUE")
    print("NO_POSTHOC_THRESHOLD_CHASE=TRUE")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE HUMAN_LABELS_CREATED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print(f"OUTPUT={html}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
