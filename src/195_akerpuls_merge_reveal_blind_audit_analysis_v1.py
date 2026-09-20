#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reveal and analyze the frozen blind M0/M1 merge audit.

This stage is allowed to read the blind key ONLY because both the viewer/sample
and all 100 human labels are formally frozen. It executes the predeclared
stratum contrasts; it does not create a fusion score, choose fusion weights,
retune thresholds, automatically merge, or mutate geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

LABEL_FREEZE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_labels_freeze_v1")
LABEL_FREEZE_JSON = LABEL_FREEZE_DIR / "AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_FREEZE_V1.json"
LABELS = LABEL_FREEZE_DIR / "merge_disagreement_audit_labels_frozen.csv"
EXPECTED_LABEL_FREEZE_SHA256 = "de4b7fc7e9a6587c966304bb70d9456f4f8d6f65cbb869c47ce6339e90057ba8"
EXPECTED_LABELS_SHA256 = "4bd2583ea4f1d4255997acbe5c602b7b0743641f7dd12ad961a8132e87969e70"

VIEWER_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_v1b")
BLIND_KEY = VIEWER_DIR / "BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
EXPECTED_BLIND_KEY_SHA256 = "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee"
EXPECTED_VIEWER_FREEZE_SHA256 = "482e817753e00cca4f92972147515bd000e4a5800dd2bb1ff74af35a89e64a6a"
EXPECTED_M2_FREEZE_SHA256 = "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_v1")
STATUS = "PASS_TO_MERGE_AUDIT_REVEAL_REVIEW"
EXPECTED_ROWS = 100
EXPECTED_STRATA = {"HH": 25, "HL": 25, "LH": 25, "LL": 25}
LABEL_ORDER = ["TYDLIG_MERGE", "MÖJLIG_MERGE", "TVEKSAM", "BEHÅLL_GRÄNS", "EJ_BEDÖMBAR"]

CONTRASTS = [
    ("HH_vs_HL", "HH", "HL", "M1 high vs low conditional on high M0"),
    ("LH_vs_LL", "LH", "LL", "M1 high vs low conditional on low M0"),
    ("HH_vs_LH", "HH", "LH", "M0 high vs low conditional on high M1"),
    ("HL_vs_LL", "HL", "LL", "M0 high vs low conditional on low M1"),
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


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value using fixed margins, scipy-compatible rule."""
    r1, r2 = a + b, c + d
    c1 = a + c
    n = r1 + r2
    lo = max(0, c1 - r2)
    hi = min(r1, c1)

    def prob(x: int) -> float:
        return (math.comb(c1, x) * math.comb(n - c1, r1 - x)) / math.comb(n, r1)

    p_obs = prob(a)
    eps = 1e-12
    p = sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs + eps)
    return min(1.0, float(p))


def odds_ratio(a: int, b: int, c: int, d: int):
    den = b * c
    num = a * d
    if den == 0:
        if num == 0:
            return None
        return float("inf")
    return float(num / den)


def wilson(success: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = success / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def stratum_metrics(g: pd.DataFrame) -> dict:
    counts = {lab: int((g["merge_label"] == lab).sum()) for lab in LABEL_ORDER}
    assessable = g.loc[g["merge_label"] != "EJ_BEDÖMBAR"]
    n = len(assessable)
    strict = int((assessable["merge_label"] == "TYDLIG_MERGE").sum())
    broad = int(assessable["merge_label"].isin(["TYDLIG_MERGE", "MÖJLIG_MERGE"]).sum())
    strict_ci = wilson(strict, n)
    broad_ci = wilson(broad, n)
    return {
        "n_total": int(len(g)),
        "n_assessable": int(n),
        "label_counts": counts,
        "strict_positive_n": strict,
        "strict_positive_rate": strict / n if n else None,
        "strict_wilson95": [strict_ci[0], strict_ci[1]],
        "broad_positive_n": broad,
        "broad_positive_rate": broad / n if n else None,
        "broad_wilson95": [broad_ci[0], broad_ci[1]],
    }


def contrast_result(name: str, high: str, low: str, meaning: str, metrics: dict, endpoint: str) -> dict:
    key_n = f"{endpoint}_positive_n"
    hi = metrics[high]
    lo = metrics[low]
    a = int(hi[key_n])
    b = int(hi["n_assessable"] - a)
    c = int(lo[key_n])
    d = int(lo["n_assessable"] - c)
    rate_hi = a / hi["n_assessable"]
    rate_lo = c / lo["n_assessable"]
    return {
        "contrast": name,
        "meaning": meaning,
        "endpoint": endpoint,
        "high_stratum": high,
        "low_stratum": low,
        "high_positive": a,
        "high_n": hi["n_assessable"],
        "high_rate": rate_hi,
        "low_positive": c,
        "low_n": lo["n_assessable"],
        "low_rate": rate_lo,
        "risk_difference_high_minus_low": rate_hi - rate_lo,
        "odds_ratio": odds_ratio(a, b, c, d),
        "fisher_two_sided_p": fisher_two_sided(a, b, c, d),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Reveal-analysis output already exists: {out}")

    if not LABEL_FREEZE_JSON.is_file() or sha256_file(LABEL_FREEZE_JSON) != EXPECTED_LABEL_FREEZE_SHA256:
        raise RuntimeError("Label freeze missing or SHA changed")
    lf = load_json(LABEL_FREEZE_JSON)
    if lf.get("status") != "FROZEN_AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_V1":
        raise RuntimeError("Unexpected label-freeze status")
    if lf.get("viewer_freeze_sha256") != EXPECTED_VIEWER_FREEZE_SHA256:
        raise RuntimeError("Label freeze viewer lineage changed")
    if lf.get("m2_diagnostic_freeze_sha256") != EXPECTED_M2_FREEZE_SHA256:
        raise RuntimeError("Label freeze M2 lineage changed")
    if lf.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Label freeze blind-key hash changed")

    if not LABELS.is_file() or sha256_file(LABELS) != EXPECTED_LABELS_SHA256:
        raise RuntimeError("Frozen label CSV missing or SHA changed")
    if not BLIND_KEY.is_file() or sha256_file(BLIND_KEY) != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Blind key missing or SHA changed")

    print("AKERPULS MERGE BLIND AUDIT REVEAL ANALYSIS V1")
    print(f"GIT_HEAD={head}")
    print(f"LABELS_FREEZE_SHA256={EXPECTED_LABEL_FREEZE_SHA256}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA256}")
    print("BLIND_KEY_REVEAL_AUTHORIZED_BY_FROZEN_LABELS=TRUE")
    print("PROGRESS=LOAD_FROZEN_LABELS_AND_REVEAL_KEY")

    labels = pd.read_csv(LABELS, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    key = pd.read_csv(BLIND_KEY, encoding="utf-8-sig", dtype=str, keep_default_na=False)

    if len(labels) != EXPECTED_ROWS or len(key) != EXPECTED_ROWS:
        raise RuntimeError("Expected exactly 100 label and key rows")
    labels["blind_index"] = pd.to_numeric(labels["blind_index"], errors="raise").astype(int)
    key["blind_index"] = pd.to_numeric(key["blind_index"], errors="raise").astype(int)
    if labels["blind_index"].nunique() != EXPECTED_ROWS or key["blind_index"].nunique() != EXPECTED_ROWS:
        raise RuntimeError("blind_index is not unique in labels/key")
    if sorted(labels["blind_index"]) != list(range(1, 101)) or sorted(key["blind_index"]) != list(range(1, 101)):
        raise RuntimeError("blind_index sets are not exactly 1..100")

    joined = labels.merge(key, on="blind_index", how="outer", validate="one_to_one", indicator=True)
    if len(joined) != EXPECTED_ROWS or not (joined["_merge"] == "both").all():
        raise RuntimeError("Frozen labels and blind key did not join 1:1")
    joined = joined.drop(columns=["_merge"])

    got_strata = joined["stratum"].value_counts().to_dict()
    if got_strata != EXPECTED_STRATA:
        raise RuntimeError(f"Revealed stratum sample census changed: {got_strata}")

    print("PROGRESS=PREDECLARED_STRATUM_ANALYSIS")
    metrics = {s: stratum_metrics(joined.loc[joined["stratum"] == s]) for s in ["HH", "HL", "LH", "LL"]}

    contrasts = []
    for name, high, low, meaning in CONTRASTS:
        contrasts.append(contrast_result(name, high, low, meaning, metrics, "strict"))
        contrasts.append(contrast_result(name, high, low, meaning, metrics, "broad"))

    by_stratum_rows = []
    for s in ["HH", "HL", "LH", "LL"]:
        m = metrics[s]
        by_stratum_rows.append({
            "stratum": s,
            "n_total": m["n_total"],
            "n_assessable": m["n_assessable"],
            **{f"label__{k}": v for k, v in m["label_counts"].items()},
            "strict_positive_n": m["strict_positive_n"],
            "strict_positive_rate": m["strict_positive_rate"],
            "strict_ci95_low": m["strict_wilson95"][0],
            "strict_ci95_high": m["strict_wilson95"][1],
            "broad_positive_n": m["broad_positive_n"],
            "broad_positive_rate": m["broad_positive_rate"],
            "broad_ci95_low": m["broad_wilson95"][0],
            "broad_ci95_high": m["broad_wilson95"][1],
        })

    out.mkdir(parents=True, exist_ok=False)
    joined_path = out / "MERGE_AUDIT_REVEALED_JOIN.csv"
    strata_path = out / "MERGE_AUDIT_BY_STRATUM.csv"
    contrasts_path = out / "MERGE_AUDIT_PREDECLARED_CONTRASTS.csv"
    joined.to_csv(joined_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(by_stratum_rows).to_csv(strata_path, index=False, encoding="utf-8")
    pd.DataFrame(contrasts).to_csv(contrasts_path, index=False, encoding="utf-8")

    summary = {
        "schema_version": "akerpuls-merge-blind-audit-reveal-analysis-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parents": {
            "labels_freeze_sha256": EXPECTED_LABEL_FREEZE_SHA256,
            "labels_sha256": EXPECTED_LABELS_SHA256,
            "viewer_freeze_sha256": EXPECTED_VIEWER_FREEZE_SHA256,
            "m2_diagnostic_freeze_sha256": EXPECTED_M2_FREEZE_SHA256,
            "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        },
        "revealed_sample_census": EXPECTED_STRATA,
        "endpoints": {
            "strict_positive": "TYDLIG_MERGE / all assessable (EJ_BEDÖMBAR excluded; TVEKSAM remains non-positive)",
            "broad_positive": "(TYDLIG_MERGE + MÖJLIG_MERGE) / all assessable (EJ_BEDÖMBAR excluded; TVEKSAM remains non-positive)",
        },
        "by_stratum": metrics,
        "predeclared_contrasts": contrasts,
        "interpretation_limits": [
            "This is a deliberately stratified extreme-signal audit, not a population prevalence estimate.",
            "M0/M1 are observational signals; Fisher tests quantify association with blinded human labels, not causal effects.",
            "No fusion sign, weight, or operational threshold is selected in this stage.",
        ],
        "guards": {
            "fusion_executed": False,
            "fusion_score_created": False,
            "fusion_weight_selected": False,
            "sign_selected": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
        },
        "next": "REVIEW_PREDECLARED_CONTRASTS_AND_DECIDE_M1_SIGN_OR_NO_GO_FOR_FUSION",
    }
    summary_path = out / "MERGE_AUDIT_REVEAL_ANALYSIS_SUMMARY_V1.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_lines = []
    for p in sorted(out.glob("*")):
        if p.is_file() and p.name != "SHA256_MANIFEST.txt":
            manifest_lines.append(f"{sha256_file(p)}  {p.name}")
    manifest = out / "SHA256_MANIFEST.txt"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    print(f"STATUS={STATUS}")
    print("REVEALED_STRATA=" + " | ".join(f"{s}:{EXPECTED_STRATA[s]}" for s in ["HH","HL","LH","LL"]))
    for s in ["HH", "HL", "LH", "LL"]:
        m = metrics[s]
        lc = m["label_counts"]
        print(
            f"STRATUM={s} N={m['n_total']} ASSESSABLE={m['n_assessable']} "
            f"TYDLIG={lc['TYDLIG_MERGE']} MOJLIG={lc['MÖJLIG_MERGE']} "
            f"TVEKSAM={lc['TVEKSAM']} BEHALL={lc['BEHÅLL_GRÄNS']} EJ={lc['EJ_BEDÖMBAR']} "
            f"STRICT={m['strict_positive_rate']:.6f} BROAD={m['broad_positive_rate']:.6f}"
        )
    for r in contrasts:
        print(
            f"CONTRAST={r['contrast']} ENDPOINT={r['endpoint']} "
            f"HIGH_RATE={r['high_rate']:.6f} LOW_RATE={r['low_rate']:.6f} "
            f"RD={r['risk_difference_high_minus_low']:.6f} "
            f"OR={r['odds_ratio']} FISHER_P={r['fisher_two_sided_p']:.8g}"
        )
    print(f"SUMMARY_SHA256={sha256_file(summary_path)}")
    print(f"JOIN_SHA256={sha256_file(joined_path)}")
    print("FUSION_EXECUTED=FALSE FUSION_WEIGHT_SELECTED=FALSE SIGN_SELECTED=FALSE THRESHOLDS_TUNED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVIEW_PREDECLARED_CONTRASTS_AND_DECIDE_M1_SIGN_OR_NO_GO_FOR_FUSION")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
