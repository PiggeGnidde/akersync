#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1B wrapper for the persistent M4 reproduction gate.

Applies the exact target/history validity rule recovered by the read-only census
 diagnostic: rows with status NO_PUBLIC_MATCH are not valid observed history.
They are mapped to __UNKNOWN__ for feature construction and excluded as targets.

The original V1 gate remains untouched as evidence of the failed pre-fit census.
2026 remains unopened.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "src" / "179_akerpuls_m4_reimplementation_reproduction_gate_v1.py"
BASE_CONFIG = ROOT / "config" / "akerpuls_m4_reimplementation_v1.json"
PATCH_CONFIG = ROOT / "config" / "akerpuls_m4_target_validity_patch_v1b.json"
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1b")
DIAGNOSTIC_JSON = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_target_census_diagnostic_v1\M4_TARGET_CENSUS_DIAGNOSTIC_V1.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_base_module():
    spec = importlib.util.spec_from_file_location("m4_repro_v1_base", BASE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    patch = json.loads(PATCH_CONFIG.read_text(encoding="utf-8"))
    rule = patch["rule"]
    excluded = set(rule["exclude_statuses"])
    if excluded != {"NO_PUBLIC_MATCH"}:
        raise RuntimeError(f"Unexpected V1B excluded statuses: {sorted(excluded)}")
    if not DIAGNOSTIC_JSON.is_file():
        raise FileNotFoundError(f"Required diagnostic evidence missing: {DIAGNOSTIC_JSON}")

    mod = load_base_module()
    original_prepare_base = mod.prepare_base

    def prepare_base_v1b(cfg: dict):
        base = list(original_prepare_base(cfg))
        ids, cls_wide, known_wide, cov_wide, share_wide, static_i, soil_i = base

        hist_meta = cfg["inputs"]["history"]
        hist_path = Path(cfg["inputs"]["directory"]) / hist_meta["file"]
        status = pd.read_csv(
            hist_path,
            usecols=["current_field_id", "history_year", "status"],
            compression="gzip",
            low_memory=False,
        )
        status["current_field_id"] = status["current_field_id"].astype("string")
        status["history_year"] = pd.to_numeric(status["history_year"], errors="raise").astype(int)
        status_wide = status.pivot(index="current_field_id", columns="history_year", values="status").reindex(ids)

        bad = status_wide.isin(sorted(excluded))
        # No-public-match is not observed crop history. Preserve calendar position but
        # make its crop class unknown and exclude it from valid-history denominators.
        cls_wide = cls_wide.mask(bad, mod.UNKNOWN)
        known_wide = known_wide & (~bad.fillna(False))
        return ids, cls_wide, known_wide, cov_wide, share_wide, static_i, soil_i

    mod.prepare_base = prepare_base_v1b

    # Feed the base gate only the original frozen model config and a fresh V1B output dir.
    old_argv = sys.argv[:]
    sys.argv = [str(BASE_SCRIPT), "--config", str(BASE_CONFIG), "--output-dir", str(Path(args.output_dir))]
    try:
        rc = mod.main()
    finally:
        sys.argv = old_argv

    out = Path(args.output_dir)
    if not out.is_dir():
        return int(rc or 1)

    provenance = {
        "schema_version": "akerpuls-m4-reproduction-v1b-provenance",
        "base_gate_script": str(BASE_SCRIPT),
        "base_gate_script_sha256": sha256_file(BASE_SCRIPT),
        "base_model_config": str(BASE_CONFIG),
        "base_model_config_sha256": sha256_file(BASE_CONFIG),
        "validity_patch": str(PATCH_CONFIG),
        "validity_patch_sha256": sha256_file(PATCH_CONFIG),
        "diagnostic_evidence": str(DIAGNOSTIC_JSON),
        "diagnostic_evidence_sha256": sha256_file(DIAGNOSTIC_JSON),
        "exclude_statuses": sorted(excluded),
        "apply_to_target_validity": bool(rule["apply_to_target_validity"]),
        "apply_to_history_feature_validity": bool(rule["apply_to_history_feature_validity"]),
        "no_public_match_history_category": rule["excluded_history_rows_are_category"],
        "v1_failed_output_preserved": r"C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1",
        "prediction_2026_executed": False,
    }
    (out / "V1B_TARGET_VALIDITY_PROVENANCE.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Refresh manifest so the provenance file is covered as well.
    mod.write_sha_manifest(out)
    print(f"V1B_VALIDITY_PATCH_SHA256={sha256_file(PATCH_CONFIG)}")
    print(f"V1B_DIAGNOSTIC_EVIDENCE_SHA256={sha256_file(DIAGNOSTIC_JSON)}")
    print("V1B_RULE=EXCLUDE_NO_PUBLIC_MATCH_FROM_TARGET_AND_HISTORY_VALIDITY")
    print("PREDICTION_2026_EXECUTED=FALSE")
    return int(rc or 0)


if __name__ == "__main__":
    raise SystemExit(main())
