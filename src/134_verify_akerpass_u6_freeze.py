#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only verification of the local U6 final freeze record + hosted preview."""
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=ROOT/"work"/"akerpass_u6_freeze"/"akerpass_unified_preview_v0a_r1_final_manifest.json"
EXPECTED="01a96dda7ced90be99a686f8de081ed72fc19f0fd4b1adf556d42de7def48173"

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def main():
    if not M.is_file(): raise FileNotFoundError(M)
    d=json.loads(M.read_text(encoding="utf-8-sig"))
    problems=[]
    if d.get("status")!="FINAL_WEB_FREEZE_PASS":problems.append("final status")
    if d.get("source_rc",{}).get("zip_sha256")!=EXPECTED:problems.append("RC SHA")
    if d.get("u5_manual_mobile_smoke",{}).get("status")!="ACK_PASS":problems.append("mobile ACK")
    if d.get("rollback",{}).get("removed_during_u6") is not True:problems.append("rollback state")
    zp=Path(d["source_rc"]["zip_path"])
    if not zp.is_file() or sha(zp)!=EXPECTED:problems.append("local RC ZIP bytes")
    if problems:
        raise RuntimeError("U6 final-freeze manifest problems: "+", ".join(problems))
    r=subprocess.run([sys.executable,str(ROOT/"src"/"132_verify_akerpass_u5_hosted.py")],cwd=ROOT)
    if r.returncode!=0: raise RuntimeError("hosted verify failed")
    print("="*100)
    print("VERIFY_AKERPASS_UNIFIED_U6_FREEZE: PASS")
    print("="*100)
    print("Final release:",d["release_name"])
    print("RC1 SHA256:",EXPECTED)
    print("Mobile/Tesla ACK: PASS")
    print("Hosted verify: PASS")
    print("="*100)
    return 0
if __name__=="__main__":raise SystemExit(main())
