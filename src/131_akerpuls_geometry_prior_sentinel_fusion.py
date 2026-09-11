#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zero-PU fusion diagnostic: frozen visual labels + 2026 geometry-history prior.

This study does not tune any threshold or define a product rule. It joins the
independently produced rolling 2026 prior to the already frozen C3 and C5D blind
visual-review cases and asks whether history adds useful rank separation beyond
the existing Sentinel separation score.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, spearmanr

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerpuls_geometry_prior_sentinel_fusion_v0.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_field_id(value: Any) -> str:
    s = str(value).strip()
    parts = s.split("|")
    if len(parts) >= 3 and parts[0] == "2025":
        return "|".join(parts[1:])
    return s


def auc_rank(score: pd.Series, positive: pd.Series) -> tuple[float, int, int, float]:
    x = pd.to_numeric(score, errors="coerce")
    y = positive.astype(bool)
    valid = x.notna() & y.notna()
    x = x[valid]
    y = y[valid]
    pos = x[y].to_numpy(dtype=float)
    neg = x[~y].to_numpy(dtype=float)
    if len(pos) == 0 or len(neg) == 0:
        return float("nan"), len(pos), len(neg), float("nan")
    u = mannwhitneyu(pos, neg, alternative="two-sided")
    auc = float(u.statistic) / float(len(pos) * len(neg))
    return auc, len(pos), len(neg), float(u.pvalue)


def median_gap(score: pd.Series, positive: pd.Series) -> tuple[float, float, float]:
    x = pd.to_numeric(score, errors="coerce")
    y = positive.astype(bool)
    p = float(x[y].median()) if (y & x.notna()).any() else float("nan")
    n = float(x[~y].median()) if ((~y) & x.notna()).any() else float("nan")
    return p, n, p - n


def build_case_frame(key_path: Path, labels: list[str], source: str) -> pd.DataFrame:
    key = pd.read_csv(key_path, dtype=str)
    if len(key) != len(labels):
        raise RuntimeError(f"{source}: key rows {len(key)} != frozen labels {len(labels)}")
    if "blind_index" not in key.columns or "parent_field_id_2025" not in key.columns:
        raise RuntimeError(f"{source}: blind key lacks required columns")
    key["blind_index"] = pd.to_numeric(key["blind_index"], errors="raise").astype(int)
    key = key.sort_values("blind_index").reset_index(drop=True)
    expected = list(range(1, len(labels) + 1))
    if key["blind_index"].tolist() != expected:
        raise RuntimeError(f"{source}: blind indices are not 1..{len(labels)}")
    key["visual_label"] = labels
    key["source_set"] = source
    key["field_id_normalized"] = key["parent_field_id_2025"].map(normalize_field_id)
    for col in ("separation_ratio", "min_largest_component_fraction", "edge_support_count"):
        if col in key.columns:
            key[col] = pd.to_numeric(key[col], errors="coerce")
    return key


def select_analysis_set(cases: pd.DataFrame, name: str) -> pd.DataFrame:
    if name == "ALL_32":
        return cases.copy()
    if name == "C3_ALL":
        return cases[cases["source_set"] == "C3"].copy()
    if name == "C3_LOCKED_PASS":
        return cases[(cases["source_set"] == "C3") & (cases["hidden_group"] == "LOCKED_PASS_REPRESENTATIVE")].copy()
    if name == "C5D_ALL":
        return cases[cases["source_set"] == "C5D"].copy()
    if name == "C5D_HIGH_CONFIDENCE_CENSUS":
        return cases[(cases["source_set"] == "C5D") & (cases["hidden_group"] == "HIGH_CONFIDENCE_CENSUS")].copy()
    raise ValueError(name)


def metric_row(frame: pd.DataFrame, set_name: str, view_name: str, positives: list[str], score_name: str) -> dict[str, Any]:
    positive = frame["visual_label"].isin(positives)
    auc, npos, nneg, p = auc_rank(frame[score_name], positive)
    med_pos, med_neg, gap = median_gap(frame[score_name], positive)
    return {
        "analysis_set": set_name,
        "binary_view": view_name,
        "score": score_name,
        "n": int(len(frame)),
        "n_positive": int(npos),
        "n_negative": int(nneg),
        "auc_rank": auc,
        "mannwhitney_two_sided_p": p,
        "median_positive": med_pos,
        "median_negative": med_neg,
        "median_gap": gap,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--rolling-dir")
    ap.add_argument("--c3-key")
    ap.add_argument("--c5d-key")
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("Fusion study guards unexpectedly enable forbidden scope")

    rolling_dir = Path(args.rolling_dir or cfg["rolling_dir"])
    c3_key = Path(args.c3_key or cfg["c3_key"])
    c5d_key = Path(args.c5d_key or cfg["c5d_key"])
    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    prior_path = rolling_dir / cfg["prior_file"]
    for p in (prior_path, c3_key, c5d_key):
        if not p.exists():
            raise FileNotFoundError(p)

    prior = pd.read_csv(prior_path, dtype={"field_id": str, "municipality_code": str})
    required_prior = {"field_id", "prototype_p_strict_same_2026", "prototype_p_splitmerge_2026"}
    missing = sorted(required_prior - set(prior.columns))
    if missing:
        raise RuntimeError(f"Prior file missing columns: {missing}")
    if len(prior) != 128636:
        raise RuntimeError(f"Expected 128636 2025 prior rows, got {len(prior)}")
    if prior["field_id"].duplicated().any():
        raise RuntimeError("Prior field_id is not unique")
    prior["field_id_normalized"] = prior["field_id"].map(normalize_field_id)
    prior["prototype_p_strict_same_2026"] = pd.to_numeric(prior["prototype_p_strict_same_2026"], errors="raise")
    prior["prototype_p_splitmerge_2026"] = pd.to_numeric(prior["prototype_p_splitmerge_2026"], errors="raise")
    prior["one_minus_prototype_p_strict_same_2026"] = 1.0 - prior["prototype_p_strict_same_2026"]

    c3 = build_case_frame(c3_key, list(cfg["labels"]["C3"]), "C3")
    c5d = build_case_frame(c5d_key, list(cfg["labels"]["C5D"]), "C5D")
    cases = pd.concat([c3, c5d], ignore_index=True, sort=False)
    if len(cases) != 32:
        raise RuntimeError(f"Expected 32 frozen blind-review cases, got {len(cases)}")

    join_cols = [
        "field_id_normalized", "field_id", "municipality_code", "history_n", "strict_count",
        "strict_streak", "splitmerge_count", "strict_fraction", "history_category",
        "prototype_p_strict_same_2026", "prototype_p_splitmerge_2026",
        "one_minus_prototype_p_strict_same_2026",
    ]
    cases = cases.merge(prior[join_cols], on="field_id_normalized", how="left", validate="many_to_one")
    missing_prior = cases["prototype_p_splitmerge_2026"].isna()
    if missing_prior.any():
        miss = cases.loc[missing_prior, ["source_set", "blind_index", "parent_field_id_2025"]]
        raise RuntimeError("Failed to join rolling prior to blind cases:\n" + miss.to_string(index=False))

    ordinal_map = {str(k): int(v) for k, v in cfg["visual_ordinal"].items()}
    cases["visual_ordinal"] = cases["visual_label"].map(ordinal_map)
    cases["strict_visual_positive"] = cases["visual_label"].isin(cfg["binary_views"]["strict"])
    cases["liberal_visual_positive"] = cases["visual_label"].isin(cfg["binary_views"]["liberal"])

    score_names = [
        "prototype_p_splitmerge_2026",
        "one_minus_prototype_p_strict_same_2026",
        "separation_ratio",
    ]
    metrics: list[dict[str, Any]] = []
    spearman_rows: list[dict[str, Any]] = []
    for set_name in cfg["analysis_sets"]:
        frame = select_analysis_set(cases, set_name)
        for view_name, positives in cfg["binary_views"].items():
            for score_name in score_names:
                metrics.append(metric_row(frame, set_name, view_name, list(positives), score_name))
        for score_name in score_names:
            x = pd.to_numeric(frame[score_name], errors="coerce")
            ok = x.notna() & frame["visual_ordinal"].notna()
            if ok.sum() >= 3:
                rho, p = spearmanr(x[ok], frame.loc[ok, "visual_ordinal"])
            else:
                rho, p = float("nan"), float("nan")
            spearman_rows.append({
                "analysis_set": set_name,
                "score": score_name,
                "n": int(ok.sum()),
                "spearman_rho_visual_ordinal": float(rho),
                "two_sided_p": float(p),
            })

    metrics_df = pd.DataFrame(metrics)
    spearman_df = pd.DataFrame(spearman_rows)
    cases.to_csv(out / "fusion_cases_32.csv", index=False, encoding="utf-8-sig")
    metrics_df.to_csv(out / "fusion_rank_metrics.csv", index=False)
    spearman_df.to_csv(out / "fusion_spearman_metrics.csv", index=False)

    # Compact group medians, useful for reading the console without defining a new threshold.
    groups = (
        cases.groupby(["source_set", "hidden_group", "visual_label"], dropna=False)
        .agg(
            n=("blind_index", "size"),
            median_p_splitmerge=("prototype_p_splitmerge_2026", "median"),
            median_p_change=("one_minus_prototype_p_strict_same_2026", "median"),
            median_separation=("separation_ratio", "median"),
        )
        .reset_index()
    )
    groups.to_csv(out / "fusion_group_medians.csv", index=False)

    summary = {
        "schema_version": cfg["schema_version"],
        "status": "PASS",
        "cases": int(len(cases)),
        "c3_cases": int((cases["source_set"] == "C3").sum()),
        "c5d_cases": int((cases["source_set"] == "C5D").sum()),
        "prior_rows": int(len(prior)),
        "prior_join_missing": int(missing_prior.sum()),
        "thresholds_tuned": False,
        "new_split_rule_defined": False,
        "automatic_geometry_change": False,
        "product_prior_frozen": False,
        "sentinel_hub_pu_used": 0,
        "interpretation": cfg["interpretation"],
    }
    (out / "fusion_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def report(set_name: str, view: str, score: str, label: str) -> None:
        row = metrics_df[(metrics_df.analysis_set == set_name) & (metrics_df.binary_view == view) & (metrics_df.score == score)].iloc[0]
        print(
            f"{label} AUC={row.auc_rank:.3f} MED_POS={row.median_positive:.4f} "
            f"MED_NEG={row.median_negative:.4f} GAP={row.median_gap:+.4f} "
            f"N_POS={int(row.n_positive)} N_NEG={int(row.n_negative)} P={row.mannwhitney_two_sided_p:.4f}"
        )

    print("AKERPULS GEOMETRY PRIOR + SENTINEL FUSION DIAGNOSTIC")
    print(f"CASES={len(cases)} C3=20 C5D=12 PRIOR_JOIN_MISSING=0")
    report("ALL_32", "strict", "prototype_p_splitmerge_2026", "ALL32_STRICT_HISTORY_SPLITMERGE")
    report("ALL_32", "strict", "separation_ratio", "ALL32_STRICT_SENTINEL_SEPARATION")
    report("ALL_32", "liberal", "prototype_p_splitmerge_2026", "ALL32_LIBERAL_HISTORY_SPLITMERGE")
    report("ALL_32", "liberal", "separation_ratio", "ALL32_LIBERAL_SENTINEL_SEPARATION")
    report("C3_LOCKED_PASS", "liberal", "prototype_p_splitmerge_2026", "C3_LOCKED_PASS_LIBERAL_HISTORY")
    report("C3_LOCKED_PASS", "liberal", "separation_ratio", "C3_LOCKED_PASS_LIBERAL_SENTINEL")
    report("C5D_HIGH_CONFIDENCE_CENSUS", "strict", "prototype_p_splitmerge_2026", "C5D_HC_STRICT_HISTORY")
    report("C5D_HIGH_CONFIDENCE_CENSUS", "strict", "separation_ratio", "C5D_HC_STRICT_SENTINEL")
    print("THRESHOLDS_TUNED=FALSE")
    print("NEW_SPLIT_RULE_DEFINED=FALSE")
    print("PRODUCT_PRIOR_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("FUSION_DIAGNOSTIC_STATUS=PASS")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
