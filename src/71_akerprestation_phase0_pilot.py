#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPrestation phase 0: exact static-context overlay pilot for Skurup.

No satellite/yield model and no web output. This runner consumes the verified
discovery caches and writes a checkpointed Skurup pilot plus STOPPUNKT B QA.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from akerprestation_phase0_discovery_core import (
    EXPECTED_BASE_COMMIT, EXPECTED_BASE_TAG, load_json, repository_snapshot, sha256_file
)
from akerprestation_phase0_overlay_core import (
    CHECKPOINT_VERSION, SCHEMA_VERSION, SOIL_SPEC, SKO_SPEC,
    atomic_json, atomic_parquet, checkpoint_valid, combine_context,
    field_id, find_frozen_akerminne_field_year_file, overlay_fields,
    percentile_dict, prepare_geometries, sha256_file as overlay_sha256_file,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT_DEFAULT = ROOT / "data" / "derived" / "akerprestation_phase0"
DISCOVERY_MANIFEST = PHASE_ROOT_DEFAULT / "manifests" / "discovery_manifest.json"
DISCOVERY_SOURCE = PHASE_ROOT_DEFAULT / "discovery" / "source"
SOIL_SOURCE = DISCOVERY_SOURCE / "jord_skogsklassificering_class1_10.gpkg"
SKO_SOURCE = DISCOVERY_SOURCE / "jordbruksverket_sko.gpkg"
PROJECT_CONFIG = ROOT / "config" / "local_paths.json"
MUNICIPALITY_CONFIG = ROOT / "config" / "akerminne_skane_municipalities.json"
PHASE_CONFIG = ROOT / "config" / "akerprestation_phase0_v0a.json"
OVERLAY_CORE = ROOT / "src" / "akerprestation_phase0_overlay_core.py"
PILOT_SCHEMA = "akerprestation-phase0-pilot-v0a"

class Logger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("w", encoding="utf-8")
    def __call__(self, message: str):
        line = str(message)
        print(line, flush=True)
        self.fh.write(line + "\n"); self.fh.flush()
    def close(self):
        self.fh.close()

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def read_municipality_name(code: str) -> str:
    doc = load_json(MUNICIPALITY_CONFIG)
    for row in doc.get("municipalities") or []:
        if str(row["code"]) == code:
            return str(row["name"])
    raise RuntimeError(f"Municipality code {code} missing from config")

def read_current_fields(project: dict[str, Any], code: str) -> gpd.GeoDataFrame:
    path = Path(project["skiften"])
    try:
        g = gpd.read_file(path, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'")
        if len(g):
            return g
    except Exception:
        pass
    g = gpd.read_file(path)
    if "region_kod" not in g.columns:
        raise RuntimeError("Current field source missing region_kod")
    return g[g["region_kod"].astype(str).str.startswith(code)].copy()

def make_ids(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    x = g.copy()
    x["current_field_id"] = [field_id(b,s) for b,s in zip(x["blockid"], x["skiftesbeteckning"])]
    return x

def checkpoint_paths(phase_root: Path, municipality: str, layer: str):
    d = phase_root / "checkpoints" / municipality / layer
    return d / "summary.parquet", d / "components.parquet", d / "checkpoint_manifest.json"

def build_or_resume_layer(
    phase_root: Path, fields: gpd.GeoDataFrame, ref: gpd.GeoDataFrame, layer: str,
    source_path: Path, field_source_hash: str, source_hash: str, municipality: str,
    reference_year: int, resume: bool, force_layer: str | None, progress_every: int,
    log: Logger,
):
    spec = SOIL_SPEC if layer == "soil_class" else SKO_SPEC
    s_path, c_path, m_path = checkpoint_paths(phase_root, municipality, layer)
    expected = {
        "schema_version": CHECKPOINT_VERSION,
        "layer": layer,
        "municipality": municipality,
        "reference_year": reference_year,
        "field_source_sha256": field_source_hash,
        "reference_source_sha256": source_hash,
        "overlay_core_sha256": overlay_sha256_file(OVERLAY_CORE),
    }
    if resume and force_layer != layer and checkpoint_valid(s_path, c_path, m_path, expected):
        log(f"[{municipality}][{layer}] checkpoint HIT - validated and reused")
        return pd.read_parquet(s_path), pd.read_parquet(c_path), load_json(m_path), True

    if force_layer == layer:
        log(f"[{municipality}][{layer}] force-layer requested - rebuilding layer")
    t0 = time.perf_counter()
    summary, components, qa = overlay_fields(
        fields, ref, spec, municipality, reference_year, progress_every, log
    )
    atomic_parquet(summary, s_path)
    atomic_parquet(components, c_path)
    manifest = {
        **expected,
        "summary_rows": int(len(summary)),
        "component_rows": int(len(components)),
        "summary_sha256": sha256_file(s_path),
        "components_sha256": sha256_file(c_path),
        "elapsed_seconds": round(time.perf_counter()-t0,3),
        "qa": qa,
        "created_utc": utc_now(),
    }
    atomic_json(manifest, m_path)
    if not checkpoint_valid(s_path,c_path,m_path,expected):
        raise RuntimeError(f"{layer}: freshly written checkpoint failed validation")
    log(f"[{municipality}][{layer}] checkpoint WRITTEN + VALIDATED")
    return summary, components, manifest, False

def area_by_code(components: pd.DataFrame, code_col: str) -> list[dict[str,Any]]:
    if components.empty:
        return []
    x=(components.groupby(code_col, dropna=False)
       .agg(component_rows=("current_field_id","size"),
            field_count=("current_field_id","nunique"),
            intersection_area_m2=("intersection_area_m2","sum"))
       .reset_index()
       .sort_values(code_col, kind="mergesort"))
    return x.to_dict("records")

def area_reconciliation(context: pd.DataFrame, components: pd.DataFrame, prefix: str) -> dict[str,float]:
    return {
        "total_field_area_m2": float(context["field_area_m2"].sum()),
        "total_intersection_area_m2": float(components["intersection_area_m2"].sum()) if len(components) else 0.0,
        "total_uncovered_area_m2": float((context["field_area_m2"] * (1.0-context[f"{prefix}_coverage_unique"])).sum()),
        "total_duplicate_overlap_area_m2": float(context[f"{prefix}_duplicate_overlap_area_m2"].sum()),
    }

def discover_frozen_akerminne(repo_root: Path, municipality_code: str, municipality: str, pilot_ids: set[str]) -> tuple[dict[str,Any], pd.DataFrame | None, str | None]:
    path=find_frozen_akerminne_field_year_file(repo_root, municipality_code, municipality)
    if path is None:
        return {"status":"FAIL","reason":"Frozen ÅkerMinne municipality field-year artifact not found in any Git worktree"},None,None
    before=sha256_file(path)
    frame=pd.read_parquet(path)
    ids=set(frame["current_field_id"].astype(str))
    current=frame[frame["history_year"].astype(int)==2025]
    qa={
        "status":"PASS",
        "artifact":str(path),
        "artifact_sha256_before":before,
        "field_year_rows":int(len(frame)),
        "unique_current_field_ids":int(len(ids)),
        "years":sorted(map(int,frame["history_year"].unique())),
        "pilot_reference_ids":len(pilot_ids),
        "matched_pilot_ids":len(pilot_ids & ids),
        "unmatched_pilot_ids":sorted(pilot_ids-ids)[:100],
        "current_2025_rows":int(len(current)),
        "join_is_one_to_one":bool(len(current)==len(ids) and current["current_field_id"].is_unique),
        "expected_11_year_rows":bool(len(frame)==len(ids)*11),
    }
    return qa,frame,before

def select_manual_ids(context: pd.DataFrame, frozen: pd.DataFrame | None) -> dict[str,Any]:
    def first_ids(mask, n=5):
        return context.loc[mask].sort_values("current_field_id",kind="mergesort")["current_field_id"].astype(str).head(n).tolist()
    categories={}
    categories["simple_single_class"]=first_ids(
        (context["soil_class_count"]==1) & (context["soil_class_coverage_unique"]>0.999) &
        (~context["mixed_soil_class"]) & (~context["crosses_sko_boundary"])
    )
    categories["class_1_5"]=first_ids(context["dominant_soil_class"].isin([1,2,3,4,5]))
    categories["mixed_class"]=first_ids(context["mixed_soil_class"])
    categories["sko_boundary"]=first_ids(context["crosses_sko_boundary"])
    problem_mask=(context["soil_class_coverage_unique"]<0.999)|(context["sko_coverage_unique"]<0.999)|(context["context_status"].isin(["OVERLAP_ANOMALY","GEOMETRY_ERROR","MISSING_SOIL_CLASS","MISSING_SKO"]))
    categories["missing_or_problem"]=first_ids(problem_mask)
    full_history=[]
    split_merge=[]
    if frozen is not None:
        counts=frozen.groupby("current_field_id")["history_year"].nunique()
        full_history=sorted(counts[counts==11].index.astype(str))[:5]
        if "reason_flags" in frozen.columns:
            m=frozen["reason_flags"].astype(str).str.contains("SPLIT|MERGE",case=False,regex=True)
            split_merge=sorted(frozen.loc[m,"current_field_id"].astype(str).unique())[:5]
        elif "identity_match_confidence" in frozen.columns:
            m=frozen["identity_match_confidence"].astype(str).str.contains("split|merge",case=False,regex=True)
            split_merge=sorted(frozen.loc[m,"current_field_id"].astype(str).unique())[:5]
    categories["akerminne_full_history"]=full_history
    categories["akerminne_split_merge"]=split_merge
    return {
        "categories":categories,
        "shortages":{k:max(0,5-len(v)) for k,v in categories.items()},
        "instructions":{
            "simple_single_class":"Check field outline, one class, and dominant class visually.",
            "class_1_5":"Check that class 1-5 comes from source polygons, not inference.",
            "mixed_class":"Check visible class boundary and reported area shares.",
            "sko_boundary":"Check field crosses official SKO boundary and reported shares.",
            "missing_or_problem":"Check source gap/overlap/geometry reason.",
            "akerminne_full_history":"Check that static context joins once to an 11-year ÅkerMinne history.",
            "akerminne_split_merge":"Check a historical split/merge keeps one static 2025 context row.",
        }
    }

def problem_selection(context: pd.DataFrame, n_each: int=5) -> list[str]:
    ids=[]
    def add(frame):
        for v in frame["current_field_id"].astype(str):
            if v not in ids: ids.append(v)
    add(context.nsmallest(n_each,"soil_class_coverage_unique"))
    add(context.nsmallest(n_each,"sko_coverage_unique"))
    add(context.nlargest(n_each,"soil_class_count"))
    add(context[context["crosses_sko_boundary"]].head(n_each))
    add(context[(context["soil_class_coverage_raw"]>1.000001)|(context["sko_coverage_raw"]>1.000001)].head(n_each))
    add(context[context["reason_flags"].astype(str).str.contains("UNVERIFIED_CLASS_CODE|REPAIRED",regex=True)].head(n_each))
    add(context[context["dominant_soil_class"].isin([1,2,3,4,5])].head(n_each))
    return ids

def write_problem_geojson(all_fields: gpd.GeoDataFrame, context: pd.DataFrame, ids: list[str], path: Path) -> None:
    f=make_ids(all_fields)
    selected=f[f["current_field_id"].isin(ids)][["current_field_id","blockid","skiftesbeteckning","geometry"]].copy()
    attrs=context[context["current_field_id"].isin(ids)].drop(columns=[c for c in context.columns if c.endswith("_soil") or c.endswith("_sko")],errors="ignore")
    out=selected.merge(attrs,on="current_field_id",how="left",validate="one_to_one")
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp.geojson")
    out.to_file(tmp,driver="GeoJSON")
    os.replace(tmp,path)

def write_unverified(soil_components: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True,exist_ok=True)
    x=soil_components[soil_components["soil_class_normalized"].isna()].copy() if len(soil_components) else pd.DataFrame()
    cols=["soil_class_raw","source_feature_id","current_field_id","intersection_area_m2","reason_flags"]
    if x.empty:
        pd.DataFrame(columns=cols).to_csv(path,index=False,encoding="utf-8-sig")
        return 0
    x[cols].to_csv(path,index=False,encoding="utf-8-sig")
    return int(len(x))


def municipality_map() -> dict[str,str]:
    doc=load_json(MUNICIPALITY_CONFIG)
    return {str(x["code"]):str(x["name"]) for x in doc.get("municipalities") or []}

def build_supplemental_real_cases(
    project:dict[str,Any], soil_ref:gpd.GeoDataFrame, sko_ref:gpd.GeoDataFrame,
    need_low_class:bool, need_mixed:bool, need_sko_boundary:bool, need_low_coverage:bool, log:Logger
) -> tuple[pd.DataFrame,gpd.GeoDataFrame]:
    """Pick a small deterministic real subset outside Skurup only when pilot lacks a required case."""
    if not (need_low_class or need_mixed or need_sko_boundary or need_low_coverage):
        return pd.DataFrame(), gpd.GeoDataFrame(columns=["current_field_id","geometry"],geometry="geometry",crs=3006)
    log("[supplement] Skurup lacks one or more required integration cases; scanning minimal real candidates outside Skurup...")
    all_fields=gpd.read_file(Path(project["skiften"]))
    all_fields=make_ids(all_fields).to_crs(3006)
    all_fields=all_fields[~all_fields["region_kod"].astype(str).str.startswith("1264")].copy()
    fmap=municipality_map()
    all_fields["municipality_code"]=all_fields["region_kod"].astype(str).str[:4]
    all_fields["actual_municipality"]=all_fields["municipality_code"].map(fmap).fillna(all_fields["municipality_code"])
    soil_fixed,_=prepare_geometries(soil_ref,"soil_class_supplement")
    sko_fixed,_=prepare_geometries(sko_ref,"sko_supplement")
    findex=all_fields.sindex
    candidates:set[int]=set()

    if need_low_class:
        low=soil_fixed[soil_fixed["KLASS"].astype(float).between(1,5)]
        if len(low):
            try: union=low.geometry.union_all()
            except Exception: union=low.geometry.unary_union
            idxs=list(findex.query(union,predicate="intersects"))
            for i in sorted(map(int,idxs))[:80]: candidates.add(i)
            log(f"[supplement] low-class candidate fields: {len(idxs):,}; testing first {min(80,len(idxs)):,}")
    if need_sko_boundary:
        try: bnd=sko_fixed.geometry.boundary.union_all()
        except Exception: bnd=sko_fixed.geometry.boundary.unary_union
        idxs=list(findex.query(bnd,predicate="intersects"))
        for i in sorted(map(int,idxs))[:80]: candidates.add(i)
        log(f"[supplement] SKO-boundary candidate fields: {len(idxs):,}; testing first {min(80,len(idxs)):,}")
    if need_low_coverage or need_mixed:
        try: bnd=soil_fixed.geometry.boundary.union_all()
        except Exception: bnd=soil_fixed.geometry.boundary.unary_union
        idxs=list(findex.query(bnd,predicate="intersects"))
        for i in sorted(map(int,idxs))[:120]: candidates.add(i)
        log(f"[supplement] class-edge candidate fields: {len(idxs):,}; testing first {min(120,len(idxs)):,}")

    if not candidates:
        return pd.DataFrame(), gpd.GeoDataFrame(columns=["current_field_id","geometry"],geometry="geometry",crs=3006)
    cand=all_fields.iloc[sorted(candidates)].copy()
    # deterministic cap; this is a diagnostic subset, not a county run
    cand=cand.sort_values("current_field_id",kind="mergesort").head(160).copy()
    log(f"[supplement] exact overlay on {len(cand):,} real candidate fields; progress every 20")
    ss,_,_=overlay_fields(cand,soil_ref,SOIL_SPEC,"Supplement",2025,20,log)
    sk,_,_=overlay_fields(cand,sko_ref,SKO_SPEC,"Supplement",2025,20,log)
    ctx=combine_context(ss,sk,"supplemental-real-cases")
    attrs=cand[["current_field_id","blockid","skiftesbeteckning","actual_municipality","municipality_code","geometry"]].copy()
    ctx=ctx.merge(attrs.drop(columns="geometry"),on="current_field_id",how="left",validate="one_to_one")
    ctx["municipality"]=ctx["actual_municipality"]
    selected=[]
    def take(mask,n=5):
        for fid in ctx.loc[mask].sort_values("current_field_id",kind="mergesort")["current_field_id"].astype(str).head(n):
            if fid not in selected: selected.append(fid)
    if need_low_class: take(ctx["dominant_soil_class"].isin([1,2,3,4,5]),8)
    if need_sko_boundary: take(ctx["crosses_sko_boundary"],5)
    if need_mixed: take(ctx["mixed_soil_class"],8)
    if need_low_coverage: take(ctx["soil_class_coverage_unique"]<0.999,8)
    ctx=ctx[ctx["current_field_id"].isin(selected)].copy()
    geoms=attrs[attrs["current_field_id"].isin(selected)].copy()
    log(f"[supplement] retained {len(ctx):,} real supplemental cases")
    return ctx,geoms


def write_markdown(qa:dict[str,Any], checklist:dict[str,Any], path:Path):
    lines=[
        "# ÅkerPrestation fas 0 – Skuruppilot QA","",
        f"**Status:** `{qa['status']}`  ",
        f"**Skiften:** {qa['reference_fields']:,}  ",
        f"**Area:** {qa['total_field_area_m2']/1e6:.2f} km²  ",
        f"**Jordbruksklass:** 1–10 bevaras; klass 1–4 är ny komplettering, ingen imputering.  ",
        f"**SKO-källa:** officiell Jordbruksverket WFS-cache från godkänd discovery.  ","",
        "## Progress / återstart","",
        f"- Soil checkpoint reused: `{qa['resume']['soil_class_reused']}`",
        f"- SKO checkpoint reused: `{qa['resume']['sko_reused']}`",
        f"- Resume self-test: `{qa['resume']['resume_test_passed']}`","",
        "## Jordbruksklass","",
        f"- Dominant klass 1–5: {qa['soil']['dominant_class_1_5_fields']:,}",
        f"- Blandklassfält: {qa['soil']['mixed_fields']:,}",
        f"- Okända klasskomponenter: {qa['soil']['unverified_component_rows']:,}",
        f"- coverage_raw > 1: {qa['soil']['coverage_raw_gt_1']:,}",
        f"- Oklassad unik area: {qa['soil']['area_reconciliation']['total_uncovered_area_m2']:.1f} m²","",
        "## SKO","",
        f"- SKO-gränsfält: {qa['sko']['boundary_fields']:,}",
        f"- coverage_raw > 1: {qa['sko']['coverage_raw_gt_1']:,}",
        f"- Otäckt unik area: {qa['sko']['area_reconciliation']['total_uncovered_area_m2']:.1f} m²","",
        "## ÅkerMinne join/regression","",
        f"- Status: `{qa['akerminne_join']['status']}`",
        f"- Matchade pilot-ID: {qa['akerminne_join'].get('matched_pilot_ids',0):,}/{qa['reference_fields']:,}",
        f"- 1:1 på 2025-referens: `{qa['akerminne_join'].get('join_is_one_to_one',False)}`",
        f"- Frozen artifact unchanged during run: `{qa['akerminne_join'].get('artifact_unchanged_during_run',False)}`","",
        "## Manuell kontroll","",
    ]
    for cat,ids in checklist["categories"].items():
        lines.append(f"### {cat}")
        if not ids: lines.append("- Inga verkliga fall i pilot/ÅkerMinne-artefakten.")
        for fid in ids: lines.append(f"- `{fid}` — {checklist['instructions'][cat]}")
        lines.append("")
    lines += ["## STOPPUNKT B","",
              "Ingen Skånekörning och ingen webbimplementation har startats.",
              "Bengt ska granska QA och manuella exempel före nästa GO.",""]
    path.write_text("\n".join(lines),encoding="utf-8")

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--municipality",default="Skurup")
    ap.add_argument("--municipality-code",default="1264")
    ap.add_argument("--layers",default="soil_class,sko")
    ap.add_argument("--resume",action="store_true")
    ap.add_argument("--resume-probe",action="store_true")
    ap.add_argument("--force-layer",choices=["soil_class","sko"])
    ap.add_argument("--dry-run",action="store_true")
    ap.add_argument("--progress-every",type=int,default=250)
    ap.add_argument("--project-config",default=str(PROJECT_CONFIG))
    ap.add_argument("--phase-root",default=str(PHASE_ROOT_DEFAULT))
    args=ap.parse_args()

    phase_root=Path(args.phase_root)
    log_path=phase_root/"logs"/("pilot_skurup_resume_probe.log" if args.resume_probe else "pilot_skurup.log")
    log=Logger(log_path)
    t_run=time.perf_counter()
    try:
        repo=repository_snapshot(ROOT)
        if repo["akerminne_v1_base_commit"]!=EXPECTED_BASE_COMMIT:
            raise RuntimeError("Frozen ÅkerMinne base mismatch")
        project=load_json(Path(args.project_config))
        config=load_json(PHASE_CONFIG)
        discovery=load_json(phase_root/"manifests"/"discovery_manifest.json")
        if discovery.get("status") not in {"PASS","PASS_WITH_WARNINGS"}:
            raise RuntimeError(f"Discovery manifest not approved: {discovery.get('status')}")
        if not SOIL_SOURCE.exists() or not SKO_SOURCE.exists():
            raise FileNotFoundError("Discovery source caches missing; rerun discovery")

        municipality=args.municipality
        code=args.municipality_code
        configured_name=read_municipality_name(code)
        if configured_name.lower()!=municipality.lower():
            raise RuntimeError(f"Municipality mismatch: {code} is {configured_name}")

        fields=read_current_fields(project,code)
        if len(fields)!=2944:
            raise RuntimeError(f"Skurup frozen control expects 2,944 fields; got {len(fields):,}")
        fields=make_ids(fields)
        if not fields["current_field_id"].is_unique:
            raise RuntimeError("Skurup current_field_id not unique")
        field_source=Path(project["skiften"])
        field_hash=sha256_file(field_source)
        soil_hash=sha256_file(SOIL_SOURCE); sko_hash=sha256_file(SKO_SOURCE)

        log("="*88)
        log("ÅkerPrestation phase 0 · SKURUP PILOT · exact class/SKO overlay")
        log("="*88)
        log(f"Base: {EXPECTED_BASE_TAG} {EXPECTED_BASE_COMMIT}")
        log(f"HEAD: {repo['head_commit']}")
        log(f"Municipality: {municipality} ({code}) · {len(fields):,} fields")
        log(f"Progress: every {args.progress_every:,} fields (full Skåne runner will use 5,000 by default)")
        if args.dry_run:
            log("DRY RUN: inputs verified; no overlay/checkpoints written")
            return 0

        requested=[x.strip() for x in args.layers.split(",") if x.strip()]
        if set(requested)-{"soil_class","sko"}:
            raise ValueError("--layers may contain soil_class,sko only")
        soil_ref=gpd.read_file(SOIL_SOURCE,layer="class1_10")
        sko_ref=gpd.read_file(SKO_SOURCE,layer="sko")
        summaries={}; components={}; manifests={}; reused={}
        for layer in requested:
            ref=soil_ref if layer=="soil_class" else sko_ref
            spath=SOIL_SOURCE if layer=="soil_class" else SKO_SOURCE
            shash=soil_hash if layer=="soil_class" else sko_hash
            s,c,m,hit=build_or_resume_layer(
                phase_root,fields,ref,layer,spath,field_hash,shash,municipality,2025,
                args.resume,args.force_layer,args.progress_every,log)
            summaries[layer]=s; components[layer]=c; manifests[layer]=m; reused[layer]=hit

        for layer in ("soil_class","sko"):
            if layer not in summaries:
                s_path,c_path,m_path=checkpoint_paths(phase_root,municipality,layer)
                expected={
                    "schema_version":CHECKPOINT_VERSION,"layer":layer,"municipality":municipality,
                    "reference_year":2025,"field_source_sha256":field_hash,
                    "reference_source_sha256":soil_hash if layer=="soil_class" else sko_hash,
                    "overlay_core_sha256":overlay_sha256_file(OVERLAY_CORE),
                }
                if not checkpoint_valid(s_path,c_path,m_path,expected):
                    raise RuntimeError(f"{layer} not requested and no valid checkpoint exists")
                summaries[layer]=pd.read_parquet(s_path); components[layer]=pd.read_parquet(c_path); manifests[layer]=load_json(m_path); reused[layer]=True

        source_manifest_id=str(discovery.get("manifest_id"))
        context=combine_context(summaries["soil_class"],summaries["sko"],source_manifest_id)
        if len(context)!=len(fields) or not context["current_field_id"].is_unique:
            raise RuntimeError("Context must contain exactly one unique row per Skurup field")

        pilot_dir=phase_root/"pilot_skurup"; qa_dir=phase_root/"qa"; manifest_dir=phase_root/"manifests"
        pilot_dir.mkdir(parents=True,exist_ok=True); qa_dir.mkdir(parents=True,exist_ok=True)
        atomic_parquet(context,pilot_dir/"field_static_context.parquet")
        atomic_parquet(components["soil_class"],pilot_dir/"field_soil_class_components.parquet")
        atomic_parquet(components["sko"],pilot_dir/"field_sko_components.parquet")
        unverified_count=write_unverified(components["soil_class"],pilot_dir/"unverified_class_codes.csv")
        unverified_sko_count=int((components["sko"]["sko_id"].astype(str).str.strip()=="").sum()) if len(components["sko"]) else 0

        pilot_ids=set(context["current_field_id"].astype(str))
        join_qa,frozen,frozen_hash_before=discover_frozen_akerminne(ROOT,code,municipality,pilot_ids)
        if frozen is not None:
            frozen_hash_after=sha256_file(Path(join_qa["artifact"]))
            join_qa["artifact_sha256_after"]=frozen_hash_after
            join_qa["artifact_unchanged_during_run"]=frozen_hash_before==frozen_hash_after
        else:
            join_qa["artifact_unchanged_during_run"]=False
        join_ok=(join_qa.get("status")=="PASS" and join_qa.get("matched_pilot_ids")==len(fields) and
                 join_qa.get("join_is_one_to_one") and join_qa.get("expected_11_year_rows") and
                 join_qa.get("artifact_unchanged_during_run"))
        join_qa["acceptance_pass"]=bool(join_ok)
        atomic_json(join_qa,pilot_dir/"akerminne_context_join_qa.json")

        soil=context
        soil_qa={
            "area_by_raw_class":area_by_code(components["soil_class"],"soil_class_raw"),
            "area_by_normalized_class":area_by_code(components["soil_class"],"soil_class_normalized"),
            "dominant_class_1_5_fields":int(context["dominant_soil_class"].isin([1,2,3,4,5]).sum()),
            "mixed_fields":int(context["mixed_soil_class"].sum()),
            "dominant_share_percentiles":percentile_dict(context["dominant_soil_class_share"]),
            "coverage_raw_percentiles":percentile_dict(context["soil_class_coverage_raw"]),
            "coverage_unique_percentiles":percentile_dict(context["soil_class_coverage_unique"]),
            "unverified_component_rows":unverified_count,
            "coverage_raw_gt_1":int((context["soil_class_coverage_raw"]>1.000001).sum()),
            "area_reconciliation":area_reconciliation(context,components["soil_class"],"soil_class"),
            "checkpoint_qa":manifests["soil_class"].get("qa",{}),
        }
        sko_qa={
            "area_by_sko":area_by_code(components["sko"],"sko_id"),
            "boundary_fields":int(context["crosses_sko_boundary"].sum()),
            "dominant_share_percentiles":percentile_dict(context["dominant_sko_share"]),
            "coverage_raw_percentiles":percentile_dict(context["sko_coverage_raw"]),
            "coverage_unique_percentiles":percentile_dict(context["sko_coverage_unique"]),
            "coverage_raw_gt_1":int((context["sko_coverage_raw"]>1.000001).sum()),
            "unverified_sko_component_rows":unverified_sko_count,
            "area_reconciliation":area_reconciliation(context,components["sko"],"sko"),
            "checkpoint_qa":manifests["sko"].get("qa",{}),
        }
        # Integration-test supplementation: only if Skurup lacks required real cases.
        supplement_context_path=pilot_dir/"supplemental_real_cases.parquet"
        supplement_geo_path=pilot_dir/"supplemental_real_cases.geojson"
        need_low=int(context["dominant_soil_class"].isin([1,2,3,4,5]).sum()) < 5
        need_mixed=int(context["mixed_soil_class"].sum()) < 5
        need_boundary=int(context["crosses_sko_boundary"].sum()) < 1
        need_problem=int(((context["soil_class_coverage_unique"]<0.999)|(context["sko_coverage_unique"]<0.999)).sum()) < 1
        supplement_ctx=pd.DataFrame()
        supplement_geoms=gpd.GeoDataFrame(columns=["current_field_id","blockid","skiftesbeteckning","geometry"],geometry="geometry",crs=3006)
        if args.resume and supplement_context_path.exists() and supplement_geo_path.exists():
            supplement_ctx=pd.read_parquet(supplement_context_path)
            supplement_geoms=gpd.read_file(supplement_geo_path)
            log(f"[supplement] checkpoint HIT - {len(supplement_ctx):,} real cases reused")
        elif need_low or need_mixed or need_boundary or need_problem:
            supplement_ctx,supplement_geoms=build_supplemental_real_cases(
                project,soil_ref,sko_ref,need_low,need_mixed,need_boundary,need_problem,log)
            if len(supplement_ctx):
                atomic_parquet(supplement_ctx,supplement_context_path)
                tmp=supplement_geo_path.with_suffix(".tmp.geojson")
                supplement_geoms.to_file(tmp,driver="GeoJSON")
                os.replace(tmp,supplement_geo_path)

        manual_context=pd.concat([context,supplement_ctx],ignore_index=True,sort=False) if len(supplement_ctx) else context.copy()
        checklist=select_manual_ids(manual_context,frozen)
        checklist["supplemental_real_case_count"]=int(len(supplement_ctx))
        if len(supplement_ctx):
            checklist["supplemental_municipalities"]=sorted(set(supplement_ctx["actual_municipality"].astype(str)))
        atomic_json(checklist,pilot_dir/"manual_checklist.json")
        pids=problem_selection(manual_context)
        problem_fields=pd.concat([fields,supplement_geoms],ignore_index=True,sort=False) if len(supplement_geoms) else fields
        write_problem_geojson(problem_fields,manual_context,pids,pilot_dir/"problem_fields.geojson")

        resume_pass=bool(args.resume_probe and reused.get("soil_class") and reused.get("sko"))
        qa={
            "schema_version":PILOT_SCHEMA,
            "status":"PASS" if join_ok and unverified_count==0 and unverified_sko_count==0 else "FAIL",
            "reference_fields":int(len(context)),
            "total_field_area_m2":float(context["field_area_m2"].sum()),
            "context_status_counts":{str(k):int(v) for k,v in context["context_status"].value_counts().sort_index().items()},
            "soil":soil_qa,"sko":sko_qa,"akerminne_join":join_qa,
            "resume":{"soil_class_reused":bool(reused.get("soil_class")),"sko_reused":bool(reused.get("sko")),
                      "resume_probe_requested":bool(args.resume_probe),"resume_test_passed":resume_pass},
            "manual_checklist":checklist,
            "problem_field_count":len(pids),
            "elapsed_seconds_this_invocation":round(time.perf_counter()-t_run,3),
            "git":{"base_tag":EXPECTED_BASE_TAG,"base_commit":EXPECTED_BASE_COMMIT,"head_commit":repo["head_commit"],"branch":repo["branch"]},
            "source_hashes":{"reference_fields":field_hash,"soil_class":soil_hash,"sko":sko_hash,"overlay_core":overlay_sha256_file(OVERLAY_CORE)},
            "output_sizes_bytes":{},
        }
        for path in [pilot_dir/"field_static_context.parquet",pilot_dir/"field_soil_class_components.parquet",
                     pilot_dir/"field_sko_components.parquet",pilot_dir/"problem_fields.geojson"]:
            qa["output_sizes_bytes"][path.name]=path.stat().st_size
        if args.resume_probe and not resume_pass:
            qa["status"]="FAIL"
        atomic_json(qa,pilot_dir/"phase0_pilot_qa.json")
        write_markdown(qa,checklist,pilot_dir/"phase0_pilot_qa.md")

        run_manifest={
            "schema_version":PILOT_SCHEMA,"created_utc":utc_now(),"status":qa["status"],
            "municipality":municipality,"municipality_code":code,"reference_year":2025,
            "discovery_manifest_id":source_manifest_id,"discovery_manifest_sha256":sha256_file(phase_root/"manifests"/"discovery_manifest.json"),
            "git":qa["git"],"sources":qa["source_hashes"],
            "outputs":{p.name:sha256_file(p) for p in [
                pilot_dir/"field_static_context.parquet",pilot_dir/"field_soil_class_components.parquet",
                pilot_dir/"field_sko_components.parquet",pilot_dir/"phase0_pilot_qa.json",
                pilot_dir/"akerminne_context_join_qa.json",pilot_dir/"problem_fields.geojson"]},
            "scope_guardrail":"Skurup pilot only. No Skåne expansion, no web, no satellite, no yield model."
        }
        atomic_json(run_manifest,manifest_dir/"run_manifest.json")

        log("="*88)
        log(f"ÅkerPrestation phase 0 SKURUP PILOT: {qa['status']}")
        log("="*88)
        log(f"Reference fields: {len(context):,}")
        log(f"Dominant class 1-5 fields: {soil_qa['dominant_class_1_5_fields']:,}")
        log(f"Mixed soil-class fields: {soil_qa['mixed_fields']:,}")
        log(f"SKO boundary fields: {sko_qa['boundary_fields']:,}")
        log(f"Unverified class component rows: {unverified_count:,}")
        log(f"Unverified SKO component rows: {unverified_sko_count:,}")
        log(f"ÅkerMinne join: {join_qa.get('matched_pilot_ids',0):,}/{len(context):,}; acceptance={join_ok}")
        log(f"Resume probe: requested={args.resume_probe}; passed={resume_pass}")
        for flag in sorted(set(";".join(context["reason_flags"].astype(str)).split(";"))):
            if flag:
                log(f"WARN_CONTEXT_FLAG_PRESENT: {flag}")
        if qa["status"]!="PASS":
            log("ERROR_PILOT_ACCEPTANCE: one or more STOPPUNKT B machine checks failed")
            return 1
        log("STOPPUNKT B: no later phase executed")
        log(f"QA: {pilot_dir/'phase0_pilot_qa.md'}")
        return 0
    except Exception as exc:
        log(f"ERROR_PILOT_EXCEPTION: {type(exc).__name__}: {exc}")
        return 1
    finally:
        log.close()

if __name__=="__main__":
    raise SystemExit(main())
