#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only historical-path discovery for ÅkerPuls Merge M1.

This preflight is based on paths documented in the Borgeby/ÅkerPass project chats:
  * C:\\AkerSync-Minne (original ÅkerMinne freeze/worktree)
  * C:\\AkerSync-Minne\\data\\derived\\akerminne_v1a\\skane
  * C:\\AkerSync-Minne\\dist\\data\\akerminne
  * C:\\AkerSync-Prestation\\dist\\data\\akerminne
  * C:\\AkerSyncRepo\\work\\akerscore_validation_csv_upload

It searches for the exact historical inputs used by the växtföljdsprior study plus
likely M3/M4 scripts/model artefacts. It never imports or executes discovered code/models.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
DEFAULT_M0 = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_historical_paths_preflight_v1")
STATUS = "PASS_M1_HISTORICAL_PATH_DISCOVERY_STOP"

HISTORICAL_ROOTS = [
    Path(r"C:\AkerSync-Minne"),
    Path(r"C:\AkerSync-Minne\data\derived\akerminne_v1a\skane"),
    Path(r"C:\AkerSync-Minne\dist\data\akerminne"),
    Path(r"C:\AkerSync-Prestation\dist\data\akerminne"),
    Path(r"C:\AkerSyncRepo\work\akerscore_validation_csv_upload"),
]

EXACT_INPUT_NAMES = {
    "akerminne_2015_2025_selected.csv.gz",
    "field_static_context_selected.csv.gz",
    "akerscore_soil_skiften_selected.csv.gz",
    "skane_index.json",
}

LIKELY_NAME_TOKENS = (
    "vaxfoljd", "vaxtfoljd", "växtföljd", "m3", "m4", "prior", "rotation", "crop_history", "model",
)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".bat", ".ps1", ".yaml", ".yml"}
SEARCH_TEXT_TOKENS = ("vaxfoljd", "vaxtfoljd", "M4", "predict_proba", "akerminne_2015_2025_selected")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_freeze(root: Path) -> Path:
    matches = []
    for p in root.glob("*.json"):
        try:
            obj = read_json(p)
        except Exception:
            continue
        if obj.get("status") == "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1" and sha256_file(p) == EXPECTED_M0_FREEZE_SHA256:
            matches.append(p)
    if len(matches) != 1:
        raise RuntimeError(f"Could not resolve exact M0 freeze SHA in {root}; matches={len(matches)}")
    return matches[0]


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def csv_gz_columns(path: Path):
    try:
        import pandas as pd
        df = pd.read_csv(path, nrows=3, compression="gzip", encoding="utf-8-sig")
        return list(map(str, df.columns))
    except Exception as e:
        return [f"<ERROR:{type(e).__name__}>"]


def text_hits(path: Path):
    try:
        if path.stat().st_size > 2_000_000:
            return []
        txt = path.read_text(encoding="utf-8", errors="ignore")
        return [tok for tok in SEARCH_TEXT_TOKENS if tok.lower() in txt.lower()]
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m0-freeze-dir", default=str(DEFAULT_M0))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    m0 = find_freeze(Path(args.m0_freeze_dir))
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    records = []
    seen = set()
    for root in HISTORICAL_ROOTS:
        if not root.exists():
            records.append({"root": str(root), "exists": False})
            continue
        records.append({"root": str(root), "exists": True, "is_dir": root.is_dir()})
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            name_low = p.name.lower()
            exact = p.name in EXACT_INPUT_NAMES
            likely_name = any(tok.lower() in name_low for tok in LIKELY_NAME_TOKENS)
            hits = text_hits(p) if p.suffix.lower() in TEXT_SUFFIXES else []
            if not (exact or likely_name or hits):
                continue
            rec = {
                "path": str(p),
                "bytes": int(p.stat().st_size),
                "sha256": sha256_file(p),
                "exact_historical_input": exact,
                "filename_signal": likely_name,
                "text_hits": hits,
            }
            if p.name.endswith(".csv.gz"):
                rec["columns"] = csv_gz_columns(p)
            records.append(rec)

    found_exact = [r for r in records if isinstance(r, dict) and r.get("exact_historical_input")]
    candidates = [r for r in records if isinstance(r, dict) and r.get("path")]

    payload = {
        "schema_version": "akerpuls-m1-historical-path-discovery-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "m0_freeze_path": str(m0),
        "m0_freeze_sha256": sha256_file(m0),
        "historical_roots": [str(x) for x in HISTORICAL_ROOTS],
        "exact_input_names": sorted(EXACT_INPUT_NAMES),
        "records": records,
        "exact_inputs_found": len(found_exact),
        "candidate_files_found": len(candidates),
        "model_executed": False,
        "m4_prediction_executed": False,
        "fusion_executed": False,
        "thresholds_tuned": False,
        "geometry_mutated": False,
        "next": "REVIEW_HISTORICAL_AKERMINNE_AND_M4_ARTEFACT_LOCATIONS",
    }

    out.mkdir(parents=True, exist_ok=False)
    (out / "M1_HISTORICAL_PATH_DISCOVERY_V1.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "AKERPULS MERGE M1 HISTORICAL PATH PREFLIGHT",
        f"STATUS={STATUS}",
        f"M0_FREEZE_SHA256={sha256_file(m0)}",
        f"ROOTS_CHECKED={len(HISTORICAL_ROOTS)}",
        f"EXACT_INPUTS_FOUND={len(found_exact)}",
        f"CANDIDATE_FILES_FOUND={len(candidates)}",
    ]
    for r in records:
        if r.get("path"):
            flags = []
            if r.get("exact_historical_input"):
                flags.append("EXACT")
            if r.get("filename_signal"):
                flags.append("NAME")
            if r.get("text_hits"):
                flags.append("TEXT:" + ",".join(r["text_hits"]))
            lines.append(f"FOUND={'|'.join(flags) or 'CAND'} {r['path']}")
            if "columns" in r:
                lines.append("  COLUMNS=" + ",".join(r["columns"][:40]))
        elif "root" in r:
            lines.append(f"ROOT_EXISTS={str(r.get('exists')).upper()} {r['root']}")
    lines += [
        "MODEL_EXECUTED=FALSE M4_PREDICTION_EXECUTED=FALSE FUSION_EXECUTED=FALSE",
        "THRESHOLDS_TUNED=FALSE GEOMETRY_MUTATED=FALSE",
        "NEXT=REVIEW_HISTORICAL_AKERMINNE_AND_M4_ARTEFACT_LOCATIONS",
        f"OUTPUT={out}",
    ]
    text = "\n".join(lines) + "\n"
    (out / "M1_HISTORICAL_PATH_DISCOVERY_V1.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
