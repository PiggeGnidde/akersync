#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C10 transparent operational layer.

C10 adds two explicit operational components to the existing C8 product:
  - AreaFit 0..100
  - BjuvProximity 0..100

and their fixed-policy combination:
  AreaLogistik = 0.55*AreaFit + 0.45*BjuvProximity

C10 does NOT:
  - modify frozen ÄrtMatch,
  - redefine C8 A/B/C/D classes,
  - fit weights or curve shapes to historical pea labels,
  - claim an agronomic probability.

Ranking is lexicographic:
  C8 class -> AreaLogistik -> ÄrtMatch -> field id.
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

DEFAULT_CONFIG = ROOT / "config" / "akerfro_ertor_c10.json"
DEFAULT_C8 = ROOT / "data" / "derived" / "akerfro_ertor_v0a" / "artkandidat_v0a_fields.parquet"
DEFAULT_C9 = ROOT / "work" / "akerfro_ertor_v0a" / "area_logistics_c9" / "artkandidat_c9_area_logistics_fields.parquet"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerfro_ertor_v0a"
DEFAULT_WORK = ROOT / "work" / "akerfro_ertor_v0a" / "operational_c10"

CLASS_RANK = {
    "A_STRONG_CANDIDATE": 1,
    "B_PHYSICAL_CANDIDATE": 2,
    "C_ROTATION_CAUTION": 3,
    "D_NOT_HIGH_PHYSICAL_MATCH": 4,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def piecewise_score(
    values: pd.Series,
    knots: list[float],
    scores: list[float],
    above_last: float,
) -> pd.Series:
    """Deterministic piecewise-linear score with constant tails."""
    if len(knots) != len(scores) or len(knots) < 2:
        raise ValueError("knots and scores must have equal length >=2")
    k = np.asarray(knots, dtype=float)
    s = np.asarray(scores, dtype=float)
    if not np.all(np.diff(k) > 0):
        raise ValueError("knots must be strictly increasing")
    if np.any((s < 0) | (s > 100)):
        raise ValueError("scores must stay within 0..100")

    x = pd.to_numeric(values, errors="coerce").to_numpy(float)
    out = np.full(len(x), np.nan, dtype=float)
    valid = np.isfinite(x)
    if valid.any():
        xv = x[valid]
        vals = np.interp(xv, k, s, left=s[0], right=float(above_last))
        out[valid] = np.clip(vals, 0.0, 100.0)
    return pd.Series(out, index=values.index)


def operational_band(score: pd.Series, cfg: dict[str, Any]) -> pd.Series:
    x = pd.to_numeric(score, errors="coerce")
    high = float(cfg["operational_bands"]["HIGH"])
    medium = float(cfg["operational_bands"]["MEDIUM"])
    out = pd.Series("UNKNOWN", index=score.index, dtype="string")
    out.loc[x.notna() & x.lt(medium)] = "LOW"
    out.loc[x.ge(medium) & x.lt(high)] = "MEDIUM"
    out.loc[x.ge(high)] = "HIGH"
    return out


def build_product(c8: pd.DataFrame, c9: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    if len(c8) != 128636 or len(c9) != 128636:
        raise RuntimeError("C10 requires 128,636 rows in both C8 and C9 products")
    if c8["current_field_id"].duplicated().any() or c9["current_field_id"].duplicated().any():
        raise RuntimeError("C10 inputs must be one row per current field")

    logistics_cols = [
        "current_field_id", "field_area_ha", "field_lat", "field_lon",
        "distance_bjuv_km", "area_band", "distance_band",
    ]
    missing = [c for c in logistics_cols if c not in c9.columns]
    if missing:
        raise RuntimeError(f"C9 sidecar missing columns: {missing}")

    out = c8.merge(
        c9[logistics_cols],
        on="current_field_id",
        how="left",
        validate="one_to_one",
    )

    acfg = cfg["area_fit"]
    out["area_fit_score"] = piecewise_score(
        out["field_area_ha"],
        [float(x) for x in acfg["knots_ha"]],
        [float(x) for x in acfg["scores"]],
        float(acfg["above_last_knot_score"]),
    )

    dcfg = cfg["bjuv_proximity"]
    out["bjuv_proximity_score"] = piecewise_score(
        out["distance_bjuv_km"],
        [float(x) for x in dcfg["knots_km"]],
        [float(x) for x in dcfg["scores"]],
        float(dcfg["above_last_knot_score"]),
    )

    weights = cfg["area_logistics"]["weights"]
    wa = float(weights["area_fit"])
    wd = float(weights["bjuv_proximity"])
    if abs((wa + wd) - 1.0) > 1e-12:
        raise RuntimeError("C10 AreaLogistik weights must sum to 1")

    valid = out["area_fit_score"].notna() & out["bjuv_proximity_score"].notna()
    out["area_logistics_score"] = np.nan
    out.loc[valid, "area_logistics_score"] = (
        wa * out.loc[valid, "area_fit_score"]
        + wd * out.loc[valid, "bjuv_proximity_score"]
    )
    out["area_logistics_band"] = operational_band(out["area_logistics_score"], cfg)

    out["c10_class_rank"] = out["artkandidat_class"].map(CLASS_RANK)
    if out["c10_class_rank"].isna().any():
        unknown = sorted(out.loc[out["c10_class_rank"].isna(), "artkandidat_class"].astype(str).unique())
        raise RuntimeError(f"Unknown C8 candidate classes in C10: {unknown}")
    out["c10_class_rank"] = out["c10_class_rank"].astype(int)

    ordered = out.sort_values(
        ["c10_class_rank", "area_logistics_score", "artmatch_score", "current_field_id"],
        ascending=[True, False, False, True],
        na_position="last",
        kind="mergesort",
    ).copy()
    ordered["operational_priority_rank"] = np.arange(1, len(ordered) + 1)
    rank_lookup = ordered.set_index("current_field_id")["operational_priority_rank"]
    out["operational_priority_rank"] = out["current_field_id"].map(rank_lookup).astype(int)

    out["c10_explanation"] = (
        "ÄrtMatch=" + out["artmatch_score"].round(1).astype("string")
        + "; class=" + out["artkandidat_class"].astype("string")
        + "; area=" + out["field_area_ha"].round(1).astype("string") + " ha"
        + " -> AreaFit=" + out["area_fit_score"].round(1).astype("string")
        + "; Bjuv=" + out["distance_bjuv_km"].round(1).astype("string") + " km"
        + " -> Proximity=" + out["bjuv_proximity_score"].round(1).astype("string")
        + "; AreaLogistik=" + out["area_logistics_score"].round(1).astype("string")
    )
    return out


def logistics_decile_diagnostic(frame: pd.DataFrame) -> pd.DataFrame:
    q = frame[
        frame["artkandidat_class"].isin(["A_STRONG_CANDIDATE", "B_PHYSICAL_CANDIDATE"])
        & frame["area_logistics_score"].notna()
    ].copy()
    q["logistics_decile"] = pd.qcut(
        q["area_logistics_score"],
        q=10,
        labels=False,
        duplicates="drop",
    ) + 1
    overall = float(q["is_positive"].mean())
    rows = []
    for d, g in q.groupby("logistics_decile", sort=True):
        rate = float(g["is_positive"].mean())
        rows.append({
            "logistics_decile": int(d),
            "n_fields": int(len(g)),
            "n_historical_positive": int(g["is_positive"].sum()),
            "historical_positive_rate_pct": 100.0 * rate,
            "enrichment_vs_AB": rate / overall if overall > 0 else np.nan,
            "score_min": float(g["area_logistics_score"].min()),
            "score_median": float(g["area_logistics_score"].median()),
            "score_max": float(g["area_logistics_score"].max()),
        })
    return pd.DataFrame(rows)


def class_band_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby(["artkandidat_class", "area_logistics_band"], dropna=False, as_index=False)
        .agg(
            n_fields=("current_field_id", "size"),
            area_logistics_mean=("area_logistics_score", "mean"),
            artmatch_mean=("artmatch_score", "mean"),
            historical_positive=("is_positive", "sum"),
        )
        .sort_values(["artkandidat_class", "area_logistics_band"], kind="mergesort")
        .reset_index(drop=True)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--c8", default=str(DEFAULT_C8))
    ap.add_argument("--c9", default=str(DEFAULT_C9))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    c8_path = Path(args.c8)
    c9_path = Path(args.c9)
    for p in [c8_path, c9_path]:
        if not p.exists():
            raise FileNotFoundError(f"C10 prerequisite missing: {p}")

    c8 = pd.read_parquet(c8_path)
    c9 = pd.read_parquet(c9_path)
    product = build_product(c8, c9, cfg)
    deciles = logistics_decile_diagnostic(product)
    class_bands = class_band_summary(product)

    out = Path(args.out)
    work = Path(args.work)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    pq = out / "artkandidat_v0a_operational_fields.parquet"
    csv = out / "artkandidat_v0a_operational_fields.csv"
    top = out / "artkandidat_v0a_operational_top1000.csv"
    p_deciles = work / "area_logistics_decile_diagnostic.csv"
    p_bands = work / "class_by_operational_band.csv"

    product.to_parquet(pq, index=False)
    product.to_csv(csv, index=False, encoding="utf-8-sig")
    product.sort_values(
        ["operational_priority_rank"],
        kind="mergesort",
    ).head(1000).to_csv(top, index=False, encoding="utf-8-sig")
    deciles.to_csv(p_deciles, index=False, encoding="utf-8-sig")
    class_bands.to_csv(p_bands, index=False, encoding="utf-8-sig")

    class_counts = product["artkandidat_class"].value_counts().to_dict()
    band_counts = product["area_logistics_band"].value_counts(dropna=False).to_dict()
    report = {
        "schema_version": "akerfro-ertor-operational-c10-v0a-candidate",
        "candidate_year": int(cfg["candidate_year"]),
        "population_fields": int(len(product)),
        "artmatch_frozen_read_only": True,
        "c8_classes_unchanged": True,
        "policy": cfg,
        "class_counts": {str(k): int(v) for k, v in class_counts.items()},
        "operational_band_counts": {str(k): int(v) for k, v in band_counts.items()},
        "semantics": (
            "C10 operational layer exposes physical match, rotation/predecessor class, "
            "AreaFit, BjuvProximity and AreaLogistik separately. It does not produce "
            "a probability of pea success or contract award."
        ),
        "post_construction_diagnostic_only": {
            "area_logistics_decile_enrichment": (
                "reported only as a sanity check; C10 v0a curves and weights must not be retuned "
                "from this diagnostic in the same analysis"
            )
        },
        "excluded": [
            "road routing / harvest travel time",
            "contract availability",
            "irrigation and water-restriction risk",
            "farmer identity / machinery / management",
            "observed 2026 crop",
        ],
        "outputs": {
            "field_product_parquet": str(pq),
            "field_product_csv": str(csv),
            "top1000": str(top),
            "logistics_decile_diagnostic": str(p_deciles),
            "class_by_operational_band": str(p_bands),
        },
    }
    summary = work / "c10_summary.json"
    summary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 128)
    print("ÅkerFrö – Ärter MVP v0a · C10 TRANSPARENT OPERATIONAL LAYER")
    print("=" * 128)
    print(f"Fields: {len(product):,} · ÄrtMatch frozen/read-only · C8 classes unchanged")
    print(
        "AreaLogistik = "
        f"{100*cfg['area_logistics']['weights']['area_fit']:.0f}% AreaFit + "
        f"{100*cfg['area_logistics']['weights']['bjuv_proximity']:.0f}% BjuvProximity "
        "(fixed policy; not label-optimized)"
    )

    print("\nCOMPONENT POLICY")
    print("  AreaFit: broad high plateau 5-12 ha; soft decline outside")
    print("  BjuvProximity: monotone decline with straight-line distance; no hard 60-km veto")

    print("\nC8 CLASS COUNTS (MUST REMAIN UNCHANGED)")
    print(product["artkandidat_class"].value_counts().to_string())

    print("\nOPERATIONAL BAND COUNTS")
    print(product["area_logistics_band"].value_counts(dropna=False).to_string())

    print("\nPOST-CONSTRUCTION SANITY CHECK · A/B LOGISTICS DECILES")
    print(deciles.to_string(index=False, formatters={
        "historical_positive_rate_pct": lambda v: f"{v:.3f}%",
        "enrichment_vs_AB": lambda v: f"{v:.2f}x",
        "score_min": lambda v: f"{v:.1f}",
        "score_median": lambda v: f"{v:.1f}",
        "score_max": lambda v: f"{v:.1f}",
    }))

    print("\nTOP 30 OPERATIONAL PRIORITY")
    show = [
        "operational_priority_rank", "current_field_id", "municipality",
        "artkandidat_class", "artmatch_score", "crop_2025_name",
        "rotation_status", "predecessor_prior",
        "field_area_ha", "area_fit_score",
        "distance_bjuv_km", "bjuv_proximity_score",
        "area_logistics_score", "area_logistics_band",
    ]
    top30 = product.sort_values("operational_priority_rank").head(30)
    print(top30[show].to_string(index=False, formatters={
        "artmatch_score": lambda v: f"{v:.2f}",
        "field_area_ha": lambda v: f"{v:.2f}",
        "area_fit_score": lambda v: f"{v:.1f}",
        "distance_bjuv_km": lambda v: f"{v:.1f}",
        "bjuv_proximity_score": lambda v: f"{v:.1f}",
        "area_logistics_score": lambda v: f"{v:.1f}",
    }))

    print("\nGUARDRAILS")
    for g in cfg["guardrails"]:
        print("  - " + g)

    print(f"\nOperational product: {pq}")
    print(f"Top 1000: {top}")
    print(f"Decile diagnostic: {p_deciles}")
    print(f"Summary: {summary}")
    print("=" * 128)
    print("C10 TRANSPARENT OPERATIONAL LAYER: PASS")
    print("=" * 128)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
