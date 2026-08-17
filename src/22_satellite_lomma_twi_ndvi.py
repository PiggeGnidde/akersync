#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — within-field TWI ↔ NDVI validation over Lomma.

Purpose
-------
Test the core ÅkerPass satellite hypothesis without using crop-to-crop level
comparisons: do topographically wetter parts of the *same* skifte repeatedly
behave differently in vegetation?

The analysis intentionally works within skifte and within date:
  * TWI is static and comes from the already validated 10 m hydrology raster.
  * NDVI observations are reused from existing Lomma GeoTIFFs; no new Copernicus
    download is performed.
  * each skifte is eroded by a small edge buffer to reduce mixed pixels/headlands,
  * TWI zones are defined from that skifte's own TWI distribution:
        low 20 %, middle 60 %, high 20 %,
  * NDVI is centred on the skifte median for each date,
  * the primary raw effect is high-TWI NDVI minus middle-TWI NDVI,
  * a Spearman TWI↔NDVI correlation is also reported,
  * a persistence metric asks whether high-TWI pixels repeatedly fall in the
    weakest NDVI quintile across dates.

Negative high_minus_mid_ndvi means the high-TWI zone is weaker than the middle
of the same field on that date. Positive persistent_weak_high_minus_mid means
high-TWI pixels more often belong to the field's weakest NDVI quintile.

This is association/validation, not proof that TWI or wetness caused the crop
response. Drainage, soil, management, disease and other factors are not yet
controlled here.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from rasterio.warp import reproject, Resampling
from scipy.stats import spearmanr

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"
DATE_RE = re.compile(r"lomma_ndvi_(\d{8})\.tif$", re.IGNORECASE)


def find_twi(cfg: dict, outdir: Path) -> Path:
    candidates: list[Path] = []
    wb = cfg.get("whitebox_work_dir")
    if wb:
        candidates.append(Path(wb) / "twi_10m.tif")

    diag = outdir.parent / "hydrology_intermediate_files.txt"
    if diag.exists():
        for line in diag.read_text(encoding="utf-8-sig").splitlines():
            p = Path(line.strip())
            if p.name.lower() == "twi_10m.tif":
                candidates.append(p)

    for p in candidates:
        if p.exists():
            return p

    msg = "\n".join(str(p) for p in candidates) or "(inga kandidater)"
    raise FileNotFoundError(
        "Hittade inte det validerade TWI-rastret twi_10m.tif. Sökte:\n" + msg
    )


def discover_ndvi(outdir: Path, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, Path]]:
    found: list[tuple[pd.Timestamp, Path]] = []
    for p in outdir.glob("lomma_ndvi_*.tif"):
        m = DATE_RE.match(p.name)
        if not m:
            continue
        d = pd.Timestamp.strptime(m.group(1), "%Y%m%d")
        if start <= d <= end and p.stat().st_size >= 10_000:
            found.append((d, p))
    found.sort(key=lambda x: x[0])
    return found


def same_grid(ds, crs, transform, width, height) -> bool:
    if ds.crs != crs or ds.width != width or ds.height != height:
        return False
    a = tuple(ds.transform)
    b = tuple(transform)
    return bool(np.allclose(a, b, rtol=0, atol=1e-7))


def read_to_reference(path: Path, ref_crs, ref_transform, width: int, height: int) -> np.ndarray:
    with rasterio.open(path) as ds:
        if same_grid(ds, ref_crs, ref_transform, width, height):
            a = ds.read(1).astype(np.float32)
            if ds.nodata is not None and np.isfinite(ds.nodata):
                a[a == ds.nodata] = np.nan
            a[~np.isfinite(a)] = np.nan
            a[(a < -1.05) | (a > 1.05)] = np.nan
            return a

        src = ds.read(1).astype(np.float32)
        dst = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=src,
            destination=dst,
            src_transform=ds.transform,
            src_crs=ds.crs,
            src_nodata=ds.nodata,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        dst[(dst < -1.05) | (dst > 1.05)] = np.nan
        return dst


def twi_to_reference(twi_path: Path, ref_crs, ref_transform, width: int, height: int) -> np.ndarray:
    with rasterio.open(twi_path) as ds:
        src = ds.read(1).astype(np.float32)
        dst = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=src,
            destination=dst,
            src_transform=ds.transform,
            src_crs=ds.crs,
            src_nodata=ds.nodata,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            dst_nodata=np.nan,
            # Preserve the validated native TWI values instead of smoothing them.
            resampling=Resampling.nearest,
        )
        dst[~np.isfinite(dst)] = np.nan
        return dst


def raster_window(geom, transform, width: int, height: int):
    try:
        w = from_bounds(*geom.bounds, transform=transform)
    except Exception:
        return None
    c0 = max(0, int(np.floor(w.col_off)))
    r0 = max(0, int(np.floor(w.row_off)))
    c1 = min(width, int(np.ceil(w.col_off + w.width)))
    r1 = min(height, int(np.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1 - c0, r1 - r0)


def finite_mean(x: np.ndarray) -> float:
    return float(np.mean(x)) if x.size else np.nan


def safe_spearman(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 5 or np.nanstd(x) <= 1e-12 or np.nanstd(y) <= 1e-12:
        return np.nan
    r = spearmanr(x, y, nan_policy="omit").statistic
    return float(r) if np.isfinite(r) else np.nan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-07-14",
                    help="Default stops well before the visually observed harvest onset")
    ap.add_argument("--edge-buffer-m", type=float, default=10.0)
    ap.add_argument("--min-pixels", type=int, default=20)
    ap.add_argument("--min-coverage", type=float, default=70.0,
                    help="Minimum valid NDVI coverage of the buffered field on a date")
    ap.add_argument("--min-persistence-dates", type=int, default=4,
                    help="Pixel needs this many valid dates for weak-frequency persistence")
    args = ap.parse_args()

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    if end < start:
        raise SystemExit("--end måste vara >= --start")

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    ndvi_files = discover_ndvi(outdir, start, end)
    if len(ndvi_files) < 3:
        raise RuntimeError(
            f"Hittade bara {len(ndvi_files)} NDVI-TIFF:ar mellan {start.date()} och {end.date()}. "
            "Kör Lomma-tidsserien först."
        )

    twi_path = find_twi(cfg, outdir)

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    lomma_skiften = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    if lomma_skiften.empty:
        raise RuntimeError("Hittade inga Lomma-skiften")

    first_date, first_tif = ndvi_files[0]
    with rasterio.open(first_tif) as ref:
        ref_crs = ref.crs
        ref_transform = ref.transform
        width, height = ref.width, ref.height
        print("=" * 118)
        print("ÅkerSync · Satellite V1a · Lomma within-field TWI ↔ NDVI")
        print("=" * 118)
        print(f"Skiften: {len(lomma_skiften):,}")
        print(f"NDVI-datum: {len(ndvi_files)} | {start.date()} — {end.date()}")
        print("Datum:", ", ".join(d.strftime("%Y-%m-%d") for d, _ in ndvi_files))
        print(f"Referensgrid: {width}×{height} | {ref_crs} | pixel {abs(ref_transform.a):.2f} m")
        print("TWI:", twi_path)
        print(f"Skifteskant exkluderas: {args.edge_buffer_m:g} m")
        print("TWI-zoner: low 20% / middle 60% / high 20% inom varje skifte")
        print("Ingen ny satellitdata laddas ned.")

    print("\nLäser/alignar befintliga NDVI-raster …")
    dates: list[pd.Timestamp] = []
    ndvi_stack: list[np.ndarray] = []
    for i, (d, p) in enumerate(ndvi_files, 1):
        print(f"  [{i:2d}/{len(ndvi_files):2d}] {d.date()}  {p.name}")
        ndvi_stack.append(read_to_reference(p, ref_crs, ref_transform, width, height))
        dates.append(d)

    print("Alignar validerad TWI till Sentinel-grid med nearest-neighbour …")
    twi = twi_to_reference(twi_path, ref_crs, ref_transform, width, height)

    # Erode in metric SWEREF99 TM before reprojection, specifically to avoid
    # headlands, roads, hedges and mixed edge pixels contaminating this first test.
    work = lomma_skiften.copy()
    work["analysis_geometry"] = work.geometry.buffer(-args.edge_buffer_m)
    valid_geom = work.analysis_geometry.notna() & ~work.analysis_geometry.is_empty
    work = work.loc[valid_geom].copy()
    work = work.set_geometry("analysis_geometry").to_crs(ref_crs)

    field_date_rows: list[dict] = []
    persistence_rows: list[dict] = []

    print(f"\nAnalyserar {len(work):,} skiften som återstår efter kantbuffer …")
    for k, (idx, r) in enumerate(work.iterrows(), 1):
        geom = r.geometry
        w = raster_window(geom, ref_transform, width, height)
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
        if int(tw_valid.sum()) < args.min_pixels:
            continue

        tw_vals = tw[tw_valid].astype(float)
        q20_twi, q80_twi = np.percentile(tw_vals, [20, 80])
        low_zone = tw_valid & (tw <= q20_twi)
        high_zone = tw_valid & (tw >= q80_twi)
        mid_zone = tw_valid & (tw > q20_twi) & (tw < q80_twi)
        if min(int(low_zone.sum()), int(high_zone.sum()), int(mid_zone.sum())) < 3:
            continue

        weak_counts = np.zeros((hh, ww), dtype=np.uint16)
        valid_counts = np.zeros((hh, ww), dtype=np.uint16)
        n_date_ok = 0

        for d, ndvi_full in zip(dates, ndvi_stack):
            nd = ndvi_full[r0:r0 + hh, c0:c0 + ww]
            valid = tw_valid & np.isfinite(nd)
            n_valid = int(valid.sum())
            coverage = 100.0 * n_valid / max(1, int(tw_valid.sum()))
            if n_valid < args.min_pixels or coverage < args.min_coverage:
                continue

            y = nd[valid].astype(float)
            x = tw[valid].astype(float)
            med = float(np.median(y))
            q20_ndvi = float(np.percentile(y, 20))
            q25_ndvi, q75_ndvi = np.percentile(y, [25, 75])
            iqr = float(q75_ndvi - q25_ndvi)

            hv = valid & high_zone
            mv = valid & mid_zone
            lv = valid & low_zone
            if min(int(hv.sum()), int(mv.sum()), int(lv.sum())) < 3:
                continue

            high_mean = finite_mean(nd[hv].astype(float))
            mid_mean = finite_mean(nd[mv].astype(float))
            low_mean = finite_mean(nd[lv].astype(float))
            high_minus_mid = high_mean - mid_mean
            low_minus_mid = low_mean - mid_mean
            high_minus_low = high_mean - low_mean

            weak = valid & (nd <= q20_ndvi)
            high_weak_pct = 100.0 * int((weak & high_zone).sum()) / max(1, int(hv.sum()))
            mid_weak_pct = 100.0 * int((weak & mid_zone).sum()) / max(1, int(mv.sum()))
            weak_in_high_pct = 100.0 * int((weak & high_zone).sum()) / max(1, int(weak.sum()))

            robust_z = high_minus_mid / iqr if iqr > 1e-6 else np.nan
            field_date_rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "blockid": str(r.get("blockid", "")),
                "skiftesbeteckning": str(r.get("skiftesbeteckning", "")),
                "area_analysis_ha": round(float(geom.area / 10000.0), 4),
                "valid_pixels": n_valid,
                "coverage_pct": round(coverage, 2),
                "twi_q20": round(float(q20_twi), 4),
                "twi_q80": round(float(q80_twi), 4),
                "ndvi_field_median": round(med, 4),
                "ndvi_field_iqr": round(iqr, 4),
                "ndvi_high_twi_mean": round(high_mean, 4),
                "ndvi_mid_twi_mean": round(mid_mean, 4),
                "ndvi_low_twi_mean": round(low_mean, 4),
                "high_minus_mid_ndvi": round(high_minus_mid, 4),
                "low_minus_mid_ndvi": round(low_minus_mid, 4),
                "high_minus_low_ndvi": round(high_minus_low, 4),
                "high_minus_mid_robust_z": round(float(robust_z), 4) if np.isfinite(robust_z) else np.nan,
                "spearman_twi_ndvi": round(safe_spearman(x, y), 4),
                "high_twi_weak_pct": round(high_weak_pct, 2),
                "mid_twi_weak_pct": round(mid_weak_pct, 2),
                "high_minus_mid_weak_pct": round(high_weak_pct - mid_weak_pct, 2),
                "weak_pixels_in_high_twi_pct": round(weak_in_high_pct, 2),
            })

            weak_counts[weak] += 1
            valid_counts[valid] += 1
            n_date_ok += 1

        enough = valid_counts >= args.min_persistence_dates
        if n_date_ok >= args.min_persistence_dates and int(enough.sum()) >= args.min_pixels:
            weak_freq = np.full((hh, ww), np.nan, dtype=np.float32)
            weak_freq[enough] = weak_counts[enough] / valid_counts[enough]
            hp = enough & high_zone
            mp = enough & mid_zone
            lp = enough & low_zone
            if min(int(hp.sum()), int(mp.sum()), int(lp.sum())) >= 3:
                high_p = float(np.nanmean(weak_freq[hp]))
                mid_p = float(np.nanmean(weak_freq[mp]))
                low_p = float(np.nanmean(weak_freq[lp]))
                persistence_rows.append({
                    "blockid": str(r.get("blockid", "")),
                    "skiftesbeteckning": str(r.get("skiftesbeteckning", "")),
                    "area_analysis_ha": round(float(geom.area / 10000.0), 4),
                    "n_eligible_dates": int(n_date_ok),
                    "persistence_pixels": int(enough.sum()),
                    "high_twi_weak_frequency": round(high_p, 4),
                    "mid_twi_weak_frequency": round(mid_p, 4),
                    "low_twi_weak_frequency": round(low_p, 4),
                    "persistent_weak_high_minus_mid": round(high_p - mid_p, 4),
                    "persistent_weak_high_minus_low": round(high_p - low_p, 4),
                })

        if k == 1 or k % 100 == 0 or k == len(work):
            print(f"\r  skifte {k:,}/{len(work):,} | field-date rows {len(field_date_rows):,}", end="", flush=True)
    print()

    field_date = pd.DataFrame(field_date_rows)
    if field_date.empty:
        raise RuntimeError("Analysen gav inga giltiga skifte×datum-rader")
    field_date["date"] = pd.to_datetime(field_date.date)

    field_summary = (
        field_date.groupby(["blockid", "skiftesbeteckning"], as_index=False)
        .agg(
            n_dates=("date", "count"),
            area_analysis_ha=("area_analysis_ha", "first"),
            median_high_minus_mid_ndvi=("high_minus_mid_ndvi", "median"),
            median_high_minus_low_ndvi=("high_minus_low_ndvi", "median"),
            median_robust_z=("high_minus_mid_robust_z", "median"),
            median_spearman_twi_ndvi=("spearman_twi_ndvi", "median"),
            median_high_minus_mid_weak_pct=("high_minus_mid_weak_pct", "median"),
        )
    )
    negshare = (
        field_date.assign(neg=field_date.high_minus_mid_ndvi < 0)
        .groupby(["blockid", "skiftesbeteckning"], as_index=False)
        .agg(high_twi_weaker_date_share=("neg", "mean"))
    )
    field_summary = field_summary.merge(negshare, on=["blockid", "skiftesbeteckning"], how="left")
    field_summary["high_twi_weaker_date_share"] = (100.0 * field_summary.high_twi_weaker_date_share).round(1)

    persistence = pd.DataFrame(persistence_rows)
    if not persistence.empty:
        field_summary = field_summary.merge(
            persistence,
            on=["blockid", "skiftesbeteckning", "area_analysis_ha"],
            how="left",
        )

    date_summary = (
        field_date.groupby("date", as_index=False)
        .agg(
            fields=("blockid", "count"),
            median_field_ndvi=("ndvi_field_median", "median"),
            median_high_minus_mid_ndvi=("high_minus_mid_ndvi", "median"),
            p10_high_minus_mid_ndvi=("high_minus_mid_ndvi", lambda x: x.quantile(.10)),
            p90_high_minus_mid_ndvi=("high_minus_mid_ndvi", lambda x: x.quantile(.90)),
            median_spearman=("spearman_twi_ndvi", "median"),
            median_high_minus_mid_weak_pct=("high_minus_mid_weak_pct", "median"),
        )
    )
    neg_by_date = (
        field_date.assign(neg=field_date.high_minus_mid_ndvi < 0)
        .groupby("date", as_index=False)
        .agg(high_twi_weaker_field_share=("neg", "mean"))
    )
    date_summary = date_summary.merge(neg_by_date, on="date", how="left")
    date_summary["high_twi_weaker_field_share"] = (100.0 * date_summary.high_twi_weaker_field_share).round(1)

    stem = f"lomma_twi_ndvi_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    field_date_csv = outdir / f"{stem}_field_date.csv"
    field_summary_csv = outdir / f"{stem}_field_summary.csv"
    date_summary_csv = outdir / f"{stem}_date_summary.csv"
    persistence_csv = outdir / f"{stem}_persistence.csv"
    summary_txt = outdir / f"{stem}_summary.txt"

    field_date.to_csv(field_date_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    field_summary.to_csv(field_summary_csv, index=False, encoding="utf-8-sig")
    date_summary.to_csv(date_summary_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    persistence.to_csv(persistence_csv, index=False, encoding="utf-8-sig")

    lines = [
        "ÅkerSync Satellite V1a — Lomma within-field TWI ↔ NDVI",
        f"Interval: {start.date()} — {end.date()}",
        f"NDVI dates used: {len(ndvi_files)}",
        f"Original Lomma skiften: {len(lomma_skiften)}",
        f"Buffered skiften considered: {len(work)}",
        f"Skiften with >=1 eligible date: {field_summary.shape[0]}",
        f"Skiften with persistence estimate: {persistence.shape[0]}",
        f"Edge buffer: {args.edge_buffer_m:g} m",
        f"Min pixels: {args.min_pixels}",
        f"Min date coverage: {args.min_coverage:.1f}%",
        "",
        "Interpretation signs:",
        "  high_minus_mid_ndvi < 0  => high-TWI zone weaker than middle zone same field/date",
        "  Spearman < 0             => NDVI tends to decrease as TWI increases within field",
        "  persistent_weak_high_minus_mid > 0 => high-TWI pixels repeatedly weak more often",
        "",
        "DATE SUMMARY:",
    ]
    for r in date_summary.itertuples(index=False):
        lines.append(
            f"  {pd.Timestamp(r.date).date()} | fields {int(r.fields):3d} | median NDVI {r.median_field_ndvi:+.4f} | "
            f"high-mid {r.median_high_minus_mid_ndvi:+.4f} | P10-P90 {r.p10_high_minus_mid_ndvi:+.4f}..{r.p90_high_minus_mid_ndvi:+.4f} | "
            f"high weaker {r.high_twi_weaker_field_share:5.1f}% | rho {r.median_spearman:+.3f}"
        )

    lines += ["", "FIELD-LEVEL AGGREGATE:"]
    lines.append(f"  Median field high-mid NDVI: {field_summary.median_high_minus_mid_ndvi.median():+.4f}")
    lines.append(f"  Median field Spearman TWI↔NDVI: {field_summary.median_spearman_twi_ndvi.median():+.3f}")
    lines.append(f"  Median share dates high-TWI weaker: {field_summary.high_twi_weaker_date_share.median():.1f}%")
    if not persistence.empty:
        lines.append(
            f"  Median persistent weak high-minus-mid: {persistence.persistent_weak_high_minus_mid.median():+.4f}"
        )
    lines += [
        "",
        "CAUTION:",
        "  Association only. This is a first empirical cross-check of TWI against vegetation response.",
        "  Drainage, soil, crop, management and weather interactions are not yet separated.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 118)
    print("TWI ↔ NDVI ANALYS KLAR")
    print("=" * 118)
    print(f"Skiften med analys: {len(field_summary)} / {len(lomma_skiften)}")
    print(f"Skiften med persistensmått: {len(persistence)}")
    print(f"Median skifte high-TWI minus middle NDVI: {field_summary.median_high_minus_mid_ndvi.median():+.4f}")
    print(f"Median skifte Spearman TWI↔NDVI: {field_summary.median_spearman_twi_ndvi.median():+.3f}")
    print(f"Median andel datum high-TWI svagare: {field_summary.high_twi_weaker_date_share.median():.1f}%")
    if not persistence.empty:
        print(f"Median persistent weak high-minus-mid: {persistence.persistent_weak_high_minus_mid.median():+.4f}")
    print("\nPer datum:")
    for r in date_summary.itertuples(index=False):
        print(
            f"  {pd.Timestamp(r.date).date()} | n={int(r.fields):3d} | high-mid {r.median_high_minus_mid_ndvi:+.4f} | "
            f"high svagare {r.high_twi_weaker_field_share:5.1f}% | rho {r.median_spearman:+.3f}"
        )
    print("\nOutput:")
    for p in (field_date_csv, field_summary_csv, date_summary_csv, persistence_csv, summary_txt):
        print(" ", p)
    print("\nOBS: detta validerar association TWI↔vegetationsmönster; det är inte ett dräneringsfacit.")
    print("SATELLITE LOMMA TWI NDVI: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
