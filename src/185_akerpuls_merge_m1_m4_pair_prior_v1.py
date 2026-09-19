#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls Merge M1: independent M4 pair-prior features on frozen M0 pair universe.

Input pair universe: exact 27,146 touching same-block 2025 field pairs frozen by M0.
Input crop prior: exact formally frozen blind M4 2026 per-field 16-class prior.

M1 is intentionally independent of M0 satellite evidence:
  * reads only field_a / field_b from the frozen M0 pair CSV;
  * does NOT read or carry m0_status, satellite_merge_score or spectral metrics;
  * computes only pair features from the two frozen M4 prior vectors and their
    history-quality diagnostics;
  * makes NO merge decision and assumes NO sign for later fusion.

No threshold tuning, no fusion, no geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

M0_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json")
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
M0_SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1")
M0_PAIRS = M0_SOURCE_DIR / "m0_satellite_merge_pairs.csv"

M4_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_freeze_v1\AKERPULS_M4_2026_PRIOR_FREEZE_V1.json")
EXPECTED_M4_FREEZE_SHA256 = "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95"
M4_SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_v1")
M4_PRIOR = M4_SOURCE_DIR / "M4_2026_FIELD_PRIOR.parquet"
EXPECTED_M4_PRIOR_SHA256 = "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_v1")
STATUS = "PASS_TO_M1_M4_PAIR_PRIOR_FREEZE_REVIEW"
EXPECTED_PAIRS = 27146
EXPECTED_FIELDS = 128636

CLASSES = [
    "höstraps", "höstvete", "vårvete", "höstkorn", "vårkorn", "havre", "råg", "rågvete",
    "sockerbetor", "matpotatis", "stärkelsepotatis", "vall på åkermark", "majs",
    "baljväxter", "träda/miljöyta", "annan gröda",
]
PROB_COLS = [f"p__{c}" for c in CLASSES]


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


def qdict(x: np.ndarray) -> dict:
    qs = [0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0]
    vals = np.quantile(np.asarray(x, dtype=np.float64), qs)
    return {str(q): float(v) for q, v in zip(qs, vals)}


def verify_m0_pair_universe() -> str:
    if not M0_FREEZE.is_file():
        raise FileNotFoundError(M0_FREEZE)
    if sha256_file(M0_FREEZE) != EXPECTED_M0_FREEZE_SHA256:
        raise RuntimeError("Frozen M0 SHA changed")
    freeze = load_json(M0_FREEZE)
    if freeze.get("status") != "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1":
        raise RuntimeError("Unexpected M0 freeze status")
    if int(freeze.get("census", {}).get("same_block_touching_pairs", -1)) != EXPECTED_PAIRS:
        raise RuntimeError("Frozen M0 pair census changed")
    source_hash = freeze.get("source_hashes", {}).get("source_pairs_csv_sha256")
    if not source_hash:
        raise RuntimeError("M0 freeze does not contain source pair CSV hash")
    if not M0_PAIRS.is_file():
        raise FileNotFoundError(M0_PAIRS)
    got = sha256_file(M0_PAIRS)
    if got != source_hash:
        raise RuntimeError(f"M0 source pair CSV changed: {got}")
    return got


def verify_m4_prior() -> tuple[str, dict]:
    if not M4_FREEZE.is_file():
        raise FileNotFoundError(M4_FREEZE)
    if sha256_file(M4_FREEZE) != EXPECTED_M4_FREEZE_SHA256:
        raise RuntimeError("Frozen M4 2026 prior SHA changed")
    freeze = load_json(M4_FREEZE)
    if freeze.get("status") != "FROZEN_AKERPULS_M4_2026_PRIOR_V1":
        raise RuntimeError("Unexpected M4 2026 prior freeze status")
    if int(freeze.get("fields", -1)) != EXPECTED_FIELDS or int(freeze.get("classes", -1)) != len(CLASSES):
        raise RuntimeError("M4 freeze population/class census changed")
    if freeze.get("key_artefacts", {}).get("M4_2026_FIELD_PRIOR.parquet") != EXPECTED_M4_PRIOR_SHA256:
        raise RuntimeError("M4 freeze does not pin expected prior Parquet")
    if not M4_PRIOR.is_file():
        raise FileNotFoundError(M4_PRIOR)
    got = sha256_file(M4_PRIOR)
    if got != EXPECTED_M4_PRIOR_SHA256:
        raise RuntimeError(f"M4 prior Parquet changed: {got}")
    guards = freeze.get("guards", {})
    if guards.get("2026_crop_labels_used") is not False or guards.get("2026_satellite_used") is not False:
        raise RuntimeError("M4 prior is not blind/pre-satellite")
    return got, freeze


def js_divergence(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    eps = 1e-15
    p = np.clip(p, eps, 1.0)
    q = np.clip(q, eps, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    q = q / q.sum(axis=1, keepdims=True)
    m = 0.5 * (p + q)
    return 0.5 * np.sum(p * np.log(p / m), axis=1) + 0.5 * np.sum(q * np.log(q / m), axis=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    m0_pair_sha = verify_m0_pair_universe()
    m4_prior_sha, _m4_freeze = verify_m4_prior()

    print("AKERPULS MERGE M1 M4 PAIR PRIOR V1")
    print(f"GIT_HEAD={head}")
    print(f"M0_FREEZE_SHA256={EXPECTED_M0_FREEZE_SHA256}")
    print(f"M4_2026_PRIOR_FREEZE_SHA256={EXPECTED_M4_FREEZE_SHA256}")
    print("M0_SATELLITE_FEATURES_READ=FALSE M0_STATUS_READ=FALSE")
    print("PROGRESS=LOAD_EXACT_FROZEN_PAIR_UNIVERSE")

    # Deliberately read ONLY the pair identity columns. This prevents accidental
    # use of M0 satellite scores/status in M1.
    pairs = pd.read_csv(M0_PAIRS, usecols=["field_a", "field_b"], dtype={"field_a": "string", "field_b": "string"})
    if len(pairs) != EXPECTED_PAIRS:
        raise RuntimeError(f"M0 pair-universe row count changed: {len(pairs)}")
    if pairs[["field_a", "field_b"]].isna().any().any():
        raise RuntimeError("Null field IDs in M0 pair universe")
    pair_key = pairs["field_a"].astype(str) + "||" + pairs["field_b"].astype(str)
    if pair_key.duplicated().any():
        raise RuntimeError("Duplicate pair key in frozen M0 universe")
    if not bool((pairs["field_a"].astype(str) <= pairs["field_b"].astype(str)).all()):
        raise RuntimeError("Frozen M0 pair ordering is no longer lexicographic")

    print("PROGRESS=LOAD_FROZEN_BLIND_2026_M4_PRIOR")
    needed = ["current_field_id"] + PROB_COLS + ["top1_class", "top1_prob", "entropy", "valid_history_years"]
    prior = pd.read_parquet(M4_PRIOR, columns=needed)
    prior["current_field_id"] = prior["current_field_id"].astype("string")
    if len(prior) != EXPECTED_FIELDS or prior["current_field_id"].nunique() != EXPECTED_FIELDS:
        raise RuntimeError("M4 prior field population/uniqueness changed")
    if list(prior[PROB_COLS].columns) != PROB_COLS:
        raise RuntimeError("M4 prior probability class order changed")
    if prior[needed].isna().any().any():
        raise RuntimeError("M4 prior contains nulls in required M1 columns")

    pmat = prior.set_index("current_field_id", drop=False)
    missing_a = ~pairs["field_a"].isin(pmat.index)
    missing_b = ~pairs["field_b"].isin(pmat.index)
    if bool(missing_a.any()) or bool(missing_b.any()):
        raise RuntimeError(f"M1 join missing fields: A={int(missing_a.sum())} B={int(missing_b.sum())}")

    a = pmat.loc[pairs["field_a"].to_numpy()].reset_index(drop=True)
    b = pmat.loc[pairs["field_b"].to_numpy()].reset_index(drop=True)
    pa = a[PROB_COLS].to_numpy(dtype=np.float64)
    pb = b[PROB_COLS].to_numpy(dtype=np.float64)

    if np.max(np.abs(pa.sum(axis=1) - 1.0)) > 1e-6 or np.max(np.abs(pb.sum(axis=1) - 1.0)) > 1e-6:
        raise RuntimeError("M4 pair probability vectors do not sum to one")

    print("PROGRESS=COMPUTE_PAIR_PRIOR_FEATURES")
    p_same = np.sum(pa * pb, axis=1)
    js = js_divergence(pa, pb)
    js_sim = 1.0 - js / math.log(2.0)
    overlap_mass = np.minimum(pa, pb).sum(axis=1)

    top3a = np.argpartition(-pa, kth=2, axis=1)[:, :3]
    top3b = np.argpartition(-pb, kth=2, axis=1)[:, :3]
    top3_overlap = np.fromiter(
        (len(set(x.tolist()).intersection(y.tolist())) for x, y in zip(top3a, top3b)),
        dtype=np.int8,
        count=EXPECTED_PAIRS,
    )

    top1_same = a["top1_class"].astype(str).to_numpy() == b["top1_class"].astype(str).to_numpy()
    top1pa = a["top1_prob"].to_numpy(dtype=np.float64)
    top1pb = b["top1_prob"].to_numpy(dtype=np.float64)
    enta = a["entropy"].to_numpy(dtype=np.float64)
    entb = b["entropy"].to_numpy(dtype=np.float64)
    vha = a["valid_history_years"].to_numpy(dtype=np.float64)
    vhb = b["valid_history_years"].to_numpy(dtype=np.float64)

    result = pd.DataFrame({
        "pair_key": pair_key.to_numpy(),
        "field_a": pairs["field_a"].to_numpy(),
        "field_b": pairs["field_b"].to_numpy(),
        "p_samecrop": p_same.astype(np.float32),
        "js_divergence_natlog": js.astype(np.float32),
        "js_similarity_01": js_sim.astype(np.float32),
        "probability_overlap_mass": overlap_mass.astype(np.float32),
        "top1_same": top1_same,
        "top1_class_a": a["top1_class"].astype(str).to_numpy(),
        "top1_class_b": b["top1_class"].astype(str).to_numpy(),
        "top1_prob_a": top1pa.astype(np.float32),
        "top1_prob_b": top1pb.astype(np.float32),
        "top1_prob_min": np.minimum(top1pa, top1pb).astype(np.float32),
        "top1_prob_product": (top1pa * top1pb).astype(np.float32),
        "top3_overlap_count": top3_overlap,
        "entropy_a": enta.astype(np.float32),
        "entropy_b": entb.astype(np.float32),
        "entropy_mean": (0.5 * (enta + entb)).astype(np.float32),
        "entropy_max": np.maximum(enta, entb).astype(np.float32),
        "entropy_absdiff": np.abs(enta - entb).astype(np.float32),
        "valid_history_years_a": vha.astype(np.float32),
        "valid_history_years_b": vhb.astype(np.float32),
        "valid_history_years_min": np.minimum(vha, vhb).astype(np.float32),
        "valid_history_years_mean": (0.5 * (vha + vhb)).astype(np.float32),
    })

    # Purely mathematical consistency guards. No merge label/score is consulted.
    if len(result) != EXPECTED_PAIRS or result["pair_key"].duplicated().any():
        raise RuntimeError("M1 output pair identity changed")
    if not ((result["p_samecrop"] >= 0) & (result["p_samecrop"] <= 1)).all():
        raise RuntimeError("p_samecrop outside [0,1]")
    if not ((result["js_divergence_natlog"] >= -1e-7) & (result["js_divergence_natlog"] <= math.log(2.0) + 1e-7)).all():
        raise RuntimeError("JS divergence outside [0, ln2]")
    if not ((result["js_similarity_01"] >= -1e-6) & (result["js_similarity_01"] <= 1 + 1e-6)).all():
        raise RuntimeError("JS similarity outside [0,1]")
    if not result["top3_overlap_count"].isin([0, 1, 2, 3]).all():
        raise RuntimeError("Invalid top3 overlap count")

    forbidden = {"m0_status", "satellite_merge_score", "field_mean_distance", "boundary_median_distance", "between_within_ratio"}
    if forbidden.intersection(result.columns):
        raise RuntimeError("M0 satellite evidence leaked into M1 output")

    out.mkdir(parents=True, exist_ok=False)
    parquet_path = out / "M1_M4_PAIR_PRIOR.parquet"
    csv_path = out / "M1_M4_PAIR_PRIOR.csv.gz"
    result.to_parquet(parquet_path, index=False, engine="pyarrow", compression="zstd")
    result.to_csv(csv_path, index=False, compression="gzip")

    top3_counts = result["top3_overlap_count"].value_counts().sort_index().to_dict()
    summary = {
        "schema_version": "akerpuls-merge-m1-m4-pair-prior-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "pair_universe": {
            "definition": "EXACT_FROZEN_M0_27146_PAIR_UNIVERSE",
            "pairs": EXPECTED_PAIRS,
            "m0_freeze_sha256": EXPECTED_M0_FREEZE_SHA256,
            "m0_source_pairs_csv_sha256": m0_pair_sha,
        },
        "m4_prior": {
            "target_year": 2026,
            "fields": EXPECTED_FIELDS,
            "classes": len(CLASSES),
            "m4_2026_prior_freeze_sha256": EXPECTED_M4_FREEZE_SHA256,
            "m4_prior_parquet_sha256": m4_prior_sha,
            "class_order": CLASSES,
        },
        "features": {
            "p_samecrop_definition": "sum_c pi_A(c)*pi_B(c)",
            "js_divergence_definition": "0.5*KL(pi_A||m)+0.5*KL(pi_B||m), m=(pi_A+pi_B)/2, natural log",
            "js_similarity_definition": "1-js_divergence/ln(2)",
            "probability_overlap_mass_definition": "sum_c min(pi_A(c),pi_B(c))",
            "top3_overlap_count_definition": "cardinality of intersection of each field's top-3 prior classes",
        },
        "descriptive_only": {
            "p_samecrop_quantiles": qdict(result["p_samecrop"].to_numpy()),
            "js_divergence_quantiles": qdict(result["js_divergence_natlog"].to_numpy()),
            "js_similarity_quantiles": qdict(result["js_similarity_01"].to_numpy()),
            "probability_overlap_mass_quantiles": qdict(result["probability_overlap_mass"].to_numpy()),
            "entropy_mean_quantiles": qdict(result["entropy_mean"].to_numpy()),
            "valid_history_years_min_quantiles": qdict(result["valid_history_years_min"].to_numpy()),
            "top1_same_count": int(result["top1_same"].sum()),
            "top1_same_rate": float(result["top1_same"].mean()),
            "top3_overlap_counts": {str(int(k)): int(v) for k, v in top3_counts.items()},
        },
        "guards": {
            "m0_satellite_features_read": False,
            "m0_status_read": False,
            "m0_satellite_score_read": False,
            "merge_label_used": False,
            "fusion_executed": False,
            "sign_assumption_for_merge": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
        },
        "next": "FREEZE_M1_PAIR_PRIOR_BEFORE_ANY_M2_FUSION_OR_HUMAN_LABEL_ANALYSIS",
    }
    summary_path = out / "M1_M4_PAIR_PRIOR_SUMMARY_V1.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_rows = []
    for p in sorted(out.glob("*")):
        if p.is_file() and p.name != "SHA256_MANIFEST.txt":
            manifest_rows.append(f"{sha256_file(p)}  {p.name}")
    manifest = out / "SHA256_MANIFEST.txt"
    manifest.write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")

    print(f"STATUS={STATUS}")
    print(f"PAIRS={len(result)} UNIQUE_PAIR_KEYS={result['pair_key'].nunique()}")
    print(f"TOP1_SAME={int(result['top1_same'].sum())} RATE={result['top1_same'].mean():.6f}")
    print(
        "P_SAMECROP_QUANTILES="
        f"P10:{np.quantile(p_same,0.10):.6f} P50:{np.quantile(p_same,0.50):.6f} "
        f"P90:{np.quantile(p_same,0.90):.6f} P95:{np.quantile(p_same,0.95):.6f}"
    )
    print(
        "JS_DIVERGENCE_QUANTILES="
        f"P10:{np.quantile(js,0.10):.6f} P50:{np.quantile(js,0.50):.6f} "
        f"P90:{np.quantile(js,0.90):.6f} P95:{np.quantile(js,0.95):.6f}"
    )
    print("TOP3_OVERLAP_COUNTS=" + " | ".join(f"{int(k)}:{int(v)}" for k, v in sorted(top3_counts.items())))
    print(f"PARQUET_SHA256={sha256_file(parquet_path)}")
    print(f"CSV_GZ_SHA256={sha256_file(csv_path)}")
    print(f"SUMMARY_SHA256={sha256_file(summary_path)}")
    print("M0_SATELLITE_FEATURES_READ=FALSE M0_STATUS_READ=FALSE M0_SCORE_READ=FALSE")
    print("FUSION_EXECUTED=FALSE SIGN_ASSUMPTION_FOR_MERGE=FALSE THRESHOLDS_TUNED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print(f"SHA256_MANIFEST={manifest}")
    print("NEXT=FREEZE_M1_PAIR_PRIOR_BEFORE_ANY_M2_FUSION_OR_HUMAN_LABEL_ANALYSIS")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
