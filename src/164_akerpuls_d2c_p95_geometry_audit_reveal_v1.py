#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reveal and analyze the frozen blind P95 line-geometry audit.

This stage may open the previously hidden blind key only because the exact
100-row label export has already been frozen and pinned. It verifies the
pre-reveal freeze SHA, labels SHA, blind-key SHA, deterministic 100-of-613
sample, and frozen proposal summary before joining any hidden metadata.

It computes only descriptive/post-reveal diagnostics. No model execution,
threshold tuning, fusion refit, smoothing, gap filling, merge, or replacement
of official 2025 geometry is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")

EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256 = "089cd1d90daa9252e93ddbe4004c7afad5f0c00ec8d54293b43fc6915e4983f0"
EXPECTED_PROPOSAL_FREEZE_SHA256 = "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a"
EXPECTED_LABELS_SHA256 = "3b9be03ea440eebf581e4f80e5a84a825a81a972ab0a44f4dfd3a2c16254d76a"
EXPECTED_BLIND_KEY_SHA256 = "75515e0f1bd7f0466657317d7176be535f73da06a3505f2bad68b3190b33b428"
EXPECTED_ROWS = 100
EXPECTED_LINE_POPULATION = 613
EXPECTED_P95_POPULATION = 618
EXPECTED_NO_INTERFACE = 5

GEOM_FREEZE_DIR = "d2c_p95_geometry_audit_freeze_v1"
GEOM_FREEZE_FILE = "P95_GEOMETRY_AUDIT_FREEZE_V1.json"
GEOM_FREEZE_MANIFEST = "p95_geometry_audit_freeze_manifest.json"
VIEWER_DIR = "d2c_p95_geometry_audit_viewer_v1"
VIEWER_MANIFEST = "p95_geometry_audit_viewer_manifest.json"
BLIND_KEY_FILE = "BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv"
PROPOSAL_FREEZE_DIR = "d2c_p95_split_line_freeze_v1"
PROPOSAL_FREEZE_FILE = "P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json"
OUTPUT_DIR = "d2c_p95_geometry_audit_reveal_v1"
OUTPUT_MANIFEST = "p95_geometry_audit_reveal_manifest.json"

SPLIT_LABELS = ["TYDLIG_SPLIT", "MÖJLIG_SPLIT", "TVEKSAM", "FALSK_SPLIT", "EJ_BEDÖMBAR"]
LINE_LABELS = ["RATT_GRANS", "NARA_GRANS", "FEL_GRANS", "EJ_BEDOMBAR", "EJ_TILLAMPLIG"]
PREDECLARED_ANALYSIS = {
    "split_positive_for_geometry": ["TYDLIG_SPLIT", "MÖJLIG_SPLIT"],
    "split_ambiguous": ["TVEKSAM"],
    "split_negative": ["FALSK_SPLIT"],
    "line_strict_positive": ["RATT_GRANS"],
    "line_broad_positive": ["RATT_GRANS", "NARA_GRANS"],
    "line_negative": ["FEL_GRANS"],
    "line_excluded": ["EJ_BEDOMBAR", "EJ_TILLAMPLIG"],
    "joint_strict_success": "split in {TYDLIG_SPLIT,MOJLIG_SPLIT} AND line=RATT_GRANS",
    "joint_broad_success": "split in {TYDLIG_SPLIT,MOJLIG_SPLIT} AND line in {RATT_GRANS,NARA_GRANS}",
}

HUMAN_SPLIT_ORDINAL = {
    "FALSK_SPLIT": 0.0,
    "TVEKSAM": 1.0,
    "MÖJLIG_SPLIT": 2.0,
    "TYDLIG_SPLIT": 3.0,
}
HUMAN_LINE_ORDINAL = {
    "FEL_GRANS": 0.0,
    "NARA_GRANS": 1.0,
    "RATT_GRANS": 2.0,
}
KEY_METRICS = [
    "fusion_score",
    "separation_ratio",
    "spatial_coherence",
    "min_child_fraction",
    "min_child_pixels",
    "supporting_snapshots",
    "raw_interface_length_m",
    "primary_line_length_m",
    "primary_fraction_of_raw",
]

INTERPRETATION_CAVEAT = (
    "The geometry-audit viewer displayed the proposed cyan line. Therefore the second "
    "split label is not independent ground truth and may be visually cued by the proposal. "
    "Use the split rate as corroborative; the primary geometry endpoint is line placement "
    "conditional on a human-visible split."
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def wilson95(k: int, n: int) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    z = 1.959963984540054
    p = k / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / den
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def spearman_midrank(x: pd.Series, y: pd.Series) -> float:
    xx = pd.to_numeric(x, errors="coerce")
    yy = pd.to_numeric(y, errors="coerce")
    m = xx.notna() & yy.notna()
    if int(m.sum()) < 3:
        return float("nan")
    xr = xx[m].rank(method="average")
    yr = yy[m].rank(method="average")
    return float(xr.corr(yr, method="pearson"))


def verify_geometry_audit_freeze(d2c: Path) -> dict[str, Any]:
    d = d2c / GEOM_FREEZE_DIR
    fp = d / GEOM_FREEZE_FILE
    mp = d / GEOM_FREEZE_MANIFEST
    for p in (fp, mp):
        if not p.is_file():
            raise FileNotFoundError(p)
    if sha256_file(fp) != EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256:
        raise RuntimeError("Pre-reveal geometry-audit freeze SHA changed")
    freeze = read_json(fp)
    manifest = read_json(mp)
    if freeze.get("status") != "FROZEN_P95_GEOMETRY_AUDIT_V1":
        raise RuntimeError("Unexpected pre-reveal geometry-audit freeze status")
    if manifest.get("geometry_audit_freeze_sha256") != EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256:
        raise RuntimeError("Geometry-audit manifest freeze binding changed")
    if freeze.get("parent_proposal_freeze_sha256") != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("Geometry-audit parent proposal freeze changed")
    if freeze.get("source_labels_sha256") != EXPECTED_LABELS_SHA256:
        raise RuntimeError("Geometry-audit labels SHA binding changed")
    if freeze.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Geometry-audit blind-key binding changed")
    if freeze.get("predeclared_analysis") != PREDECLARED_ANALYSIS:
        raise RuntimeError("Predeclared analysis changed")
    if freeze.get("blind_key_opened_by_this_stage") is not False or freeze.get("reveal_executed") is not False:
        raise RuntimeError("Pre-reveal freeze does not certify blind state")
    return freeze


def validate_labels(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    if sha256_file(path) != EXPECTED_LABELS_SHA256:
        raise RuntimeError("Frozen geometry-audit labels SHA changed")
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"blind_index": int})
    req = [
        "parent_proposal_freeze_sha256",
        "blind_key_sha256",
        "blind_index",
        "split_label",
        "line_label",
        "note",
    ]
    if list(df.columns) != req:
        raise RuntimeError(f"Unexpected labels columns: {list(df.columns)}")
    if len(df) != EXPECTED_ROWS or df.blind_index.duplicated().any():
        raise RuntimeError("Labels are not 100 unique blind-index rows")
    if sorted(df.blind_index.tolist()) != list(range(1, EXPECTED_ROWS + 1)):
        raise RuntimeError("Labels blind_index domain changed")
    if set(df.parent_proposal_freeze_sha256.astype(str)) != {EXPECTED_PROPOSAL_FREEZE_SHA256}:
        raise RuntimeError("Labels proposal-freeze binding changed")
    if set(df.blind_key_sha256.astype(str)) != {EXPECTED_BLIND_KEY_SHA256}:
        raise RuntimeError("Labels blind-key binding changed")
    if df.split_label.isna().any() or df.line_label.isna().any():
        raise RuntimeError("Labels contain missing split/line decisions")
    if set(df.split_label.astype(str)) - set(SPLIT_LABELS):
        raise RuntimeError("Labels contain unknown split decision")
    if set(df.line_label.astype(str)) - set(LINE_LABELS):
        raise RuntimeError("Labels contain unknown line decision")
    return df


def verify_viewer_and_key(d2c: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    vdir = d2c / VIEWER_DIR
    mp = vdir / VIEWER_MANIFEST
    kp = vdir / BLIND_KEY_FILE
    for p in (mp, kp):
        if not p.is_file():
            raise FileNotFoundError(p)
    vm = read_json(mp)
    if vm.get("status") != "PASS_TO_BLIND_P95_LINE_GEOMETRY_AUDIT":
        raise RuntimeError("Viewer status changed")
    if vm.get("parent_proposal_freeze_sha256") != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("Viewer proposal-freeze binding changed")
    if int(vm.get("audit_sample", -1)) != EXPECTED_ROWS or int(vm.get("line_population", -1)) != EXPECTED_LINE_POPULATION:
        raise RuntimeError("Viewer sample/population census changed")
    if vm.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Viewer blind-key SHA binding changed")
    if vm.get("predeclared_analysis") != PREDECLARED_ANALYSIS:
        raise RuntimeError("Viewer predeclared analysis changed")
    if sha256_file(kp) != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Blind-key file SHA changed")

    key = pd.read_csv(kp, encoding="utf-8-sig", dtype={"blind_index": int, "parent_field_id_2025": str})
    required = [
        "blind_index", "parent_field_id_2025", "sample_hash", "blind_hash",
        "analysis_cell_id", "fusion_score", "separation_ratio", "spatial_coherence",
        "min_child_fraction", "min_child_pixels", "supporting_snapshots",
        "raw_interface_length_m", "primary_line_length_m", "primary_fraction_of_raw",
    ]
    if list(key.columns) != required:
        raise RuntimeError(f"Unexpected blind-key columns: {list(key.columns)}")
    if len(key) != EXPECTED_ROWS or key.blind_index.duplicated().any() or key.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Blind key is not 100 unique index/field rows")
    if sorted(key.blind_index.tolist()) != list(range(1, EXPECTED_ROWS + 1)):
        raise RuntimeError("Blind-key index domain changed")

    sample_salt = str(vm.get("sample_salt", ""))
    blind_salt = str(vm.get("blind_order_salt", ""))
    if not sample_salt or not blind_salt:
        raise RuntimeError("Viewer sample/blind salts missing")
    for r in key.itertuples(index=False):
        fid = str(r.parent_field_id_2025)
        if str(r.sample_hash) != sha256_text(f"{sample_salt}|{fid}"):
            raise RuntimeError(f"Sample hash mismatch for {fid}")
        if str(r.blind_hash) != sha256_text(f"{blind_salt}|{fid}"):
            raise RuntimeError(f"Blind hash mismatch for {fid}")
    got_population_sha = sha256_text("\n".join(sorted(key.parent_field_id_2025.astype(str))) + "\n")
    if got_population_sha != vm.get("sample_population_sha256"):
        raise RuntimeError("Blind-key 100-field population SHA changed")
    return key, vm


def verify_proposal_population(d2c: Path, key: pd.DataFrame, vm: dict[str, Any]) -> pd.DataFrame:
    fdir = d2c / PROPOSAL_FREEZE_DIR
    fp = fdir / PROPOSAL_FREEZE_FILE
    if not fp.is_file():
        raise FileNotFoundError(fp)
    if sha256_file(fp) != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("Proposal freeze SHA changed")
    freeze = read_json(fp)
    if freeze.get("status") != "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1":
        raise RuntimeError("Proposal freeze status changed")
    if int(freeze.get("line_available_fields", -1)) != EXPECTED_LINE_POPULATION:
        raise RuntimeError("Proposal line-available population changed")
    if int(freeze.get("no_shared_interface_fields", -1)) != EXPECTED_NO_INTERFACE:
        raise RuntimeError("Proposal no-interface census changed")

    rec = freeze.get("source_output_hashes", {}).get("p95_split_proposal_summary.csv")
    if not rec:
        raise RuntimeError("Proposal freeze does not pin summary CSV")
    summary_path = Path(rec["path"])
    if not summary_path.is_file() or sha256_file(summary_path) != rec.get("sha256"):
        raise RuntimeError("Frozen proposal summary changed")
    summary = pd.read_csv(summary_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    line_pop = summary.loc[summary.proposal_status.astype(str).eq("LINE_AVAILABLE")].copy()
    if len(line_pop) != EXPECTED_LINE_POPULATION or line_pop.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Frozen proposal summary no longer has 613 unique line fields")

    # Recreate the deterministic sample from the entire 613-line population.
    sample_salt = str(vm["sample_salt"])
    expected = line_pop[["parent_field_id_2025"]].copy()
    expected["sample_hash"] = [sha256_text(f"{sample_salt}|{fid}") for fid in expected.parent_field_id_2025.astype(str)]
    expected = expected.sort_values(["sample_hash", "parent_field_id_2025"]).head(EXPECTED_ROWS)
    if set(expected.parent_field_id_2025.astype(str)) != set(key.parent_field_id_2025.astype(str)):
        raise RuntimeError("Revealed key is not the frozen deterministic 100-of-613 sample")

    sidx = summary.set_index("parent_field_id_2025", drop=False)
    for r in key.itertuples(index=False):
        fid = str(r.parent_field_id_2025)
        if fid not in sidx.index:
            raise RuntimeError(f"Revealed field missing from proposal summary: {fid}")
        s = sidx.loc[fid]
        if str(r.analysis_cell_id) != str(s.get("analysis_cell_id", "")):
            raise RuntimeError(f"Analysis-cell mismatch for {fid}")
        for col in KEY_METRICS:
            a = float(getattr(r, col))
            b = float(s[col])
            if not math.isfinite(a) or not math.isfinite(b) or abs(a - b) > 1e-9 * max(1.0, abs(b)):
                raise RuntimeError(f"Revealed metric mismatch {fid} {col}: {a} != {b}")
    return line_pop


def metric_correlations(joined: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    split_df = joined[joined.split_label.astype(str).isin(HUMAN_SPLIT_ORDINAL)].copy()
    split_df["human_split_ordinal"] = split_df.split_label.map(HUMAN_SPLIT_ORDINAL).astype(float)
    split_corr = {m: spearman_midrank(split_df[m], split_df["human_split_ordinal"]) for m in KEY_METRICS}

    line_df = joined[joined.line_label.astype(str).isin(HUMAN_LINE_ORDINAL)].copy()
    line_df["human_line_ordinal"] = line_df.line_label.map(HUMAN_LINE_ORDINAL).astype(float)
    line_corr = {m: spearman_midrank(line_df[m], line_df["human_line_ordinal"]) for m in KEY_METRICS}
    return split_corr, line_corr


def population_comparison(line_pop: pd.DataFrame, key: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in KEY_METRICS:
        pop = pd.to_numeric(line_pop[m], errors="coerce").dropna()
        sam = pd.to_numeric(key[m], errors="coerce").dropna()
        out[m] = {
            "population_n": int(len(pop)),
            "sample_n": int(len(sam)),
            "population_mean": float(pop.mean()),
            "sample_mean": float(sam.mean()),
            "population_p50": float(pop.median()),
            "sample_p50": float(sam.median()),
        }
    out["analysis_cells"] = {
        "population_unique": int(line_pop.analysis_cell_id.astype(str).nunique()),
        "sample_unique": int(key.analysis_cell_id.astype(str).nunique()),
    }
    return out


def main() -> int:
    head = git_guard()
    ap = argparse.ArgumentParser()
    ap.add_argument("labels_csv", help="Exact frozen p95_geometry_audit_labels.csv")
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    args = ap.parse_args()

    d2c = Path(args.d2c_dir)
    labels_path = Path(args.labels_csv)

    print("P95_GEOMETRY_AUDIT_REVEAL_PROGRESS=VERIFY_PRE_REVEAL_FREEZE", flush=True)
    verify_geometry_audit_freeze(d2c)
    labels = validate_labels(labels_path)
    key, vm = verify_viewer_and_key(d2c)
    line_pop = verify_proposal_population(d2c, key, vm)

    print("P95_GEOMETRY_AUDIT_REVEAL_PROGRESS=OPEN_AND_JOIN_FROZEN_BLIND_KEY", flush=True)
    joined = labels.merge(key, on="blind_index", how="inner", validate="one_to_one")
    if len(joined) != EXPECTED_ROWS or joined.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Reveal join is not 100 unique fields")

    split_counts = {x: int((joined.split_label.astype(str) == x).sum()) for x in SPLIT_LABELS}
    line_counts = {x: int((joined.line_label.astype(str) == x).sum()) for x in LINE_LABELS}

    split_strict = joined.split_label.astype(str).eq("TYDLIG_SPLIT")
    split_positive = joined.split_label.astype(str).isin(["TYDLIG_SPLIT", "MÖJLIG_SPLIT"])
    line_assessable = joined.line_label.astype(str).isin(["RATT_GRANS", "NARA_GRANS", "FEL_GRANS"])
    line_strict = joined.line_label.astype(str).eq("RATT_GRANS")
    line_broad = joined.line_label.astype(str).isin(["RATT_GRANS", "NARA_GRANS"])

    split_strict_n = int(split_strict.sum())
    split_broad_n = int(split_positive.sum())
    line_assessable_n = int(line_assessable.sum())
    line_strict_n = int((line_assessable & line_strict).sum())
    line_broad_n = int((line_assessable & line_broad).sum())
    cond_n = int(split_positive.sum())
    cond_line_strict_n = int((split_positive & line_strict).sum())
    cond_line_broad_n = int((split_positive & line_broad).sum())
    cond_line_wrong_n = int((split_positive & joined.line_label.astype(str).eq("FEL_GRANS")).sum())
    joint_strict_n = cond_line_strict_n
    joint_broad_n = cond_line_broad_n

    intervals = {
        "split_strict_wilson95": wilson95(split_strict_n, EXPECTED_ROWS),
        "split_broad_wilson95": wilson95(split_broad_n, EXPECTED_ROWS),
        "line_assessable_strict_wilson95": wilson95(line_strict_n, line_assessable_n),
        "line_assessable_broad_wilson95": wilson95(line_broad_n, line_assessable_n),
        "conditional_split_positive_line_strict_wilson95": wilson95(cond_line_strict_n, cond_n),
        "conditional_split_positive_line_broad_wilson95": wilson95(cond_line_broad_n, cond_n),
        "joint_strict_wilson95": wilson95(joint_strict_n, EXPECTED_ROWS),
        "joint_broad_wilson95": wilson95(joint_broad_n, EXPECTED_ROWS),
    }

    split_corr, line_corr = metric_correlations(joined)
    pop_compare = population_comparison(line_pop, key)

    # Descriptive extrapolation only: sample is deterministic hash-selected, not a probability sample.
    strict_linepop_rate = joint_strict_n / EXPECTED_ROWS
    broad_linepop_rate = joint_broad_n / EXPECTED_ROWS
    expected_joint_strict_line_fields = strict_linepop_rate * EXPECTED_LINE_POPULATION
    expected_joint_broad_line_fields = broad_linepop_rate * EXPECTED_LINE_POPULATION
    full_p95_strict_rate = expected_joint_strict_line_fields / EXPECTED_P95_POPULATION
    full_p95_broad_rate = expected_joint_broad_line_fields / EXPECTED_P95_POPULATION

    out = d2c / OUTPUT_DIR
    if out.exists():
        mp = out / OUTPUT_MANIFEST
        if not mp.is_file():
            raise RuntimeError(f"Reveal output exists without manifest: {out}")
        old = read_json(mp)
        if (
            old.get("source_labels_sha256") != EXPECTED_LABELS_SHA256
            or old.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256
            or old.get("parent_geometry_audit_freeze_sha256") != EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256
        ):
            raise RuntimeError("Existing reveal belongs to different frozen sources")
        for rec in old.get("output_hashes", {}).values():
            p = Path(rec["path"])
            if not p.is_file() or sha256_file(p) != rec["sha256"]:
                raise RuntimeError(f"Existing reveal output changed: {p}")
        print("AKERPULS D2C P95 GEOMETRY AUDIT REVEAL")
        print("STATUS=REVEALED_P95_GEOMETRY_AUDIT_V1_CACHED")
        print(f"OUTPUT={out}")
        return 0

    out.mkdir(parents=True, exist_ok=False)
    revealed_path = out / "p95_geometry_audit_revealed_100.csv"
    joined.to_csv(revealed_path, index=False, encoding="utf-8-sig")

    summary_obj = {
        "schema_version": "akerpuls-d2c-p95-geometry-audit-reveal-summary-v1",
        "status": "REVEALED_P95_GEOMETRY_AUDIT_V1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_geometry_audit_freeze_sha256": EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256,
        "parent_proposal_freeze_sha256": EXPECTED_PROPOSAL_FREEZE_SHA256,
        "source_labels_sha256": EXPECTED_LABELS_SHA256,
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "sample_n": EXPECTED_ROWS,
        "line_population_n": EXPECTED_LINE_POPULATION,
        "p95_population_n": EXPECTED_P95_POPULATION,
        "no_interface_n": EXPECTED_NO_INTERFACE,
        "split_counts": split_counts,
        "line_counts": line_counts,
        "predeclared_analysis": PREDECLARED_ANALYSIS,
        "metrics": {
            "split_strict": {"k": split_strict_n, "n": EXPECTED_ROWS, "rate": split_strict_n / EXPECTED_ROWS},
            "split_broad": {"k": split_broad_n, "n": EXPECTED_ROWS, "rate": split_broad_n / EXPECTED_ROWS},
            "line_assessable_strict": {"k": line_strict_n, "n": line_assessable_n, "rate": line_strict_n / line_assessable_n},
            "line_assessable_broad": {"k": line_broad_n, "n": line_assessable_n, "rate": line_broad_n / line_assessable_n},
            "conditional_on_split_positive_line_strict": {"k": cond_line_strict_n, "n": cond_n, "rate": cond_line_strict_n / cond_n},
            "conditional_on_split_positive_line_broad": {"k": cond_line_broad_n, "n": cond_n, "rate": cond_line_broad_n / cond_n},
            "conditional_on_split_positive_line_wrong": {"k": cond_line_wrong_n, "n": cond_n, "rate": cond_line_wrong_n / cond_n},
            "joint_strict": {"k": joint_strict_n, "n": EXPECTED_ROWS, "rate": joint_strict_n / EXPECTED_ROWS},
            "joint_broad": {"k": joint_broad_n, "n": EXPECTED_ROWS, "rate": joint_broad_n / EXPECTED_ROWS},
        },
        "wilson95_descriptive": {k: {"lo": v[0], "hi": v[1]} for k, v in intervals.items()},
        "descriptive_extrapolation": {
            "expected_joint_strict_among_613_line_fields": expected_joint_strict_line_fields,
            "expected_joint_broad_among_613_line_fields": expected_joint_broad_line_fields,
            "joint_strict_rate_if_5_no_interface_count_as_failures_in_full_618_p95": full_p95_strict_rate,
            "joint_broad_rate_if_5_no_interface_count_as_failures_in_full_618_p95": full_p95_broad_rate,
            "note": "Descriptive only; the 100 fields were deterministic hash-selected rather than sampled probabilistically.",
        },
        "post_reveal_exploratory_spearman": {
            "with_split_ordinal": split_corr,
            "with_line_quality_ordinal_assessable_only": line_corr,
        },
        "sample_vs_613_population": pop_compare,
        "interpretation_caveat": INTERPRETATION_CAVEAT,
        "guards": {
            "reveal_executed": True,
            "blind_key_opened": True,
            "model_executed": False,
            "thresholds_tuned": False,
            "fusion_refit": False,
            "smoothing": False,
            "gap_filling": False,
            "merge_executed": False,
            "official_2025_geometry_replaced": False,
            "automatic_geometry_mutation": False,
            "review_only": True,
        },
        "next_step": (
            "Interpret the frozen reveal. Decide separately whether smoothing is needed "
            "for display/export and whether any proposal tier may advance beyond review-only."
        ),
    }
    summary_path = out / "P95_GEOMETRY_AUDIT_REVEAL_SUMMARY_V1.json"
    write_json(summary_path, summary_obj)

    def pct(k: int, n: int) -> float:
        return 100.0 * k / n if n else float("nan")

    report = f"""# ÅkerPuls P95 geometry audit — revealed analysis v1

Status: `REVEALED_P95_GEOMETRY_AUDIT_V1`

## Frozen lineage
- Pre-reveal geometry-audit freeze: `{EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256}`
- Proposal freeze: `{EXPECTED_PROPOSAL_FREEZE_SHA256}`
- Exact labels: `{EXPECTED_LABELS_SHA256}`
- Exact blind key: `{EXPECTED_BLIND_KEY_SHA256}`
- Audit sample: {EXPECTED_ROWS} of {EXPECTED_LINE_POPULATION} P95 fields with a primary line.
- Full P95 population: {EXPECTED_P95_POPULATION}; no shared interface: {EXPECTED_NO_INTERFACE}.

## Frozen human result
Split:
- `TYDLIG_SPLIT`: {split_counts["TYDLIG_SPLIT"]}
- `MÖJLIG_SPLIT`: {split_counts["MÖJLIG_SPLIT"]}
- `TVEKSAM`: {split_counts["TVEKSAM"]}
- `FALSK_SPLIT`: {split_counts["FALSK_SPLIT"]}

Line:
- `RATT_GRANS`: {line_counts["RATT_GRANS"]}
- `NARA_GRANS`: {line_counts["NARA_GRANS"]}
- `FEL_GRANS`: {line_counts["FEL_GRANS"]}
- `EJ_TILLAMPLIG`: {line_counts["EJ_TILLAMPLIG"]}

## Predeclared endpoints
- Split strict (`TYDLIG`): {split_strict_n}/{EXPECTED_ROWS} = {pct(split_strict_n, EXPECTED_ROWS):.2f}%.
- Split broad (`TYDLIG+MÖJLIG`): {split_broad_n}/{EXPECTED_ROWS} = {pct(split_broad_n, EXPECTED_ROWS):.2f}%.
- Conditional on split-positive: line strict (`RATT`): {cond_line_strict_n}/{cond_n} = {pct(cond_line_strict_n, cond_n):.2f}%.
- Conditional on split-positive: line broad (`RATT+NARA`): {cond_line_broad_n}/{cond_n} = {pct(cond_line_broad_n, cond_n):.2f}%.
- Conditional on split-positive: wrong line: {cond_line_wrong_n}/{cond_n} = {pct(cond_line_wrong_n, cond_n):.2f}%.
- Joint strict: {joint_strict_n}/{EXPECTED_ROWS} = {pct(joint_strict_n, EXPECTED_ROWS):.2f}%.
- Joint broad: {joint_broad_n}/{EXPECTED_ROWS} = {pct(joint_broad_n, EXPECTED_ROWS):.2f}%.

Among all {line_assessable_n} human-assessable lines (excluding `EJ_TILLAMPLIG/EJ_BEDOMBAR`):
- strict line placement: {line_strict_n}/{line_assessable_n} = {pct(line_strict_n, line_assessable_n):.2f}%.
- broad line placement: {line_broad_n}/{line_assessable_n} = {pct(line_broad_n, line_assessable_n):.2f}%.

## Descriptive extrapolation
If the frozen 100-field rates are applied descriptively to the 613 line-available P95 fields:
- joint strict ≈ {expected_joint_strict_line_fields:.1f} fields.
- joint broad ≈ {expected_joint_broad_line_fields:.1f} fields.

If the five P95 fields with no shared interface are counted as geometry failures:
- full-P95 joint strict ≈ {100.0 * full_p95_strict_rate:.2f}%.
- full-P95 joint broad ≈ {100.0 * full_p95_broad_rate:.2f}%.

These are descriptive extrapolations, not probability-sample estimates.

## Important interpretation caveat
{INTERPRETATION_CAVEAT}

The first P95 human audit (without a proposed split line shown) remains the cleaner
validation of whether a candidate is truly split. This second audit is primarily
a validation of where the proposed line lies when a visible split is judged to exist.

## Post-reveal diagnostics
Hidden score/geometry correlations are recorded in `P95_GEOMETRY_AUDIT_REVEAL_SUMMARY_V1.json`.
They are exploratory only and may not be used to retroactively retune the frozen D2C ranking.

## Scope
No model, threshold, fusion score, split proposal, smoothing rule, or official 2025 geometry
was changed by reveal.
"""
    report_path = out / "P95_GEOMETRY_AUDIT_REVEAL_REPORT_V1.md"
    write_text(report_path, report)

    output_files = [revealed_path, summary_path, report_path]
    output_hashes = {
        p.name: {"path": str(p), "sha256": sha256_file(p), "bytes": int(p.stat().st_size)}
        for p in output_files
    }
    manifest = {
        "schema_version": "akerpuls-d2c-p95-geometry-audit-reveal-manifest-v1",
        "status": "REVEALED_P95_GEOMETRY_AUDIT_V1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_geometry_audit_freeze_sha256": EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256,
        "parent_proposal_freeze_sha256": EXPECTED_PROPOSAL_FREEZE_SHA256,
        "source_labels_sha256": EXPECTED_LABELS_SHA256,
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "output_hashes": output_hashes,
        "reveal_executed": True,
        "blind_key_opened": True,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "smoothing": False,
        "gap_filling": False,
        "merge_executed": False,
        "official_2025_geometry_replaced": False,
        "automatic_geometry_mutation": False,
        "review_only": True,
    }
    manifest_path = out / OUTPUT_MANIFEST
    write_json(manifest_path, manifest)

    print("AKERPULS D2C P95 GEOMETRY AUDIT REVEAL")
    print("STATUS=REVEALED_P95_GEOMETRY_AUDIT_V1")
    print(f"PARENT_GEOMETRY_AUDIT_FREEZE_SHA256={EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA256}")
    print(f"SAMPLE={EXPECTED_ROWS}/{EXPECTED_LINE_POPULATION} P95_TOTAL={EXPECTED_P95_POPULATION} NO_INTERFACE={EXPECTED_NO_INTERFACE}")
    print(f"SPLIT_STRICT={split_strict_n}/{EXPECTED_ROWS} SPLIT_BROAD={split_broad_n}/{EXPECTED_ROWS}")
    print(f"LINE_ASSESSABLE={line_assessable_n}/{EXPECTED_ROWS} LINE_STRICT={line_strict_n}/{line_assessable_n} LINE_BROAD={line_broad_n}/{line_assessable_n}")
    print(f"CONDITIONAL_ON_SPLIT_POSITIVE={cond_n} LINE_STRICT={cond_line_strict_n}/{cond_n} LINE_BROAD={cond_line_broad_n}/{cond_n} LINE_WRONG={cond_line_wrong_n}/{cond_n}")
    print(f"JOINT_STRICT={joint_strict_n}/{EXPECTED_ROWS} JOINT_BROAD={joint_broad_n}/{EXPECTED_ROWS}")
    print(f"FULL_P95_DESCRIPTIVE_JOINT_STRICT={full_p95_strict_rate:.6f} FULL_P95_DESCRIPTIVE_JOINT_BROAD={full_p95_broad_rate:.6f}")
    print(f"POST_REVEAL_SPEARMAN_FUSION_SPLIT={split_corr['fusion_score']:.6f}")
    print(f"POST_REVEAL_SPEARMAN_SEPARATION_SPLIT={split_corr['separation_ratio']:.6f}")
    print(f"POST_REVEAL_SPEARMAN_PRIMARY_FRACTION_LINE={line_corr['primary_fraction_of_raw']:.6f}")
    print("REVEAL_EXECUTED=TRUE BLIND_KEY_OPENED=TRUE")
    print("MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE SMOOTHING=FALSE GAP_FILLING=FALSE")
    print("OFFICIAL_2025_GEOMETRY_REPLACED=FALSE AUTOMATIC_GEOMETRY_MUTATION=FALSE REVIEW_ONLY=TRUE")
    print("INTERPRETATION=LINE_PLACEMENT_PRIMARY_ENDPOINT_SPLIT_RATE_CORROBORATIVE_BECAUSE_CYAN_LINE_WAS_VISIBLE")
    print("NEXT=INTERPRET_AND_DECIDE_SMOOTHING_OR_GEOMETRY_ADOPTION_POLICY")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
