#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose the historical target-census mismatch before any M4 fit.

Read-only. Tests plausible target-validity rules from the frozen ÅkerMinne
columns against the frozen STOPPUNKT-C sample counts for 2021-2025.
No model fit and no 2026 prediction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
DEFAULT_CONFIG = ROOT / "config" / "akerpuls_m4_reimplementation_v1.json"
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_target_census_diagnostic_v1")
STATUS = "PASS_M4_TARGET_CENSUS_DIAGNOSTIC_STOP"

FROZEN_N = {2021: 118190, 2022: 119101, 2023: 120330, 2024: 122065, 2025: 128636}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def truthy(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    s = series.astype("string").str.strip().str.lower()
    return s.isin({"1", "true", "t", "yes", "y"})


def compile_rules(cfg: dict):
    return [
        (item["class"], [re.compile(p, flags=re.IGNORECASE) for p in item["patterns"]])
        for item in cfg["crop_name_mapping_rules"]
    ]


def map_crop_name(name, known: bool, rules) -> str | None:
    if not known or pd.isna(name):
        return None
    s = str(name).strip()
    for cls, pats in rules:
        if any(p.search(s) for p in pats):
            return cls
    return "annan gröda"


def count_rule(df: pd.DataFrame, base: pd.Series, mask: pd.Series) -> int:
    return int((base & mask.fillna(False)).sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    meta = cfg["inputs"]["history"]
    p = Path(cfg["inputs"]["directory"]) / meta["file"]
    if sha256_file(p) != meta["sha256"]:
        raise RuntimeError("Frozen ÅkerMinne input SHA mismatch")

    wanted = [
        "current_field_id", "history_year", "dominant_crop_name", "dominant_crop_known",
        "dominant_crop_share", "coverage_raw", "status", "reason_flags",
        "identity_match_confidence", "identity_match_reason", "primary_f_current",
        "primary_f_historical", "material_overlap_anomaly",
    ]
    header = pd.read_csv(p, compression="gzip", nrows=0).columns.tolist()
    use = [c for c in wanted if c in header]
    df = pd.read_csv(p, compression="gzip", usecols=use, low_memory=False)
    df["history_year"] = pd.to_numeric(df["history_year"], errors="raise").astype(int)
    known = truthy(df["dominant_crop_known"])
    rules = compile_rules(cfg)
    mapped = pd.Series(
        [map_crop_name(n, bool(k), rules) for n, k in zip(df["dominant_crop_name"], known)],
        index=df.index, dtype="string"
    )
    base_all = known & mapped.isin(cfg["target_classes"])

    # Precompute robust numeric / boolean columns where available.
    num = {}
    for c in ("coverage_raw", "dominant_crop_share", "primary_f_current", "primary_f_historical"):
        if c in df.columns:
            num[c] = pd.to_numeric(df[c], errors="coerce")
    anomaly = truthy(df["material_overlap_anomaly"]) if "material_overlap_anomaly" in df.columns else pd.Series(False, index=df.index)

    rows = []
    print("AKERPULS M4 TARGET CENSUS DIAGNOSTIC")
    print(f"GIT_HEAD={head}")
    print(f"HISTORY_SHA256={sha256_file(p)}")

    for year in sorted(FROZEN_N):
        ym = df["history_year"].eq(year)
        base = base_all & ym
        frozen = FROZEN_N[year]
        current = int(base.sum())
        print(f"YEAR={year} CURRENT={current} FROZEN={frozen} EXCESS={current-frozen}")

        # Exact status decomposition among currently-valid targets.
        status_counts = {}
        if "status" in df.columns:
            vc = df.loc[base, "status"].astype("string").fillna("<NA>").value_counts(dropna=False)
            status_counts = {str(k): int(v) for k, v in vc.items()}
            print("  STATUS=" + " | ".join(f"{k}:{v}" for k, v in status_counts.items()))

        candidates = {"current_known_mapped": current}
        if "status" in df.columns:
            st = df["status"].astype("string")
            candidates["exclude_PARTIAL_COVERAGE"] = count_rule(df, base, st.ne("PARTIAL_COVERAGE"))
            candidates["status_SINGLE_OR_MIXED"] = count_rule(df, base, st.isin(["SINGLE_CROP", "MIXED_CROPS"]))
            candidates["status_SINGLE_ONLY"] = count_rule(df, base, st.eq("SINGLE_CROP"))
            candidates["exclude_NO_PUBLIC_MATCH"] = count_rule(df, base, st.ne("NO_PUBLIC_MATCH"))

        candidates["exclude_material_overlap_anomaly"] = count_rule(df, base, ~anomaly)

        for c in ("coverage_raw", "dominant_crop_share", "primary_f_current", "primary_f_historical"):
            if c in num:
                for thr in (0.50, 0.80, 0.90, 0.95, 0.99):
                    candidates[f"{c}_ge_{thr:.2f}"] = count_rule(df, base, num[c].ge(thr))

        if "identity_match_confidence" in df.columns:
            conf = df["identity_match_confidence"].astype("string")
            vals = sorted(conf.loc[base].dropna().unique().tolist())
            print("  IDENTITY_CONF=" + " | ".join(f"{v}:{int((base & conf.eq(v)).sum())}" for v in vals))
            # Useful cumulative rules for common ordinal labels if present.
            for allowed_name, allowed in {
                "identity_not_LOW": [v for v in vals if str(v).upper() not in {"LOW", "LÅG"}],
                "identity_HIGH_ONLY": [v for v in vals if str(v).upper() in {"HIGH", "HÖG"}],
                "identity_HIGH_MEDIUM": [v for v in vals if str(v).upper() in {"HIGH", "HÖG", "MEDIUM", "MEDEL"}],
            }.items():
                if allowed:
                    candidates[allowed_name] = count_rule(df, base, conf.isin(allowed))

        ranked = sorted(
            ((name, n, n - frozen, abs(n - frozen)) for name, n in candidates.items()),
            key=lambda x: (x[3], x[0]),
        )
        print("  CLOSEST=" + " | ".join(f"{name}:{n}(delta={delta:+d})" for name, n, delta, _ in ranked[:8]))

        rows.append({
            "year": year,
            "frozen_n": frozen,
            "current_n": current,
            "excess": current - frozen,
            "status_counts": status_counts,
            "candidate_counts": candidates,
            "closest_rules": [
                {"rule": name, "n": n, "delta": delta, "abs_delta": ad}
                for name, n, delta, ad in ranked[:15]
            ],
        })

    # Search for a single candidate rule that exactly matches all five years.
    common_rules = set.intersection(*(set(r["candidate_counts"].keys()) for r in rows))
    exact_all = []
    scored = []
    for rule in sorted(common_rules):
        deltas = [r["candidate_counts"][rule] - r["frozen_n"] for r in rows]
        sae = int(sum(abs(d) for d in deltas))
        max_abs = int(max(abs(d) for d in deltas))
        scored.append((sae, max_abs, rule, deltas))
        if all(d == 0 for d in deltas):
            exact_all.append(rule)
    scored.sort()

    print("BEST_GLOBAL_RULES=" + " | ".join(
        f"{rule}:SAE={sae},MAX={mx},DELTAS={deltas}" for sae, mx, rule, deltas in scored[:10]
    ))
    print("EXACT_ALL_YEARS=" + (",".join(exact_all) if exact_all else "NONE"))

    payload = {
        "schema_version": "akerpuls-m4-target-census-diagnostic-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "history_sha256": sha256_file(p),
        "frozen_n": FROZEN_N,
        "years": rows,
        "exact_all_year_rules": exact_all,
        "best_global_rules": [
            {"rule": rule, "sum_abs_error": sae, "max_abs_error": mx, "deltas": deltas}
            for sae, mx, rule, deltas in scored[:20]
        ],
        "model_fit_executed": False,
        "prediction_2026_executed": False,
        "fusion_executed": False,
        "next": "REVIEW_TARGET_VALIDITY_RULE_BEFORE_PATCHING_REPRODUCTION_GATE",
    }

    out.mkdir(parents=True, exist_ok=False)
    (out / "M4_TARGET_CENSUS_DIAGNOSTIC_V1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (out / "M4_TARGET_CENSUS_DIAGNOSTIC_V1.csv").open("w", encoding="utf-8", newline="") as f:
        pd.DataFrame([
            {
                "year": r["year"], "frozen_n": r["frozen_n"], "current_n": r["current_n"],
                "excess": r["excess"],
                **{f"n__{k}": v for k, v in r["candidate_counts"].items()},
            }
            for r in rows
        ]).to_csv(f, index=False)

    print(f"STATUS={STATUS}")
    print("MODEL_FIT_EXECUTED=FALSE PREDICTION_2026_EXECUTED=FALSE FUSION_EXECUTED=FALSE")
    print("NEXT=REVIEW_TARGET_VALIDITY_RULE_BEFORE_PATCHING_REPRODUCTION_GATE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
