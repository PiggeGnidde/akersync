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

    # A formal freeze package may legitimately contain both a freeze JSON and a
    # manifest JSON carrying the same frozen status. Identity is therefore the
    # pinned freeze SHA, not status-string uniqueness.
    status_matches: list[tuple[Path, dict[str, Any], str]] = []
    sha_matches: list[tuple[Path, dict[str, Any]]] = []
    for p in sorted(root.glob("*.json")):
        try:
            obj = read_json(p)
        except Exception:
            continue
        if obj.get("status") != "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1":
            continue
        got = sha256_file(p)
        status_matches.append((p, obj, got))
        if got == EXPECTED_M0_FREEZE_SHA256:
            sha_matches.append((p, obj))

    if len(sha_matches) == 1:
        return sha_matches[0]

    diag = [f"{p.name}:{got}" for p, _obj, got in status_matches]
    if not sha_matches:
        raise RuntimeError(
            "Pinned M0 freeze JSON not found by SHA. "
            f"expected={EXPECTED_M0_FREEZE_SHA256} status_candidates={diag}"
        )
    raise RuntimeError(
        "Pinned M0 freeze SHA matched more than one JSON unexpectedly: "
        f"expected={EXPECTED_M0_FREEZE_SHA256} matches={[p.name for p, _ in sha_matches]}"
    )


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


def classify_file(path: Path) -> list[str]:
    n = path.name.lower()
    s = str(path).lower()
    groups = []
    if any(x in n for x in ("manifest", "freeze", "stoppunkt", "stop_e")):
        groups.append("manifest_like")
    if path.suffix.lower() in {".txt", ".json", ".pkl", ".pickle", ".joblib", ".bin"} and any(
        x in n for x in ("model", "lightgbm", "lgbm", "booster", "m4")
    ):
        groups.append("model_like")
    if path.suffix.lower() == ".py" and any(x in n for x in ("feature", "predict", "m4", "vax", "prior")):
        groups.append("feature_builder_like")
    if path.suffix.lower() in {".csv", ".parquet", ".json"} and any(
        x in n for x in ("prior", "prediction", "predict", "prob", "2026")
    ):
        groups.append("prior_export_like")
    if any(x in n for x in ("contract", "model_card", "data_contract", "taxonomy", "class")):
        groups.append("contract_like")
    return groups


def inspect_file(path: Path, root: Path) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "relative_path": str(path.relative_to(root)),
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
        "suffix": path.suffix.lower(),
        "groups": classify_file(path),
    }
    if path.suffix.lower() == ".json":
        rec["metadata"] = json_metadata(path)
    elif path.suffix.lower() == ".csv":
        rec["metadata"] = csv_metadata(path)
    elif path.suffix.lower() == ".parquet":
        rec["metadata"] = parquet_metadata(path)
    return rec


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

    files = [p for p in sorted(vax.rglob("*")) if p.is_file()]
    inventory = [inspect_file(p, vax) for p in files]
    groups = {k: [] for k in ("manifest_like", "model_like", "feature_builder_like", "prior_export_like", "contract_like")}
    for rec in inventory:
        for g in rec["groups"]:
            groups[g].append(rec["relative_path"])

    result = {
        "schema_version": "akerpuls-merge-m1-m4-input-discovery-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "m0_freeze": {
            "path": str(m0_path),
            "sha256": sha256_file(m0_path),
            "status": m0.get("status"),
        },
        "vaxtfoljd_root": str(vax),
        "files_inventoried": len(inventory),
        "groups": groups,
        "inventory": inventory,
        "guards": {
            "model_executed": False,
            "m4_prediction_executed": False,
            "fusion_executed": False,
            "thresholds_tuned": False,
            "geometry_mutated": False,
        },
        "next": "REVIEW_EXACT_M4_ARTEFACTS_THEN_BUILD_2026_FIELD_PRIOR_AND_PAIR_PRIOR",
    }

    out.mkdir(parents=True, exist_ok=False)
    j = out / "M1_M4_INPUT_DISCOVERY_V1.json"
    j.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = [
        "# ÅkerPuls Merge M1 — M4 input discovery v1",
        "",
        f"Status: `{STATUS}`",
        "",
        f"M0 freeze: `{m0_path}`",
        f"M0 freeze SHA256: `{sha256_file(m0_path)}`",
        f"Växtföljd root: `{vax}`",
        f"Files inventoried: **{len(inventory)}**",
        "",
    ]
    for k in ("manifest_like", "model_like", "feature_builder_like", "prior_export_like", "contract_like"):
        md.append(f"## {k}")
        if groups[k]:
            md.extend([f"- `{x}`" for x in groups[k]])
        else:
            md.append("- none")
        md.append("")
    md.extend([
        "## Guard",
        "Read-only discovery only. No model execution, 2026 prediction, fusion, threshold tuning, or geometry mutation.",
        "",
    ])
    (out / "M1_M4_INPUT_DISCOVERY_V1.md").write_text("\n".join(md), encoding="utf-8")

    print("AKERPULS MERGE M1 M4 INPUT PREFLIGHT")
    print(f"STATUS={STATUS}")
    print(f"M0_FREEZE_SHA256={sha256_file(m0_path)}")
    print(f"VAXTFOLJD_ROOT={vax}")
    print(f"FILES_INVENTORIED={len(inventory)}")
    for k in ("manifest_like", "model_like", "feature_builder_like", "prior_export_like", "contract_like"):
        print(f"{k.upper()}={len(groups[k])}")
        for x in groups[k][:12]:
            print(f"  {x}")
    print("MODEL_EXECUTED=FALSE M4_PREDICTION_EXECUTED=FALSE FUSION_EXECUTED=FALSE")
    print("THRESHOLDS_TUNED=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVIEW_EXACT_M4_ARTEFACTS_THEN_BUILD_2026_FIELD_PRIOR_AND_PAIR_PRIOR")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
