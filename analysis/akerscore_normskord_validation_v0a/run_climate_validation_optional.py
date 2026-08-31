#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the standard climate model only when at least 8 complete SKO remain."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sko-fit-table", required=True); ap.add_argument("--climate-csv", required=True)
    ap.add_argument("--output-dir", required=True); ap.add_argument("--exclude-sko", nargs="*", default=[])
    ap.add_argument("--label", default="crop")
    args = ap.parse_args()

    fit = pd.read_csv(args.sko_fit_table, dtype={"sko_id": str}); climate = pd.read_csv(args.climate_csv, dtype={"sko_id": str})
    fit["sko_id"] = fit["sko_id"].astype(str).str.zfill(4); climate["sko_id"] = climate["sko_id"].astype(str).str.zfill(4)
    df = fit.merge(climate, on="sko_id", how="inner", validate="one_to_one")
    if args.exclude_sko:
        ex = {str(v).zfill(4) for v in args.exclude_sko}; df = df[~df["sko_id"].isin(ex)].copy()
    needed = ["norm_t_ha", "mean_akerscore_areaweighted", "temp_apr_jul_c", "precip_apr_jul_mm"]
    n = len(df.dropna(subset=needed))
    if n < 8:
        print(f"{args.label}: climate model SKIPPED — only {n} complete SKO (<8 guardrail).")
        print("Score-only output remains available; 4-parameter climate LOOCV would be too thin.")
        return 0

    script = Path(__file__).with_name("run_climate_validation.py")
    cmd = [sys.executable, str(script), "--sko-fit-table", args.sko_fit_table, "--climate-csv", args.climate_csv, "--output-dir", args.output_dir]
    if args.exclude_sko: cmd += ["--exclude-sko", *args.exclude_sko]
    return subprocess.call(cmd)


if __name__ == "__main__": raise SystemExit(main())
