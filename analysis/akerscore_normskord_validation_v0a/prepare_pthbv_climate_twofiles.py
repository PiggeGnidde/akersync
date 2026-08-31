#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare PTHBV climate covariates when SMHI supplies tas and pr as separate NetCDF files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from prepare_pthbv_climate import (
    START_YEAR,
    END_YEAR,
    MONTHS,
    aggregate_climate,
    aggregate_sko,
    build_grid,
    discover_crs,
    discover_time_name,
    discover_variable,
    discover_xy,
    exact_field_climate,
    load_field_geometries,
)
from run_validation import verify_inputs, load_inputs, prepare_wheat


def _same_numeric(a, b) -> bool:
    aa = np.asarray(a)
    bb = np.asarray(b)
    return aa.shape == bb.shape and np.allclose(aa.astype(float), bb.astype(float), rtol=0, atol=1e-9, equal_nan=True)


def _same_time(a, b) -> bool:
    aa = pd.DatetimeIndex(pd.to_datetime(np.asarray(a)))
    bb = pd.DatetimeIndex(pd.to_datetime(np.asarray(b)))
    return len(aa) == len(bb) and np.array_equal(aa.values, bb.values)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--temp-netcdf", required=True)
    ap.add_argument("--precip-netcdf", required=True)
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--local-paths", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--temp-var")
    ap.add_argument("--precip-var")
    ap.add_argument("--grid-crs", help="Override NetCDF grid CRS, e.g. EPSG:3006 or EPSG:3021")
    args = ap.parse_args()

    temp_path = Path(args.temp_netcdf)
    precip_path = Path(args.precip_netcdf)
    input_dir = Path(args.input_dir)
    local_paths = Path(args.local_paths)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for p in (temp_path, precip_path):
        if not p.exists():
            raise FileNotFoundError(p)

    print("=" * 88)
    print("SMHI PTHBV climate preparation — separate tas/pr files")
    print(f"Period: {START_YEAR}-{END_YEAR}; months: {MONTHS}")
    print("=" * 88)
    print("Temperature NetCDF :", temp_path)
    print("Precipitation NetCDF:", precip_path)
    print("Fields             :", local_paths)

    verify_inputs(input_dir)
    ctx, hist, score = load_inputs(input_dir)
    wheat, wheat_qa = prepare_wheat(ctx, hist, score)
    needed_ids = set(wheat["current_field_id"].astype(str).unique())
    print(f"Primary winter-wheat field-years: {len(wheat):,}; unique fields: {len(needed_ids):,}")

    ds_t = xr.open_dataset(temp_path, decode_times=True)
    ds_p = xr.open_dataset(precip_path, decode_times=True)
    try:
        temp_name = discover_variable(ds_t, "temperature", args.temp_var)
        precip_name = discover_variable(ds_p, "precipitation", args.precip_var)

        t_time = discover_time_name(ds_t, ds_t[temp_name])
        p_time = discover_time_name(ds_p, ds_p[precip_name])
        t_x, t_y = discover_xy(ds_t, ds_t[temp_name], t_time)
        p_x, p_y = discover_xy(ds_p, ds_p[precip_name], p_time)
        crs_t = discover_crs(ds_t, ds_t[temp_name], t_x, t_y, args.grid_crs)
        crs_p = discover_crs(ds_p, ds_p[precip_name], p_x, p_y, args.grid_crs)

        if crs_t != crs_p:
            raise RuntimeError(f"Temperature and precipitation grids have different CRS: {crs_t} vs {crs_p}")
        if not _same_numeric(ds_t[t_x].values, ds_p[p_x].values):
            raise RuntimeError("Temperature and precipitation x coordinates differ")
        if not _same_numeric(ds_t[t_y].values, ds_p[p_y].values):
            raise RuntimeError("Temperature and precipitation y coordinates differ")
        if not _same_time(ds_t[t_time].values, ds_p[p_time].values):
            raise RuntimeError("Temperature and precipitation time coordinates differ")

        rename = {}
        if p_time != t_time:
            rename[p_time] = t_time
        if p_x != t_x:
            rename[p_x] = t_x
        if p_y != t_y:
            rename[p_y] = t_y
        p_da = ds_p[precip_name].rename(rename) if rename else ds_p[precip_name]

        # Keep the temperature grid coordinates as the canonical PTHBV grid.
        merged = xr.Dataset(
            {
                temp_name: ds_t[temp_name],
                precip_name: p_da,
            }
        )

        print(f"PTHBV variables: temperature={temp_name!r}, precipitation={precip_name!r}")
        print(f"PTHBV axes: time={t_time!r}, x={t_x!r}, y={t_y!r}, CRS={crs_t.to_string()}")

        t_mean, p_mean, climate_meta = aggregate_climate(
            merged, temp_name, precip_name, t_time, t_y, t_x
        )
        grid = build_grid(ds_t, t_mean, p_mean, t_x, t_y, crs_t)
        print(f"Finite PTHBV cells: {len(grid):,}")

        fields = load_field_geometries(local_paths, needed_ids)
        field_climate = exact_field_climate(fields, grid)
        sko_climate, match_qa = aggregate_sko(wheat, field_climate)

        field_climate.to_csv(output_dir / "field_climate_2011_2025_apr_jul.csv.gz", index=False)
        sko_climate.to_csv(
            output_dir / "sko_climate_2011_2025_apr_jul.csv",
            index=False,
            encoding="utf-8-sig",
        )

        qa = {
            "version": "akerscore-normskord-pthbv-climate-v0a-twofiles",
            "source": "SMHI PTHBV",
            "temperature_netcdf": str(temp_path),
            "precipitation_netcdf": str(precip_path),
            "period": {"start_year": START_YEAR, "end_year": END_YEAR, "months": list(MONTHS)},
            "spatial_method": "exact current-field polygon x PTHBV grid-cell intersection; then wheat-field-year area weighting",
            "grid_crs": crs_t.to_string(),
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
    finally:
        ds_t.close()
        ds_p.close()


if __name__ == "__main__":
    raise SystemExit(main())
