#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C8 ÄrtKandidat.

Transparent product-facing candidate classes for candidate year 2026.

Inputs:
  - frozen ÄrtMatch v0a field score (READ ONLY)
  - C7 rotation eligibility scenarios
  - C7 t-1 matched predecessor enrichment
  - frozen ÅkerMinne 2025 dominant crop/status for current predecessor

No new ML is fitted. No frozen ÄrtMatch artifact is modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.build_history import (
    load_config as load_base_config,
    load_frozen_summary,
    municipality_dirs,
)
from analysis.akerfro_ertor_v0a.crop_groups import normalize_crop_name

DEFAULT_BASE_CONFIG = ROOT / "config" / "akerfro_ertor_v0a.json"
DEFAULT_C8_CONFIG = ROOT / "config" / "akerfro_ertor_c8.json"
DEFAULT_AKERMINNE_ROOT = ROOT.parent / "AkerSync-Minne"
DEFAULT_ARTMATCH = ROOT / "data" / "derived" / "akerfro_ertor_v0a" / "artmatch_v0a_fields.parquet"
DEFAULT_C7 = ROOT / "work" / "akerfro_ertor_v0a" / "rotation_predecessor_c7"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerfro_ertor_v0a"

CLASS_ORDER = [
    "A_STRONG_CANDIDATE",
    "B_PHYSICAL_CANDIDATE",
    "C_ROTATION_CAUTION",
    "D_NOT_HIGH_PHYSICAL_MATCH",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def current_crop_2025(summary: pd.DataFrame) -> pd.DataFrame:
    q = summary[summary["history_year"].eq(2025)][[
        "current_field_id",
        "dominant_crop_name",
        "status",
        "is_clean",
        "akerfro_group",
    ]].copy()
    if q["current_field_id"].duplicated().any():
        raise RuntimeError("Duplicate current_field_id in 2025 ÅkerMinne summary")
    q = q.rename(columns={
        "dominant_crop_name": "crop_2025_name",
        "status": "crop_2025_status",
        "is_clean": "crop_2025_is_clean",
        "akerfro_group": "crop_2025_akerfro_group",
    })
    q["crop_2025_key"] = q["crop_2025_name"].map(normalize_crop_name).astype("string")
    return q


def predecessor_policy(
    enrichment: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    required = {
        "crop_key", "crop_name", "positive_count",
        "positive_pct", "control_pct", "enrichment_ratio",
    }
    missing = required - set(enrichment.columns)
    if missing:
        raise RuntimeError(f"C7 lag-1 enrichment missing columns: {sorted(missing)}")

    pcfg = cfg["predecessor"]
    min_events = int(pcfg["min_positive_events"])
    pos_thr = float(pcfg["positive_min_enrichment"])
    neg_thr = float(pcfg["negative_max_enrichment"])

    p = enrichment[list(required)].copy()
    p["crop_key"] = p["crop_key"].astype("string")
    p["positive_count"] = pd.to_numeric(p["positive_count"], errors="coerce").fillna(0).astype(int)
    p["enrichment_ratio"] = pd.to_numeric(p["enrichment_ratio"], errors="coerce")

    reliable = p["positive_count"].ge(min_events) & p["enrichment_ratio"].notna()
    p["predecessor_prior"] = "LOW_SUPPORT"
    p.loc[
        reliable & p["enrichment_ratio"].ge(pos_thr),
        "predecessor_prior"
    ] = "POSITIVE"
    p.loc[
        reliable
        & p["enrichment_ratio"].gt(neg_thr)
        & p["enrichment_ratio"].lt(pos_thr),
        "predecessor_prior"
    ] = "NEUTRAL"
    p.loc[
        reliable & p["enrichment_ratio"].le(neg_thr),
        "predecessor_prior"
    ] = "NEGATIVE"
    return p


def rotation_status(frame: pd.DataFrame, gap: int) -> pd.Series:
    target = frame[f"eligible_target_any_component_{gap}y"].fillna(False).astype(bool)
    any_pea = frame[f"eligible_any_pea_clean_{gap}y"].fillna(False).astype(bool)
    pea_faba = frame[f"eligible_pea_or_faba_clean_{gap}y"].fillna(False).astype(bool)

    out = pd.Series("ROTATION_OK", index=frame.index, dtype="string")
    out.loc[target & any_pea & ~pea_faba] = "CAUTION_RECENT_FABA"
    out.loc[target & ~any_pea] = "CAUTION_RECENT_OTHER_PEA"
    out.loc[~target] = "CAUTION_RECENT_CONSERVART"
    return out


def build_candidate(
    artmatch: pd.DataFrame,
    rotation: pd.DataFrame,
    crop2025: pd.DataFrame,
    pred_policy: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if len(artmatch) != 128636 or len(rotation) != 128636 or len(crop2025) != 128636:
        raise RuntimeError(
            "C8 population anchor requires 128,636 rows in ÄrtMatch, C7 rotation and ÅkerMinne 2025"
        )

    keep_rot = [
        "current_field_id", "municipality", "candidate_year",
        "last_conservart_clean_year", "last_conservart_any_component_year",
        "last_other_pea_clean_year", "last_faba_bean_clean_year",
        "last_any_pea_clean_year", "last_pea_or_faba_clean_year",
    ]
    gap = int(cfg["rotation_gap_years"])
    keep_rot += [
        f"eligible_target_clean_{gap}y",
        f"eligible_target_any_component_{gap}y",
        f"eligible_any_pea_clean_{gap}y",
        f"eligible_pea_or_faba_clean_{gap}y",
    ]
    keep_rot = [c for c in keep_rot if c in rotation.columns]

    out = artmatch.merge(
        rotation[keep_rot],
        on="current_field_id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_c7"),
    )
    out = out.merge(
        crop2025,
        on="current_field_id",
        how="left",
        validate="one_to_one",
    )

    pred_keep = [
        "crop_key", "crop_name", "positive_count",
        "positive_pct", "control_pct", "enrichment_ratio", "predecessor_prior",
    ]
    out = out.merge(
        pred_policy[pred_keep],
        left_on="crop_2025_key",
        right_on="crop_key",
        how="left",
        validate="many_to_one",
    )
    out = out.drop(columns=["crop_key"], errors="ignore")
    out = out.rename(columns={
        "crop_name": "predecessor_reference_crop_name",
        "positive_count": "predecessor_positive_count",
        "positive_pct": "predecessor_positive_pct",
        "control_pct": "predecessor_control_pct",
        "enrichment_ratio": "predecessor_enrichment_ratio",
    })

    out["predecessor_prior"] = out["predecessor_prior"].fillna("UNKNOWN").astype("string")
    out.loc[
        ~out["crop_2025_is_clean"].fillna(False).astype(bool),
        "predecessor_prior"
    ] = "UNKNOWN_NONCLEAN_2025"

    out["rotation_status"] = rotation_status(out, gap)
    out["rotation_ok"] = out["rotation_status"].eq("ROTATION_OK")

    scored = pd.to_numeric(out["artmatch_score"], errors="coerce")
    q = float(cfg["artmatch_high_quantile"])
    threshold = float(scored.dropna().quantile(q))
    out["artmatch_high_threshold"] = threshold
    out["artmatch_high"] = scored.ge(threshold) & out["artmatch_status"].ne("INSUFFICIENT_CORE")

    cls = pd.Series("D_NOT_HIGH_PHYSICAL_MATCH", index=out.index, dtype="string")
    high = out["artmatch_high"]
    caution = high & ~out["rotation_ok"]
    ok = high & out["rotation_ok"]
    positive_pred = out["predecessor_prior"].eq("POSITIVE")

    cls.loc[caution] = "C_ROTATION_CAUTION"
    cls.loc[ok] = "B_PHYSICAL_CANDIDATE"
    cls.loc[ok & positive_pred] = "A_STRONG_CANDIDATE"
    out["artkandidat_class"] = cls

    out["artkandidat_rank"] = out["artkandidat_class"].map({
        "A_STRONG_CANDIDATE": 1,
        "B_PHYSICAL_CANDIDATE": 2,
        "C_ROTATION_CAUTION": 3,
        "D_NOT_HIGH_PHYSICAL_MATCH": 4,
    }).astype(int)

    out["artkandidat_reason"] = ""
    out.loc[out["artkandidat_class"].eq("A_STRONG_CANDIDATE"), "artkandidat_reason"] = (
        "high ÄrtMatch; observed rotation OK; positive historical t-1 predecessor prior"
    )
    out.loc[out["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE"), "artkandidat_reason"] = (
        "high ÄrtMatch; observed rotation OK; no positive t-1 predecessor prior required"
    )
    out.loc[out["artkandidat_class"].eq("C_ROTATION_CAUTION"), "artkandidat_reason"] = (
        "high ÄrtMatch; recent observed pea/faba history triggers rotation caution"
    )
    d_missing = out["artkandidat_class"].eq("D_NOT_HIGH_PHYSICAL_MATCH") & scored.isna()
    d_low = out["artkandidat_class"].eq("D_NOT_HIGH_PHYSICAL_MATCH") & scored.notna()
    out.loc[d_missing, "artkandidat_reason"] = "ÄrtMatch unavailable because core physical data are insufficient"
    out.loc[d_low, "artkandidat_reason"] = "ÄrtMatch below transparent top-20-percent MVP threshold"

    meta = {
        "artmatch_high_quantile": q,
        "artmatch_high_threshold_score": threshold,
        "scored_fields": int(scored.notna().sum()),
        "high_artmatch_fields": int(out["artmatch_high"].sum()),
    }
    return out, meta


def class_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cls in CLASS_ORDER:
        g = frame[frame["artkandidat_class"].eq(cls)]
        x = pd.to_numeric(g["artmatch_score"], errors="coerce")
        rows.append({
            "artkandidat_class": cls,
            "n_fields": int(len(g)),
            "pct_all_fields": 100.0 * len(g) / len(frame),
            "artmatch_mean": float(x.mean()) if x.notna().any() else np.nan,
            "artmatch_median": float(x.median()) if x.notna().any() else np.nan,
            "rotation_ok_pct": 100.0 * float(g["rotation_ok"].mean()) if len(g) else np.nan,
            "positive_predecessor_pct": (
                100.0 * float(g["predecessor_prior"].eq("POSITIVE").mean())
                if len(g) else np.nan
            ),
        })
    return pd.DataFrame(rows)


def predecessor_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby(
            ["predecessor_prior", "crop_2025_name"],
            dropna=False,
            as_index=False,
        )
        .agg(
            n_fields=("current_field_id", "size"),
            mean_artmatch=("artmatch_score", "mean"),
            n_A=("artkandidat_class", lambda s: int((s == "A_STRONG_CANDIDATE").sum())),
            n_B=("artkandidat_class", lambda s: int((s == "B_PHYSICAL_CANDIDATE").sum())),
            n_C=("artkandidat_class", lambda s: int((s == "C_ROTATION_CAUTION").sum())),
        )
        .sort_values(["n_fields", "crop_2025_name"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", default=str(DEFAULT_BASE_CONFIG))
    ap.add_argument("--c8-config", default=str(DEFAULT_C8_CONFIG))
    ap.add_argument("--akerminne-root", default=str(DEFAULT_AKERMINNE_ROOT))
    ap.add_argument("--artmatch", default=str(DEFAULT_ARTMATCH))
    ap.add_argument("--c7-root", default=str(DEFAULT_C7))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    base_cfg = load_base_config(Path(args.base_config))
    cfg = load_json(Path(args.c8_config))
    candidate_year = int(cfg["candidate_year"])

    artmatch_path = Path(args.artmatch)
    rotation_path = Path(args.c7_root) / f"rotation_eligibility_{candidate_year}.parquet"
    enrichment_path = Path(args.c7_root) / "predecessor_lag1_enrichment.csv"
    for p in [artmatch_path, rotation_path, enrichment_path]:
        if not p.exists():
            raise FileNotFoundError(f"C8 prerequisite missing: {p}")

    artmatch = pd.read_parquet(artmatch_path)
    rotation = pd.read_parquet(rotation_path)
    enrichment = pd.read_csv(enrichment_path)

    dirs = municipality_dirs(Path(args.akerminne_root), base_cfg)
    summary = load_frozen_summary(dirs, base_cfg)
    crop2025 = current_crop_2025(summary)

    pred_policy = predecessor_policy(enrichment, cfg)
    candidate, meta = build_candidate(artmatch, rotation, crop2025, pred_policy, cfg)
    classes = class_summary(candidate)
    pred_summary = predecessor_summary(candidate)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "work" / "akerfro_ertor_v0a" / "artkandidat_c8"
    work.mkdir(parents=True, exist_ok=True)

    fields_path = out / "artkandidat_v0a_fields.parquet"
    csv_path = out / "artkandidat_v0a_fields.csv"
    top_path = out / "artkandidat_v0a_top_candidates.csv"
    class_path = work / "artkandidat_class_summary.csv"
    pred_policy_path = work / "predecessor_policy.csv"
    pred_summary_path = work / "predecessor_field_summary.csv"

    candidate.to_parquet(fields_path, index=False)
    candidate.to_csv(csv_path, index=False, encoding="utf-8-sig")
    candidate.sort_values(
        ["artkandidat_rank", "artmatch_score", "predecessor_enrichment_ratio"],
        ascending=[True, False, False],
        na_position="last",
        kind="mergesort",
    ).head(1000).to_csv(top_path, index=False, encoding="utf-8-sig")
    classes.to_csv(class_path, index=False, encoding="utf-8-sig")
    pred_policy.to_csv(pred_policy_path, index=False, encoding="utf-8-sig")
    pred_summary.to_csv(pred_summary_path, index=False, encoding="utf-8-sig")

    report = {
        "schema_version": "akerfro-ertor-artkandidat-c8-v0a-candidate",
        "candidate_year": candidate_year,
        "population_fields": int(len(candidate)),
        "artmatch_frozen_read_only": True,
        "policy": cfg,
        "derived_thresholds": meta,
        "class_counts": {
            str(k): int(v)
            for k, v in candidate["artkandidat_class"].value_counts().items()
        },
        "rotation_status_counts": {
            str(k): int(v)
            for k, v in candidate["rotation_status"].value_counts().items()
        },
        "predecessor_prior_counts": {
            str(k): int(v)
            for k, v in candidate["predecessor_prior"].value_counts().items()
        },
        "semantics": (
            "MVP candidate prioritization for where processing peas could plausibly be placed in 2026. "
            "A/B/C/D are transparent screening classes, not agronomic probabilities and not contract predictions."
        ),
        "excluded": [
            "processor distance/logistics",
            "contract availability",
            "irrigation and water restriction risk",
            "farm-level machinery/management",
            "2026 observed crop",
        ],
        "outputs": {
            "fields_parquet": str(fields_path),
            "fields_csv": str(csv_path),
            "top1000": str(top_path),
            "class_summary": str(class_path),
            "predecessor_policy": str(pred_policy_path),
            "predecessor_field_summary": str(pred_summary_path),
        },
    }
    summary_path = work / "artkandidat_c8_summary.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 126)
    print("ÅkerFrö – Ärter MVP v0a · C8 ÄRTKANDIDAT")
    print("=" * 126)
    print(f"Candidate year: {candidate_year} · fields: {len(candidate):,}")
    print("ÄrtMatch v0a: FROZEN / READ-ONLY")
    print(
        f"High ÄrtMatch = top {100*(1-meta['artmatch_high_quantile']):.0f}% of scored fields "
        f"=> threshold {meta['artmatch_high_threshold_score']:.2f}"
    )
    print(f"High-ÄrtMatch fields: {meta['high_artmatch_fields']:,}")

    print("\nÄRTKANDIDAT CLASSES")
    print(classes.to_string(index=False, formatters={
        "pct_all_fields": lambda v: f"{v:.2f}%",
        "artmatch_mean": lambda v: "NA" if pd.isna(v) else f"{v:.2f}",
        "artmatch_median": lambda v: "NA" if pd.isna(v) else f"{v:.2f}",
        "rotation_ok_pct": lambda v: f"{v:.2f}%",
        "positive_predecessor_pct": lambda v: f"{v:.2f}%",
    }))

    print("\nROTATION STATUS")
    print(candidate["rotation_status"].value_counts().to_string())

    print("\nT-1 PREDECESSOR POLICY FROM C7")
    show_policy = pred_policy[
        pred_policy["predecessor_prior"].isin(["POSITIVE", "NEGATIVE"])
    ].sort_values(
        ["predecessor_prior", "enrichment_ratio", "positive_count"],
        ascending=[True, False, False],
        kind="mergesort",
    )
    print(show_policy[[
        "crop_name", "positive_count", "positive_pct", "control_pct",
        "enrichment_ratio", "predecessor_prior"
    ]].to_string(index=False, formatters={
        "positive_pct": lambda v: f"{v:.2f}%",
        "control_pct": lambda v: f"{v:.2f}%",
        "enrichment_ratio": lambda v: f"{v:.2f}x",
    }))

    print("\nTOP 30 A-CANDIDATES")
    show = [
        "current_field_id", "municipality", "artmatch_score",
        "crop_2025_name", "predecessor_enrichment_ratio",
        "rotation_status", "last_conservart_any_component_year",
        "last_other_pea_clean_year", "last_faba_bean_clean_year",
    ]
    top_a = candidate[candidate["artkandidat_class"].eq("A_STRONG_CANDIDATE")].sort_values(
        ["artmatch_score", "predecessor_enrichment_ratio"],
        ascending=[False, False],
        na_position="last",
        kind="mergesort",
    ).head(30)
    print(top_a[show].to_string(index=False, formatters={
        "artmatch_score": lambda v: f"{v:.2f}",
        "predecessor_enrichment_ratio": lambda v: "NA" if pd.isna(v) else f"{v:.2f}x",
    }))

    print("\nEXCLUDED FROM C8")
    print("  processor/logistics · contracts · irrigation/water risk · farm management · 2026 observed crop")
    print("\nGUARDRAIL")
    for g in cfg["guardrails"]:
        print("  - " + g)

    print(f"\nField product: {fields_path}")
    print(f"Top candidates: {top_path}")
    print(f"Summary: {summary_path}")
    print("=" * 126)
    print("C8 ÄRTKANDIDAT: PASS")
    print("=" * 126)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
