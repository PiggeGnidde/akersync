#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — Lomma hydroclimate classification 2018..2026.

Purpose
-------
Before downloading historical Sentinel pixels, classify candidate years by
weather using official SMHI meteorological observations. This is a transparent
regional weather stratification for selecting contrasting years in the
TWI↔vegetation experiment; it is not yet a physical soil-water-balance model.

SMHI parameters
---------------
  5 : daily precipitation amount (mm/day)
  2 : daily mean air temperature (deg C)

Method
------
  * nearby SMHI CORE stations are discovered from the API,
  * corrected-archive data are preferred,
  * recent missing dates are supplemented from latest-months when available,
  * up to three nearby stations per parameter are inverse-distance weighted,
  * March..July summaries are calculated for 2018..2026,
  * a relative early-summer hydroclimate score is defined as
        z(precip Jun01-Jul15) - z(Tmean Jun01-Jul15),
  * the Sentinel multiyear preflight is joined when available,
  * one dry/hot, one middle and one wet/cool year are recommended for the first
    controlled historical pixel download.

Labels are RELATIVE within 2018..2026, not SMHI climatological normals and not
measured field water balance. Precipitation is spatially variable and ET is not
explicitly modelled here.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"
SMHI_BASE = "https://opendata-download-metobs.smhi.se/api/version/1.0"
PARAMS = {"precip_mm": 5, "tmean_c": 2}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_bytes(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AkerSync-SMHI-Weather/1.0", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"SMHI HTTP {e.code}: {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Kunde inte nå SMHI: {e}") from e


def get_json(url: str) -> dict:
    return json.loads(get_bytes(url).decode("utf-8"))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_api_time(v):
    if v is None or v == "":
        return pd.NaT
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
            return pd.to_datetime(int(v), unit="ms", utc=True).tz_convert(None)
        return pd.to_datetime(v, utc=True).tz_convert(None)
    except Exception:
        return pd.NaT


def station_catalogue(param: int, lat0: float, lon0: float) -> pd.DataFrame:
    url = f"{SMHI_BASE}/parameter/{param}.json?measuringStations=core"
    obj = get_json(url)
    stations = obj.get("station", []) or []
    rows = []
    for s in stations:
        try:
            lat = float(s.get("latitude"))
            lon = float(s.get("longitude"))
            key = str(s.get("key"))
        except (TypeError, ValueError):
            continue
        if not key or key == "None":
            continue
        network = str(s.get("measuringStations", "")).upper()
        if network and network != "CORE":
            continue
        rows.append({
            "station_key": key,
            "station_name": str(s.get("name", "")),
            "latitude": lat,
            "longitude": lon,
            "distance_km": haversine_km(lat0, lon0, lat, lon),
            "active": bool(s.get("active", False)),
            "network": network or "CORE",
            "from": parse_api_time(s.get("from")),
            "to": parse_api_time(s.get("to")),
        })
    if not rows:
        raise RuntimeError(f"SMHI parameter {param}: inga CORE-stationer i katalogen")
    return pd.DataFrame(rows).sort_values("distance_km").reset_index(drop=True)


def parse_archive_csv(raw: bytes) -> pd.DataFrame:
    """Parse SMHI sample-style and interval-style corrected archive CSV."""
    txt = raw.decode("utf-8-sig", errors="replace")
    table = list(csv.reader(io.StringIO(txt), delimiter=";"))
    header_i = rep_i = value_i = quality_i = None

    for i, row in enumerate(table):
        cells = [c.strip() for c in row]
        low = [c.lower() for c in cells]
        for j, c in enumerate(low):
            if "representativt dygn" in c:
                header_i, rep_i = i, j
                break
        if header_i is not None:
            for j, c in enumerate(low):
                if "nederbördsmängd" in c or "lufttemperatur" in c:
                    value_i = j
                if "kvalitet" in c:
                    quality_i = j
            if value_i is None and rep_i + 1 < len(cells):
                value_i = rep_i + 1
            if quality_i is None and value_i is not None and value_i + 1 < len(cells):
                quality_i = value_i + 1
            break

    rows = []
    if header_i is not None and rep_i is not None and value_i is not None:
        for r in table[header_i + 1:]:
            if max(rep_i, value_i) >= len(r):
                continue
            d = r[rep_i].strip()
            if not DATE_RE.match(d):
                continue
            try:
                val = float(r[value_i].strip().replace(",", "."))
            except ValueError:
                continue
            quality = r[quality_i].strip() if quality_i is not None and quality_i < len(r) else ""
            rows.append({"date": pd.Timestamp(d), "value": val, "quality": quality, "source": "corrected-archive"})
    else:
        for r in table:
            if len(r) < 3:
                continue
            d = r[0].strip()
            if not DATE_RE.match(d):
                continue
            try:
                val = float(r[2].strip().replace(",", "."))
            except ValueError:
                continue
            quality = r[3].strip() if len(r) > 3 else ""
            rows.append({"date": pd.Timestamp(d), "value": val, "quality": quality, "source": "corrected-archive"})

    if not rows:
        return pd.DataFrame(columns=["date", "value", "quality", "source"])
    return pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def parse_latest_json(obj: dict) -> pd.DataFrame:
    """Parse latest-months JSON for both SAMPLING and INTERVAL value types."""
    vals = obj.get("value", []) or []
    rows = []
    for x in vals:
        raw_date = x.get("date")
        if raw_date is None:
            raw_date = x.get("ref")
        if raw_date is None:
            raw_date = x.get("to")
        ts = parse_api_time(raw_date)
        try:
            val = float(str(x.get("value")).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if pd.isna(ts):
            continue
        rows.append({
            "date": pd.Timestamp(ts).normalize(),
            "value": val,
            "quality": str(x.get("quality", "")),
            "source": "latest-months",
        })
    if not rows:
        return pd.DataFrame(columns=["date", "value", "quality", "source"])
    return pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def fetch_station_series(param: int, station_key: str) -> pd.DataFrame:
    archive_url = f"{SMHI_BASE}/parameter/{param}/station/{station_key}/period/corrected-archive/data.csv"
    try:
        arc = parse_archive_csv(get_bytes(archive_url))
    except RuntimeError:
        arc = pd.DataFrame(columns=["date", "value", "quality", "source"])

    latest_url = f"{SMHI_BASE}/parameter/{param}/station/{station_key}/period/latest-months/data.json"
    try:
        recent = parse_latest_json(get_json(latest_url))
    except RuntimeError:
        recent = pd.DataFrame(columns=["date", "value", "quality", "source"])

    if arc.empty and recent.empty:
        return arc
    if arc.empty:
        return recent
    if recent.empty:
        return arc

    x = pd.concat([recent, arc], ignore_index=True)
    x["priority"] = np.where(x.source.eq("corrected-archive"), 1, 0)
    x = x.sort_values(["date", "priority"]).drop_duplicates("date", keep="last")
    return x.drop(columns="priority").sort_values("date").reset_index(drop=True)


def target_dates(year_start: int, year_end: int) -> pd.DatetimeIndex:
    chunks = [pd.date_range(f"{y}-03-01", f"{y}-07-15", freq="D") for y in range(year_start, year_end + 1)]
    return chunks[0] if len(chunks) == 1 else chunks[0].append(chunks[1:])


def select_stations(param_name, param, cat, dates, n_stations, candidates, min_station_coverage):
    target_set = pd.DataFrame({"date": dates})
    tested = []
    for r in cat.head(candidates).itertuples(index=False):
        print(f"    provar {r.station_name} ({r.station_key}), {r.distance_km:.1f} km …", end="", flush=True)
        s = fetch_station_series(param, r.station_key)
        sub = target_set.merge(s[["date", "value", "quality", "source"]], on="date", how="left")
        cov = 100.0 * sub.value.notna().mean()
        print(f" coverage {cov:.1f}%")
        tested.append((r, s, cov))

    good = [x for x in tested if x[2] >= min_station_coverage]
    if len(good) < n_stations:
        good = sorted(tested, key=lambda x: (-x[2], x[0].distance_km))
    else:
        good = sorted(good, key=lambda x: x[0].distance_km)
    chosen = good[:n_stations]
    if not chosen:
        raise RuntimeError(f"{param_name}: ingen användbar SMHI-station")
    return chosen


def aggregate_region(chosen, dates, value_name: str, min_daily_stations: int):
    base = pd.DataFrame({"date": dates})
    meta, value_cols, weight_cols = [], [], []
    for j, (r, s, cov) in enumerate(chosen, 1):
        c = f"s{j}"
        base = base.merge(s[["date", "value"]].rename(columns={"value": c}), on="date", how="left")
        w = 1.0 / (max(float(r.distance_km), 5.0) ** 2)
        value_cols.append(c)
        weight_cols.append(w)
        meta.append({
            "parameter": value_name,
            "station_rank": j,
            "station_key": r.station_key,
            "station_name": r.station_name,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "distance_km": round(float(r.distance_km), 2),
            "target_coverage_pct": round(float(cov), 2),
            "idw_weight_raw": w,
        })

    vals = base[value_cols].to_numpy(dtype=float)
    weights = np.asarray(weight_cols, dtype=float)
    valid = np.isfinite(vals)
    n = valid.sum(axis=1)
    num = np.sum(np.where(valid, vals * weights[None, :], 0.0), axis=1)
    den = np.sum(np.where(valid, weights[None, :], 0.0), axis=1)
    reg = np.full(len(base), np.nan, dtype=float)
    ok = (n >= min_daily_stations) & (den > 0)
    reg[ok] = num[ok] / den[ok]
    base[value_name] = reg
    base[f"{value_name}_stations"] = n
    return base[["date", value_name, f"{value_name}_stations"]], meta


def zscore(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x, errors="coerce")
    sd = x.std(ddof=0)
    if not np.isfinite(sd) or sd <= 1e-12:
        return pd.Series(np.nan, index=x.index)
    return (x - x.mean()) / sd


def summarize_years(daily: pd.DataFrame, year_start: int, year_end: int) -> pd.DataFrame:
    rows = []
    for y in range(year_start, year_end + 1):
        def win(md0: str, md1: str):
            a, b = pd.Timestamp(f"{y}-{md0}"), pd.Timestamp(f"{y}-{md1}")
            x = daily[(daily.date >= a) & (daily.date <= b)]
            return x, (b - a).days + 1

        marjul, n_marjul = win("03-01", "07-15")
        aprmay, _ = win("04-01", "05-31")
        earlysum, n_earlysum = win("06-01", "07-15")
        rows.append({
            "year": y,
            "precip_mar01_jul15_mm": marjul.precip_mm.sum(min_count=1),
            "precip_apr01_may31_mm": aprmay.precip_mm.sum(min_count=1),
            "precip_jun01_jul15_mm": earlysum.precip_mm.sum(min_count=1),
            "tmean_mar01_jul15_c": marjul.tmean_c.mean(),
            "tmean_apr01_may31_c": aprmay.tmean_c.mean(),
            "tmean_jun01_jul15_c": earlysum.tmean_c.mean(),
            "gdd5_mar01_jul15": np.nansum(np.maximum(marjul.tmean_c.to_numpy(dtype=float) - 5.0, 0.0)) if marjul.tmean_c.notna().any() else np.nan,
            "precip_coverage_marjul_pct": 100.0 * marjul.precip_mm.notna().sum() / n_marjul,
            "temp_coverage_marjul_pct": 100.0 * marjul.tmean_c.notna().sum() / n_marjul,
            "precip_coverage_earlysummer_pct": 100.0 * earlysum.precip_mm.notna().sum() / n_earlysum,
            "temp_coverage_earlysummer_pct": 100.0 * earlysum.tmean_c.notna().sum() / n_earlysum,
        })

    out = pd.DataFrame(rows)
    out["z_precip_earlysummer"] = zscore(out.precip_jun01_jul15_mm)
    out["z_temp_earlysummer"] = zscore(out.tmean_jun01_jul15_c)
    out["hydroclimate_score"] = out.z_precip_earlysummer - out.z_temp_earlysummer

    valid = out.hydroclimate_score.notna()
    ranks = out.loc[valid, "hydroclimate_score"].rank(method="first")
    n = len(ranks)
    labels = []
    for rank in ranks:
        frac = (rank - 0.5) / max(1, n)
        labels.append("dry_hot_relative" if frac < 1/3 else "wet_cool_relative" if frac >= 2/3 else "middle_relative")
    out["weather_class"] = "insufficient_data"
    out.loc[valid, "weather_class"] = labels
    return out


def add_preflight(years: pd.DataFrame, outdir: Path, year_start: int, year_end: int) -> pd.DataFrame:
    p = outdir / f"lomma_multiyear_preflight_{year_start}_{year_end}_dates.csv"
    if not p.exists():
        years["sentinel_dates_found"] = np.nan
        years["sentinel_good_windows"] = np.nan
        return years
    x = pd.read_csv(p)
    if "selected_date" not in x or "good_catalog_cloud" not in x:
        return years
    x["selected_date"] = pd.to_datetime(x.selected_date, errors="coerce")
    x["good_catalog_cloud"] = x.good_catalog_cloud.astype(str).str.lower().isin(["true", "1", "yes"])
    s = x.groupby("year", as_index=False).agg(
        sentinel_dates_found=("selected_date", lambda a: int(a.notna().sum())),
        sentinel_good_windows=("good_catalog_cloud", "sum"),
        sentinel_worst_selected_max_cloud_pct=("max_cloud_pct", "max"),
    )
    return years.merge(s, on="year", how="left")


def recommend_years(years: pd.DataFrame) -> pd.DataFrame:
    x = years[
        years.hydroclimate_score.notna()
        & (years.precip_coverage_earlysummer_pct >= 85)
        & (years.temp_coverage_earlysummer_pct >= 85)
    ].copy()
    if "sentinel_good_windows" in x:
        good = x[x.sentinel_good_windows.fillna(0) >= 3]
        if len(good) >= 3:
            x = good
    if len(x) < 3:
        return pd.DataFrame()

    dry = x.loc[x.hydroclimate_score.idxmin()].copy()
    wet = x.loc[x.hydroclimate_score.idxmax()].copy()
    remaining = x[~x.year.isin([dry.year, wet.year])].copy()
    if remaining.empty:
        return pd.DataFrame()
    middle = remaining.loc[remaining.hydroclimate_score.abs().idxmin()].copy()

    rows = []
    for role, r in [("dry_hot", dry), ("middle", middle), ("wet_cool", wet)]:
        rows.append({
            "role": role,
            "year": int(r.year),
            "hydroclimate_score": round(float(r.hydroclimate_score), 4),
            "precip_jun01_jul15_mm": round(float(r.precip_jun01_jul15_mm), 1),
            "tmean_jun01_jul15_c": round(float(r.tmean_jun01_jul15_c), 2),
            "sentinel_good_windows": int(r.sentinel_good_windows) if "sentinel_good_windows" in r and pd.notna(r.sentinel_good_windows) else np.nan,
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--year-start", type=int, default=2018)
    ap.add_argument("--year-end", type=int, default=2026)
    ap.add_argument("--stations", type=int, default=3)
    ap.add_argument("--station-candidates", type=int, default=10)
    ap.add_argument("--min-station-coverage", type=float, default=80.0)
    ap.add_argument("--min-daily-stations", type=int, default=2)
    args = ap.parse_args()

    if args.year_end < args.year_start:
        raise SystemExit("--year-end måste vara >= --year-start")
    if args.stations < 1:
        raise SystemExit("--stations måste vara >= 1")

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    lomma_skiften = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    if lomma_skiften.empty:
        raise RuntimeError("Hittade inga Lomma-skiften")

    minx, miny, maxx, maxy = lomma_skiften.total_bounds
    pt = gpd.GeoSeries([Point((minx + maxx)/2, (miny + maxy)/2)], crs=3006).to_crs(4326).iloc[0]
    lon0, lat0 = float(pt.x), float(pt.y)
    dates = target_dates(args.year_start, args.year_end)

    print("=" * 118)
    print("ÅkerSync · Satellite V1a · Lomma SMHI weather classification")
    print("=" * 118)
    print(f"År: {args.year_start}–{args.year_end}")
    print(f"Lomma referenspunkt: lat {lat0:.5f}, lon {lon0:.5f}")
    print("SMHI CORE · parameter 5 dygnsnederbörd + parameter 2 dygnsmedeltemperatur")
    print("Corrected archive först; latest-months fyller bara senaste luckor.")
    print(f"Regional proxy: upp till {args.stations} stationer, inverse-distance weighted.")
    print("Weather labels är relativa inom studieåren, inte klimatnormaler.\n")

    regional_parts = []
    station_meta = []
    for value_name, param in PARAMS.items():
        title = "nederbörd" if value_name == "precip_mm" else "temperatur"
        print(f"[{title}] Hämtar SMHI CORE-stationskatalog …")
        cat = station_catalogue(param, lat0, lon0)
        chosen = select_stations(value_name, param, cat, dates, args.stations, args.station_candidates, args.min_station_coverage)
        print("  valda:")
        for r, _, cov in chosen:
            print(f"    {r.station_name} ({r.station_key}) | {r.distance_km:.1f} km | coverage {cov:.1f}%")
        reg, meta = aggregate_region(chosen, dates, value_name, args.min_daily_stations)
        regional_parts.append(reg)
        station_meta.extend(meta)

    daily = regional_parts[0]
    for x in regional_parts[1:]:
        daily = daily.merge(x, on="date", how="outer")
    daily = daily.sort_values("date").reset_index(drop=True)

    years = summarize_years(daily, args.year_start, args.year_end)
    years = add_preflight(years, outdir, args.year_start, args.year_end)
    rec = recommend_years(years)

    stem = f"lomma_weather_{args.year_start}_{args.year_end}"
    stations_csv = outdir / f"{stem}_stations.csv"
    daily_csv = outdir / f"{stem}_daily.csv"
    years_csv = outdir / f"{stem}_year_classification.csv"
    rec_csv = outdir / f"{stem}_recommended_years.csv"
    summary_txt = outdir / f"{stem}_summary.txt"

    pd.DataFrame(station_meta).to_csv(stations_csv, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    years.to_csv(years_csv, index=False, encoding="utf-8-sig")
    rec.to_csv(rec_csv, index=False, encoding="utf-8-sig")

    lines = [
        "ÅkerSync Satellite V1a — Lomma SMHI weather classification",
        f"Years: {args.year_start}–{args.year_end}",
        f"Reference point: {lat0:.5f}, {lon0:.5f}",
        "SMHI parameter 5 = daily precipitation; parameter 2 = daily mean air temperature.",
        "CORE stations only. Corrected archive preferred; latest-months only fills recent gaps.",
        "Hydroclimate score = z(precip Jun01-Jul15) - z(Tmean Jun01-Jul15).",
        "Labels are relative within study years, not climatological normals or field water balance.",
        "",
        "YEAR CLASSIFICATION:",
    ]
    for r in years.sort_values("year").itertuples(index=False):
        good = getattr(r, "sentinel_good_windows", np.nan)
        goodtxt = "NA" if not np.isfinite(good) else f"{int(good)}/4"
        lines.append(
            f"  {int(r.year)} | P Jun-Jul15 {r.precip_jun01_jul15_mm:6.1f} mm | "
            f"T {r.tmean_jun01_jul15_c:5.2f} C | score {r.hydroclimate_score:+6.3f} | "
            f"{r.weather_class:17s} | Sentinel GOOD {goodtxt}"
        )
    if not rec.empty:
        lines += ["", "RECOMMENDED FIRST HISTORICAL PIXEL YEARS:"]
        for r in rec.itertuples(index=False):
            goodtxt = "NA" if not np.isfinite(r.sentinel_good_windows) else str(int(r.sentinel_good_windows))
            lines.append(
                f"  {r.role:8s}: {int(r.year)} | score {r.hydroclimate_score:+.3f} | "
                f"P {r.precip_jun01_jul15_mm:.1f} mm | T {r.tmean_jun01_jul15_c:.2f} C | Sentinel GOOD {goodtxt}/4"
            )
    lines += [
        "",
        "CAUTION:",
        "  Regional station weather stratification only; not causal proof and not a soil-water balance.",
        "  Next test: compare within-field TWI response curves between contrasting years.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 118)
    print("SMHI WEATHER CLASSIFICATION KLAR")
    print("=" * 118)
    for r in years.sort_values("year").itertuples(index=False):
        good = getattr(r, "sentinel_good_windows", np.nan)
        goodtxt = "NA" if not np.isfinite(good) else f"{int(good)}/4"
        print(
            f"  {int(r.year)} | P Jun1-Jul15 {r.precip_jun01_jul15_mm:6.1f} mm | "
            f"T {r.tmean_jun01_jul15_c:5.2f} C | hydro score {r.hydroclimate_score:+6.3f} | "
            f"{r.weather_class:17s} | Sentinel GOOD {goodtxt}"
        )
    if not rec.empty:
        print("\nFörsta kontrollerade historiska pixeltest:")
        for r in rec.itertuples(index=False):
            goodtxt = "NA" if not np.isfinite(r.sentinel_good_windows) else str(int(r.sentinel_good_windows))
            print(
                f"  {r.role:8s}: {int(r.year)} | score {r.hydroclimate_score:+.3f} | "
                f"P {r.precip_jun01_jul15_mm:.1f} mm | T {r.tmean_jun01_jul15_c:.2f} C | Sentinel GOOD {goodtxt}/4"
            )

    print("\nOutput:")
    for pth in (stations_csv, daily_csv, years_csv, rec_csv, summary_txt):
        print(" ", pth)
    print("\nSATELLITE LOMMA WEATHER CLASSIFICATION: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
