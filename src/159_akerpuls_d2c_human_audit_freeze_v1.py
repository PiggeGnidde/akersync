#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the completed blind D2C human audit after reveal.

This stage consumes the exact exported 100-field blind labels and the exact reveal
key produced by the frozen post-D2C viewer. It verifies their SHA256 hashes and
the parent D2C freeze, joins labels to the revealed P95/P90-only strata, computes
pre-declared strict/broad audit metrics, and writes a separate immutable audit
freeze package.

No model is executed, no threshold/fusion is changed, no split line is generated,
and no D2C frozen artifact is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_D2C_STATUS = "FROZEN_FULL_SKANE_QA_RANKING_V1"
EXPECTED_D2C_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"
EXPECTED_LABELS_SHA256 = "c5918bb3f74e205182e7f04612b3d48dac6f6cde103f94502759db222645041f"
EXPECTED_BLIND_KEY_SHA256 = "ee5f5bd3795f06040a2036e66d2a448b7c21986900d83454a702f412dad70200"
EXPECTED_ROWS = 100
P95_POP = 618
P90_ONLY_POP = 518
P90PLUS_POP = P95_POP + P90_ONLY_POP
LABEL_ORDER = ["TYDLIG_SPLIT", "MÖJLIG_SPLIT", "TVEKSAM", "FALSK_SPLIT", "EJ_BEDÖMBAR"]
STRICT_POSITIVE = {"TYDLIG_SPLIT"}
BROAD_POSITIVE = {"TYDLIG_SPLIT", "MÖJLIG_SPLIT"}
OUTPUT_DIRNAME = "d2c_visual_audit_freeze_v1"
FREEZE_NAME = "D2C_HUMAN_AUDIT_FREEZE_V1.json"
MANIFEST_NAME = "d2c_human_audit_manifest.json"

EXPECTED_COUNTS = {
    "P95_HIGH_PRIORITY": {
        "TYDLIG_SPLIT": 19, "MÖJLIG_SPLIT": 20, "TVEKSAM": 8, "FALSK_SPLIT": 3, "EJ_BEDÖMBAR": 0,
    },
    "P90_ONLY": {
        "TYDLIG_SPLIT": 10, "MÖJLIG_SPLIT": 9, "TVEKSAM": 18, "FALSK_SPLIT": 13, "EJ_BEDÖMBAR": 0,
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


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


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    n1 = a + b
    n2 = c + d
    m1 = a + c
    total = n1 + n2
    denom = math.comb(total, n1)

    def prob(x: int) -> float:
        return math.comb(m1, x) * math.comb(total - m1, n1 - x) / denom

    lo = max(0, n1 - (total - m1))
    hi = min(n1, m1)
    p_obs = prob(a)
    return min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs + 1e-15))


def spearman_midrank(x: pd.Series, y: pd.Series) -> float:
    xr = pd.to_numeric(x, errors="raise").rank(method="average")
    yr = pd.to_numeric(y, errors="raise").rank(method="average")
    return float(xr.corr(yr, method="pearson"))


def verify_d2c(d2c: Path) -> dict[str, Any]:
    manifest_path = d2c / "d2c_manifest.json"
    freeze_path = d2c / "D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json"
    for p in (manifest_path, freeze_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    manifest = read_json(manifest_path)
    if manifest.get("status") != EXPECTED_D2C_STATUS:
        raise RuntimeError(f"D2C status changed: {manifest.get('status')}")
    if manifest.get("freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("D2C manifest freeze SHA changed")
    if sha256_file(freeze_path) != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("D2C freeze file SHA changed")
    census = manifest.get("census", {})
    if int(census.get("p90plus", -1)) != P90PLUS_POP or int(census.get("p95", -1)) != P95_POP:
        raise RuntimeError(f"D2C frozen census changed: {census}")
    return manifest


def validate_sources(labels_path: Path, key_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not labels_path.is_file():
        raise FileNotFoundError(labels_path)
    if not key_path.is_file():
        raise FileNotFoundError(key_path)
    labels_sha = sha256_file(labels_path)
    key_sha = sha256_file(key_path)
    if labels_sha != EXPECTED_LABELS_SHA256:
        raise RuntimeError(f"Audit labels SHA changed: {labels_sha}")
    if key_sha != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError(f"Blind key SHA changed: {key_sha}")

    labels = pd.read_csv(labels_path, encoding="utf-8-sig", dtype={"blind_index": int})
    key = pd.read_csv(key_path, encoding="utf-8-sig", dtype={"blind_index": int, "parent_field_id_2025": str})
    req_labels = {"parent_d2c_freeze_sha256", "blind_key_sha256", "blind_index", "label", "note"}
    req_key = {
        "blind_index", "parent_field_id_2025", "audit_group", "qa_tier", "fusion_score",
        "prototype_p_splitmerge_2026", "separation_ratio", "true_loo_min_child_dice",
        "analysis_cell_id", "blind_hash",
    }
    if not req_labels.issubset(labels.columns):
        raise RuntimeError(f"Labels columns changed: {list(labels.columns)}")
    if not req_key.issubset(key.columns):
        raise RuntimeError(f"Blind-key columns changed: {list(key.columns)}")
    if len(labels) != EXPECTED_ROWS or len(key) != EXPECTED_ROWS:
        raise RuntimeError(f"Expected 100 labels/key rows, got {len(labels)}/{len(key)}")
    if labels.blind_index.duplicated().any() or key.blind_index.duplicated().any():
        raise RuntimeError("Duplicate blind_index in audit sources")
    expected_idx = list(range(1, EXPECTED_ROWS + 1))
    if sorted(labels.blind_index.tolist()) != expected_idx or sorted(key.blind_index.tolist()) != expected_idx:
        raise RuntimeError("Audit blind_index domain changed")
    if set(labels.parent_d2c_freeze_sha256.astype(str)) != {EXPECTED_D2C_FREEZE_SHA256}:
        raise RuntimeError("Labels parent D2C freeze binding changed")
    if set(labels.blind_key_sha256.astype(str)) != {EXPECTED_BLIND_KEY_SHA256}:
        raise RuntimeError("Labels blind-key binding changed")
    if labels.label.isna().any() or (labels.label.astype(str).str.len() == 0).any():
        raise RuntimeError("Audit contains missing labels")
    bad = sorted(set(labels.label.astype(str)) - set(LABEL_ORDER))
    if bad:
        raise RuntimeError(f"Unknown audit labels: {bad}")
    if key.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Blind key contains duplicate field IDs")

    strata = key.audit_group.astype(str).value_counts().to_dict()
    if strata != {"P95_HIGH_PRIORITY": 50, "P90_ONLY": 50}:
        raise RuntimeError(f"Blind-key strata changed: {strata}")
    return labels, key


def summary_rows(merged: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for group, pop in (("P95_HIGH_PRIORITY", P95_POP), ("P90_ONLY", P90_ONLY_POP)):
        x = merged[merged.audit_group.astype(str) == group]
        counts = x.label.astype(str).value_counts().to_dict()
        n = len(x)
        strict_k = sum(int(counts.get(lab, 0)) for lab in STRICT_POSITIVE)
        broad_k = sum(int(counts.get(lab, 0)) for lab in BROAD_POSITIVE)
        strict_ci = wilson95(strict_k, n)
        broad_ci = wilson95(broad_k, n)
        row = {
            "audit_group": group,
            "population_n": pop,
            "audit_n": n,
            **{f"n_{lab.lower()}": int(counts.get(lab, 0)) for lab in LABEL_ORDER},
            "strict_positive_n": strict_k,
            "strict_precision": strict_k / n,
            "strict_wilson95_lo": strict_ci[0],
            "strict_wilson95_hi": strict_ci[1],
            "broad_positive_n": broad_k,
            "broad_precision": broad_k / n,
            "broad_wilson95_lo": broad_ci[0],
            "broad_wilson95_hi": broad_ci[1],
            "clear_false_n": int(counts.get("FALSK_SPLIT", 0)),
            "clear_false_fraction": int(counts.get("FALSK_SPLIT", 0)) / n,
        }
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels_csv", help="Exact exported d2c_visual_audit_labels.csv")
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    ap.add_argument("--blind-key")
    args = ap.parse_args()

    head = git_guard()
    d2c = Path(args.d2c_dir)
    viewer = d2c / "d2c_visual_audit_viewer_v1"
    key_path = Path(args.blind_key) if args.blind_key else viewer / "BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
    labels_path = Path(args.labels_csv)

    print("D2C_AUDIT_FREEZE_PROGRESS=VERIFY_PARENT_AND_EXACT_REVIEW_ARTIFACTS", flush=True)
    verify_d2c(d2c)
    labels, key = validate_sources(labels_path, key_path)

    merged = labels.merge(key, on="blind_index", how="inner", validate="one_to_one")
    merged["label"] = merged["label"].astype(str)

    observed = {}
    for group in ("P95_HIGH_PRIORITY", "P90_ONLY"):
        vc = merged.loc[merged.audit_group.astype(str) == group, "label"].value_counts().to_dict()
        observed[group] = {lab: int(vc.get(lab, 0)) for lab in LABEL_ORDER}
    if observed != EXPECTED_COUNTS:
        raise RuntimeError(f"Revealed audit count table changed: {observed}")

    rows = summary_rows(merged)
    by_group = {r["audit_group"]: r for r in rows}
    p95 = by_group["P95_HIGH_PRIORITY"]
    p90 = by_group["P90_ONLY"]

    strict_fisher = fisher_two_sided(
        int(p95["strict_positive_n"]), 50 - int(p95["strict_positive_n"]),
        int(p90["strict_positive_n"]), 50 - int(p90["strict_positive_n"]),
    )
    broad_fisher = fisher_two_sided(
        int(p95["broad_positive_n"]), 50 - int(p95["broad_positive_n"]),
        int(p90["broad_positive_n"]), 50 - int(p90["broad_positive_n"]),
    )

    w95 = P95_POP / P90PLUS_POP
    w90 = P90_ONLY_POP / P90PLUS_POP
    weighted_labels = {}
    for lab in LABEL_ORDER:
        if lab == "EJ_BEDÖMBAR":
            weighted_labels[lab] = 0.0
            continue
        p_a = EXPECTED_COUNTS["P95_HIGH_PRIORITY"][lab] / 50.0
        p_b = EXPECTED_COUNTS["P90_ONLY"][lab] / 50.0
        weighted_labels[lab] = w95 * p_a + w90 * p_b
    weighted_strict = sum(weighted_labels[x] for x in STRICT_POSITIVE)
    weighted_broad = sum(weighted_labels[x] for x in BROAD_POSITIVE)

    ordinal = {"FALSK_SPLIT": 0, "TVEKSAM": 1, "MÖJLIG_SPLIT": 2, "TYDLIG_SPLIT": 3}
    corr_df = merged[merged.label.isin(ordinal)].copy()
    corr_df["human_ordinal"] = corr_df.label.map(ordinal).astype(float)
    correlations = {
        "fusion_score": spearman_midrank(corr_df["fusion_score"], corr_df["human_ordinal"]),
        "separation_ratio": spearman_midrank(corr_df["separation_ratio"], corr_df["human_ordinal"]),
        "true_loo_min_child_dice": spearman_midrank(corr_df["true_loo_min_child_dice"], corr_df["human_ordinal"]),
        "prototype_p_splitmerge_2026": spearman_midrank(corr_df["prototype_p_splitmerge_2026"], corr_df["human_ordinal"]),
    }

    out = d2c / OUTPUT_DIRNAME
    if out.exists():
        mpath = out / MANIFEST_NAME
        if not mpath.is_file():
            raise RuntimeError(f"Audit freeze directory exists without manifest: {out}")
        old = read_json(mpath)
        if old.get("source_labels_sha256") != EXPECTED_LABELS_SHA256 or old.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
            raise RuntimeError("Existing audit freeze is bound to different sources")
        for rec in old.get("output_hashes", {}).values():
            p = Path(rec["path"])
            if not p.is_file() or sha256_file(p) != rec["sha256"]:
                raise RuntimeError(f"Existing audit freeze output changed: {p}")
        print("AKERPULS D2C HUMAN AUDIT FREEZE")
        print("STATUS=FROZEN_D2C_HUMAN_AUDIT_V1_CACHED")
        print(f"AUDIT_FREEZE_SHA256={old.get('audit_freeze_sha256')}")
        print(f"OUTPUT={out}")
        return 0

    out.mkdir(parents=True, exist_ok=False)

    frozen_labels = out / "d2c_visual_audit_labels_frozen.csv"
    frozen_key = out / "BLIND_KEY_REVEALED_FROZEN.csv"
    shutil.copyfile(labels_path, frozen_labels)
    shutil.copyfile(key_path, frozen_key)

    merged_path = out / "d2c_visual_audit_revealed_100.csv"
    merged.to_csv(merged_path, index=False, encoding="utf-8-sig")
    summary_path = out / "d2c_visual_audit_summary.csv"
    pd.DataFrame(rows).to_csv(summary_path, index=False, encoding="utf-8-sig")

    freeze = {
        "schema_version": "akerpuls-d2c-human-audit-freeze-v1",
        "status": "FROZEN_D2C_HUMAN_AUDIT_V1",
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_d2c_status": EXPECTED_D2C_STATUS,
        "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
        "source_labels_sha256": EXPECTED_LABELS_SHA256,
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "audit_rows": EXPECTED_ROWS,
        "predeclared_interpretation": {
            "strict_positive_labels": sorted(STRICT_POSITIVE),
            "broad_positive_labels": sorted(BROAD_POSITIVE),
            "tveksam_reported_separately": True,
            "falsk_split_is_clear_false_positive": True,
            "ej_bedomdbar_excluded_from_assessable_if_present": True,
        },
        "revealed_counts": observed,
        "stratum_metrics": rows,
        "population_weights": {
            "P95_HIGH_PRIORITY": w95,
            "P90_ONLY": w90,
            "P95_population": P95_POP,
            "P90_only_population": P90_ONLY_POP,
            "P90plus_population": P90PLUS_POP,
        },
        "weighted_descriptive_estimates": {
            "label_fractions": weighted_labels,
            "strict_precision": weighted_strict,
            "broad_precision": weighted_broad,
            "note": "Descriptive stratum-weighted extrapolation only; audit sample was deterministic/geography-aware, not a simple random sample.",
        },
        "between_strata_tests": {
            "strict_fisher_two_sided_p": strict_fisher,
            "broad_fisher_two_sided_p": broad_fisher,
        },
        "post_reveal_exploratory_spearman": correlations,
        "guards": {
            "model_executed": False,
            "thresholds_tuned": False,
            "fusion_refit": False,
            "split_line_generated": False,
            "merge_executed": False,
            "geometry_mutated": False,
            "d2c_frozen_artifacts_modified": False,
        },
        "next_step": "Generate P95 split-line proposals as separate review-only geometry; do not replace official 2025 geometry.",
    }
    freeze_path = out / FREEZE_NAME
    write_json(freeze_path, freeze)
    freeze_sha = sha256_file(freeze_path)

    report = f"""# ÅkerPuls D2C human audit freeze v1

Status: `FROZEN_D2C_HUMAN_AUDIT_V1`

## Lineage
- Parent D2C freeze: `{EXPECTED_D2C_FREEZE_SHA256}`
- Frozen label export: `{EXPECTED_LABELS_SHA256}`
- Revealed blind key: `{EXPECTED_BLIND_KEY_SHA256}`
- Audit rows: 100 (50 P95, 50 P90-only)

## Pre-declared interpretation
- Strict positive: `TYDLIG_SPLIT`
- Broad positive: `TYDLIG_SPLIT + MÖJLIG_SPLIT`
- `TVEKSAM` reported separately.
- `FALSK_SPLIT` is a clear false positive.
- No field was `EJ_BEDÖMBAR`.

## Revealed result
| Stratum | Tydlig | Möjlig | Tveksam | Falsk | Strict | Broad |
|---|---:|---:|---:|---:|---:|---:|
| P95 | 19 | 20 | 8 | 3 | 38.0% | 78.0% |
| P90-only | 10 | 9 | 18 | 13 | 20.0% | 38.0% |

Two-sided Fisher exact p-values:
- strict P95 vs P90-only: `{strict_fisher:.12g}`
- broad P95 vs P90-only: `{broad_fisher:.12g}`

Fixed-stratum weighted descriptive P90+ estimates:
- `TYDLIG_SPLIT`: {100.0 * weighted_labels["TYDLIG_SPLIT"]:.2f}%
- `MÖJLIG_SPLIT`: {100.0 * weighted_labels["MÖJLIG_SPLIT"]:.2f}%
- `TVEKSAM`: {100.0 * weighted_labels["TVEKSAM"]:.2f}%
- `FALSK_SPLIT`: {100.0 * weighted_labels["FALSK_SPLIT"]:.2f}%
- strict: {100.0 * weighted_strict:.2f}%
- broad: {100.0 * weighted_broad:.2f}%

These weighted figures are descriptive extrapolations because the audit sample was deterministic/geography-aware, not a simple random sample.

## Post-reveal exploratory diagnostics
Spearman correlation with human ordinal label (`FALSK=0`, `TVEKSAM=1`, `MÖJLIG=2`, `TYDLIG=3`):
- fusion score: {correlations["fusion_score"]:.6f}
- separation ratio: {correlations["separation_ratio"]:.6f}
- TRUE-LOO min child Dice: {correlations["true_loo_min_child_dice"]:.6f}
- history prior: {correlations["prototype_p_splitmerge_2026"]:.6f}

These diagnostics are exploratory and must not be used to retroactively retune the frozen D2C ranking.

## Scope guard
This freeze generated no split line and changed no 2025 geometry, model, fusion score, or threshold.

Next authorized stage: generate review-only split-line proposals for the frozen P95 population.
"""
    report_path = out / "D2C_HUMAN_AUDIT_REPORT_V1.md"
    write_text(report_path, report)

    output_files = [frozen_labels, frozen_key, merged_path, summary_path, freeze_path, report_path]
    output_hashes = {
        p.name: {"path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in output_files
    }
    manifest = {
        "schema_version": "akerpuls-d2c-human-audit-freeze-manifest-v1",
        "status": "FROZEN_D2C_HUMAN_AUDIT_V1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
        "source_labels_sha256": EXPECTED_LABELS_SHA256,
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "audit_freeze_sha256": freeze_sha,
        "output_hashes": output_hashes,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "split_line_generated": False,
        "geometry_mutated": False,
        "d2c_frozen_artifacts_modified": False,
        "next_step_authorized": "P95_REVIEW_ONLY_SPLIT_LINE_PROPOSALS",
    }
    write_json(out / MANIFEST_NAME, manifest)

    print("AKERPULS D2C HUMAN AUDIT FREEZE")
    print("STATUS=FROZEN_D2C_HUMAN_AUDIT_V1")
    print(f"PARENT_D2C_FREEZE_SHA256={EXPECTED_D2C_FREEZE_SHA256}")
    print(f"SOURCE_LABELS_SHA256={EXPECTED_LABELS_SHA256}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA256}")
    print("P95_COUNTS=TYDLIG:19 MOJLIG:20 TVEKSAM:8 FALSK:3")
    print("P90_ONLY_COUNTS=TYDLIG:10 MOJLIG:9 TVEKSAM:18 FALSK:13")
    print(f"P95_STRICT={p95['strict_precision']:.6f} P95_BROAD={p95['broad_precision']:.6f}")
    print(f"P90_ONLY_STRICT={p90['strict_precision']:.6f} P90_ONLY_BROAD={p90['broad_precision']:.6f}")
    print(f"WEIGHTED_P90PLUS_STRICT={weighted_strict:.6f} WEIGHTED_P90PLUS_BROAD={weighted_broad:.6f}")
    print(f"FISHER_STRICT_P={strict_fisher:.12g} FISHER_BROAD_P={broad_fisher:.12g}")
    print(f"AUDIT_FREEZE_SHA256={freeze_sha}")
    print("MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE")
    print("SPLIT_LINE_GENERATED=FALSE GEOMETRY_MUTATED=FALSE D2C_FROZEN_ARTIFACTS_MODIFIED=FALSE")
    print("NEXT=P95_REVIEW_ONLY_SPLIT_LINE_PROPOSALS")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
