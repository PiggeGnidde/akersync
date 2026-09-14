#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1-S3g: diagnose the single frozen D1-S3f acceptance miss without retuning.

Reads only already materialized C7 Process-reference and direct-S3 outputs.
No network, no S3 downloads, no Process API, no model rerun and no thresholds
are changed. The purpose is to identify the two baseline-candidate disagreements
and decompose the maximum fusion-score difference into its three frozen signals.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REF = Path(r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7c_fusion_validation")
S3 = Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3f_c7_end_to_end_parity_v1\s3_c7c_fusion_validation")
D1S3F = Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3f_c7_end_to_end_parity_v1")
FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json")
OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3g_review_diagnostic_v1")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def as_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def finite(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-dir", default=str(REF))
    ap.add_argument("--s3-dir", default=str(S3))
    ap.add_argument("--d1s3f-dir", default=str(D1S3F))
    ap.add_argument("--freeze", default=str(FREEZE))
    ap.add_argument("--output-dir", default=str(OUT))
    args = ap.parse_args()

    ref = Path(args.ref_dir); s3 = Path(args.s3_dir); parent = Path(args.d1s3f_dir)
    freeze_path = Path(args.freeze); out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)

    manifest = read_json(parent / "d1s3f_manifest.json")
    if manifest.get("status") != "REVIEW":
        raise RuntimeError(f"D1-S3g expects frozen D1-S3f REVIEW, got {manifest.get('status')}")
    checks = manifest.get("comparison", {}).get("checks", {})
    false_checks = sorted([k for k, v in checks.items() if v is not True])
    if false_checks != ["fusion_score_max"]:
        raise RuntimeError(f"Expected only fusion_score_max to fail, got {false_checks}")

    freeze = read_json(freeze_path)
    signals = list(freeze["signals"])
    weights = [float(x) for x in freeze["weights"]]
    nref = int(freeze.get("development_candidates") or len(freeze["reference_sorted_values"][signals[0]]))
    if nref <= 0 or len(signals) != 3 or len(weights) != 3:
        raise RuntimeError("Unexpected fusion freeze structure")
    nominal_one_rank_fusion_step = 1.0 / (3.0 * nref)

    rf = pd.read_csv(ref / "c7c_field_validation.csv", dtype={"parent_field_id_2025": str})
    sf = pd.read_csv(s3 / "c7c_field_validation.csv", dtype={"parent_field_id_2025": str})
    ref_cand = set(rf.loc[rf.discovery_type.astype(str).eq("SPLIT_CANDIDATE"), "parent_field_id_2025"].astype(str))
    s3_cand = set(sf.loc[sf.discovery_type.astype(str).eq("SPLIT_CANDIDATE"), "parent_field_id_2025"].astype(str))
    only_ref = sorted(ref_cand - s3_cand)
    only_s3 = sorted(s3_cand - ref_cand)

    fmerge = rf.merge(sf, on="parent_field_id_2025", suffixes=("_ref", "_s3"), validate="one_to_one")
    disagreements = fmerge[fmerge.discovery_type_ref.astype(str) != fmerge.discovery_type_s3.astype(str)].copy()
    keep = ["parent_field_id_2025", "discovery_type_ref", "discovery_type_s3"]
    for col in ["separation_ratio", "spatial_coherence", "min_child_fraction", "supporting_snapshots",
                "sep_april", "sep_may", "sep_june", "sep_july"]:
        for suf in ("_ref", "_s3"):
            if col + suf in disagreements.columns:
                keep.append(col + suf)
    disagreements[keep].to_csv(out / "baseline_disagreements.csv", index=False, encoding="utf-8-sig")

    rc = pd.read_csv(ref / "c7c_fusion_candidates.csv", dtype={"parent_field_id_2025": str})
    sc = pd.read_csv(s3 / "c7c_fusion_candidates.csv", dtype={"parent_field_id_2025": str})
    common = rc.merge(sc, on="parent_field_id_2025", suffixes=("_ref", "_s3"), how="inner", validate="one_to_one")
    common["fusion_abs_diff"] = np.abs(pd.to_numeric(common.fusion_score_ref, errors="coerce") -
                                        pd.to_numeric(common.fusion_score_s3, errors="coerce"))
    common["nominal_fusion_rank_steps"] = common["fusion_abs_diff"] / nominal_one_rank_fusion_step

    detail_cols = ["parent_field_id_2025", "fusion_score_ref", "fusion_score_s3", "fusion_abs_diff",
                   "nominal_fusion_rank_steps"]
    for sig in signals:
        for base in [sig, f"cdf_{sig}"]:
            rcol, scol = base + "_ref", base + "_s3"
            if rcol in common.columns and scol in common.columns:
                common[f"absdiff_{base}"] = np.abs(pd.to_numeric(common[rcol], errors="coerce") -
                                                     pd.to_numeric(common[scol], errors="coerce"))
                detail_cols += [rcol, scol, f"absdiff_{base}"]
    for col in ["fusion_ge_dev_p90", "fusion_ge_dev_p95", "locked_split_pass"]:
        rcol, scol = col + "_ref", col + "_s3"
        if rcol in common.columns and scol in common.columns:
            detail_cols += [rcol, scol]

    top = common.sort_values(["fusion_abs_diff", "parent_field_id_2025"], ascending=[False, True]).head(20).copy()
    top[detail_cols].to_csv(out / "fusion_top20_differences.csv", index=False, encoding="utf-8-sig")

    maxrow = top.iloc[0]
    max_id = str(maxrow.parent_field_id_2025)
    max_diff = float(maxrow.fusion_abs_diff)
    component_diffs = {}
    raw_diffs = {}
    for sig in signals:
        ccol = f"absdiff_cdf_{sig}"
        rcol = f"absdiff_{sig}"
        component_diffs[sig] = finite(maxrow.get(ccol))
        raw_diffs[sig] = finite(maxrow.get(rcol))

    p90_ref = bool(as_bool(pd.Series([maxrow.get("fusion_ge_dev_p90_ref", False)])).iloc[0])
    p90_s3 = bool(as_bool(pd.Series([maxrow.get("fusion_ge_dev_p90_s3", False)])).iloc[0])
    p95_ref = bool(as_bool(pd.Series([maxrow.get("fusion_ge_dev_p95_ref", False)])).iloc[0])
    p95_s3 = bool(as_bool(pd.Series([maxrow.get("fusion_ge_dev_p95_s3", False)])).iloc[0])

    summary = {
        "schema_version": "akerpuls-d1s3g-review-diagnostic-v1",
        "status": "DIAGNOSTIC_COMPLETE",
        "d1s3f_status": manifest.get("status"),
        "failed_frozen_checks": false_checks,
        "reference_baseline_candidates": len(ref_cand),
        "s3_baseline_candidates": len(s3_cand),
        "baseline_only_reference": only_ref,
        "baseline_only_s3": only_s3,
        "field_discovery_disagreements": int(len(disagreements)),
        "fusion_common_candidates": int(len(common)),
        "fusion_reference_population_n": nref,
        "nominal_one_rank_fusion_step": nominal_one_rank_fusion_step,
        "maximum_fusion_difference_field": max_id,
        "maximum_fusion_abs_difference": max_diff,
        "maximum_difference_nominal_rank_steps": float(maxrow.nominal_fusion_rank_steps),
        "maximum_field_raw_signal_abs_differences": raw_diffs,
        "maximum_field_cdf_abs_differences": component_diffs,
        "maximum_field_p90_ref": p90_ref,
        "maximum_field_p90_s3": p90_s3,
        "maximum_field_p95_ref": p95_ref,
        "maximum_field_p95_s3": p95_s3,
        "thresholds_changed": False,
        "acceptance_reinterpreted": False,
        "process_api_calls": 0,
        "sentinel_hub_pu_used": 0,
        "network_calls": 0,
        "full_skane_s3_authorized": False,
        "interpretation": "Post-REVIEW diagnosis only. D1-S3f remains REVIEW regardless of this diagnostic; no frozen acceptance criterion is waived or changed."
    }
    (out / "d1s3g_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS D1-S3G REVIEW DIAGNOSTIC - ZERO NETWORK / ZERO PU")
    print("STATUS=DIAGNOSTIC_COMPLETE")
    print("FAILED_FROZEN_CHECKS=" + ",".join(false_checks))
    print(f"BASELINE_REF={len(ref_cand)} S3={len(s3_cand)} ONLY_REF={len(only_ref)} ONLY_S3={len(only_s3)} DISCOVERY_DISAGREEMENTS={len(disagreements)}")
    print("BASELINE_ONLY_REF_IDS=" + (",".join(only_ref) if only_ref else "NONE"))
    print("BASELINE_ONLY_S3_IDS=" + (",".join(only_s3) if only_s3 else "NONE"))
    print(f"FUSION_COMMON={len(common)} FROZEN_REFERENCE_N={nref} NOMINAL_ONE_RANK_STEP={nominal_one_rank_fusion_step:.9f}")
    print(f"MAX_FUSION_DIFF_FIELD={max_id} ABS_DIFF={max_diff:.9f} NOMINAL_RANK_STEPS={float(maxrow.nominal_fusion_rank_steps):.3f}")
    for sig in signals:
        print(f"MAX_FIELD_SIGNAL {sig} RAW_ABS_DIFF={raw_diffs[sig]} CDF_ABS_DIFF={component_diffs[sig]}")
    print(f"MAX_FIELD_TIERS P90_REF={str(p90_ref).upper()} P90_S3={str(p90_s3).upper()} P95_REF={str(p95_ref).upper()} P95_S3={str(p95_s3).upper()}")
    print("THRESHOLDS_CHANGED=FALSE")
    print("D1S3F_STATUS_REMAINS=REVIEW")
    print("PROCESS_API_CALLS=0")
    print("SENTINEL_HUB_PU_USED=0")
    print("NETWORK_CALLS=0")
    print("FULL_SKANE_S3_AUTHORIZED=FALSE")
    print("D1S3G_STATUS=DIAGNOSTIC_COMPLETE")
    print("OUTPUT=" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
