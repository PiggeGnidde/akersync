#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

from akerprestation_phase0_discovery_core import load_json, sha256_file
from akerprestation_phase0_overlay_core import SCHEMA_VERSION

ROOT=Path(__file__).resolve().parents[1]
PHASE=ROOT/"data"/"derived"/"akerprestation_phase0"
PILOT=PHASE/"pilot_skurup"

def req(path:Path):
    if not path.exists(): raise FileNotFoundError(path)
    return path

def main()->int:
    qa=load_json(req(PILOT/"phase0_pilot_qa.json"))
    join=load_json(req(PILOT/"akerminne_context_join_qa.json"))
    manifest=load_json(req(PHASE/"manifests"/"run_manifest.json"))
    context=pd.read_parquet(req(PILOT/"field_static_context.parquet"))
    soil=pd.read_parquet(req(PILOT/"field_soil_class_components.parquet"))
    sko=pd.read_parquet(req(PILOT/"field_sko_components.parquet"))
    errors=[]
    if qa.get("status")!="PASS": errors.append("QA status is not PASS")
    if len(context)!=2944 or not context["current_field_id"].is_unique: errors.append("context is not 2,944 unique fields")
    if set(context["schema_version"].astype(str))!={SCHEMA_VERSION}: errors.append("context schema version mismatch")
    if not {"soil_class_raw","soil_class_normalized","intersection_area_m2","field_share_raw","component_rank","source_feature_id"}.issubset(soil.columns): errors.append("soil component schema incomplete")
    if not {"sko_id","intersection_area_m2","field_share_raw","component_rank","source_feature_id"}.issubset(sko.columns): errors.append("SKO component schema incomplete")
    if int(qa["soil"]["unverified_component_rows"])!=0: errors.append("unverified soil class code present")
    if int(qa["sko"].get("unverified_sko_component_rows",0))!=0: errors.append("unverified SKO id intersects pilot field")
    if not join.get("acceptance_pass"): errors.append("ÅkerMinne join acceptance failed")
    if not qa.get("resume",{}).get("resume_test_passed"): errors.append("resume self-test did not pass")
    if not req(PILOT/"problem_fields.geojson").exists(): errors.append("problem_fields.geojson missing")
    for name,expected in (manifest.get("outputs") or {}).items():
        p=PILOT/name
        if not p.exists() or sha256_file(p)!=expected: errors.append(f"manifest hash mismatch: {name}")
    print("="*82)
    print("ÅkerPrestation phase 0 · VERIFY SKURUP PILOT")
    print("="*82)
    print(f"Context rows: {len(context):,}")
    print(f"Soil components: {len(soil):,}")
    print(f"SKO components: {len(sko):,}")
    print(f"ÅkerMinne join acceptance: {join.get('acceptance_pass')}")
    print(f"Resume self-test: {qa.get('resume',{}).get('resume_test_passed')}")
    if errors:
        for e in errors: print("ERROR_VERIFY: "+e)
        print("VERIFY_AKERPRESTATION_PHASE0_PILOT_SKURUP: FAIL")
        return 1
    print("VERIFY_AKERPRESTATION_PHASE0_PILOT_SKURUP: PASS")
    print("STOPPUNKT B: no Skåne/web phase executed")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
