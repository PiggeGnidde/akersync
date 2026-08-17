#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — within-field TWI quintile response curves.

Purpose
-------
Follow up the first Lomma TWI↔NDVI association test with a more informative,
non-parametric response curve.  Instead of only low/middle/high TWI zones, each
field's buffered interior is split into five field-relative TWI quintiles.
For every field and date we calculate the median NDVI in Q1..Q5 and centre each
quintile on that field/date's own NDVI median.

This answers questions such as:
  * is the response approximately monotone with TWI?
  * are only the wettest/driest tails different?
  * is there a U-shape or threshold effect?
  * does the curve change sign through the season?

Inference
---------
The independent unit for population inference is the FIELD, not the pixel.
For each date and TWI quintile we therefore bootstrap fields to obtain a 95%
CI for the median within-field NDVI deviation, and run a two-sided sign test
against zero.  We also aggregate each field across dates first and repeat the
same field-level inference for an overall seasonal curve, avoiding pixel-level
pseudo-replication.

No new satellite data is downloaded. Existing Lomma NDVI GeoTIFFs and the
validated 10 m TWI raster are reused through helper functions from step 22.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from scipy.stats import binomtest

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"


def load_step22():
    path = ROOT / "src" / "22_satellite_lomma_twi_ndvi.py"
    spec = importlib.util.spec_from_file_location("akersync_sat_twi22", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bootstrap_median_ci(x: np.ndarray, n_boot: int, rng: np.random.Generator):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return np.nan, np.nan, np.nan
    med = float(np.median(x))
    if x.size == 1 or n_boot <= 0:
        return med, np.nan, np.nan
    # Field-level bootstrap. Chunk to keep memory modest for large n_boot.
    boot = np.empty(n_boot, dtype=float)
    chunk = 250
    done = 0
    while done < n_boot:
        m = min(chunk, n_boot - done)
        idx = rng.integers(0, x.size, size=(m, x.size))
        boot[done:done + m] = np.median(x[idx], axis=1)
        done += m
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return med, float(lo), float(hi)


def sign_test(x: np.ndarray):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    pos = int(np.sum(x > 0))
    neg = int(np.sum(x < 0))
    nz = pos + neg
    if nz == 0:
        return pos, neg, np.nan
    p = float(binomtest(pos, n=nz, p=0.5, alternative="two-sided").pvalue)
    return pos, neg, p


def infer_series(x: pd.Series, n_boot: int, rng: np.random.Generator) -> dict:
    a = pd.to_numeric(x, errors="coerce").to_numpy(dtype=float)
    a = a[np.isfinite(a)]
    med, lo, hi = bootstrap_median_ci(a, n_boot, rng)
    pos, neg, p = sign_test(a)
    return {
        "n_fields": int(a.size),
        "median": med,
        "ci95_low": lo,
        "ci95_high": hi,
        "positive_fields": pos,
        "negative_fields": neg,
        "positive_share_pct": (100.0 * pos / (pos + neg)) if (pos + neg) else np.nan,
        "sign_p_two_sided": p,
    }


def add_curve_shape(df: pd.DataFrame) -> pd.DataFrame:
    """Add simple descriptive shape metrics to one-row-per-date/overall tables."""
    out = df.copy()
    qcols = [f"q{i}_median_dev" for i in range(1, 6)]
    out["q5_minus_q1"] = out["q5_median_dev"] - out["q1_median_dev"]
    out["q5_minus_q3"] = out["q5_median_dev"] - out["q3_median_dev"]
    out["q1_minus_q3"] = out["q1_median_dev"] - out["q3_median_dev"]

    slopes = []
    u_curv = []
    for r in out.itertuples(index=False):
        y = np.array([getattr(r, c) for c in qcols], dtype=float)
        ok = np.isfinite(y)
        if ok.sum() >= 3:
            q = np.arange(1, 6, dtype=float)[ok]
            yy = y[ok]
            slopes.append(float(np.polyfit(q, yy, 1)[0]))
        else:
            slopes.append(np.nan)
        # Positive => tails above the middle; negative => tails below middle.
        if np.isfinite(y[[0, 2, 4]]).all():
            u_curv.append(float((y[0] + y[4]) / 2.0 - y[2]))
        else:
            u_curv.append(np.nan)
    out["linear_slope_per_quintile"] = slopes
    out["tail_mean_minus_q3"] = u_curv
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-07-14",
                    help="Default stops before visually observed harvest onset")
    ap.add_argument("--edge-buffer-m", type=float, default=10.0)
    ap.add_argument("--min-pixels", type=int, default=25)
    ap.add_argument("--min-zone-pixels", type=int, default=3)
    ap.add_argument("--min-coverage", type=float, default=70.0)
    ap.add_argument("--bootstrap", type=int, default=2000,
                    help="Field-level bootstrap replicates per date/quintile")
    ap.add_argument("--seed", type=int, default=230817)
    args = ap.parse_args()

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    if end < start:
        raise SystemExit("--end måste vara >= --start")

    s22 = load_step22()
    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    ndvi_files = s22.discover_ndvi(outdir, start, end)
    if len(ndvi_files) < 3:
        raise RuntimeError(
            f"Hittade bara {len(ndvi_files)} NDVI-TIFF:ar mellan {start.date()} och {end.date()}."
        )
    twi_path = s22.find_twi(cfg, outdir)

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    lomma_skiften = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    if lomma_skiften.empty:
        raise RuntimeError("Hittade inga Lomma-skiften")

    _, first_tif = ndvi_files[0]
    with rasterio.open(first_tif) as ref:
        ref_crs = ref.crs
        ref_transform = ref.transform
        width, height = ref.width, ref.height

    print("=" * 122)
    print("ÅkerSync · Satellite V1a · Lomma TWI quintile response curve")
    print("=" * 122)
    print(f"Skiften: {len(lomma_skiften):,}")
    print(f"NDVI-datum: {len(ndvi_files)} | {start.date()} — {end.date()}")
    print("Datum:", ", ".join(d.strftime("%Y-%m-%d") for d, _ in ndvi_files))
    print(f"Referensgrid: {width}×{height} | {ref_crs} | pixel {abs(ref_transform.a):.2f} m")
    print("TWI:", twi_path)
    print(f"Kantbuffer: {args.edge_buffer_m:g} m | bootstrap: {args.bootstrap:,}")
    print("TWI-zoner: Q1..Q5 = fältspecifika 20%-kvintiler")
    print("Inferens: skifte är oberoende enhet; inga pixel-p-värden.")
    print("Ingen ny satellitdata laddas ned.")

    print("\nLäser/alignar befintliga NDVI-raster …")
    dates: list[pd.Timestamp] = []
    ndvi_stack: list[np.ndarray] = []
    for i, (d, p) in enumerate(ndvi_files, 1):
        print(f"  [{i:2d}/{len(ndvi_files):2d}] {d.date()}  {p.name}")
        ndvi_stack.append(s22.read_to_reference(p, ref_crs, ref_transform, width, height))
        dates.append(d)

    print("Alignar validerad TWI till Sentinel-grid med nearest-neighbour …")
    twi = s22.twi_to_reference(twi_path, ref_crs, ref_transform, width, height)

    # Remove one Sentinel pixel from field edges in metric CRS before reprojection.
    work = lomma_skiften.copy()
    work["analysis_geometry"] = work.geometry.buffer(-args.edge_buffer_m)
    ok_geom = work.analysis_geometry.notna() & ~work.analysis_geometry.is_empty
    work = work.loc[ok_geom].copy()
    work = work.set_geometry("analysis_geometry").to_crs(ref_crs)

    rows: list[dict] = []
    field_count = 0
    print(f"\nBygger Q1–Q5-kurvor för {len(work):,} buffrade skiften …")

    for k, (_, r) in enumerate(work.iterrows(), 1):
        geom = r.geometry
        w = s22.raster_window(geom, ref_transform, width, height)
        if w is None:
            continue
        r0, c0 = int(w.row_off), int(w.col_off)
        hh, ww = int(w.height), int(w.width)
        tr = rasterio.windows.transform(w, ref_transform)
        inside = geometry_mask(
            [geom.__geo_interface__],
            out_shape=(hh, ww),
            transform=tr,
            invert=True,
            all_touched=False,
        )
        if int(inside.sum()) < args.min_pixels:
            continue

        tw = twi[r0:r0 + hh, c0:c0 + ww]
        tw_valid = inside & np.isfinite(tw)
        n_twi = int(tw_valid.sum())
        if n_twi < args.min_pixels:
            continue

        tw_vals = tw[tw_valid].astype(float)
        edges = np.percentile(tw_vals, [0, 20, 40, 60, 80, 100])
        # If the field has too little TWI variation for five meaningful bins, skip.
        if np.unique(np.round(edges, 8)).size < 6:
            continue

        zones = []
        for qi in range(5):
            if qi == 0:
                z = tw_valid & (tw >= edges[qi]) & (tw <= edges[qi + 1])
            else:
                z = tw_valid & (tw > edges[qi]) & (tw <= edges[qi + 1])
            zones.append(z)
        if min(int(z.sum()) for z in zones) < args.min_zone_pixels:
            continue

        any_date = False
        for d, ndvi_full in zip(dates, ndvi_stack):
            nd = ndvi_full[r0:r0 + hh, c0:c0 + ww]
            valid = tw_valid & np.isfinite(nd)
            n_valid = int(valid.sum())
            coverage = 100.0 * n_valid / max(1, n_twi)
            if n_valid < args.min_pixels or coverage < args.min_coverage:
                continue

            y_all = nd[valid].astype(float)
            field_med = float(np.median(y_all))
            q_meds = []
            q_ns = []
            valid_date = True
            for z in zones:
                zv = valid & z
                nz = int(zv.sum())
                if nz < args.min_zone_pixels:
                    valid_date = False
                    break
                q_ns.append(nz)
                q_meds.append(float(np.median(nd[zv].astype(float))))
            if not valid_date:
                continue

            any_date = True
            base = {
                "date": d.strftime("%Y-%m-%d"),
                "blockid": str(r.get("blockid", "")),
                "skiftesbeteckning": str(r.get("skiftesbeteckning", "")),
                "area_analysis_ha": round(float(geom.area / 10000.0), 4),
                "valid_pixels": n_valid,
                "coverage_pct": round(coverage, 2),
                "ndvi_field_median": round(field_med, 5),
                "twi_q20": round(float(edges[1]), 5),
                "twi_q40": round(float(edges[2]), 5),
                "twi_q60": round(float(edges[3]), 5),
                "twi_q80": round(float(edges[4]), 5),
            }
            for qi, (qm, qn) in enumerate(zip(q_meds, q_ns), 1):
                rows.append({
                    **base,
                    "twi_quintile": qi,
                    "zone_pixels": qn,
                    "ndvi_quintile_median": round(qm, 5),
                    "ndvi_dev_from_field_median": round(qm - field_med, 5),
                })
        if any_date:
            field_count += 1

        if k == 1 or k % 100 == 0 or k == len(work):
            print(f"\r  skifte {k:,}/{len(work):,} | giltiga skiften {field_count:,} | rader {len(rows):,}", end="", flush=True)
    print()

    fdq = pd.DataFrame(rows)
    if fdq.empty:
        raise RuntimeError("Inga giltiga skifte×datum×TWI-kvintil-rader")
    fdq["date"] = pd.to_datetime(fdq.date)

    rng = np.random.default_rng(args.seed)
    curve_rows: list[dict] = []
    print("\nBootstrappar fältnivåkurva per datum …")
    for d, gd in fdq.groupby("date", sort=True):
        rec: dict = {"date": pd.Timestamp(d)}
        for q in range(1, 6):
            x = gd.loc[gd.twi_quintile == q, "ndvi_dev_from_field_median"]
            st = infer_series(x, args.bootstrap, rng)
            rec[f"q{q}_n_fields"] = st["n_fields"]
            rec[f"q{q}_median_dev"] = st["median"]
            rec[f"q{q}_ci95_low"] = st["ci95_low"]
            rec[f"q{q}_ci95_high"] = st["ci95_high"]
            rec[f"q{q}_positive_share_pct"] = st["positive_share_pct"]
            rec[f"q{q}_sign_p"] = st["sign_p_two_sided"]
        curve_rows.append(rec)
    date_curve = add_curve_shape(pd.DataFrame(curve_rows))

    # First aggregate repeated dates within each field; then infer across fields.
    field_curve = (
        fdq.groupby(["blockid", "skiftesbeteckning", "twi_quintile"], as_index=False)
        .agg(
            n_dates=("date", "nunique"),
            area_analysis_ha=("area_analysis_ha", "first"),
            median_dev_across_dates=("ndvi_dev_from_field_median", "median"),
        )
    )

    overall_rec: dict = {"scope": "field_median_across_dates"}
    for q in range(1, 6):
        x = field_curve.loc[field_curve.twi_quintile == q, "median_dev_across_dates"]
        st = infer_series(x, args.bootstrap, rng)
        overall_rec[f"q{q}_n_fields"] = st["n_fields"]
        overall_rec[f"q{q}_median_dev"] = st["median"]
        overall_rec[f"q{q}_ci95_low"] = st["ci95_low"]
        overall_rec[f"q{q}_ci95_high"] = st["ci95_high"]
        overall_rec[f"q{q}_positive_share_pct"] = st["positive_share_pct"]
        overall_rec[f"q{q}_sign_p"] = st["sign_p_two_sided"]
    overall_curve = add_curve_shape(pd.DataFrame([overall_rec]))

    # Explicit Q5-Q1 and Q5-Q3 contrasts at FIELD level per date, with bootstrap/sign test.
    contrast_rows: list[dict] = []
    wide_fd = fdq.pivot_table(
        index=["date", "blockid", "skiftesbeteckning"],
        columns="twi_quintile",
        values="ndvi_dev_from_field_median",
        aggfunc="first",
    ).reset_index()
    for d, gd in wide_fd.groupby("date", sort=True):
        for name, a, b in [("q5_minus_q1", 5, 1), ("q5_minus_q3", 5, 3), ("q1_minus_q3", 1, 3)]:
            x = pd.to_numeric(gd[a], errors="coerce") - pd.to_numeric(gd[b], errors="coerce")
            st = infer_series(x, args.bootstrap, rng)
            contrast_rows.append({"date": pd.Timestamp(d), "contrast": name, **st})
    contrasts = pd.DataFrame(contrast_rows)

    stem = f"lomma_twi_response_curve_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    fdq_csv = outdir / f"{stem}_field_date_quintiles.csv"
    field_csv = outdir / f"{stem}_field_curve.csv"
    date_csv = outdir / f"{stem}_date_curve.csv"
    contrast_csv = outdir / f"{stem}_date_contrasts.csv"
    overall_csv = outdir / f"{stem}_overall_curve.csv"
    summary_txt = outdir / f"{stem}_summary.txt"

    fdq.to_csv(fdq_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    field_curve.to_csv(field_csv, index=False, encoding="utf-8-sig")
    date_curve.to_csv(date_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    contrasts.to_csv(contrast_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    overall_curve.to_csv(overall_csv, index=False, encoding="utf-8-sig")

    lines = [
        "ÅkerSync Satellite V1a — Lomma TWI quintile NDVI response curve",
        f"Interval: {start.date()} — {end.date()}",
        f"NDVI dates: {len(ndvi_files)}",
        f"Fields with >=1 valid curve: {field_count} / {len(lomma_skiften)}",
        f"Edge buffer: {args.edge_buffer_m:g} m",
        f"Min coverage/date: {args.min_coverage:.1f}%",
        f"Bootstrap replicates: {args.bootstrap}",
        "",
        "Each Q value below is median[NDVI quintile median - field/date NDVI median] across fields.",
        "95% CI is a field bootstrap. Sign p is two-sided H0: positive/negative field effects equally likely.",
        "",
        "PER DATE:",
    ]
    for r in date_curve.itertuples(index=False):
        vals = " ".join(f"Q{i} {getattr(r, f'q{i}_median_dev'):+.4f}" for i in range(1, 6))
        lines.append(
            f"  {pd.Timestamp(r.date).date()} | {vals} | Q5-Q1 {r.q5_minus_q1:+.4f} | slope {r.linear_slope_per_quintile:+.4f}"
        )

    o = overall_curve.iloc[0]
    lines += [
        "",
        "OVERALL FIELD-MEDIAN-ACROSS-DATES CURVE:",
        "  " + " ".join(f"Q{i} {o[f'q{i}_median_dev']:+.4f}" for i in range(1, 6)),
        f"  Q5-Q1 {o['q5_minus_q1']:+.4f} | Q5-Q3 {o['q5_minus_q3']:+.4f} | slope {o['linear_slope_per_quintile']:+.4f}",
        "",
        "CAUTION:",
        "  Association only. TWI is a topographic propensity, not drainage status or observed wetness.",
        "  2026 is one season; weather, crop, soil and management interactions are not yet separated.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 122)
    print("TWI QUINTILE RESPONSE CURVE KLAR")
    print("=" * 122)
    print(f"Skiften med >=1 giltig kurva: {field_count} / {len(lomma_skiften)}")
    print("\nPer datum · median NDVI-avvikelse inom skifte:")
    for r in date_curve.itertuples(index=False):
        vals = " | ".join(f"Q{i} {getattr(r, f'q{i}_median_dev'):+.4f}" for i in range(1, 6))
        print(
            f"  {pd.Timestamp(r.date).date()} | {vals} | Q5-Q1 {r.q5_minus_q1:+.4f}"
        )

    print("\nOverall · först median över datum inom varje skifte, sedan population över skiften:")
    print("  " + " | ".join(f"Q{i} {o[f'q{i}_median_dev']:+.4f}" for i in range(1, 6)))
    print(f"  Q5-Q1 {o['q5_minus_q1']:+.4f} | Q5-Q3 {o['q5_minus_q3']:+.4f} | slope {o['linear_slope_per_quintile']:+.4f}")

    print("\nQ5 signifikans per datum (bootstrap-CI + sign-test):")
    for r in date_curve.itertuples(index=False):
        print(
            f"  {pd.Timestamp(r.date).date()} | Q5 {r.q5_median_dev:+.4f} "
            f"CI95 [{r.q5_ci95_low:+.4f}, {r.q5_ci95_high:+.4f}] | "
            f"positiva {r.q5_positive_share_pct:5.1f}% | p={r.q5_sign_p:.4g}"
        )

    print("\nOutput:")
    for p in (fdq_csv, field_csv, date_csv, contrast_csv, overall_csv, summary_txt):
        print(" ", p)
    print("\nOBS: curve = inom-skifte association mellan TWI-kvintil och NDVI, inte kausal dräneringseffekt.")
    print("SATELLITE LOMMA TWI RESPONSE CURVE: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
