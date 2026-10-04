#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify ÅkerPass unified preview RC1 package against its frozen manifest."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/"work"/"akerpass_unified_rc1"
MANIFEST=WORK/"akerpass_unified_preview_v0a_r1_rc1_manifest.json"

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_zip_member(zf:zipfile.ZipFile,info:zipfile.ZipInfo)->str:
    h=hashlib.sha256()
    with zf.open(info,"r") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def main()->int:
    if not MANIFEST.is_file():
        raise FileNotFoundError(MANIFEST)
    m=json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    problems=[]

    zp=Path(m["package"]["path"])
    if not zp.is_file():
        problems.append(f"ZIP MISSING {zp}")
    else:
        if int(zp.stat().st_size)!=int(m["package"]["bytes"]):
            problems.append("ZIP SIZE MISMATCH")
        got=sha256_file(zp)
        if got!=m["package"]["sha256"]:
            problems.append("ZIP SHA256 MISMATCH")

    expected={str(x["path"]):x for x in m["dist"]["files_manifest"]}
    if len(expected)!=189:
        problems.append(f"MANIFEST FILE COUNT {len(expected)} != 189")

    if zp.is_file():
        print("="*118)
        print("ÅkerPass Unified Preview v0a-r1 RC1 · PACKAGE VERIFY")
        print("="*118)
        print("Checking all ZIP members byte-for-byte against frozen dist hashes...")
        with zipfile.ZipFile(zp,"r") as zf:
            infos=[i for i in zf.infolist() if not i.is_dir()]
            names=[i.filename for i in infos]
            if len(names)!=len(expected):
                problems.append(f"ZIP MEMBER COUNT {len(names)} != {len(expected)}")
            if len(names)!=len(set(names)):
                problems.append("ZIP HAS DUPLICATE MEMBER NAMES")
            if "index.html" not in names:
                problems.append("ZIP ROOT index.html MISSING")
            for name in names:
                p=Path(name)
                if p.is_absolute() or ".." in p.parts or "\\" in name:
                    problems.append(f"UNSAFE ZIP PATH {name}")

            actual=set(names)
            missing=sorted(set(expected)-actual)
            extra=sorted(actual-set(expected))
            if missing:
                problems.append("ZIP MISSING MEMBERS: "+", ".join(missing[:8]))
            if extra:
                problems.append("ZIP EXTRA MEMBERS: "+", ".join(extra[:8]))

            for n,info in enumerate(infos,1):
                spec=expected.get(info.filename)
                if spec is None:
                    continue
                if int(info.file_size)!=int(spec["bytes"]):
                    problems.append(f"ZIP MEMBER SIZE MISMATCH {info.filename}")
                    continue
                got=sha256_zip_member(zf,info)
                if got!=spec["sha256"]:
                    problems.append(f"ZIP MEMBER SHA256 MISMATCH {info.filename}")
                if n%25==0 or n==len(infos):
                    print(f"  verified {n:>3}/{len(infos)} files",flush=True)

    a=m.get("anchors") or {}
    if int(a.get("rotation_v1a_releases_verified",0))!=43:
        problems.append("RC ROTATION ANCHOR MISMATCH")
    if int(a.get("bestmatch_v0c_candidates",0))!=16004:
        problems.append("RC BESTMATCH CANDIDATE ANCHOR MISMATCH")
    if int(a.get("bestmatch_v0c_screening_union",0))!=5000:
        problems.append("RC SCREENING UNION ANCHOR MISMATCH")
    if int(a.get("akervatten_fields",0))!=128636:
        problems.append("RC ÅKERVATTEN ANCHOR MISMATCH")
    if int(a.get("viss_positive_fields",0))!=16626:
        problems.append("RC VISS ANCHOR MISMATCH")
    if int(a.get("groundwater_level_impact_fields",0))!=5495:
        problems.append("RC GW LEVEL ANCHOR MISMATCH")
    pui=a.get("rotation_priority_ui") or {}
    if int(pui.get("bestmatch_rank",0))!=37 or int(pui.get("d0_area_lt_1ha",0))!=6:
        problems.append("RC PRIORITY UI ANCHOR MISMATCH")
    if m.get("deployment_performed") is not False:
        problems.append("RC MANIFEST CLAIMS DEPLOYMENT")

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -",p)
        print("="*118)
        print("VERIFY_AKERPASS_UNIFIED_RC1: FAIL")
        return 2

    print("\nRC freeze:",m["release_name"])
    print(f"Files: {len(expected):,}")
    print(f"ZIP: {zp}")
    print(f"ZIP SHA256: {m['package']['sha256']}")
    print("Rotation v1.1: 43/43")
    print("BestMatch v0c: 16,004 candidates · screening union 5,000")
    print("ÅkerVatten/VISS/GW: 128,636 / 16,626 / 5,495")
    print("Deployment: NO")
    print("="*118)
    print("VERIFY_AKERPASS_UNIFIED_RC1: PASS")
    print("="*118)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
