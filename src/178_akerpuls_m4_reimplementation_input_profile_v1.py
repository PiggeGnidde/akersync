#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only profile gate before reimplementing frozen M4.

Verifies the three frozen input hashes, profiles crop labels/static domains and
reports local ML package availability. No model is fit, no 2026 prediction is
made, no fusion is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
DEFAULT_M0 = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1")
DEFAULT_INPUT_DIR = Path(r"C:\AkerSyncRepo\work\akerscore_validation_csv_upload")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_reimplementation_input_profile_v1")
STATUS = "PASS_M4_REIMPLEMENTATION_INPUT_PROFILE_STOP"

EXPECTED_INPUTS = {
    "akerminne_2015_2025_selected.csv.gz": "05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf",
    "field_static_context_selected.csv.gz": "31db31b79b53a4c0aa32621fb7bfa44165ea65b6b46371c32e4e19935f59feea",
    "akerscore_soil_skiften_selected.csv.gz": "71dfd711a4243b3cbe465de7eaa013725b2d2f9be3a8890d213a89bc095427da",
}

TARGET_CLASSES = [
    "höstraps", "höstvete", "vårvete", "höstkorn", "vårkorn", "havre", "råg", "rågvete",
    "sockerbetor", "matpotatis", "stärkelsepotatis", "vall på åkermark", "majs",
    "baljväxter", "träda/miljöyta", "annan gröda",
]


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


def pkg_version(name: str):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def top_values(series: pd.Series, limit: int = 50):
    counts = series.astype("string").fillna("<NA>").value_counts(dropna=False).head(limit)
    return [{"value": str(k), "count": int(v)} for k, v in counts.items()]


def num_profile(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce")
    qs = s.quantile([0.0, 0.01, 0.05, 0.50, 0.95, 0.99, 1.0]).to_dict()
    return {
        "valid": int(s.notna().sum()),
        "missing": int(s.isna().sum()),
        "quantiles": {str(k): (None if pd.isna(v) else float(v)) for k, v in qs.items()},
    }


def require_columns(df: pd.DataFrame, cols: list[str], label: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"{label} missing columns: {missing}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m0-freeze-dir", default=str(DEFAULT_M0))
    ap.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    m0 = find_m0_freeze(Path(args.m0_freeze_dir))
    inp = Path(args.input_dir)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    paths = {name: inp / name for name in EXPECTED_INPUTS}
    hashes = {}
    for name, expected in EXPECTED_INPUTS.items():
        p = paths[name]
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha256_file(p)
        hashes[name] = got
        if got != expected:
            raise RuntimeError(f"Frozen input SHA changed for {name}: {got}")

    hist = pd.read_csv(paths["akerminne_2015_2025_selected.csv.gz"], compression="gzip", low_memory=False)
    static = pd.read_csv(paths["field_static_context_selected.csv.gz"], compression="gzip", low_memory=False)
    soil = pd.read_csv(paths["akerscore_soil_skiften_selected.csv.gz"], compression="gzip", low_memory=False)

    require_columns(hist, [
        "current_field_id", "reference_year", "history_year", "dominant_crop_name",
        "dominant_crop_group", "dominant_crop_known", "dominant_crop_share", "coverage_raw",
        "status", "reason_flags",
    ], "history")
    require_columns(static, [
        "current_field_id", "municipality", "field_area_m2", "dominant_soil_class",
        "dominant_sko_id", "context_status", "reason_flags",
    ], "static")
    require_columns(soil, ["current_field_id", "akerscore_soil_p50"], "soil")

    hist_dups = int(hist.duplicated(["current_field_id", "history_year"]).sum())
    static_dups = int(static.duplicated(["current_field_id"]).sum())
    soil_dups = int(soil.duplicated(["current_field_id"]).sum())

    profile = {
        "schema_version": "akerpuls-m4-reimplementation-input-profile-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "m0_freeze_sha256": sha256_file(m0),
        "frozen_input_hashes": hashes,
        "target_classes_frozen_order": TARGET_CLASSES,
        "history": {
            "rows": int(len(hist)),
            "unique_fields": int(hist["current_field_id"].nunique()),
            "history_year_min": int(pd.to_numeric(hist["history_year"], errors="coerce").min()),
            "history_year_max": int(pd.to_numeric(hist["history_year"], errors="coerce").max()),
            "reference_year_values": sorted(pd.to_numeric(hist["reference_year"], errors="coerce").dropna().astype(int).unique().tolist()),
            "field_year_duplicates": hist_dups,
            "dominant_crop_name_top": top_values(hist["dominant_crop_name"], 100),
            "dominant_crop_group_top": top_values(hist["dominant_crop_group"], 100),
            "dominant_crop_known_top": top_values(hist["dominant_crop_known"], 20),
            "status_top": top_values(hist["status"], 40),
            "reason_flags_top": top_values(hist["reason_flags"], 40),
            "coverage_raw": num_profile(hist["coverage_raw"]),
            "dominant_crop_share": num_profile(hist["dominant_crop_share"]),
        },
        "static": {
            "rows": int(len(static)),
            "unique_fields": int(static["current_field_id"].nunique()),
            "field_duplicates": static_dups,
            "municipality_unique": int(static["municipality"].nunique(dropna=True)),
            "municipality_top": top_values(static["municipality"], 40),
            "sko_unique": int(static["dominant_sko_id"].nunique(dropna=True)),
            "sko_top": top_values(static["dominant_sko_id"], 50),
            "soil_class_top": top_values(static["dominant_soil_class"], 50),
            "context_status_top": top_values(static["context_status"], 40),
            "reason_flags_top": top_values(static["reason_flags"], 40),
            "field_area_m2": num_profile(static["field_area_m2"]),
        },
        "soil_score": {
            "rows": int(len(soil)),
            "unique_fields": int(soil["current_field_id"].nunique()),
            "field_duplicates": soil_dups,
            "akerscore_soil_p50": num_profile(soil["akerscore_soil_p50"]),
        },
        "packages": {
            "python": sys.version.split()[0],
            "pandas": pkg_version("pandas"),
            "numpy": pkg_version("numpy"),
            "scikit-learn": pkg_version("scikit-learn"),
            "lightgbm": pkg_version("lightgbm"),
        },
        "model_executed": False,
        "m4_prediction_executed": False,
        "fusion_executed": False,
        "thresholds_tuned": False,
        "geometry_mutated": False,
        "next": "DESIGN_AND_RUN_M4_REIMPLEMENTATION_REPRODUCTION_GATE",
    }

    if profile["history"]["rows"] != 1414996 or profile["history"]["unique_fields"] != 128636:
        raise RuntimeError("Frozen ÅkerMinne census changed")
    if profile["static"]["rows"] != 128636 or profile["static"]["unique_fields"] != 128636:
        raise RuntimeError("Frozen static-context census changed")
    if profile["soil_score"]["rows"] != 128636 or profile["soil_score"]["unique_fields"] != 128636:
        raise RuntimeError("Frozen soil-score census changed")
    if hist_dups or static_dups or soil_dups:
        raise RuntimeError(f"Unexpected duplicates hist={hist_dups} static={static_dups} soil={soil_dups}")

    out.mkdir(parents=True, exist_ok=False)
    json_path = out / "M4_REIMPLEMENTATION_INPUT_PROFILE_V1.json"
    json_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "AKERPULS M4 REIMPLEMENTATION INPUT PROFILE",
        f"STATUS={STATUS}",
        f"M0_FREEZE_SHA256={sha256_file(m0)}",
        f"HISTORY_ROWS={len(hist)} UNIQUE_FIELDS={hist['current_field_id'].nunique()} YEARS={profile['history']['history_year_min']}-{profile['history']['history_year_max']}",
        f"STATIC_ROWS={len(static)} UNIQUE_FIELDS={static['current_field_id'].nunique()} MUNICIPALITIES={static['municipality'].nunique(dropna=True)} SKO={static['dominant_sko_id'].nunique(dropna=True)}",
        f"SOIL_ROWS={len(soil)} UNIQUE_FIELDS={soil['current_field_id'].nunique()}",
        "INPUT_HASHES=PASS_ALL_3",
        "PACKAGES=" + " ".join(f"{k}:{v or 'MISSING'}" for k, v in profile["packages"].items()),
        "DOMINANT_CROP_NAME_TOP=" + " | ".join(f"{x['value']}:{x['count']}" for x in profile["history"]["dominant_crop_name_top"][:40]),
        "DOMINANT_CROP_GROUP_TOP=" + " | ".join(f"{x['value']}:{x['count']}" for x in profile["history"]["dominant_crop_group_top"][:40]),
        "STATUS_TOP=" + " | ".join(f"{x['value']}:{x['count']}" for x in profile["history"]["status_top"][:20]),
        "MODEL_EXECUTED=FALSE M4_PREDICTION_EXECUTED=FALSE FUSION_EXECUTED=FALSE",
        "THRESHOLDS_TUNED=FALSE GEOMETRY_MUTATED=FALSE",
        f"PROFILE_JSON={json_path}",
        "NEXT=DESIGN_AND_RUN_M4_REIMPLEMENTATION_REPRODUCTION_GATE",
        f"OUTPUT={out}",
    ]
    txt = "\n".join(lines) + "\n"
    (out / "M4_REIMPLEMENTATION_INPUT_PROFILE_V1.txt").write_text(txt, encoding="utf-8")
    print(txt, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
