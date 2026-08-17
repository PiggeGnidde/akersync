#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — controlled historical TWI↔NDVI experiment.

Purpose
-------
Run the first controlled multi-year test of the ÅkerPass water-response idea on
three weather-contrasting years selected independently from SMHI observations.
Default selection is read from step 25:
  dry/hot, middle, wet/cool.

For each selected year the script:
  1) reads the four preflight-selected Sentinel-2 dates (early Apr, late May,
     late Jun, early Jul),
  2) downloads/reuses cloud-masked Sentinel-2 NDVI through the already proven
     openEO workflow from step 20,
  3) samples the SAME fixed 2025 Lomma skifte geometries and the validated 10 m
     TWI raster,
  4) buffers field edges by 10 m,
  5) splits each field into its own TWI quintiles Q1..Q5,
  6) centres quintile NDVI on that field/date median,
  7) aggregates first at field level and only then across fields,
  8) reports Q1..Q5, Q5-Q1 and linear quintile slope by year/window and by year.

Inference uses fields as independent units. Bootstrap confidence intervals and
sign tests are descriptive population checks, not pixel-level pseudo-replication.

Important historical geometry caveat
------------------------------------
The 2025 skifte polygons are used as fixed physical sampling footprints for all
historical years. This measures what happened at the same physical places, but
it does NOT assert that the administrative field boundaries or crop were the
same in 2018/2023/etc. Historical boundary/crop controls are a later refinement.
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
from shapely.geometry import box

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"


def load_module(filename: str, name: str):
    path = ROOT / "src" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def median_or_nan(x) -> float:
    a = pd.to_numeric(pd.Series(x), errors="coerce").to_numpy(dtype=float)
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else np.nan


def slope5(vals) -> float:
    y = np.asarray(vals, dtype=float)
    ok = np.isfinite(y)
    if ok.sum() < 3:
        return np.nan
    x = np.arange(1, 6, dtype=float)[ok]
    return float(np.polyfit(x, y[ok], 1)[0])


def read_plan(outdir: Path, year_start: int, year_end: int, explicit_years: list[int] | None):
    preflight = outdir / f"lomma_multiyear_preflight_{year_start}_{year_end}_dates.csv"
    recfile = outdir / f"lomma_weather_{year_start}_{year_end}_recommended_years.csv"
    weatherfile = outdir / f"lomma_weather_{year_start}_{year_end}_year_classification.csv"

    if not preflight.exists():
        raise FileNotFoundError(f"Saknar preflight: {preflight}")
    if not weatherfile.exists():
        raise FileNotFoundError(f"Saknar väderklassning: {weatherfile}")

    pf = pd.read_csv(preflight)
    pf["selected_date"] = pd.to_datetime(pf.selected_date, errors="coerce")
    weather = pd.read_csv(weatherfile)

    if explicit_years:
        years = list(dict.fromkeys(int(y) for y in explicit_years))
        role_map = {y: "explicit" for y in years}
    else:
        if not recfile.exists():
            raise FileNotFoundError(f"Saknar rekommenderade år: {recfile}")
        rec = pd.read_csv(recfile)
        if rec.empty or not {"role", "year"}.issubset(rec.columns):
            raise RuntimeError("recommended_years.csv är tom eller saknar role/year")
        years = [int(y) for y in rec.year.tolist()]
        role_map = {int(r.year): str(r.role) for r in rec.itertuples(index=False)}

    plan = pf[pf.year.astype(int).isin(years)].copy()
    plan = plan[plan.selected_date.notna()].copy()
    if plan.empty:
        raise RuntimeError("Inga preflight-datum för valda år")
    plan["year"] = plan.year.astype(int)
    plan["weather_role"] = plan.year.map(role_map).fillna("selected")

    expected = plan.groupby("year").window.nunique()
    missing = [y for y in years if int(expected.get(y, 0)) < 4]
    if missing:
        raise RuntimeError(f"Valda år saknar fyra preflight-fönster: {missing}")

    cols = [
        "year", "weather_role", "window", "selected_date", "item_count",
        "min_cloud_pct", "mean_cloud_pct", "max_cloud_pct", "good_catalog_cloud",
    ]
    for c in cols:
        if c not in plan.columns:
            plan[c] = np.nan
    plan = plan[cols].sort_values(["year", "selected_date"]).reset_index(drop=True)

    wcols = [
        "year", "weather_class", "hydroclimate_score",
        "precip_jun01_jul15_mm", "tmean_jun01_jul15_c",
        "sentinel_good_windows",
    ]
    have = [c for c in wcols if c in weather.columns]
    wx = weather[have].copy()
    plan = plan.merge(wx, on="year", how="left")
    return plan, years


def build_lomma(cfg: dict):
    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lb = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    ls = skiften[skiften.blockid.astype(str).isin(lb.blockid.astype(str))].copy()
    if lb.empty or ls.empty:
        raise RuntimeError("Hittade inte Lomma-block/skiften")
    return ls


def make_spatial(lomma_skiften: gpd.GeoDataFrame):
    minx, miny, maxx, maxy = lomma_skiften.total_bounds
    bbox3006 = gpd.GeoSeries([box(minx - 100, miny - 100, maxx + 100, maxy + 100)], crs=3006)
    west, south, east, north = [float(x) for x in bbox3006.to_crs(4326).total_bounds]
    return {
        "west": west, "south": south, "east": east, "north": north, "crs": "EPSG:4326"
    }


def download_selected(plan: pd.DataFrame, outdir: Path, spatial: dict, ts20):
    import openeo

    con = openeo.connect(ts20.BACKEND).authenticate_oidc()
    print("openEO auth: OK")
    paths = {}
    for i, r in enumerate(plan.itertuples(index=False), 1):
        d = pd.Timestamp(r.selected_date)
        date0 = d.strftime("%Y-%m-%d")
        stamp = d.strftime("%Y%m%d")
        tif = outdir / f"lomma_ndvi_{stamp}.tif"
        print(
            f"\n[{i:2d}/{len(plan):2d}] {int(r.year)} {r.weather_role:8s} | "
            f"{r.window:15s} | {date0} | katalog max-moln {float(r.max_cloud_pct):.1f}%"
        )
        ts20.download_ndvi(con, spatial, date0, tif)
        if not tif.exists() or tif.stat().st_size < 10_000:
            raise RuntimeError(f"NDVI-TIFF saknas/är för liten efter jobb: {tif}")
        paths[(int(r.year), str(r.window), date0)] = tif
    return paths


def analyse(
    plan: pd.DataFrame,
    tif_paths: dict,
    lomma_skiften: gpd.GeoDataFrame,
    twi_path: Path,
    s22,
    edge_buffer_m: float,
    min_pixels: int,
    min_zone_pixels: int,
    min_coverage: float,
):
    first = next(iter(tif_paths.values()))
    with rasterio.open(first) as ref:
        ref_crs = ref.crs
        ref_transform = ref.transform
        width, height = ref.width, ref.height

    print(f"\nReferensgrid: {width}×{height} | {ref_crs} | pixel {abs(ref_transform.a):.2f} m")
    print("Läser/alignar historiska NDVI-raster …")

    ndvi_by_key = {}
    for r in plan.itertuples(index=False):
        date0 = pd.Timestamp(r.selected_date).strftime("%Y-%m-%d")
        key = (int(r.year), str(r.window), date0)
        p = tif_paths[key]
        print(f"  {int(r.year)} {r.window:15s} {date0} | {p.name}")
        ndvi_by_key[key] = s22.read_to_reference(p, ref_crs, ref_transform, width, height)

    print("Alignar validerad TWI till Sentinel-grid med nearest-neighbour …")
    twi = s22.twi_to_reference(twi_path, ref_crs, ref_transform, width, height)

    work = lomma_skiften.copy()
    work["analysis_geometry"] = work.geometry.buffer(-edge_buffer_m)
    ok = work.analysis_geometry.notna() & ~work.analysis_geometry.is_empty
    work = work.loc[ok].copy()
    work = work.set_geometry("analysis_geometry").to_crs(ref_crs)

    rows = []
    print(f"Analyserar {len(work):,} buffrade 2025-skiften som fasta historiska footprints …")

    plan_records = list(plan.itertuples(index=False))
    for k, (_, r) in enumerate(work.iterrows(), 1):
        geom = r.geometry
        w = s22.raster_window(geom, ref_transform, width, height)
        if w is None:
            continue
        r0, c0 = int(w.row_off), int(w.col_off)
        hh, ww = int(w.height), int(w.width)
        tr = rasterio.windows.transform(w, ref_transform)
        inside = geometry_mask(
            [geom.__geo_interface__], out_shape=(hh, ww), transform=tr,
            invert=True, all_touched=False,
        )
        if int(inside.sum()) < min_pixels:
            continue

        tw = twi[r0:r0 + hh, c0:c0 + ww]
        tw_valid = inside & np.isfinite(tw)
        if int(tw_valid.sum()) < min_pixels:
            continue
        tv = tw[tw_valid].astype(float)
        edges = np.percentile(tv, [0, 20, 40, 60, 80, 100])
        if np.unique(np.round(edges, 8)).size < 6:
            continue

        zones = []
        for qi in range(5):
            if qi == 0:
                z = tw_valid & (tw >= edges[qi]) & (tw <= edges[qi + 1])
            else:
                z = tw_valid & (tw > edges[qi]) & (tw <= edges[qi + 1])
            zones.append(z)
        if min(int(z.sum()) for z in zones) < min_zone_pixels:
            continue

        for pr in plan_records:
            date0 = pd.Timestamp(pr.selected_date).strftime("%Y-%m-%d")
            key = (int(pr.year), str(pr.window), date0)
            nd = ndvi_by_key[key][r0:r0 + hh, c0:c0 + ww]
            valid = tw_valid & np.isfinite(nd)
            n_valid = int(valid.sum())
            coverage = 100.0 * n_valid / max(1, int(tw_valid.sum()))
            if n_valid < min_pixels or coverage < min_coverage:
                continue

            field_med = float(np.median(nd[valid]))
            rec = {
                "year": int(pr.year),
                "weather_role": str(pr.weather_role),
                "weather_class": getattr(pr, "weather_class", ""),
                "hydroclimate_score": getattr(pr, "hydroclimate_score", np.nan),
                "precip_jun01_jul15_mm": getattr(pr, "precip_jun01_jul15_mm", np.nan),
                "tmean_jun01_jul15_c": getattr(pr, "tmean_jun01_jul15_c", np.nan),
                "window": str(pr.window),
                "date": date0,
                "blockid": str(r.get("blockid", "")),
                "skiftesbeteckning": str(r.get("skiftesbeteckning", "")),
                "area_analysis_ha": round(float(geom.area / 10000.0), 4),
                "valid_pixels": n_valid,
                "coverage_pct": round(float(coverage), 2),
                "ndvi_field_median": round(field_med, 4),
            }

            qdev = []
            qraw = []
            zone_ok = True
            for qi, z in enumerate(zones, 1):
                vz = valid & z
                if int(vz.sum()) < min_zone_pixels:
                    zone_ok = False
                    break
                med = float(np.median(nd[vz]))
                dev = med - field_med
                rec[f"q{qi}_ndvi_median"] = round(med, 4)
                rec[f"q{qi}_median_dev"] = round(dev, 4)
                rec[f"q{qi}_pixels"] = int(vz.sum())
                qraw.append(med)
                qdev.append(dev)
            if not zone_ok:
                continue

            rec["q5_minus_q1"] = round(qdev[4] - qdev[0], 4)
            rec["q5_minus_q3"] = round(qdev[4] - qdev[2], 4)
            rec["linear_slope_per_quintile"] = round(slope5(qdev), 5)
            rows.append(rec)

        if k == 1 or k % 100 == 0 or k == len(work):
            print(f"\r  skifte {k:,}/{len(work):,} | giltiga field-date {len(rows):,}", end="", flush=True)
    print()

    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("Historiska TWI-kurvan gav inga giltiga field-date-rader")
    return out


def aggregate_results(field_date: pd.DataFrame, s23, n_boot: int, seed: int):
    rng = np.random.default_rng(seed)
    qcols = [f"q{i}_median_dev" for i in range(1, 6)]

    # One field contributes once to each year/window population curve.
    date_rows = []
    for (year, role, window, date), g in field_date.groupby(
        ["year", "weather_role", "window", "date"], sort=True
    ):
        rec = {
            "year": int(year), "weather_role": role, "window": window, "date": date,
            "fields": int(g[["blockid", "skiftesbeteckning"]].drop_duplicates().shape[0]),
            "median_coverage_pct": float(g.coverage_pct.median()),
        }
        for q in qcols:
            rec[q] = median_or_nan(g[q])
        rec["q5_minus_q1"] = rec["q5_median_dev"] - rec["q1_median_dev"]
        rec["q5_minus_q3"] = rec["q5_median_dev"] - rec["q3_median_dev"]
        rec["linear_slope_per_quintile"] = slope5([rec[q] for q in qcols])

        inf = s23.infer_series(g["q5_minus_q1"], n_boot, rng)
        rec["q5q1_ci95_low"] = inf["ci95_low"]
        rec["q5q1_ci95_high"] = inf["ci95_high"]
        rec["q5q1_positive_share_pct"] = inf["positive_share_pct"]
        rec["q5q1_sign_p_two_sided"] = inf["sign_p_two_sided"]
        date_rows.append(rec)
    by_window = pd.DataFrame(date_rows).sort_values(["year", "date"]).reset_index(drop=True)

    # Aggregate dates within each field/year first. This prevents a field with
    # four windows from acting as four independent population observations.
    agg_map = {q: "median" for q in qcols}
    agg_map.update({
        "q5_minus_q1": "median", "q5_minus_q3": "median",
        "linear_slope_per_quintile": "median", "area_analysis_ha": "first",
    })
    field_year = (
        field_date.groupby(
            ["year", "weather_role", "blockid", "skiftesbeteckning"], as_index=False
        ).agg(agg_map)
    )

    year_rows = []
    for (year, role), g in field_year.groupby(["year", "weather_role"], sort=True):
        rec = {
            "year": int(year), "weather_role": role,
            "fields": int(g[["blockid", "skiftesbeteckning"]].drop_duplicates().shape[0]),
        }
        wx = field_date[field_date.year.eq(year)].iloc[0]
        for c in ["weather_class", "hydroclimate_score", "precip_jun01_jul15_mm", "tmean_jun01_jul15_c"]:
            rec[c] = wx.get(c, np.nan)
        for q in qcols:
            rec[q] = median_or_nan(g[q])
        rec["q5_minus_q1"] = median_or_nan(g["q5_minus_q1"])
        rec["q5_minus_q3"] = median_or_nan(g["q5_minus_q3"])
        rec["linear_slope_per_quintile"] = median_or_nan(g["linear_slope_per_quintile"])
        inf = s23.infer_series(g["q5_minus_q1"], n_boot, rng)
        rec["q5q1_ci95_low"] = inf["ci95_low"]
        rec["q5q1_ci95_high"] = inf["ci95_high"]
        rec["q5q1_positive_share_pct"] = inf["positive_share_pct"]
        rec["q5q1_sign_p_two_sided"] = inf["sign_p_two_sided"]
        year_rows.append(rec)
    by_year = pd.DataFrame(year_rows).sort_values("year").reset_index(drop=True)
    return by_window, field_year, by_year


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--year-start", type=int, default=2018)
    ap.add_argument("--year-end", type=int, default=2026)
    ap.add_argument("--years", type=int, nargs="*", default=None,
                    help="Override weather-selected years, e.g. --years 2018 2023 2025")
    ap.add_argument("--edge-buffer-m", type=float, default=10.0)
    ap.add_argument("--min-pixels", type=int, default=25)
    ap.add_argument("--min-zone-pixels", type=int, default=3)
    ap.add_argument("--min-coverage", type=float, default=70.0)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=260817)
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    ts20 = load_module("20_satellite_lomma_timeseries.py", "akersync_ts20_hist26")
    s22 = load_module("22_satellite_lomma_twi_ndvi.py", "akersync_twi22_hist26")
    s23 = load_module("23_satellite_lomma_twi_response_curve.py", "akersync_twi23_hist26")

    plan, years = read_plan(outdir, args.year_start, args.year_end, args.years)
    lomma_skiften = build_lomma(cfg)
    spatial = make_spatial(lomma_skiften)
    twi_path = s22.find_twi(cfg, outdir)

    print("=" * 126)
    print("ÅkerSync · Satellite V1a · CONTROLLED HISTORICAL TWI RESPONSE EXPERIMENT")
    print("=" * 126)
    print("År:", ", ".join(str(y) for y in years))
    print(f"Skiften (2025 fixed footprints): {len(lomma_skiften):,}")
    print(f"Planerade Sentinel-datum: {len(plan)}")
    print(f"Kantbuffer: {args.edge_buffer_m:g} m | min coverage: {args.min_coverage:.0f}% | bootstrap: {args.bootstrap:,}")
    print("TWI:", twi_path)
    print("\nVald experimentplan:")
    for r in plan.itertuples(index=False):
        print(
            f"  {int(r.year)} {r.weather_role:8s} | {r.window:15s} | "
            f"{pd.Timestamp(r.selected_date).date()} | max-moln {float(r.max_cloud_pct):5.1f}%"
        )
    print("\nOBS: 2025-skiften används som fasta fysiska footprints även historiskt; äldre administrativa gränser kan ha skiljt sig.")

    tif_paths = download_selected(plan, outdir, spatial, ts20)
    field_date = analyse(
        plan, tif_paths, lomma_skiften, twi_path, s22,
        args.edge_buffer_m, args.min_pixels, args.min_zone_pixels, args.min_coverage,
    )
    by_window, field_year, by_year = aggregate_results(field_date, s23, args.bootstrap, args.seed)

    ytag = "_".join(str(y) for y in years)
    stem = f"lomma_historical_twi_experiment_{ytag}"
    plan_csv = outdir / f"{stem}_plan.csv"
    fd_csv = outdir / f"{stem}_field_date_quintiles.csv"
    fy_csv = outdir / f"{stem}_field_year.csv"
    bw_csv = outdir / f"{stem}_year_window_curve.csv"
    by_csv = outdir / f"{stem}_year_curve.csv"
    summary_txt = outdir / f"{stem}_summary.txt"

    plan.to_csv(plan_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    field_date.to_csv(fd_csv, index=False, encoding="utf-8-sig")
    field_year.to_csv(fy_csv, index=False, encoding="utf-8-sig")
    by_window.to_csv(bw_csv, index=False, encoding="utf-8-sig")
    by_year.to_csv(by_csv, index=False, encoding="utf-8-sig")

    lines = [
        "ÅkerSync Satellite V1a — controlled historical TWI response experiment",
        "Years: " + ", ".join(str(y) for y in years),
        f"Fixed 2025 Lomma field footprints: {len(lomma_skiften)}",
        f"Planned observations: {len(plan)}",
        f"Valid field-date rows: {len(field_date)}",
        "",
        "YEAR × WINDOW CURVES:",
    ]
    for r in by_window.itertuples(index=False):
        lines.append(
            f"  {int(r.year)} {r.weather_role:8s} {r.window:15s} {r.date} | n={int(r.fields):3d} | "
            f"Q1 {r.q1_median_dev:+.4f} Q2 {r.q2_median_dev:+.4f} Q3 {r.q3_median_dev:+.4f} "
            f"Q4 {r.q4_median_dev:+.4f} Q5 {r.q5_median_dev:+.4f} | Q5-Q1 {r.q5_minus_q1:+.4f} | "
            f"slope {r.linear_slope_per_quintile:+.4f} | coverage {r.median_coverage_pct:.1f}%"
        )
    lines += ["", "YEAR OVERALL (field first, then population):"]
    for r in by_year.itertuples(index=False):
        lines.append(
            f"  {int(r.year)} {r.weather_role:8s} | hydro {float(r.hydroclimate_score):+.3f} | n={int(r.fields):3d} | "
            f"Q1 {r.q1_median_dev:+.4f} Q2 {r.q2_median_dev:+.4f} Q3 {r.q3_median_dev:+.4f} "
            f"Q4 {r.q4_median_dev:+.4f} Q5 {r.q5_median_dev:+.4f} | Q5-Q1 {r.q5_minus_q1:+.4f} "
            f"CI95 [{r.q5q1_ci95_low:+.4f}, {r.q5q1_ci95_high:+.4f}] | "
            f"positive {r.q5q1_positive_share_pct:.1f}% | slope {r.linear_slope_per_quintile:+.4f}"
        )
    lines += [
        "",
        "INTERPRETATION GUARDRAILS:",
        "  This is an association between field-relative TWI and field-relative NDVI response.",
        "  Weather classes are regional SMHI proxies, not measured field water balance.",
        "  2025 field polygons are fixed historical sampling footprints; historical field/crop boundaries may differ.",
        "  The primary comparison is the same seasonal window across weather-contrasting years, not raw NDVI level between crops.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 126)
    print("HISTORICAL TWI EXPERIMENT KLAR")
    print("=" * 126)
    print("\nÅr × säsongsfönster:")
    for r in by_window.itertuples(index=False):
        print(
            f"  {int(r.year)} {r.weather_role:8s} | {r.window:15s} | n={int(r.fields):3d} | "
            f"Q1 {r.q1_median_dev:+.4f} Q2 {r.q2_median_dev:+.4f} Q3 {r.q3_median_dev:+.4f} "
            f"Q4 {r.q4_median_dev:+.4f} Q5 {r.q5_median_dev:+.4f} | "
            f"Q5-Q1 {r.q5_minus_q1:+.4f} | slope {r.linear_slope_per_quintile:+.4f}"
        )

    print("\nÅr overall · först median över fönster inom skifte, sedan population:")
    for r in by_year.itertuples(index=False):
        print(
            f"  {int(r.year)} {r.weather_role:8s} | hydro {float(r.hydroclimate_score):+6.3f} | n={int(r.fields):3d} | "
            f"Q5-Q1 {r.q5_minus_q1:+.4f} CI95 [{r.q5q1_ci95_low:+.4f}, {r.q5q1_ci95_high:+.4f}] | "
            f"positiva {r.q5q1_positive_share_pct:5.1f}% | slope {r.linear_slope_per_quintile:+.4f}"
        )

    print("\nOutput:")
    for p in (plan_csv, fd_csv, fy_csv, bw_csv, by_csv, summary_txt):
        print(" ", p)
    print("\nOBS: jämför i första hand samma window mellan år; historiska 2025-footprints är en medveten första approximation.")
    print("SATELLITE LOMMA HISTORICAL TWI EXPERIMENT: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
