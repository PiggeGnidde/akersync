#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent verifier for ÅkerVatten web v0a."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"src") not in sys.path:
    sys.path.insert(0,str(ROOT/"src"))

spec=importlib.util.spec_from_file_location("akervatten_web_build_verify",ROOT/"src/111_build_akervatten_web_v0a.py")
assert spec and spec.loader
BUILD=importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


def load_json(path:Path)->dict:
    if not path.exists():
        raise RuntimeError(f"Missing verifier input: {path}")
    text=path.read_text(encoding="utf-8-sig")
    def reject_constant(v:str):
        raise RuntimeError(f"Browser-invalid numeric constant {v} in {path}")
    return json.loads(text,parse_constant=reject_constant)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-dist",required=True,type=Path)
    ap.add_argument("--dist",required=True,type=Path)
    ap.add_argument("--work",default=str(ROOT/"work/akervatten_web_v0a"),type=Path)
    args=ap.parse_args()

    base=args.base_dist.resolve();dist=args.dist.resolve();work=args.work.resolve()
    problems=[]

    manifest=load_json(work/"akervatten_web_manifest.json")
    index=load_json(dist/"data/akervatten/skane_index.json")

    if manifest.get("status")!="PASS":
        problems.append("BUILD MANIFEST NOT PASS")
    scope=manifest.get("scope") or {}
    if scope.get("akervatten_model_recalculated") is not False:
        problems.append("BUILD CLAIMS WATER MODEL RECALCULATION")
    if scope.get("akerfro_base_changed") is not False:
        problems.append("BUILD CLAIMS ÅKERFRÖ BASE CHANGE")
    if scope.get("overall_water_score_created") is not False:
        problems.append("BUILD CLAIMS OVERALL SCORE")
    if scope.get("deployment") is not False:
        problems.append("BUILD CLAIMS DEPLOYMENT")

    if index.get("schema_version")!=BUILD.INDEX_SCHEMA or index.get("status")!="PASS":
        problems.append("WEB INDEX CONTRACT MISMATCH")
    if int(index.get("field_count",-1))!=BUILD.EXPECTED_FIELDS:
        problems.append("WEB INDEX FIELD COUNT MISMATCH")
    if int(index.get("municipality_count",-1))!=BUILD.EXPECTED_MUNICIPALITIES:
        problems.append("WEB INDEX MUNICIPALITY COUNT MISMATCH")
    if index.get("coverage")!=BUILD.EXPECTED_COVERAGE:
        problems.append("WEB INDEX SCORE COVERAGE MISMATCH")
    lg=index.get("large_groundwater") or {}
    if int(lg.get("direct_magazine_fields",-1))!=BUILD.EXPECTED_LARGE_DIRECT:
        problems.append("WEB INDEX LARGE-GW DIRECT COVERAGE MISMATCH")
    if int(lg.get("capacity_class_fields",-1))!=BUILD.EXPECTED_LARGE_CAPACITY:
        problems.append("WEB INDEX LARGE-GW CAPACITY COVERAGE MISMATCH")
    if index.get("overall_score")!="NOT_CREATED":
        problems.append("WEB INDEX OVERALL SCORE CREATED")
    if index.get("legal_status")!="NOT_ASSESSED":
        problems.append("WEB INDEX LEGAL STATUS CHANGED")

    entries=index.get("municipalities") or []
    total=0
    field_ids=set()
    for entry in entries:
        path=dist/Path(str(entry["file"]))
        if not path.exists():
            problems.append(f"MISSING MUNICIPALITY SIDECAR {path}")
            continue
        if path.stat().st_size!=int(entry["bytes"]):
            problems.append(f"SIZE MISMATCH {path}")
        if BUILD.sha256_file(path)!=str(entry["sha256"]):
            problems.append(f"HASH MISMATCH {path}")
        p=load_json(path)
        if p.get("schema_version")!=BUILD.SCHEMA:
            problems.append(f"SCHEMA MISMATCH {path}")
        if p.get("municipality")!=entry.get("municipality"):
            problems.append(f"MUNICIPALITY MISMATCH {path}")
        n=int(p.get("field_count",-1))
        fields=p.get("fields") or {}
        if n!=len(fields):
            problems.append(f"FIELD COUNT MISMATCH {path}")
        total+=max(n,0)
        overlap=field_ids.intersection(fields)
        if overlap:
            problems.append(f"DUPLICATE FIELD IDS ACROSS SIDECARS {path}")
        field_ids.update(fields)

    if total!=BUILD.EXPECTED_FIELDS:
        problems.append(f"SIDECAR TOTAL {total} != {BUILD.EXPECTED_FIELDS}")
    if len(entries)!=BUILD.EXPECTED_MUNICIPALITIES:
        problems.append("SIDECAR MUNICIPALITY COUNT MISMATCH")

    regional=index.get("regional") or {}
    for key in ("groundwater_history","surfacewater_history","large_groundwater"):
        meta=regional.get(key) or {}
        path=dist/Path(str(meta.get("file","")))
        if not path.exists():
            problems.append(f"MISSING REGIONAL FILE {key}")
            continue
        if path.stat().st_size!=int(meta.get("bytes",-1)):
            problems.append(f"REGIONAL SIZE MISMATCH {key}")
        if BUILD.sha256_file(path)!=str(meta.get("sha256","")):
            problems.append(f"REGIONAL HASH MISMATCH {key}")
        doc=load_json(path)
        features=doc.get("features") or []
        if len(features)!=int(meta.get("features",-1)):
            problems.append(f"REGIONAL FEATURE COUNT MISMATCH {key}")
        if not features:
            problems.append(f"REGIONAL FILE EMPTY {key}")

    if int((regional.get("groundwater_history") or {}).get("features",-1))!=786:
        problems.append("GROUNDWATER HISTORY POLYGON COUNT != 786")
    if int((regional.get("surfacewater_history") or {}).get("features",-1))<502:
        problems.append("SURFACE-WATER POLYGON COUNT < 502")

    html_path=dist/"index.html"
    html=html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    for token in (
        "AKERNORM_WEB_UI_V1","AKERFRO_ERTOR_WEB_UI_V0A","AKERVATTEN_WEB_UI_V0A",
        'data-layer="fro"','data-layer="vatten"',
        "ÅkerVatten · informationslager","Ingen totalscore",
        "assets/akervatten_v0a.css","assets/akervatten_v0a.js",
        "window.AKERVATTEN_WEB_CONFIG","$"+"{akervattenSection(p)}",
    ):
        if token not in html:
            problems.append(f"TARGET INDEX MISSING TOKEN {token}")

    for path,tokens in (
        (dist/"assets/akervatten_v0a.css",(".akv-controls",".akv-layer-grid","@media(max-width:700px)")),
        (dist/"assets/akervatten_v0a.js",("currentWaterLayer","large_gw","groundwater_history","Vattenrätt: ej bedömd","akervattenSection")),
    ):
        if not path.exists() or path.stat().st_size<=200:
            problems.append(f"WEB ASSET MISSING/TOO SMALL {path}")
            continue
        text=path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                problems.append(f"ASSET {path.name} MISSING TOKEN {token}")

    try:
        BUILD.verify_base_target(base,dist)
    except Exception as exc:
        problems.append("PROTECTED ÅKERFRÖ BASE DIFFERS: "+str(exc))

    if manifest.get("base_index_sha256")!=BUILD.sha256_file(base/"index.html"):
        problems.append("MANIFEST BASE INDEX HASH MISMATCH")
    if html_path.exists() and manifest.get("patched_index_sha256")!=BUILD.sha256_file(html_path):
        problems.append("MANIFEST PATCHED INDEX HASH MISMATCH")

    result={
        "schema_version":"akervatten-web-verification-v0a",
        "status":"FAIL" if problems else "PASS",
        "field_count":total,
        "municipality_count":len(entries),
        "akernorm_marker_present":"AKERNORM_WEB_UI_V1" in html,
        "akerfro_marker_present":"AKERFRO_ERTOR_WEB_UI_V0A" in html,
        "akervatten_marker_present":"AKERVATTEN_WEB_UI_V0A" in html,
        "overall_score_created":False,
        "legal_status":"NOT_ASSESSED",
        "problems":problems,
    }
    work.mkdir(parents=True,exist_ok=True)
    (work/"verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*100)
    print("ÅkerVatten WEB VERIFY")
    print("="*100)
    print(f"Fields: {total:,} · municipalities: {len(entries)}")
    print("ÅkerNorm marker:", "YES" if result["akernorm_marker_present"] else "NO")
    print("ÅkerFrö marker:", "YES" if result["akerfro_marker_present"] else "NO")
    print("ÅkerVatten marker:", "YES" if result["akervatten_marker_present"] else "NO")
    print("Overall water score: NOT CREATED")
    print("Legal status: NOT ASSESSED")
    if problems:
        print("\nPROBLEMS")
        for p in problems: print("  - "+p)
        print("="*100);print("VERIFY_AKERVATTEN_WEB_V0A: FAIL");return 2
    print("="*100);print("VERIFY_AKERVATTEN_WEB_V0A: PASS");print("="*100);return 0


if __name__=="__main__":
    raise SystemExit(main())
