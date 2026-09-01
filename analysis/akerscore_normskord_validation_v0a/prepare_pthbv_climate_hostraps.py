#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare fixed 2011–2025 Apr–Jul PTHBV climate covariates for Höstraps field-years.

Apr–Jul is deliberately kept identical to the previous crop replications. For
winter rapeseed it is a spring/summer yield-forming climate proxy, not the full
crop lifecycle (autumn establishment and winter are not represented).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from prepare_pthbv_climate import (
    START_YEAR, END_YEAR, MONTHS, aggregate_climate, aggregate_sko, build_grid,
    discover_crs, discover_time_name, discover_variable, discover_xy,
    exact_field_climate, load_field_geometries,
)
from prepare_pthbv_climate_twofiles import _same_numeric, _same_month_axis, _month_keys
from run_validation import verify_inputs, load_inputs
from run_hostraps_validation import prepare_crop, CROP_LABEL


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--temp-netcdf", required=True)
    ap.add_argument("--precip-netcdf", required=True)
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--local-paths", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--grid-crs")
    args = ap.parse_args()

    temp_path = Path(args.temp_netcdf)
    precip_path = Path(args.precip_netcdf)
    input_dir = Path(args.input_dir)
    local_paths = Path(args.local_paths)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    verify_inputs(input_dir)
    ctx, hist, score = load_inputs(input_dir)
    crop, crop_qa = prepare_crop(ctx, hist, score)
    needed_ids = set(crop["current_field_id"].astype(str).unique())

    print("=" * 88)
    print(f"SMHI PTHBV climate preparation — {CROP_LABEL}")
    print(f"Period: {START_YEAR}-{END_YEAR}; months: {MONTHS}")
    print("=" * 88)
    print(f"Primary crop field-years: {len(crop):,}; unique fields: {len(needed_ids):,}")

    ds_t = xr.open_dataset(temp_path, decode_times=True)
    ds_p = xr.open_dataset(precip_path, decode_times=True)
    try:
        temp_name = discover_variable(ds_t, "temperature", None)
        precip_name = discover_variable(ds_p, "precipitation", None)
        t_time = discover_time_name(ds_t, ds_t[temp_name])
        p_time = discover_time_name(ds_p, ds_p[precip_name])
        t_x, t_y = discover_xy(ds_t, ds_t[temp_name], t_time)
        p_x, p_y = discover_xy(ds_p, ds_p[precip_name], p_time)
        crs_t = discover_crs(ds_t, ds_t[temp_name], t_x, t_y, args.grid_crs)
        crs_p = discover_crs(ds_p, ds_p[precip_name], p_x, p_y, args.grid_crs)
        if crs_t != crs_p:
            raise RuntimeError(f"tas/pr CRS differ: {crs_t} vs {crs_p}")
        if not _same_numeric(ds_t[t_x].values, ds_p[p_x].values):
            raise RuntimeError("tas/pr x coordinates differ")
        if not _same_numeric(ds_t[t_y].values, ds_p[p_y].values):
            raise RuntimeError("tas/pr y coordinates differ")
        if not _same_month_axis(ds_t[t_time].values, ds_p[p_time].values):
            raise RuntimeError(
                f"tas/pr calendar-month axes differ: tas={_month_keys(ds_t[t_time].values)[:3]}..., "
                f"pr={_month_keys(ds_p[p_time].values)[:3]}..."
            )

        t_idx = pd.DatetimeIndex(pd.to_datetime(ds_t[t_time].values))
        p_idx = pd.DatetimeIndex(pd.to_datetime(ds_p[p_time].values))
        max_offset = float(np.max(np.abs((p_idx - t_idx).total_seconds()))) if len(t_idx) else 0.0
        rename = {}
        if p_time != t_time: rename[p_time] = t_time
        if p_x != t_x: rename[p_x] = t_x
        if p_y != t_y: rename[p_y] = t_y
        p_da = ds_p[precip_name].rename(rename) if rename else ds_p[precip_name]
        p_da = p_da.assign_coords({t_time: ds_t[t_time].values})
        merged = xr.Dataset({temp_name: ds_t[temp_name], precip_name: p_da})

        t_mean, p_mean, climate_meta = aggregate_climate(
            merged, temp_name, precip_name, t_time, t_y, t_x
        )
        climate_meta["tas_pr_time_alignment"] = "calendar_month"
        climate_meta["tas_pr_max_timestamp_offset_seconds"] = max_offset
        climate_meta["crop_window_interpretation"] = (
            "Apr-Jul spring/summer yield-forming climate proxy; not full winter-rapeseed lifecycle"
        )
        grid = build_grid(ds_t, t_mean, p_mean, t_x, t_y, crs_t)
        print(f"Finite PTHBV cells: {len(grid):,}")

        fields = load_field_geometries(local_paths, needed_ids)
        field_climate = exact_field_climate(fields, grid)
        sko_climate, match_qa = aggregate_sko(crop, field_climate)

        field_climate.to_csv(output_dir / "field_climate_2011_2025_apr_jul.csv.gz", index=False)
        sko_climate.to_csv(
            output_dir / "sko_climate_2011_2025_apr_jul.csv", index=False, encoding="utf-8-sig"
        )
        qa = {
            "version": "akerscore-normskord-pthbv-hostraps-v0a",
            "crop": CROP_LABEL,
            "period": {"start_year": START_YEAR, "end_year": END_YEAR, "months": list(MONTHS)},
            "spatial_method": (
                "exact current-field polygon x PTHBV grid-cell intersection; "
                "then winter-rapeseed field-year area weighting"
            ),
            "climate_window_guardrail": (
                "Apr-Jul is kept fixed for replication and does not include autumn establishment or winter."
            ),
            "crop_qa": crop_qa,
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
        print("\nHÖSTRAPS PTHBV CLIMATE PREPARATION: PASS")
        return 0
    finally:
        ds_t.close()
        ds_p.close()


if __name__ == "__main__":
    raise SystemExit(main())
