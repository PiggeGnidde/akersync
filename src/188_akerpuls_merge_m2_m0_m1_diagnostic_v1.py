#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls Merge M2 diagnostic: compare frozen M0 satellite and frozen M1 prior.

This stage is descriptive only. It joins the exact 27,146 frozen pair universe
and quantifies association/disagreement between M0 and M1. It does NOT create a
fusion score, choose a sign, tune a threshold, use human merge labels, adopt any
merge, or mutate geometry.
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

M0_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json")
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
M0_PAIRS = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1\m0_satellite_merge_pairs.csv")

M1_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_freeze_v1\AKERPULS_MERGE_M1_M4_PAIR_PRIOR_FREEZE_V1.json")
EXPECTED_M1_FREEZE_SHA256 = "5d39f6fea78260bd46cfa2aa99f8043abb02f1f67f57b73a9e30ae7273d9c20f"
M1_PRIOR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_v1b\M1_M4_PAIR_PRIOR.parquet")
EXPECTED_M1_PARQUET_SHA256 = "a2e6c2d091ad3b71b9112dea2627704c2d966fdb178a295db6af66df0c55a9f4"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_v1")
STATUS = "PASS_M2_M0_M1_DIAGNOSTIC_STOP"
EXPECTED_PAIRS = 27146
EXPECTED_ASSESSABLE = 22358
EXPECTED_STATUS_COUNTS = {"MERGE_CANDIDATE": 2398, "KEEP_BOUNDARY": 19960, "UNCERTAIN": 4788}

M1_METRICS = [
    "p_samecrop",
    "js_similarity_01",
    "probability_overlap_mass",
    "top1_prob_product",
    "entropy_mean",
    "valid_history_years_min",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def qstats(s: pd.Series) -> dict:
    x = pd.to_numeric(s, errors="coerce").dropna().to_numpy(dtype=float)
    if not len(x):
        return {"n": 0}
    return {
        "n": int(len(x)),
        "mean": float(np.mean(x)),
        "p10": float(np.quantile(x, 0.10)),
        "p25": float(np.quantile(x, 0.25)),
        "p50": float(np.quantile(x, 0.50)),
        "p75": float(np.quantile(x, 0.75)),
        "p90": float(np.quantile(x, 0.90)),
    }


def verify_inputs() -> tuple[str, str]:
    if not M0_FREEZE.is_file() or sha256_file(M0_FREEZE) != EXPECTED_M0_FREEZE_SHA256:
        raise RuntimeError("M0 freeze missing or SHA changed")
    m0f = load_json(M0_FREEZE)
    if m0f.get("status") != "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1":
        raise RuntimeError("Unexpected M0 freeze status")
    m0_csv_sha = m0f.get("source_hashes", {}).get("source_pairs_csv_sha256")
    if not m0_csv_sha or not M0_PAIRS.is_file() or sha256_file(M0_PAIRS) != m0_csv_sha:
        raise RuntimeError("Frozen M0 source pair CSV changed")

    if not M1_FREEZE.is_file() or sha256_file(M1_FREEZE) != EXPECTED_M1_FREEZE_SHA256:
        raise RuntimeError("M1 freeze missing or SHA changed")
    m1f = load_json(M1_FREEZE)
    if m1f.get("status") != "FROZEN_AKERPULS_MERGE_M1_M4_PAIR_PRIOR_V1":
        raise RuntimeError("Unexpected M1 freeze status")
    if m1f.get("parent_freezes", {}).get("m0_satellite_only_freeze_sha256") != EXPECTED_M0_FREEZE_SHA256:
        raise RuntimeError("M1 is not based on expected M0 pair universe")
    if not M1_PRIOR.is_file() or sha256_file(M1_PRIOR) != EXPECTED_M1_PARQUET_SHA256:
        raise RuntimeError("Frozen M1 Parquet changed")
    return m0_csv_sha, EXPECTED_M1_PARQUET_SHA256


def percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def decile_from_pct(p: pd.Series) -> pd.Series:
    return np.minimum(10, np.maximum(1, np.ceil(p.astype(float) * 10.0).astype(int)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")
    m0_csv_sha, m1_sha = verify_inputs()

    print("AKERPULS MERGE M2 M0-vs-M1 DIAGNOSTIC V1")
    print(f"GIT_HEAD={head}")
    print(f"M0_FREEZE_SHA256={EXPECTED_M0_FREEZE_SHA256}")
    print(f"M1_FREEZE_SHA256={EXPECTED_M1_FREEZE_SHA256}")
    print("FUSION_EXECUTED=FALSE SIGN_SELECTED=FALSE HUMAN_LABELS_USED=FALSE")
    print("PROGRESS=LOAD_FROZEN_M0_AND_M1")

    m0_cols = [
        "field_a", "field_b", "m0_status", "satellite_merge_score",
        "satellite_score_percentile", "field_mean_distance",
        "between_within_ratio", "boundary_median_distance",
        "valid_boundary_snapshots", "strong_edge_snapshots",
    ]
    m0 = pd.read_csv(M0_PAIRS, usecols=m0_cols, dtype={"field_a": "string", "field_b": "string"})
    m0["pair_key"] = m0["field_a"].astype(str) + "||" + m0["field_b"].astype(str)
    if len(m0) != EXPECTED_PAIRS or m0["pair_key"].nunique() != EXPECTED_PAIRS:
        raise RuntimeError("M0 pair census/uniqueness changed")
    status_counts = m0["m0_status"].astype(str).value_counts().to_dict()
    if status_counts != EXPECTED_STATUS_COUNTS:
        raise RuntimeError(f"M0 status census changed: {status_counts}")

    m1_cols = [
        "pair_key", "field_a_m0", "field_b_m0", "p_samecrop",
        "js_divergence_natlog", "js_similarity_01", "probability_overlap_mass",
        "top1_same", "top1_class_a", "top1_class_b",
        "top1_prob_min", "top1_prob_product", "top3_overlap_count",
        "entropy_mean", "entropy_max", "valid_history_years_min",
    ]
    m1 = pd.read_parquet(M1_PRIOR, columns=m1_cols)
    if len(m1) != EXPECTED_PAIRS or m1["pair_key"].nunique() != EXPECTED_PAIRS:
        raise RuntimeError("M1 pair census/uniqueness changed")
    if not bool((m1["pair_key"].astype(str) == (m1["field_a_m0"].astype(str) + "||" + m1["field_b_m0"].astype(str))).all()):
        raise RuntimeError("M1 pair-key lineage changed")

    joined = m0.merge(m1, on="pair_key", how="outer", validate="one_to_one", indicator=True)
    if len(joined) != EXPECTED_PAIRS or not bool((joined["_merge"] == "both").all()):
        raise RuntimeError("M0/M1 exact pair join failed")
    joined = joined.drop(columns=["_merge"])
    if not bool((joined["field_a"].astype(str) == joined["field_a_m0"].astype(str)).all()):
        raise RuntimeError("M0/M1 A-side pair identity mismatch")
    if not bool((joined["field_b"].astype(str) == joined["field_b_m0"].astype(str)).all()):
        raise RuntimeError("M0/M1 B-side pair identity mismatch")

    assessable = joined["m0_status"].isin(["MERGE_CANDIDATE", "KEEP_BOUNDARY"])
    if int(assessable.sum()) != EXPECTED_ASSESSABLE:
        raise RuntimeError(f"Assessable census changed: {int(assessable.sum())}")

    print("PROGRESS=DESCRIPTIVE_ASSOCIATION_AND_DISAGREEMENT")

    # Association only on M0-assessable pairs. These are descriptive correlations,
    # not evidence that any M1 direction is correct for true merge.
    corr = {}
    aa = joined.loc[assessable].copy()
    for col in M1_METRICS:
        corr[col] = {
            "spearman_with_satellite_merge_score": float(
                aa[["satellite_merge_score", col]].corr(method="spearman").iloc[0, 1]
            ),
            "pearson_with_satellite_merge_score": float(
                aa[["satellite_merge_score", col]].corr(method="pearson").iloc[0, 1]
            ),
        }

    by_status = {}
    for status in ["MERGE_CANDIDATE", "KEEP_BOUNDARY", "UNCERTAIN"]:
        g = joined.loc[joined["m0_status"] == status]
        by_status[status] = {
            "n": int(len(g)),
            "top1_same_rate": float(g["top1_same"].mean()),
            "top3_overlap_mean": float(g["top3_overlap_count"].mean()),
            "p_samecrop": qstats(g["p_samecrop"]),
            "js_similarity_01": qstats(g["js_similarity_01"]),
            "probability_overlap_mass": qstats(g["probability_overlap_mass"]),
            "entropy_mean": qstats(g["entropy_mean"]),
        }

    # Fixed rank diagnostics; not tuned thresholds.
    joined["m1_p_samecrop_percentile_all"] = percentile_rank(joined["p_samecrop"])
    joined["m1_p_samecrop_decile_all"] = decile_from_pct(joined["m1_p_samecrop_percentile_all"])

    decile_rows = []
    for d in range(1, 11):
        g = joined.loc[joined["m1_p_samecrop_decile_all"] == d]
        ga = g.loc[g["m0_status"].isin(["MERGE_CANDIDATE", "KEEP_BOUNDARY"])]
        decile_rows.append({
            "m1_p_samecrop_decile_all": d,
            "n_all": int(len(g)),
            "merge_candidate": int((g["m0_status"] == "MERGE_CANDIDATE").sum()),
            "keep_boundary": int((g["m0_status"] == "KEEP_BOUNDARY").sum()),
            "uncertain": int((g["m0_status"] == "UNCERTAIN").sum()),
            "assessable_n": int(len(ga)),
            "m0_candidate_rate_among_assessable": (
                float((ga["m0_status"] == "MERGE_CANDIDATE").mean()) if len(ga) else None
            ),
            "median_m0_satellite_score_assessable": (
                float(ga["satellite_merge_score"].median()) if len(ga) else None
            ),
        })
    deciles = pd.DataFrame(decile_rows)

    # On the exact assessable subset, compare percentile ranks and fixed top-tail
    # intersections. These are disagreement diagnostics only.
    aa["m0_score_pct_diag"] = percentile_rank(aa["satellite_merge_score"])
    aa["m1_samecrop_pct_diag"] = percentile_rank(aa["p_samecrop"])
    aa["m0_decile_diag"] = decile_from_pct(aa["m0_score_pct_diag"])
    aa["m1_decile_diag"] = decile_from_pct(aa["m1_samecrop_pct_diag"])

    ctab = pd.crosstab(aa["m0_decile_diag"], aa["m1_decile_diag"], dropna=False)
    ctab = ctab.reindex(index=range(1, 11), columns=range(1, 11), fill_value=0)

    tails = {}
    for q in (0.90, 0.95):
        m0_hi = aa["m0_score_pct_diag"] > q
        m1_hi = aa["m1_samecrop_pct_diag"] > q
        both = m0_hi & m1_hi
        tails[str(q)] = {
            "m0_high_n": int(m0_hi.sum()),
            "m1_high_n": int(m1_hi.sum()),
            "both_high_n": int(both.sum()),
            "m0_only_n": int((m0_hi & ~m1_hi).sum()),
            "m1_only_n": int((~m0_hi & m1_hi).sum()),
            "neither_high_n": int((~m0_hi & ~m1_hi).sum()),
            "jaccard_high_sets": float(both.sum() / (m0_hi | m1_hi).sum()),
        }

    top1_table = pd.crosstab(joined["m0_status"], joined["top1_same"]).reindex(
        index=["MERGE_CANDIDATE", "KEEP_BOUNDARY", "UNCERTAIN"], columns=[False, True], fill_value=0
    )

    out.mkdir(parents=True, exist_ok=False)
    join_path = out / "M2_M0_M1_DIAGNOSTIC_JOIN.parquet"
    decile_path = out / "M2_M1_P_SAMECROP_DECILES.csv"
    ctab_path = out / "M2_ASSESSABLE_M0_M1_DECILE_CROSSTAB.csv"
    joined.to_parquet(join_path, index=False, engine="pyarrow", compression="zstd")
    deciles.to_csv(decile_path, index=False)
    ctab.to_csv(ctab_path, index=True, index_label="m0_decile_diag")

    summary = {
        "schema_version": "akerpuls-merge-m2-m0-m1-diagnostic-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parents": {
            "m0_freeze_sha256": EXPECTED_M0_FREEZE_SHA256,
            "m0_source_pairs_csv_sha256": m0_csv_sha,
            "m1_freeze_sha256": EXPECTED_M1_FREEZE_SHA256,
            "m1_parquet_sha256": m1_sha,
        },
        "census": {
            "pairs": EXPECTED_PAIRS,
            "assessable": EXPECTED_ASSESSABLE,
            "m0_status_counts": EXPECTED_STATUS_COUNTS,
        },
        "association_assessable_only": corr,
        "m1_descriptive_by_m0_status": by_status,
        "fixed_rank_tail_overlap_assessable_only": tails,
        "m0_status_by_m1_top1_same": {
            status: {"false": int(top1_table.loc[status, False]), "true": int(top1_table.loc[status, True])}
            for status in top1_table.index
        },
        "interpretation_limits": [
            "M0 status is satellite-baseline output, not ground-truth merge label.",
            "Association or tail overlap cannot establish the correct sign of M1 for true merge.",
            "No M0/M1 fusion score is created in this stage.",
            "Human merge labels remain unopened in this stage.",
        ],
        "guards": {
            "fusion_executed": False,
            "fusion_score_created": False,
            "sign_selected": False,
            "human_labels_used": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
        },
        "next": "REVIEW_M2_ASSOCIATION_THEN_DESIGN_BLIND_HUMAN_AUDIT_FOR_M0_M1_SIGN_AND_FUSION",
    }
    summary_path = out / "M2_M0_M1_DIAGNOSTIC_SUMMARY_V1.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = []
    for p in sorted(out.glob("*")):
        if p.is_file() and p.name != "SHA256_MANIFEST.txt":
            rows.append(f"{sha256_file(p)}  {p.name}")
    manifest = out / "SHA256_MANIFEST.txt"
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")

    print(f"STATUS={STATUS}")
    print(f"PAIRS={EXPECTED_PAIRS} ASSESSABLE={EXPECTED_ASSESSABLE}")
    for col in M1_METRICS:
        print(
            f"CORR_{col.upper()}_WITH_M0_SCORE="
            f"SPEARMAN:{corr[col]['spearman_with_satellite_merge_score']:.6f} "
            f"PEARSON:{corr[col]['pearson_with_satellite_merge_score']:.6f}"
        )
    for status in ["MERGE_CANDIDATE", "KEEP_BOUNDARY", "UNCERTAIN"]:
        x = by_status[status]
        print(
            f"M1_BY_M0_STATUS={status} N={x['n']} TOP1_SAME_RATE={x['top1_same_rate']:.6f} "
            f"P_SAME_P50={x['p_samecrop']['p50']:.6f} P_SAME_P90={x['p_samecrop']['p90']:.6f}"
        )
    for q in ("0.9", "0.95"):
        x = tails[q]
        print(
            f"TAIL_OVERLAP_Q={q} M0_HIGH={x['m0_high_n']} M1_HIGH={x['m1_high_n']} "
            f"BOTH={x['both_high_n']} M0_ONLY={x['m0_only_n']} M1_ONLY={x['m1_only_n']} "
            f"JACCARD={x['jaccard_high_sets']:.6f}"
        )
    print(f"JOIN_PARQUET_SHA256={sha256_file(join_path)}")
    print(f"SUMMARY_SHA256={sha256_file(summary_path)}")
    print("FUSION_EXECUTED=FALSE FUSION_SCORE_CREATED=FALSE SIGN_SELECTED=FALSE HUMAN_LABELS_USED=FALSE")
    print("THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVIEW_M2_ASSOCIATION_THEN_DESIGN_BLIND_HUMAN_AUDIT_FOR_M0_M1_SIGN_AND_FUSION")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
