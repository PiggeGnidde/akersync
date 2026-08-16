#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geometry V1a crop contrast: compare extreme shape within matched size bands.

Purpose
-------
Test whether very awkward field geometry is associated with different 2025 crop
choices / land use. This is an exploratory validation analysis, not a
machineability score.

Primary comparison (default):
- keep fields 1.0–5.0 ha
- rank ONLY by rectangularity within that size band
- export bottom/top 100 and 500
- attach raw 2025 crop code and a crop-name reference from the supplied 2026
  Jordbruksverket crop-code list

Why size-band first?
A huge irregular field can still allow long machine runs. Restricting the
primary comparison to a narrow area band avoids mixing the effect of field size
with the effect of shape. Sensitivity summaries are also produced for 1–2,
2–5, 5–20 and 20+ ha.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


PASTURE_NON_ARABLE = {52, 53, 54, 55, 56, 61, 89, 90, 95}
BUFFER_ENVIRONMENTAL = {60, 66, 77, 81, 82, 318}
NON_AG_OTHER = {83, 86, 314}


def code_int(v):
    if pd.isna(v):
        return np.nan
    try:
        return int(float(str(v).strip()))
    except Exception:
        return np.nan


def land_use_group(code):
    if pd.isna(code):
        return "unknown"
    c = int(code)
    if c in PASTURE_NON_ARABLE:
        return "pasture_non_arable"
    if c in BUFFER_ENVIRONMENTAL:
        return "buffer_fallow_environment"
    if c in NON_AG_OTHER:
        return "non_ag_other"
    return "arable_or_specialty_crop"


def attach_labels(df: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["crop_code_2025"] = x["crop_code"].map(code_int)
    r = ref.copy()
    r["crop_code_2025"] = pd.to_numeric(r["crop_code"], errors="coerce")
    r = r.dropna(subset=["crop_code_2025"]).copy()
    r["crop_code_2025"] = r["crop_code_2025"].astype(int)
    r = r[["crop_code_2025", "crop_name_reference_2026"]].drop_duplicates("crop_code_2025")
    x = x.merge(r, on="crop_code_2025", how="left", validate="many_to_one")
    x["land_use_group"] = x["crop_code_2025"].map(land_use_group)
    x["crop_label_match"] = np.where(x["crop_name_reference_2026"].notna(), "matched_to_2026_reference", "no_reference_match")
    return x


def rank_band(df: pd.DataFrame, low: float, high: float | None) -> pd.DataFrame:
    mask = df["area_ha"].ge(low)
    if high is not None:
        mask &= df["area_ha"].le(high)
    z = df[mask].copy()
    z = z[z["rectangularity"].notna()].copy()
    z["rect_rank_ascending"] = z["rectangularity"].rank(method="first", ascending=True).astype(int)
    z["rect_rank_descending"] = z["rectangularity"].rank(method="first", ascending=False).astype(int)
    z["rect_percentile_within_band"] = z["rectangularity"].rank(method="average", pct=True)
    return z


def subset_with_rank(z: pd.DataFrame, n: int, best: bool) -> pd.DataFrame:
    if best:
        out = z.sort_values(["rectangularity", "area_ha", "erl_proxy_m"], ascending=[False, False, False]).head(n).copy()
    else:
        out = z.sort_values(["rectangularity", "area_ha", "erl_proxy_m"], ascending=[True, True, True]).head(n).copy()
    out.insert(0, "selection_rank", range(1, len(out) + 1))
    return out


def crop_mix(rows: list[dict], label: str, df: pd.DataFrame):
    total = len(df)
    if total == 0:
        return
    for (code, name, group), g in df.groupby(["crop_code_2025", "crop_name_reference_2026", "land_use_group"], dropna=False):
        rows.append({
            "selection": label,
            "n_fields": total,
            "crop_code_2025": code,
            "crop_name_reference_2026": name,
            "land_use_group": group,
            "count": len(g),
            "share_pct": 100.0 * len(g) / total,
            "area_ha_sum": float(g["area_ha"].sum()),
        })


def group_mix(rows: list[dict], label: str, df: pd.DataFrame):
    total = len(df)
    if total == 0:
        return
    for group, g in df.groupby("land_use_group", dropna=False):
        rows.append({
            "selection": label,
            "n_fields": total,
            "land_use_group": group,
            "count": len(g),
            "share_pct": 100.0 * len(g) / total,
            "area_ha_sum": float(g["area_ha"].sum()),
        })


def band_summary(df: pd.DataFrame, bands):
    rows = []
    for label, low, high in bands:
        z = rank_band(df, low, high)
        if len(z) == 0:
            continue
        k = min(500, max(1, int(round(0.10 * len(z)))))
        worst = subset_with_rank(z, k, best=False)
        best = subset_with_rank(z, k, best=True)
        for side, s in [("worst_rect", worst), ("best_rect", best)]:
            groups = s["land_use_group"].value_counts(normalize=True)
            rows.append({
                "area_band": label,
                "n_in_band": len(z),
                "selection": side,
                "n_selected": len(s),
                "rect_median": float(s["rectangularity"].median()),
                "area_median_ha": float(s["area_ha"].median()),
                "erl_median_m": float(s["erl_proxy_m"].median()),
                "pasture_non_arable_pct": 100.0 * float(groups.get("pasture_non_arable", 0.0)),
                "buffer_fallow_environment_pct": 100.0 * float(groups.get("buffer_fallow_environment", 0.0)),
                "non_ag_other_pct": 100.0 * float(groups.get("non_ag_other", 0.0)),
                "arable_or_specialty_crop_pct": 100.0 * float(groups.get("arable_or_specialty_crop", 0.0)),
            })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geometry-csv", default="data/derived/geometry_v1a_skiften.csv")
    ap.add_argument("--crop-reference", default="data/reference/grodkoder_2026_reference.csv")
    ap.add_argument("--min-area", type=float, default=1.0)
    ap.add_argument("--max-area", type=float, default=5.0)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    geom_path = root / args.geometry_csv
    ref_path = root / args.crop_reference
    outdir = root / "data" / "derived"
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(geom_path, dtype={"blockid": str, "skiftesbeteckning": str, "crop_code": str})
    ref = pd.read_csv(ref_path)
    for c in ["area_ha", "rectangularity", "convexity", "erl_proxy_m", "mbr_aspect_ratio", "perimeter_per_ha_m", "hole_count"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["geometry_valid"].fillna(False).astype(bool) & df["area_ha"].gt(0) & df["rectangularity"].notna()].copy()
    df = attach_labels(df, ref)

    primary = rank_band(df, args.min_area, args.max_area)
    if len(primary) < 100:
        raise RuntimeError(f"För få skiften i primärbandet {args.min_area:g}–{args.max_area:g} ha: {len(primary)}")

    outputs = {}
    for n in (100, 500):
        k = min(n, len(primary))
        worst = subset_with_rank(primary, k, best=False)
        best = subset_with_rank(primary, k, best=True)
        wp = outdir / f"geometry_crop_worst_{n}_{args.min_area:g}to{args.max_area:g}ha.csv"
        bp = outdir / f"geometry_crop_best_{n}_{args.min_area:g}to{args.max_area:g}ha.csv"
        worst.to_csv(wp, index=False, encoding="utf-8-sig")
        best.to_csv(bp, index=False, encoding="utf-8-sig")
        outputs[f"worst{n}"] = worst
        outputs[f"best{n}"] = best

    ranked_path = outdir / f"geometry_crop_ranked_{args.min_area:g}to{args.max_area:g}ha.csv"
    primary.sort_values("rectangularity").to_csv(ranked_path, index=False, encoding="utf-8-sig")

    crop_rows = []
    group_rows = []
    crop_mix(crop_rows, "baseline_size_band", primary)
    group_mix(group_rows, "baseline_size_band", primary)
    for key, data in outputs.items():
        crop_mix(crop_rows, key, data)
        group_mix(group_rows, key, data)
    crop_mix_df = pd.DataFrame(crop_rows)
    group_mix_df = pd.DataFrame(group_rows)
    crop_mix_path = outdir / "geometry_crop_mix_extremes.csv"
    group_mix_path = outdir / "geometry_landuse_group_mix_extremes.csv"
    crop_mix_df.to_csv(crop_mix_path, index=False, encoding="utf-8-sig")
    group_mix_df.to_csv(group_mix_path, index=False, encoding="utf-8-sig")

    bands = [("1-2 ha", 1.0, 2.0), ("2-5 ha", 2.0, 5.0), ("5-20 ha", 5.0, 20.0), ("20+ ha", 20.0, None)]
    sensitivity = band_summary(df, bands)
    sensitivity_path = outdir / "geometry_crop_sizeband_sensitivity.csv"
    sensitivity.to_csv(sensitivity_path, index=False, encoding="utf-8-sig")

    w100 = outputs["worst100"]
    b100 = outputs["best100"]
    def pct(d, group):
        return 100.0 * float((d["land_use_group"] == group).mean()) if len(d) else 0.0

    print("=" * 112)
    print("ÅkerSync · Geometry × 2025 grödkod · size-matched revealed-preference test")
    print("=" * 112)
    print(f"Primär population: {args.min_area:g}–{args.max_area:g} ha: {len(primary):,} skiften")
    print("Rankning: ENDAST rectangularity inom samma storleksband — ingen maskinbarhets-score.")
    print("Grödkod = rå kod från 2025-skiften. Grödnamen matchas mot bifogad 2026-lista som referens.")
    print()
    print("Bottom 100 vs Top 100 inom samma storleksband:")
    print(f"  Rect median:              {w100.rectangularity.median():.3f}  vs  {b100.rectangularity.median():.3f}")
    print(f"  Area median ha:           {w100.area_ha.median():.2f}  vs  {b100.area_ha.median():.2f}")
    print(f"  ERL median m:             {w100.erl_proxy_m.median():.1f}  vs  {b100.erl_proxy_m.median():.1f}")
    print(f"  Bete ej åker %:           {pct(w100,'pasture_non_arable'):.1f}  vs  {pct(b100,'pasture_non_arable'):.1f}")
    print(f"  Skydd/träda/miljö %:      {pct(w100,'buffer_fallow_environment'):.1f}  vs  {pct(b100,'buffer_fallow_environment'):.1f}")
    print(f"  Odling/specialgröda %:    {pct(w100,'arable_or_specialty_crop'):.1f}  vs  {pct(b100,'arable_or_specialty_crop'):.1f}")
    print()
    print("10 värsta, med 2025 grödkod:")
    for i, r in enumerate(w100.head(10).itertuples(index=False), 1):
        name = r.crop_name_reference_2026 if isinstance(r.crop_name_reference_2026, str) else "[saknar referensnamn]"
        print(f"{i:2d}. {r.kommun:14s} {r.area_ha:5.2f} ha  rect={r.rectangularity:6.3f}  ERL={r.erl_proxy_m:6.1f} m  kod={r.crop_code_2025!s:>4s}  {name}")
    print()
    print("Output:")
    for n in (100, 500):
        print(" ", outdir / f"geometry_crop_worst_{n}_{args.min_area:g}to{args.max_area:g}ha.csv")
        print(" ", outdir / f"geometry_crop_best_{n}_{args.min_area:g}to{args.max_area:g}ha.csv")
    print(" ", crop_mix_path)
    print(" ", group_mix_path)
    print(" ", sensitivity_path)
    print(" ", ranked_path)
    print()
    print("Tolkning: detta testar om markanvändningen redan avslöjar att dålig geometri är besvärlig. Det är inte en ny score.")


if __name__ == "__main__":
    main()
