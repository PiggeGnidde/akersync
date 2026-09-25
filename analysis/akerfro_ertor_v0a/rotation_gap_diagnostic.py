#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · B-diagnostic: observed repeat gaps.

Uses only the already-built STOPPUNKT B clean positive field-year table.
It does not infer or freeze an agronomic rotation rule.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IN = ROOT / "data" / "derived" / "akerfro_ertor_v0a"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "rotation_gap_diagnostic"
DEFAULT_CONFIG = ROOT / "config" / "akerfro_ertor_v0a.json"


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_repeat_table(positives: pd.DataFrame) -> pd.DataFrame:
    required = {
        "history_year", "municipality", "current_field_id",
        "current_block_id", "current_skiftesbeteckning", "current_area_m2",
    }
    missing = sorted(required - set(positives.columns))
    if missing:
        raise ValueError(f"Positive table missing columns: {missing}")

    x = positives.copy()
    x["history_year"] = pd.to_numeric(x["history_year"], errors="raise").astype(int)
    x = x.sort_values(["current_field_id", "history_year"], kind="mergesort")

    counts = x.groupby("current_field_id").size()
    repeated_ids = counts[counts >= 2].index
    repeated = x[x["current_field_id"].isin(repeated_ids)].copy()

    rows = []
    for field_id, g in repeated.groupby("current_field_id", sort=True):
        years = sorted(g["history_year"].astype(int).tolist())
        if len(years) != 2:
            raise RuntimeError(
                f"{field_id}: expected exactly 2 clean CONSERVART years in current B result; got {years}"
            )
        meta = g.iloc[-1]
        rows.append({
            "current_field_id": field_id,
            "municipality": meta["municipality"],
            "current_block_id": meta["current_block_id"],
            "current_skiftesbeteckning": meta["current_skiftesbeteckning"],
            "current_area_m2": float(meta["current_area_m2"]),
            "first_conservart_year": years[0],
            "second_conservart_year": years[1],
            "gap_years": years[1] - years[0],
        })
    return pd.DataFrame(rows).sort_values(
        ["gap_years", "first_conservart_year", "current_field_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def gap_counts(repeats: pd.DataFrame) -> pd.DataFrame:
    if repeats.empty:
        return pd.DataFrame(columns=["gap_years", "n_fields", "pct_repeated_fields"])
    out = (
        repeats.groupby("gap_years").size().rename("n_fields").reset_index()
        .sort_values("gap_years", kind="mergesort")
    )
    out["pct_repeated_fields"] = 100.0 * out["n_fields"] / len(repeats)
    return out


def pair_counts(repeats: pd.DataFrame) -> pd.DataFrame:
    if repeats.empty:
        return pd.DataFrame(
            columns=["first_conservart_year", "second_conservart_year", "gap_years", "n_fields"]
        )
    return (
        repeats.groupby(
            ["first_conservart_year", "second_conservart_year", "gap_years"]
        ).size().rename("n_fields").reset_index()
        .sort_values(
            ["n_fields", "gap_years", "first_conservart_year"],
            ascending=[False, True, True],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )


def summarize(repeats: pd.DataFrame, gaps: pd.DataFrame, pairs: pd.DataFrame) -> dict:
    if repeats.empty:
        raise RuntimeError("No repeated clean CONSERVART fields found")
    mode_count = int(gaps["n_fields"].max())
    modal_gaps = gaps.loc[gaps["n_fields"] == mode_count, "gap_years"].astype(int).tolist()
    return {
        "schema_version": "akerfro-ertor-rotation-gap-diagnostic-v0a",
        "repeated_fields": int(len(repeats)),
        "min_gap_years": int(repeats["gap_years"].min()),
        "median_gap_years": float(repeats["gap_years"].median()),
        "mean_gap_years": float(repeats["gap_years"].mean()),
        "max_gap_years": int(repeats["gap_years"].max()),
        "modal_gap_years": modal_gaps,
        "modal_gap_field_count": mode_count,
        "distinct_year_pairs": int(len(pairs)),
        "interpretation_caution": (
            "Observed repeat gaps are descriptive only. The 2015-2025 window creates "
            "left/right censoring, and the 2017 Bjuv processor shock changes exposure. "
            "Do not freeze a rotation threshold from this distribution alone."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-root", default=str(DEFAULT_IN))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    input_root = Path(args.input_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = load_config(Path(args.config))

    positive_path = input_root / "pea_positive_field_years.parquet"
    if not positive_path.exists():
        raise FileNotFoundError(
            f"{positive_path} missing; run STOPPUNKT B first"
        )
    positives = pd.read_parquet(positive_path)

    repeats = build_repeat_table(positives)
    gaps = gap_counts(repeats)
    pairs = pair_counts(repeats)

    anchors = cfg.get("checkpoint_b_anchors") or {}
    if anchors:
        expected_repeated = int(anchors["fields_with_2plus_clean_conservart_years"])
        expected_max = int(anchors["max_clean_conservart_years_on_one_field"])
        if len(repeats) != expected_repeated:
            raise RuntimeError(
                f"B anchor mismatch: expected {expected_repeated} repeated fields; got {len(repeats)}"
            )
        if expected_max != 2:
            raise RuntimeError(
                f"Diagnostic currently expects B max recurrence == 2; config says {expected_max}"
            )

    repeats_path = out / "repeated_conservart_fields.csv"
    gaps_path = out / "rotation_gap_counts.csv"
    pairs_path = out / "rotation_year_pair_counts.csv"
    json_path = out / "rotation_gap_summary.json"

    repeats.to_csv(repeats_path, index=False, encoding="utf-8-sig")
    gaps.to_csv(gaps_path, index=False, encoding="utf-8-sig")
    pairs.to_csv(pairs_path, index=False, encoding="utf-8-sig")
    summary = summarize(repeats, gaps, pairs)
    summary["outputs"] = {
        "repeated_fields": str(repeats_path),
        "gap_counts": str(gaps_path),
        "year_pair_counts": str(pairs_path),
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("ÅkerFrö – Ärter MVP v0a · B ROTATION-GAP DIAGNOSTIC")
    print("=" * 78)
    print(f"Repeated clean CONSERVART fields: {len(repeats):,}")
    print(
        f"Gap years: min={summary['min_gap_years']} "
        f"median={summary['median_gap_years']:.1f} "
        f"mean={summary['mean_gap_years']:.2f} "
        f"max={summary['max_gap_years']}"
    )
    print(
        "Modal gap(s): "
        + ", ".join(map(str, summary["modal_gap_years"]))
        + f" years ({summary['modal_gap_field_count']} fields)"
    )

    print("\nGAP DISTRIBUTION")
    print(gaps.to_string(index=False, formatters={
        "pct_repeated_fields": lambda v: f"{v:.1f}%"
    }))

    print("\nTOP YEAR PAIRS")
    print(pairs.head(20).to_string(index=False))

    print("\nCAUTION")
    print(summary["interpretation_caution"])
    print(f"\nRepeated fields: {repeats_path}")
    print(f"Gap counts: {gaps_path}")
    print(f"Year-pair counts: {pairs_path}")
    print(f"Summary: {json_path}")
    print("=" * 78)
    print("B ROTATION-GAP DIAGNOSTIC: PASS")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
