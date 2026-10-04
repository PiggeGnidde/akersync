#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Package the already-QAed ÅkerPass unified dist as RC1.

IMPORTANT: this script never rebuilds the web. It freezes exactly the current
dist_akerpass_unified_v0a after the independent verifier has passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/"dist_akerpass_unified_v0a"
UWORK=ROOT/"work"/"akerpass_unified_web_v0a"
WORK=ROOT/"work"/"akerpass_unified_rc1"
RELEASE=ROOT/"release"
ZIP_PATH=RELEASE/"akerpass_unified_preview_v0a_r1_rc1.zip"
MANIFEST=WORK/"akerpass_unified_preview_v0a_r1_rc1_manifest.json"
DIST_MANIFEST=UWORK/"dist_manifest.json"
BUILD_MANIFEST=UWORK/"build_manifest.json"
VERIFICATION=UWORK/"verification.json"

EXPECTED_FILES=189
EXPECTED_ROTATION_RELEASES=43
EXPECTED_BESTMATCH_CANDIDATES=16004
EXPECTED_SCREENING_UNION=5000
EXPECTED_WATER_FIELDS=128636
EXPECTED_VISS_POSITIVE=16626
EXPECTED_GW_LEVEL_IMPACT=5495

# Store formats that are already compressed; deflate text/JSON/GeoJSON/HTML/CSS/JS.
STORE_SUFFIXES={
    ".png",".jpg",".jpeg",".webp",".gif",".zip",".gz",".bz2",".xz",
    ".woff",".woff2",".ttf",".otf",".pdf",".mp4",".webm",".tif",".tiff",
}

def stable_json(obj)->str:
    return json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n"

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def git_value(*args:str)->str:
    return subprocess.check_output(["git",*args],cwd=ROOT,text=True,encoding="utf-8").strip()

def is_ancestor(old:str,new:str)->bool:
    r=subprocess.run(["git","merge-base","--is-ancestor",old,new],cwd=ROOT)
    return r.returncode==0

def load_json(path:Path)->dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))

def scan_dist()->list[dict]:
    rows=[]
    for p in sorted(x for x in DIST.rglob("*") if x.is_file()):
        rows.append({
            "path":p.relative_to(DIST).as_posix(),
            "bytes":int(p.stat().st_size),
            "sha256":sha256_file(p),
        })
    return rows

def tree_sha(rows:list[dict])->str:
    payload=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def compare_unified_manifest(rows:list[dict])->None:
    m=load_json(DIST_MANIFEST)
    old=m.get("files") or []
    # Normalize to the exact fields that define the frozen tree.
    a=[{"path":str(x["path"]),"bytes":int(x["bytes"]),"sha256":str(x["sha256"])} for x in old]
    b=[{"path":str(x["path"]),"bytes":int(x["bytes"]),"sha256":str(x["sha256"])} for x in rows]
    if a!=b:
        old_map={x["path"]:(int(x["bytes"]),x["sha256"]) for x in a}
        new_map={x["path"]:(int(x["bytes"]),x["sha256"]) for x in b}
        missing=sorted(set(old_map)-set(new_map))
        extra=sorted(set(new_map)-set(old_map))
        changed=sorted(k for k in set(old_map)&set(new_map) if old_map[k]!=new_map[k])
        raise RuntimeError(
            "Current dist differs from the independently verified dist manifest. "
            f"missing={missing[:5]}, extra={extra[:5]}, changed={changed[:5]}"
        )

def write_deterministic_zip(rows:list[dict])->None:
    RELEASE.mkdir(parents=True,exist_ok=True)
    tmp=ZIP_PATH.with_suffix(".zip.tmp")
    if tmp.exists():
        tmp.unlink()
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(
        tmp,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True
    ) as zf:
        for i,row in enumerate(rows,1):
            rel=row["path"]
            src=DIST/Path(rel)
            info=zipfile.ZipInfo(rel,date_time=(1980,1,1,0,0,0))
            info.create_system=3
            info.external_attr=(0o100644 & 0xFFFF)<<16
            if src.suffix.lower() in STORE_SUFFIXES:
                info.compress_type=zipfile.ZIP_STORED
            else:
                info.compress_type=zipfile.ZIP_DEFLATED
            with src.open("rb") as rf, zf.open(info,"w",force_zip64=True) as wf:
                for chunk in iter(lambda:rf.read(8*1024*1024),b""):
                    wf.write(chunk)
            if i%25==0 or i==len(rows):
                print(f"  ZIP {i:>3}/{len(rows)} files",flush=True)
    os.replace(tmp,ZIP_PATH)

def validate_semantic_anchors()->dict:
    v=load_json(VERIFICATION)
    if v.get("status")!="PASS":
        raise RuntimeError("Unified independent verification is not PASS")
    if int((v.get("rotation_v1a") or {}).get("sidecar_records_verified",0))!=EXPECTED_ROTATION_RELEASES:
        raise RuntimeError("Rotation v1.1 verification anchor drift")
    access=v.get("access") or {}
    if int(access.get("candidate_fields",0))!=EXPECTED_BESTMATCH_CANDIDATES:
        raise RuntimeError("BestMatch v0c candidate anchor drift")
    if int(access.get("field_union_count",0))!=EXPECTED_SCREENING_UNION:
        raise RuntimeError("BestMatch screening-union anchor drift")
    water=v.get("water_viss") or {}
    if int(water.get("field_count",0))!=EXPECTED_WATER_FIELDS:
        raise RuntimeError("ÅkerVatten field anchor drift")
    if int(water.get("viss_positive_fields",0))!=EXPECTED_VISS_POSITIVE:
        raise RuntimeError("VISS positive anchor drift")
    if int(water.get("groundwater_level_impact_fields",0))!=EXPECTED_GW_LEVEL_IMPACT:
        raise RuntimeError("Groundwater-level-impact anchor drift")
    if v.get("rapskartan_present") is not True:
        raise RuntimeError("Rapskartan missing in unified verification")
    if v.get("new_total_score_created") is not False:
        raise RuntimeError("Unexpected total score")
    if v.get("water_legal_assessment_created") is not False:
        raise RuntimeError("Unexpected water legal assessment")

    pui=v.get("rotation_v1a_priority_ui") or {}
    if (
        int(pui.get("fields",0))!=43
        or int(pui.get("bestmatch_v0c_fields",0))!=37
        or int(pui.get("d0_area_lt_1ha_fields",0))!=6
    ):
        raise RuntimeError("Rotation v1.1 priority-presentation anchor drift")

    return {
        "rotation_v1a_releases_verified":43,
        "rotation_priority_ui":{"bestmatch_rank":37,"d0_area_lt_1ha":6},
        "bestmatch_v0c_candidates":16004,
        "bestmatch_v0c_screening_union":5000,
        "akervatten_fields":128636,
        "viss_positive_fields":16626,
        "groundwater_level_impact_fields":5495,
        "rapskartan_2025":True,
        "new_total_score":False,
        "water_legal_assessment":False,
    }

def main()->int:
    if not DIST.is_dir():
        raise FileNotFoundError(DIST)
    for p in [DIST_MANIFEST,BUILD_MANIFEST,VERIFICATION]:
        if not p.is_file():
            raise FileNotFoundError(p)

    branch=git_value("branch","--show-current")
    if branch!="feature/akerpass-unified-web-v0a-r1":
        raise RuntimeError(f"RC1 package must run on feature/akerpass-unified-web-v0a-r1; got {branch}")

    porcelain=git_value("status","--porcelain")
    if porcelain:
        raise RuntimeError("Tracked working tree is not clean before RC packaging")

    build=load_json(BUILD_MANIFEST)
    build_head=str(build.get("repository_head") or "")
    tooling_head=git_value("rev-parse","HEAD")
    if not build_head or len(build_head)<7:
        raise RuntimeError("Unified build manifest has no valid repository_head")
    if not is_ancestor(build_head,tooling_head):
        raise RuntimeError(
            f"QAed dist build HEAD {build_head} is not an ancestor of RC tooling HEAD {tooling_head}"
        )

    anchors=validate_semantic_anchors()

    print("="*118)
    print("ÅkerPass Unified Preview v0a-r1 · U4 RC1 PACKAGE")
    print("="*118)
    print("Freezing the existing QAed dist; NO rebuild.")
    print("Dist build HEAD:",build_head)
    print("RC tooling HEAD:",tooling_head)

    print("\n[1/3] Hash exact current dist and compare with independent verifier manifest...")
    rows=scan_dist()
    if len(rows)!=EXPECTED_FILES:
        raise RuntimeError(f"RC file-count anchor drift: {len(rows)} != {EXPECTED_FILES}")
    compare_unified_manifest(rows)
    total_bytes=sum(int(x["bytes"]) for x in rows)
    dsha=tree_sha(rows)
    print(f"  files={len(rows):,} · bytes={total_bytes:,} · tree_sha256={dsha}")

    print("\n[2/3] Build deterministic deploy ZIP (index.html at ZIP root)...")
    if not (DIST/"index.html").is_file():
        raise RuntimeError("Unified dist has no root index.html")
    write_deterministic_zip(rows)
    zsha=sha256_file(ZIP_PATH)
    zbytes=ZIP_PATH.stat().st_size
    print(f"  {ZIP_PATH}")
    print(f"  ZIP bytes={zbytes:,} · sha256={zsha}")

    print("\n[3/3] Write RC manifest...")
    WORK.mkdir(parents=True,exist_ok=True)
    manifest={
        "schema_version":"akerpass-unified-preview-v0a-r1-rc1-manifest-v1",
        "release_name":"akerpass-unified-preview-v0a-r1-rc1",
        "status":"RELEASE_CANDIDATE_FROZEN_LOCAL_ARTIFACT",
        "deployment_performed":False,
        "dist":{
            "path":str(DIST),
            "files":len(rows),
            "bytes":total_bytes,
            "tree_sha256":dsha,
            "files_manifest":rows,
        },
        "package":{
            "path":str(ZIP_PATH),
            "bytes":zbytes,
            "sha256":zsha,
            "layout":"web root at ZIP root; index.html at root",
            "deterministic_zip_timestamps":"1980-01-01T00:00:00",
        },
        "git":{
            "repository":"PiggeGnidde/akersync",
            "branch":branch,
            "dist_build_head":build_head,
            "rc_tooling_head":tooling_head,
        },
        "upstream":{
            "rotation_v1a":"FORMALLY_FROZEN",
            "bestmatch_v0c":"FORMALLY_FROZEN",
            "akervatten_viss_vattentryck_v1":"forward-ported frozen web payload",
            "rapskartan_2025":"separate special view",
        },
        "anchors":anchors,
        "manual_qa_before_rc":[
            "Staffanstorp 61723351559|2B visually confirmed A / ROTATION_OK_BOUNDARY_SPILL / BestMatch v0c #273",
            "Staffanstorp 61723351559|2A visually confirmed A / ROTATION_OK_BOUNDARY_SPILL / BestMatch v0c #1436",
            "Whole-Skåne ranking selector visually confirmed to expose only frozen BestMatch v0c",
        ],
        "u5_required_https_mobile_smoke":[
            "ÅkerVatten VISS layer on real phone",
            "field drawer and touch interaction on narrow viewport",
            "Min position permission and GPS location",
            "Följ mig ON/OFF while moving",
            "pan/zoom behavior while follow mode is active",
            "layer and municipality switching",
            "Rapskartan 2025 navigation and backlink",
        ],
        "freeze_rule":"Do not modify RC1 package. Any dist change requires RC2 or later.",
    }
    MANIFEST.write_text(stable_json(manifest),encoding="utf-8")

    print("="*118)
    print("U4 RC1 PACKAGE CREATED")
    print("="*118)
    print(f"RC: {ZIP_PATH}")
    print(f"Manifest: {MANIFEST}")
    print("Deployment: NO")
    print("Next gate: verify package, then U5 deploy to preview.akerpass.se + real mobile/GPS smoke.")
    print("="*118)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
