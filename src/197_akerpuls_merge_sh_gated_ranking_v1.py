#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build conservative full-population S2026/Hprior gated merge ranking.

Human-facing terminology:
  S2026  = frozen M0 satellite-only merge evidence.
  Hprior = frozen M1 history/ÅkerMinne same-crop prior.

The legacy M0/M1 names remain only for frozen lineage compatibility.

Rule is intentionally categorical, not a fitted fusion:
  A CONFIRMED_HIGH: S2026 > P90 and Hprior > P75
  B SAT_HIGH_H_MID: S2026 > P90 and P25 < Hprior <= P75
  C SAT_HIGH_H_LOW: S2026 > P90 and Hprior <= P25
  D S_NOT_HIGH:     assessable but S2026 <= P90
  U M0_UNCERTAIN:   frozen M0 uncertain / not assessable

P90/P25/P75 are exactly the pre-label V1B audit design thresholds. No human
labels are used to calculate ranks, thresholds, scores or tiers here.

No continuous fusion, no fitted weights, no automatic merge, no geometry mutation.
Candidate universe remains same-2025-block only; block boundaries are hard walls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

M2_JOIN = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_v1\M2_M0_M1_DIAGNOSTIC_JOIN.parquet")
EXPECTED_M2_JOIN_SHA256 = "e4cfed6a9e2488a91eeaeea5535492d040ff972287b62bdb07fad702fba7137d"
EXPECTED_M2_FREEZE_SHA256 = "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859"
REVEAL_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_freeze_v1\AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_FREEZE_V1.json")
EXPECTED_REVEAL_FREEZE_SHA256 = "8ce0e0bd606da13f59576c63afd98d5fdebca655d23c88b4c17e2da42b8c9612"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_sh_gated_ranking_v1")
STATUS = "PASS_TO_SH_GATED_RANKING_REVIEW"
EXPECTED_PAIRS = 27146
EXPECTED_ASSESSABLE = 22358
EXPECTED_UNCERTAIN = 4788

S_GATE = 0.90
H_LOW = 0.25
H_HIGH = 0.75

TIER_ORDER = [
    "A_CONFIRMED_HIGH",
    "B_SAT_HIGH_H_MID",
    "C_SAT_HIGH_H_LOW",
    "D_S_NOT_HIGH",
    "U_M0_UNCERTAIN",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_guard() -> str:
    branch = subprocess.check_output(["git","branch","--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    if subprocess.check_output(["git","status","--short"], cwd=ROOT, text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT, text=True).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output already exists: {out}")

    if not M2_JOIN.is_file() or sha256_file(M2_JOIN) != EXPECTED_M2_JOIN_SHA256:
        raise RuntimeError("Frozen M2 join missing or changed")
    if not REVEAL_FREEZE.is_file() or sha256_file(REVEAL_FREEZE) != EXPECTED_REVEAL_FREEZE_SHA256:
        raise RuntimeError("Frozen reveal analysis missing or changed")

    d = pd.read_parquet(M2_JOIN)
    if len(d) != EXPECTED_PAIRS or d["pair_key"].nunique() != EXPECTED_PAIRS:
        raise RuntimeError("Frozen pair universe changed")

    assessable = d["m0_status"].isin(["MERGE_CANDIDATE","KEEP_BOUNDARY"])
    if int(assessable.sum()) != EXPECTED_ASSESSABLE:
        raise RuntimeError("Assessable census changed")
    if int((~assessable).sum()) != EXPECTED_UNCERTAIN:
        raise RuntimeError("Uncertain census changed")

    # Exact same Hprior percentile definition as the pre-label V1B audit:
    # average empirical pct rank among the frozen M0-assessable population only.
    d["hprior_percentile"] = np.nan
    d.loc[assessable, "hprior_percentile"] = (
        d.loc[assessable, "p_samecrop"].rank(method="average", pct=True)
    )

    if d.loc[assessable, "satellite_score_percentile"].isna().any():
        raise RuntimeError("S2026 percentile missing in assessable population")
    if d.loc[assessable, "hprior_percentile"].isna().any():
        raise RuntimeError("Hprior percentile missing in assessable population")

    s = d["satellite_score_percentile"]
    h = d["hprior_percentile"]

    d["sh_tier"] = "U_M0_UNCERTAIN"
    d.loc[assessable & (s <= S_GATE), "sh_tier"] = "D_S_NOT_HIGH"
    d.loc[assessable & (s > S_GATE) & (h <= H_LOW), "sh_tier"] = "C_SAT_HIGH_H_LOW"
    d.loc[assessable & (s > S_GATE) & (h > H_LOW) & (h <= H_HIGH), "sh_tier"] = "B_SAT_HIGH_H_MID"
    d.loc[assessable & (s > S_GATE) & (h > H_HIGH), "sh_tier"] = "A_CONFIRMED_HIGH"

    d["review_role"] = d["sh_tier"].map({
        "A_CONFIRMED_HIGH": "HIGHEST_PRIORITY_REVIEW__HISTORY_CONFIRMS",
        "B_SAT_HIGH_H_MID": "HIGH_PRIORITY_REVIEW__HISTORY_INTERMEDIATE",
        "C_SAT_HIGH_H_LOW": "REVIEW_WITH_CAUTION__HISTORY_CONTRADICTS",
        "D_S_NOT_HIGH": "NO_MERGE_PROPOSAL_V1",
        "U_M0_UNCERTAIN": "NO_MERGE_PROPOSAL_V1_UNCERTAIN",
    })

    d["automatic_merge"] = False
    d["geometry_mutated"] = False
    d["cross_block_allowed"] = False
    d["block_boundary_hard_wall"] = True

    counts = {tier: int((d["sh_tier"] == tier).sum()) for tier in TIER_ORDER}
    if sum(counts.values()) != EXPECTED_PAIRS:
        raise RuntimeError("Tier census does not sum to frozen pair universe")

    high_total = counts["A_CONFIRMED_HIGH"] + counts["B_SAT_HIGH_H_MID"] + counts["C_SAT_HIGH_H_LOW"]
    # These were already observed pre-label in the V1B feasibility build.
    if counts["A_CONFIRMED_HIGH"] != 1011:
        raise RuntimeError(f"A tier changed from pre-label V1B census: {counts['A_CONFIRMED_HIGH']}")
    if counts["C_SAT_HIGH_H_LOW"] != 54:
        raise RuntimeError(f"C tier changed from pre-label V1B census: {counts['C_SAT_HIGH_H_LOW']}")
    if high_total != 2236:
        raise RuntimeError(f"S2026>P90 census changed: {high_total}")

    cross = pd.crosstab(d["sh_tier"], d["m0_status"]).reindex(TIER_ORDER, fill_value=0)

    keep_cols = [
        "pair_key","field_a","field_b","m0_status",
        "satellite_merge_score","satellite_score_percentile",
        "p_samecrop","hprior_percentile",
        "top1_same","top1_class_a","top1_class_b",
        "sh_tier","review_role",
        "automatic_merge","geometry_mutated","cross_block_allowed","block_boundary_hard_wall",
    ]
    missing = [c for c in keep_cols if c not in d.columns]
    if missing:
        raise RuntimeError(f"Expected frozen columns missing: {missing}")

    out.mkdir(parents=True, exist_ok=False)
    parquet = out / "MERGE_SH_GATED_RANKING_V1.parquet"
    csv = out / "MERGE_SH_GATED_RANKING_V1.csv.gz"
    cross_csv = out / "MERGE_SH_GATED_RANKING_BY_M0_STATUS.csv"
    summary_path = out / "MERGE_SH_GATED_RANKING_SUMMARY_V1.json"

    d[keep_cols].to_parquet(parquet, index=False)
    d[keep_cols].to_csv(csv, index=False, encoding="utf-8", compression="gzip")
    cross.to_csv(cross_csv, encoding="utf-8")

    summary = {
        "schema_version": "akerpuls-merge-sh-gated-ranking-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "terminology": {
            "S2026": "legacy frozen M0 satellite-only merge signal",
            "Hprior": "legacy frozen M1 ÅkerMinne/M4 history prior",
            "legacy_names_retained_only_for_lineage": True,
        },
        "parents": {
            "m2_diagnostic_freeze_sha256": EXPECTED_M2_FREEZE_SHA256,
            "m2_join_sha256": EXPECTED_M2_JOIN_SHA256,
            "reveal_analysis_freeze_sha256": EXPECTED_REVEAL_FREEZE_SHA256,
        },
        "population": {
            "pairs_same_2025_block_only": EXPECTED_PAIRS,
            "assessable": EXPECTED_ASSESSABLE,
            "uncertain": EXPECTED_UNCERTAIN,
        },
        "rule": {
            "S2026_gate_percentile_gt": S_GATE,
            "Hprior_low_percentile_le": H_LOW,
            "Hprior_high_percentile_gt": H_HIGH,
            "threshold_origin": "PRE_LABEL_V1B_AUDIT_DESIGN__NOT_POST_LABEL_TUNING",
            "continuous_fusion": False,
            "fitted_weights": False,
        },
        "tier_counts": counts,
        "s2026_high_total": high_total,
        "audit_evidence": {
            "A_vs_C_directly_supported_by_first_blind_audit": True,
            "B_middle_history_not_directly_validated": True,
            "A_first_audit_broad_rate": 0.88,
            "A_first_audit_strict_rate": 0.64,
            "C_first_audit_broad_rate": 0.56,
            "C_first_audit_strict_rate": 0.28,
            "note": "Rates are from deliberately stratified audit samples and are not population prevalence estimates.",
        },
        "policy": {
            "block_boundary_hard_wall": True,
            "cross_block_merge_allowed": False,
            "automatic_merge": False,
            "geometry_mutated": False,
            "ranking_review_only": True,
        },
        "next": "INDEPENDENT_BLIND_VALIDATION_OF_A_CONFIRMED_HIGH_AND_B_SAT_HIGH_H_MID_BEFORE_OPERATIONAL_MERGE",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS MERGE S2026/HPRIOR GATED RANKING V1")
    print(f"STATUS={STATUS}")
    print(f"GIT_HEAD={head}")
    print(f"REVEAL_ANALYSIS_FREEZE_SHA256={EXPECTED_REVEAL_FREEZE_SHA256}")
    print("TERMINOLOGY=S2026_LEGACY_M0__HPRIOR_LEGACY_M1")
    print(f"PAIR_UNIVERSE={EXPECTED_PAIRS} ASSESSABLE={EXPECTED_ASSESSABLE} UNCERTAIN={EXPECTED_UNCERTAIN}")
    print(f"S2026_GATE_GT_P{int(S_GATE*100)} HPRIOR_HIGH_GT_P{int(H_HIGH*100)} HPRIOR_LOW_LE_P{int(H_LOW*100)}")
    print("TIER_COUNTS=" + " | ".join(f"{k}:{counts[k]}" for k in TIER_ORDER))
    print(f"S2026_HIGH_TOTAL={high_total}")
    print("BLOCK_BOUNDARY_HARD_WALL=TRUE CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print("CONTINUOUS_FUSION=FALSE FITTED_WEIGHTS=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print(f"PARQUET_SHA256={sha256_file(parquet)}")
    print(f"CSV_GZ_SHA256={sha256_file(csv)}")
    print(f"SUMMARY_SHA256={sha256_file(summary_path)}")
    print("NEXT=INDEPENDENT_BLIND_VALIDATION_OF_A_CONFIRMED_HIGH_AND_B_SAT_HIGH_H_MID_BEFORE_OPERATIONAL_MERGE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
