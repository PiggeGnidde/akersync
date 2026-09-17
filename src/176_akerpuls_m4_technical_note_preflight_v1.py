#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only extraction of the frozen M4 Technical Note text from the freeze ZIP.

No ZIP extraction to the source tree, no model execution, no prediction, no fusion.
The DOCX is read as nested ZIP bytes and its Word XML is converted to plain text.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
EXPECTED_VAX_ZIP_SHA256 = "bb6be8437027573a525c8344c34ce372e49b867ec52a67f2466475d6cf60ce6e"
EXPECTED_NOTE_SHA256 = "6affc684ac76e334a7db5367cdee0c41f78c8d8420a5e303382d8e59af551311"
NOTE_SUFFIX = "AkerPuls_Vaxtfoljdsprior_Technical_Note_V1.docx"
DEFAULT_M0 = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1")
DEFAULT_ZIP = Path(r"C:\AkerSyncRepo\work\vaxtfoljd_prior_v1_freeze\vaxfoljd_prior_v1_freeze.zip")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_technical_note_preflight_v1")
STATUS = "PASS_M4_TECHNICAL_NOTE_TEXT_DISCOVERY_STOP"
KEYWORDS = (
    "M4", "LightGBM", "feature", "historik", "recency", "count", "andel", "coverage",
    "dominant", "kommun", "SKO", "jord", "ÅkerScore", "category", "categorical", "encoding",
    "2018", "2021", "2025", "16", "klass",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def find_m0_freeze(root: Path) -> Path:
    hits = []
    for p in root.glob("*.json"):
        try:
            obj = read_json(p)
        except Exception:
            continue
        if obj.get("status") == "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1" and sha256_file(p) == EXPECTED_M0_FREEZE_SHA256:
            hits.append(p)
    if len(hits) != 1:
        raise RuntimeError(f"Could not resolve exact M0 freeze in {root}: {len(hits)} matches")
    return hits[0]


def docx_paragraphs(docx_bytes: bytes) -> list[str]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as dz:
        xml = dz.read("word/document.xml")
    root = ET.fromstring(xml)
    out = []
    for p in root.findall(".//w:p", ns):
        chunks = [t.text or "" for t in p.findall(".//w:t", ns)]
        s = "".join(chunks).strip()
        if s:
            out.append(s)
    return out


def excerpt_indices(paragraphs: list[str]) -> list[int]:
    idx = set()
    for i, p in enumerate(paragraphs):
        low = p.lower()
        if any(k.lower() in low for k in KEYWORDS):
            for j in range(max(0, i - 1), min(len(paragraphs), i + 2)):
                idx.add(j)
    return sorted(idx)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m0-freeze-dir", default=str(DEFAULT_M0))
    ap.add_argument("--vax-zip", default=str(DEFAULT_ZIP))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    m0 = find_m0_freeze(Path(args.m0_freeze_dir))
    zpath = Path(args.vax_zip)
    if not zpath.is_file():
        raise FileNotFoundError(zpath)
    if sha256_file(zpath) != EXPECTED_VAX_ZIP_SHA256:
        raise RuntimeError("Frozen vaxfoljd ZIP SHA changed")

    with zipfile.ZipFile(zpath, "r") as z:
        members = [n for n in z.namelist() if n.endswith(NOTE_SUFFIX)]
        if len(members) != 1:
            raise RuntimeError(f"Expected exactly one Technical Note DOCX, found {len(members)}")
        member = members[0]
        docx = z.read(member)
    if sha256_bytes(docx) != EXPECTED_NOTE_SHA256:
        raise RuntimeError("Technical Note DOCX SHA changed")

    paragraphs = docx_paragraphs(docx)
    if len(paragraphs) < 20:
        raise RuntimeError(f"Technical Note text unexpectedly short: {len(paragraphs)} paragraphs")
    ex_idx = excerpt_indices(paragraphs)

    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")
    out.mkdir(parents=True)
    full = "\n".join(f"[{i+1:04d}] {p}" for i, p in enumerate(paragraphs)) + "\n"
    (out / "M4_TECHNICAL_NOTE_TEXT_V1.txt").write_text(full, encoding="utf-8")
    excerpts = "\n".join(f"[{i+1:04d}] {paragraphs[i]}" for i in ex_idx) + "\n"
    (out / "M4_TECHNICAL_NOTE_EXCERPTS_V1.txt").write_text(excerpts, encoding="utf-8")
    meta = {
        "schema_version": "akerpuls-m4-technical-note-preflight-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "m0_freeze_sha256": sha256_file(m0),
        "vax_zip_sha256": sha256_file(zpath),
        "technical_note_member": member,
        "technical_note_sha256": sha256_bytes(docx),
        "paragraphs": len(paragraphs),
        "excerpt_paragraphs": len(ex_idx),
        "zip_extracted": False,
        "model_executed": False,
        "m4_prediction_executed": False,
        "fusion_executed": False,
        "thresholds_tuned": False,
        "geometry_mutated": False,
        "next": "REVIEW_M4_IMPLEMENTATION_DETAILS_THEN_BUILD_REPRODUCTION_GATE",
    }
    (out / "M4_TECHNICAL_NOTE_PREFLIGHT_V1.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS M4 TECHNICAL NOTE PREFLIGHT")
    print(f"STATUS={STATUS}")
    print(f"M0_FREEZE_SHA256={sha256_file(m0)}")
    print(f"VAX_ZIP_SHA256={sha256_file(zpath)}")
    print(f"TECHNICAL_NOTE_SHA256={sha256_bytes(docx)}")
    print(f"PARAGRAPHS={len(paragraphs)} EXCERPT_PARAGRAPHS={len(ex_idx)}")
    print("ZIP_EXTRACTED=FALSE MODEL_EXECUTED=FALSE M4_PREDICTION_EXECUTED=FALSE FUSION_EXECUTED=FALSE")
    print("THRESHOLDS_TUNED=FALSE GEOMETRY_MUTATED=FALSE")
    print(f"EXCERPTS={out / 'M4_TECHNICAL_NOTE_EXCERPTS_V1.txt'}")
    print(f"FULL_TEXT={out / 'M4_TECHNICAL_NOTE_TEXT_V1.txt'}")
    print("NEXT=REVIEW_M4_IMPLEMENTATION_DETAILS_THEN_BUILD_REPRODUCTION_GATE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
