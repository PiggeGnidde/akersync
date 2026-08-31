#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare long-run PTHBV climate covariates for the ÅkerScore × normskörd test.

Primary climate definition (frozen for this exploratory v0a):
- source: SMHI PTHBV gridded precipitation and temperature;
- years: 2011–2025 inclusive;
- growing period: April–July;
- temperature: mean temperature over April–July (deg C);
- precipitation: mean annual April–July precipitation sum (mm);
- spatial aggregation: exact polygon overlap of current 2025 wheat-field geometry
  with PTHBV grid cells, then the same wheat-field-year area weighting as the
  normskörd validation.

The script is read-only with respect to all ÅkerPass source/derived data.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from pyproj import CRS
from shapely.geometry import box

from run_validation import verify_inputs, load_inputs, prepare_wheat, weighted_mean

START_YEAR = 2011
END_YEAR = 2025
MONTHS = (4, 5, 6, 7)
TARGET_CRS = "EPSG:3006"
MIN_FIELD_GRID_COVERAGE = 0.95


def text_id(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def field_id(blockid: Any, skiftesbeteckning: Any) -> str:
    return f"{text_id(blockid)}|{text_id(skiftesbeteckning)}"


def _descriptor(name: str, da: xr.DataArray) -> str:
    return " ".join(
        str(v) for v in [
            name,
            da.attrs.get("standard_name", ""),
            da.attrs.get("long_name", ""),
            da.attrs.get("description", ""),
            da.attrs.get("units", ""),
        ]
    ).lower()


def discover_variable(ds: xr.Dataset, kind: str, override: str | None) -> str:
    if override:
        if override not in ds.data_vars:
            raise RuntimeError(f"Requested {kind} variable {override!r} not in NetCDF data_vars")
        return override

    ranked: list[tuple[int, str]] = []
    for name, da in ds.data_vars.items():
        if da.ndim < 2:
            continue
        d = _descriptor(name, da)
        score = 0
        if kind == "temperature":
            if any(k in d for k in ["temperature", "temperatur", "air_temperature", " temp", "tas"]):
                score += 20
            units = str(da.attrs.get("units", "")).lower()
            if any(k in units for k in ["celsius", "degc", "degree_c", "kelvin", " k"]):
                score += 5
        else:
            if any(k in d for k in ["precipitation", "precip", "nederb", "rain", "prcp"]):
                score += 20
            units = str(da.attrs.get("units", "")).lower()
            if any(k in units for k in ["mm", "kg m-2", "kg/m2"]):
                score += 5
        if score:
            ranked.append((score, name))
    if not ranked:
        raise RuntimeError(
            f"Could not identify {kind} variable. Run inspect_pthbv.py and pass "
            f"--{'temp-var' if kind == 'temperature' else 'precip-var'} explicitly."
        )
    ranked.sort(reverse=True)
    return ranked[0][1]


def discover_time_name(ds: xr.Dataset, da: xr.DataArray) -> str:
    for dim in da.dims:
        if dim in ds.coords:
            vals = ds.coords[dim].values
            if np.issubdtype(np.asarray(vals).dtype, np.datetime64):
                return dim
    for name, coord in ds.coords.items():
        if name in da.dims and "time" in name.lower():
            return name
    raise RuntimeError("Could not identify a datetime time coordinate in PTHBV NetCDF")


def discover_xy(ds: xr.Dataset, da: xr.DataArray, time_name: str) -> tuple[str, str]:
    dims = [d for d in da.dims if d != time_name]
    if len(dims) != 2:
        raise RuntimeError(f"Expected exactly two spatial dimensions; got {dims}")

    def axis_score(dim: str, axis: str) -> int:
        c = ds.coords.get(dim)
        text = dim.lower()
        if c is not None:
            text += " " + str(c.attrs.get("standard_name", "")).lower()
            text += " " + str(c.attrs.get("axis", "")).lower()
            text += " " + str(c.attrs.get("long_name", "")).lower()
        if axis == "x":
            return sum(k in text for k in ["longitude", "projection_x", "easting", " x", "lon", "axis=x"])
        return sum(k in text for k in ["latitude", "projection_y", "northing", " y", "lat", "axis=y"])

    d0, d1 = dims
    if axis_score(d0, "x") > axis_score(d1, "x") and axis_score(d1, "y") >= axis_score(d0, "y"):
        xdim, ydim = d0, d1
    elif axis_score(d1, "x") > axis_score(d0, "x") and axis_score(d0, "y") >= axis_score(d1, "y"):
        xdim, ydim = d1, d0
    else:
        # Common CF convention is (time, y, x).
        ydim, xdim = d0, d1

    for dim in (xdim, ydim):
        if dim not in ds.coords or ds.coords[dim].ndim != 1:
            raise RuntimeError(
                f"Spatial coordinate {dim!r} is not a 1-D coordinate. "
                "v0a exact polygon-grid overlay requires 1-D x/y coordinates; "
                "run inspect_pthbv.py and return the output if this occurs."
            )
    return xdim, ydim


def discover_crs(ds: xr.Dataset, da: xr.DataArray, xdim: str, ydim: str, override: str | None) -> CRS:
    if override:
        return CRS.from_user_input(override)

    xc, yc = ds.coords[xdim], ds.coords[ydim]
    sx = (xdim + " " + str(xc.attrs.get("standard_name", ""))).lower()
    sy = (ydim + " " + str(yc.attrs.get("standard_name", ""))).lower()
    if ("lon" in sx or "longitude" in sx) and ("lat" in sy or "latitude" in sy):
        return CRS.from_epsg(4326)

    grid_mapping = da.attrs.get("grid_mapping")
    candidates = []
    if grid_mapping and grid_mapping in ds.variables:
        candidates.append(ds[grid_mapping])
    candidates.extend(
        v for name, v in ds.variables.items()
        if name != grid_mapping and "grid_mapping_name" in v.attrs
    )
    for c in candidates:
        attrs = dict(c.attrs)
        for key in ("spatial_ref", "crs_wkt"):
            if attrs.get(key):
                try:
                    return CRS.from_wkt(str(attrs[key]))
                except Exception:
                    pass
        try:
            return CRS.from_cf(attrs)
        except Exception:
            pass

    xv = np.asarray(xc.values, float)
    yv = np.asarray(yc.values, float)
    xm, ym = float(np.nanmedian(xv)), float(np.nanmedian(yv))
    if 5 <= xm <= 30 and 50 <= ym <= 75:
        return CRS.from_epsg(4326)
    if 200_000 <= xm <= 900_000 and 5_500_000 <= ym <= 8_000_000:
        return CRS.from_epsg(3006)
    if 1_000_000 <= xm <= 2_000_000 and 5_500_000 <= ym <= 8_000_000:
        # Historic PTHBV products have commonly used RT90 2.5 gon V.
        return CRS.from_epsg(3021)

    raise RuntimeError(
        "Could not infer PTHBV CRS safely. Pass --grid-crs explicitly after "
        "running inspect_pthbv.py. Coordinate medians: " f"x={xm}, y={ym}"
    )


def coordinate_bounds(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or len(values) < 2:
        raise RuntimeError("Need at least two 1-D spatial coordinate values")
    mids = (values[:-1] + values[1:]) / 2.0
    edges = np.empty(len(values) + 1, dtype=float)
    edges[1:-1] = mids
    edges[0] = values[0] - (mids[0] - values[0])
    edges[-1] = values[-1] + (values[-1] - mids[-1])
    lo = np.minimum(edges[:-1], edges[1:])
    hi = np.maximum(edges[:-1], edges[1:])
    return lo, hi


def timestep_weights_days(times: pd.DatetimeIndex) -> np.ndarray:
    if len(times) < 2:
        return np.ones(len(times), dtype=float)
    diffs = np.diff(times.values).astype("timedelta64[D]").astype(float)
    median_gap = float(np.nanmedian(diffs))
    # Monthly PTHBV output: day-weight monthly mean temperature.
    if median_gap >= 20:
        return times.days_in_month.to_numpy(dtype=float)
    # Daily output: each daily mean gets equal weight.
    return np.ones(len(times), dtype=float)


def aggregate_climate(ds: xr.Dataset, temp_name: str, precip_name: str, time_name: str, ydim: str, xdim: str):
    temp = ds[temp_name]
    precip = ds[precip_name]
    times = pd.DatetimeIndex(pd.to_datetime(ds[time_name].values))
    keep = (
        (times.year >= START_YEAR)
        & (times.year <= END_YEAR)
        & np.isin(times.month, MONTHS)
    )
    if not keep.any():
        raise RuntimeError("PTHBV file contains no 2011–2025 April–July observations")

    selected_times = times[keep]
    t = temp.isel({time_name: np.where(keep)[0]}).transpose(time_name, ydim, xdim).astype(float)
    p = precip.isel({time_name: np.where(keep)[0]}).transpose(time_name, ydim, xdim).astype(float)

    t_units = str(temp.attrs.get("units", "")).lower()
    if "kelvin" in t_units or t_units.strip() in {"k", "degk"}:
        t = t - 273.15

    day_w = timestep_weights_days(selected_times)
    w_da = xr.DataArray(day_w, coords={time_name: t[time_name]}, dims=[time_name])
    t_mean = t.weighted(w_da).mean(time_name, skipna=True)

    p_units = str(precip.attrs.get("units", "")).lower().replace("**", "^")
    p_acc = p
    if any(s in p_units for s in ["s-1", "/s", "sec-1"]):
        # Convert a rate to accumulation over each timestep.
        seconds = day_w * 86400.0
        p_acc = p * xr.DataArray(seconds, coords={time_name: p[time_name]}, dims=[time_name])
    elif any(s in p_units for s in ["day-1", "/day", "d-1"]):
        p_acc = p * w_da

    # PTHBV precipitation in kg/m2 is numerically mm water.
    annual = []
    for year in range(START_YEAR, END_YEAR + 1):
        idx = np.where(selected_times.year == year)[0]
        if len(idx) == 0:
            raise RuntimeError(f"Missing growing-season climate observations for {year}")
        annual.append(p_acc.isel({time_name: idx}).sum(time_name, skipna=True))
    p_mean_annual = xr.concat(annual, dim="climate_year").mean("climate_year", skipna=True)

    return t_mean, p_mean_annual, {
        "temperature_variable": temp_name,
        "temperature_units_source": str(temp.attrs.get("units", "")),
        "precipitation_variable": precip_name,
        "precipitation_units_source": str(precip.attrs.get("units", "")),
        "selected_time_steps": int(keep.sum()),
        "time_start": str(selected_times.min()),
        "time_end": str(selected_times.max()),
        "monthly_like": bool(np.median(np.diff(selected_times.values).astype("timedelta64[D]").astype(float)) >= 20) if len(selected_times) > 1 else False,
    }


def build_grid(ds: xr.Dataset, t_mean: xr.DataArray, p_mean: xr.DataArray, xdim: str, ydim: str, crs: CRS) -> gpd.GeoDataFrame:
    xv = np.asarray(ds.coords[xdim].values, float)
    yv = np.asarray(ds.coords[ydim].values, float)
    xlo, xhi = coordinate_bounds(xv)
    ylo, yhi = coordinate_bounds(yv)
    tv = np.asarray(t_mean.transpose(ydim, xdim).values, float)
    pv = np.asarray(p_mean.transpose(ydim, xdim).values, float)

    rows = []
    for iy in range(len(yv)):
        for ix in range(len(xv)):
            temp_c = tv[iy, ix]
            precip_mm = pv[iy, ix]
            if not (np.isfinite(temp_c) and np.isfinite(precip_mm)):
                continue
            rows.append({
                "cell_id": f"{iy}:{ix}",
                "temp_apr_jul_c": float(temp_c),
                "precip_apr_jul_mm": float(precip_mm),
                "geometry": box(xlo[ix], ylo[iy], xhi[ix], yhi[iy]),
            })
    if not rows:
        raise RuntimeError("No finite PTHBV climate grid cells after aggregation")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs).to_crs(TARGET_CRS)


def load_field_geometries(local_paths: Path, needed_ids: set[str]) -> gpd.GeoDataFrame:
    cfg = json.loads(local_paths.read_text(encoding="utf-8-sig"))
    source = Path(str(cfg.get("skiften") or ""))
    if not source.exists():
        raise FileNotFoundError(f"2025 skiften source not found: {source}")
    fields = gpd.read_file(source)
    required = {"blockid", "skiftesbeteckning", "geometry"}
    missing = required - set(fields.columns)
    if missing:
        raise RuntimeError(f"2025 skiften source missing columns {sorted(missing)}")
    fields["current_field_id"] = [
        field_id(b, s) for b, s in zip(fields["blockid"], fields["skiftesbeteckning"])
    ]
    fields = fields[fields["current_field_id"].isin(needed_ids)][["current_field_id", "geometry"]].copy()
    if fields["current_field_id"].duplicated().any():
        raise RuntimeError("Duplicate current_field_id in 2025 geometry source")
    missing_ids = needed_ids - set(fields["current_field_id"])
    if missing_ids:
        raise RuntimeError(f"Missing {len(missing_ids)} wheat-field geometries from 2025 source")
    fields = fields.to_crs(TARGET_CRS)
    try:
        from shapely import make_valid
        fields.geometry = fields.geometry.map(make_valid)
    except Exception:
        fields.geometry = fields.geometry.buffer(0)
    fields["field_geometry_area_m2"] = fields.geometry.area
    return fields


def exact_field_climate(fields: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> pd.DataFrame:
    xmin, ymin, xmax, ymax = fields.total_bounds
    grid = grid.cx[xmin:xmax, ymin:ymax].copy()
    if grid.empty:
        raise RuntimeError("No PTHBV grid cells overlap wheat-field bounding box")

    joined = gpd.sjoin(
        fields[["current_field_id", "field_geometry_area_m2", "geometry"]],
        grid[["cell_id", "temp_apr_jul_c", "precip_apr_jul_mm", "geometry"]],
        how="inner", predicate="intersects",
    ).reset_index(drop=True)
    if joined.empty:
        raise RuntimeError("No field/PTHBV-grid intersections")

    right_geoms = grid.geometry.loc[joined["index_right"]].to_list()
    left_geoms = joined.geometry.to_list()
    joined["overlap_m2"] = [
        float(a.intersection(b).area) for a, b in zip(left_geoms, right_geoms)
    ]
    joined = joined[joined["overlap_m2"] > 1e-6].copy()
    joined["temp_x_area"] = joined["temp_apr_jul_c"] * joined["overlap_m2"]
    joined["precip_x_area"] = joined["precip_apr_jul_mm"] * joined["overlap_m2"]

    agg = joined.groupby("current_field_id", sort=False).agg(
        overlap_m2=("overlap_m2", "sum"),
        field_geometry_area_m2=("field_geometry_area_m2", "first"),
        temp_x_area=("temp_x_area", "sum"),
        precip_x_area=("precip_x_area", "sum"),
        climate_cells=("cell_id", "nunique"),
    ).reset_index()
    agg["grid_coverage"] = agg["overlap_m2"] / agg["field_geometry_area_m2"]
    agg["temp_apr_jul_c"] = agg["temp_x_area"] / agg["overlap_m2"]
    agg["precip_apr_jul_mm"] = agg["precip_x_area"] / agg["overlap_m2"]
    agg["precip_apr_jul_mm_day"] = agg["precip_apr_jul_mm"] / 122.0
    return agg


def aggregate_sko(wheat: pd.DataFrame, field_climate: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    w = wheat.merge(
        field_climate[["current_field_id", "grid_coverage", "temp_apr_jul_c", "precip_apr_jul_mm"]],
        on="current_field_id", how="left", validate="many_to_one",
    )
    total_area = float(w["weight_m2"].sum())
    good = w[
        w["temp_apr_jul_c"].notna()
        & w["precip_apr_jul_mm"].notna()
        & w["grid_coverage"].ge(MIN_FIELD_GRID_COVERAGE)
    ].copy()
    good_area = float(good["weight_m2"].sum())

    rows = []
    for sko, g in good.groupby("dominant_sko_id", sort=True):
        rows.append({
            "sko_id": str(sko),
            "field_years_climate": int(len(g)),
            "unique_fields_climate": int(g["current_field_id"].nunique()),
            "wheat_fieldyear_area_ha_climate": float(g["weight_m2"].sum() / 10_000.0),
            "temp_apr_jul_c": weighted_mean(g["temp_apr_jul_c"], g["weight_m2"]),
            "precip_apr_jul_mm": weighted_mean(g["precip_apr_jul_mm"], g["weight_m2"]),
        })
    sko = pd.DataFrame(rows)
    sko["precip_apr_jul_mm_day"] = sko["precip_apr_jul_mm"] / 122.0
    qa = {
        "primary_wheat_field_years": int(len(w)),
        "climate_matched_field_years": int(len(good)),
        "fieldyear_match_share": float(len(good) / len(w)) if len(w) else None,
        "primary_wheat_fieldyear_area_ha": total_area / 10_000.0,
        "climate_matched_fieldyear_area_ha": good_area / 10_000.0,
        "area_match_share": good_area / total_area if total_area else None,
        "min_field_grid_coverage": MIN_FIELD_GRID_COVERAGE,
    }
    return sko, qa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--netcdf", required=True)
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--local-paths", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--temp-var")
    ap.add_argument("--precip-var")
    ap.add_argument("--grid-crs", help="Override NetCDF grid CRS, e.g. EPSG:3006 or EPSG:3021")
    args = ap.parse_args()

    nc_path = Path(args.netcdf)
    input_dir = Path(args.input_dir)
    local_paths = Path(args.local_paths)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not nc_path.exists():
        raise FileNotFoundError(nc_path)

    print("=" * 88)
    print("SMHI PTHBV climate preparation — 2011–2025, April–July")
    print("=" * 88)
    print("NetCDF:", nc_path)
    print("Fields :", local_paths)

    verify_inputs(input_dir)
    ctx, hist, score = load_inputs(input_dir)
    wheat, wheat_qa = prepare_wheat(ctx, hist, score)
    needed_ids = set(wheat["current_field_id"].astype(str).unique())
    print(f"Primary winter-wheat field-years: {len(wheat):,}; unique fields: {len(needed_ids):,}")

    ds = xr.open_dataset(nc_path, decode_times=True)
    temp_name = discover_variable(ds, "temperature", args.temp_var)
    precip_name = discover_variable(ds, "precipitation", args.precip_var)
    time_name = discover_time_name(ds, ds[temp_name])
    xdim, ydim = discover_xy(ds, ds[temp_name], time_name)
    crs = discover_crs(ds, ds[temp_name], xdim, ydim, args.grid_crs)
    print(f"PTHBV variables: temperature={temp_name!r}, precipitation={precip_name!r}")
    print(f"PTHBV axes: time={time_name!r}, x={xdim!r}, y={ydim!r}, CRS={crs.to_string()}")

    t_mean, p_mean, climate_meta = aggregate_climate(
        ds, temp_name, precip_name, time_name, ydim, xdim
    )
    grid = build_grid(ds, t_mean, p_mean, xdim, ydim, crs)
    ds.close()
    print(f"Finite PTHBV cells: {len(grid):,}")

    fields = load_field_geometries(local_paths, needed_ids)
    field_climate = exact_field_climate(fields, grid)
    sko_climate, match_qa = aggregate_sko(wheat, field_climate)

    field_climate.to_csv(output_dir / "field_climate_2011_2025_apr_jul.csv.gz", index=False)
    sko_climate.to_csv(output_dir / "sko_climate_2011_2025_apr_jul.csv", index=False, encoding="utf-8-sig")

    qa = {
        "version": "akerscore-normskord-pthbv-climate-v0a",
        "source": "SMHI PTHBV",
        "netcdf": str(nc_path),
        "period": {"start_year": START_YEAR, "end_year": END_YEAR, "months": list(MONTHS)},
        "spatial_method": "exact current-field polygon x PTHBV grid-cell intersection; then wheat-field-year area weighting",
        "grid_crs": crs.to_string(),
        "grid_cells_finite_sweden": int(len(grid)),
        "wheat_qa": wheat_qa,
        "climate_metadata": climate_meta,
        "match_qa": match_qa,
    }
    (output_dir / "climate_qa.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\nSKO CLIMATE")
    print(sko_climate.to_string(index=False))
    print("\nMATCH QA")
    print(json.dumps(match_qa, ensure_ascii=False, indent=2))
    if match_qa["area_match_share"] is not None and match_qa["area_match_share"] < 0.98:
        print("WARN: less than 98% of primary wheat field-year area received climate data")
    print("\nPTHBV CLIMATE PREPARATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
