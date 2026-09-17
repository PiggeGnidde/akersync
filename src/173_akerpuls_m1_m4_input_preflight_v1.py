#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only preflight for ÅkerPuls Merge M1 M4 pair prior.

Purpose: discover the exact frozen växtföljdsprior/M4 artefacts on the user's
local machine before any 2026 prediction or pair-prior computation is coded or
executed. This stage verifies the frozen M0 lineage, inventories the M4 freeze
package, and reports schemas/metadata only.

No model execution, no threshold tuning, no fusion, no geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
DEFAULT_M0_FREEZE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1")
DEFAULT_VAX_DIR = Path(r"C:\AkerSyncRepo\work\vaxtfoljd_prior_v1_freeze")
DEFAULT_WORK = Path(r"C:\AkerSyncRepo\work")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_input_preflight_v1")
STATUS = "PASS_M1_M4_INPUT_DISCOVERY_STOP"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def find_m0_freeze(root: Path) -> tuple[Path, dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    matches = []
    for p in root.glob("*.json"):
        try:
            obj = read_json(p)
        except Exception:
            continue
        if obj.get("status") == "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1":
            matches.append((p, obj))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one M0 freeze JSON in {root}, found {len(matches)}")
    p, obj = matches[0]
    got = sha256_file(p)
    if got != EXPECTED_M0_FREEZE_SHA256:
        raise RuntimeError(f"M0 freeze SHA changed: {got}")
    return p, obj


def find_vax_dir(explicit: Path) -> Path:
    if explicit.is_dir():
        return explicit
    if not DEFAULT_WORK.is_dir():
        raise FileNotFoundError(explicit)
    candidates = [p for p in DEFAULT_WORK.iterdir() if p.is_dir() and "vax" in p.name.lower() and "foljd" in p.name.lower()]
    if len(candidates) == 1:
        return candidates[0]
    names = [str(p) for p in sorted(candidates)]
    raise RuntimeError(f"Could not uniquely resolve växtföljd freeze dir. explicit={explicit} candidates={names}")


def json_metadata(path: Path) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    if path.stat().st_size > 5_000_000:
        return rec
    try:
        obj = read_json(path)
    except Exception as e:
        return {"json_error": type(e).__name__}
    if isinstance(obj, dict):
        rec["top_level_keys"] = sorted(map(str, obj.keys()))[:100]
        for k in ("status", "schema_version", "version", "phase", "model", "model_name", "target_year", "prediction_year"):
            if k in obj and isinstance(obj[k], (str, int, float, bool, type(None))):
                rec[k] = obj[k]
    return rec


def csv_metadata(path: Path) -> dict[str, Any]:
    import pandas as pd
    try:
        df = pd.read_csv(path, nrows=5, encoding="utf-8-sig")
        return {"columns": list(map(str, df.columns)), "sample_rows_read": int(len(df))}
    except Exception as e:
        return {"csv_error": type(e).__name__}


def parquet_metadata(path: Path) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(path)
        return {"rows": int(pf.metadata.num_rows), "columns": list(map(str, pf.schema.names))}
    except Exception as e:
        return {"parquet_error": type(e).__name__}


def text_signals(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 2_000_000:
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}
    low = text.lower()
    keys = {
        "mentions_lightgbm": "lightgbm" in low or "lgbmclassifier" in low,
        "mentions_predict_proba": "predict_proba" in low,
        "mentions_2026": "2026" in low,
        "mentions_feature": "feature" in low,
        "mentions_m4": "m4" in low,
    }
    return {k: v for k, v in keys.items() if v}


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allowed_text = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".csv"}
    interesting_binary = {".parquet", ".joblib", ".pkl", ".pickle", ".model", ".bin", ".ubj"}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel = str(p.relative_to(root))
        except Exception:
            rel = str(p)
        rec: dict[str, Any] = {
            "relative_path": rel,
            "bytes": int(p.stat().st_size),
            "suffix": p.suffix.lower(),
        }
        name_low = p.name.lower()
        if p.suffix.lower() in allowed_text or p.suffix.lower() in interesting_binary or any(x in name_low for x in ("manifest", "model", "feature", "prior", "freeze", "contract")):
            rec["sha256"] = sha256_file(p)
        if p.suffix.lower() == ".json":
            rec.update(json_metadata(p))
        elif p.suffix.lower() == ".csv":
            rec.update(csv_metadata(p))
        elif p.suffix.lower() == ".parquet":
            rec.update(parquet_metadata(p))
        elif p.suffix.lower() in {".py", ".md", ".txt"}:
            rec.update(text_signals(p))
        rows.append(rec)
    return rows


def classify_candidates(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    out = {"manifest_like": [], "model_like": [], "feature_builder_like": [], "prior_export_like": [], "contract_like": []}
    for r in rows:
        rel = str(r["relative_path"])
        low = rel.lower()
        if "manifest" in low:
            out["manifest_like"].append(rel)
        if any(x in low for x in ("model", "booster", "lightgbm", "m4")) and r.get("suffix") in {".txt", ".json", ".joblib", ".pkl", ".pickle", ".model", ".bin", ".ubj", ".py"}:
            out["model_like"].append(rel)
        if r.get("suffix") == ".py" and (r.get("mentions_feature") or r.get("mentions_predict_proba")):
            out["feature_builder_like"].append(rel)
        if "prior" in low and r.get("suffix") in {".csv", ".parquet", ".json"}:
            out["prior_export_like"].append(rel)
        if "contract" in low or "card" in low:
            out["contract_like"].append(rel)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m0-freeze-dir", default=str(DEFAULT_M0_FREEZE_DIR))
    ap.add_argument("--vax-dir", default=str(DEFAULT_VAX_DIR))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    m0_path, m0 = find_m0_freeze(Path(args.m0_freeze_dir))
    vax = find_vax_dir(Path(args.vax_dir))
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    print("M1_M4_PREFLIGHT_PROGRESS=INVENTORY_FROZEN_VAXTFOLJD_PACKAGE", flush=True)
    rows = inventory(vax)
    cand = classify_candidates(rows)
    out.mkdir(parents=True, exist_ok=False)

    result = {
        "schema_version": "akerpuls-merge-m1-m4-input-preflight-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "m0_freeze": {
            "path": str(m0_path),
            "sha256": EXPECTED_M0_FREEZE_SHA256,
            "status": m0.get("status"),
        },
        "vaxfoljd_root": str(vax),
        "file_count": len(rows),
        "candidate_groups": cand,
        "files": rows,
        "guards": {
            "model_executed": False,
            "m4_prediction_executed": False,
            "m0_modified": False,
            "fusion_executed": False,
            "thresholds_tuned": False,
            "geometry_mutated": False,
        },
        "next": "REVIEW_EXACT_M4_ARTEFACTS_THEN_BUILD_2026_FIELD_PRIOR_AND_PAIR_PRIOR",
    }
    j = out / "M1_M4_INPUT_DISCOVERY_V1.json"
    j.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# ÅkerPuls M1 M4 input discovery v1",
        "",
        f"Status: `{STATUS}`",
        f"M0 freeze SHA256: `{EXPECTED_M0_FREEZE_SHA256}`",
        f"Växtföljd root: `{vax}`",
        f"Files inventoried: {len(rows)}",
        "",
    ]
    for group, vals in cand.items():
        lines.append(f"## {group}")
        lines.extend([f"- `{x}`" for x in vals] or ["- none detected"])
        lines.append("")
    (out / "M1_M4_INPUT_DISCOVERY_V1.md").write_text("\n".join(lines), encoding="utf-8")

    print("AKERPULS MERGE M1 M4 INPUT PREFLIGHT")
    print(f"STATUS={STATUS}")
    print(f"M0_FREEZE_SHA256={EXPECTED_M0_FREEZE_SHA256}")
    print(f"VAXTFOLJD_ROOT={vax}")
    print(f"FILES_INVENTORIED={len(rows)}")
    print(f"MANIFEST_LIKE={len(cand['manifest_like'])} MODEL_LIKE={len(cand['model_like'])} FEATURE_BUILDER_LIKE={len(cand['feature_builder_like'])} PRIOR_EXPORT_LIKE={len(cand['prior_export_like'])}")
    print("MODEL_EXECUTED=FALSE M4_PREDICTION_EXECUTED=FALSE FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVIEW_DISCOVERY_AND_BUILD_EXACT_M1")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
