#!/usr/bin/env python3
from __future__ import annotations
import hashlib, importlib.util, json, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
SRC = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_v1b")
FREEZE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_freeze_v1")
FREEZE_JSON = FREEZE_DIR / "AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_FREEZE_V1.json"
FROZEN_MANIFEST = FREEZE_DIR / "SOURCE_VIEWER_MANIFEST.json"
EXPECTED_FREEZE_SHA = "482e817753e00cca4f92972147515bd000e4a5800dd2bb1ff74af35a89e64a6a"
EXPECTED_KEY_SHA = "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee"

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def main():
    branch=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(branch)
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")

    if sha(FREEZE_JSON) != EXPECTED_FREEZE_SHA:
        raise RuntimeError("Viewer freeze SHA changed")
    freeze=json.loads(FREEZE_JSON.read_text(encoding="utf-8-sig"))
    sh=freeze["source_hashes"]
    if sh["blind_key_sha256"] != EXPECTED_KEY_SHA:
        raise RuntimeError("Blind-key hash changed")

    names=sorted(p.name for p in (SRC/"images").glob("audit_*.jpg"))
    exp=[f"audit_{i:03d}.jpg" for i in range(1,101)]
    if names != exp:
        raise RuntimeError("Expected exactly audit_001..audit_100.jpg")

    spec=importlib.util.spec_from_file_location("builder",ROOT/"src"/"191_akerpuls_merge_blind_disagreement_audit_viewer_v1b.py")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    items=[{"blind_index":i,"image":f"images/audit_{i:03d}.jpg"} for i in range(1,101)]
    text=mod.build_html(items,EXPECTED_KEY_SHA)
    got=hashlib.sha256(text.encode("utf-8")).hexdigest()
    if got != sh["html_sha256"]:
        raise RuntimeError(f"Regenerated HTML SHA mismatch: {got}")

    html=SRC/"index.html"
    if not html.exists():
        html.write_text(text,encoding="utf-8")
    if sha(html) != sh["html_sha256"]:
        raise RuntimeError("index.html SHA mismatch after restore")

    if sha(FROZEN_MANIFEST) != sh["source_manifest_sha256"]:
        raise RuntimeError("Frozen manifest-copy SHA mismatch")
    manifest=SRC/"MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_MANIFEST_V1.json"
    if not manifest.exists():
        shutil.copyfile(FROZEN_MANIFEST,manifest)
    if sha(manifest) != sh["source_manifest_sha256"]:
        raise RuntimeError("Viewer manifest SHA mismatch after restore")

    print("STATUS=RESTORED_FROZEN_BLIND_AUDIT_VIEWER")
    print(f"INDEX_HTML_SHA256={sh['html_sha256']}")
    print(f"VIEWER_MANIFEST_SHA256={sh['source_manifest_sha256']}")
    print("BLIND_KEY_CONTENTS_READ=FALSE SAMPLE_REBUILT=FALSE")
    print(f"OUTPUT={html}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
