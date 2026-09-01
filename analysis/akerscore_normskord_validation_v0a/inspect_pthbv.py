#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
import xarray as xr


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect SMHI PTHBV NetCDF structure.")
    ap.add_argument("netcdf")
    args = ap.parse_args()
    path = Path(args.netcdf)
    if not path.exists():
        raise FileNotFoundError(path)
    ds = xr.open_dataset(path, decode_times=True)
    print(ds)
    print("\nGLOBAL ATTRS")
    for k, v in ds.attrs.items():
        print(f"  {k}: {v}")
    print("\nVARIABLES")
    for name, da in ds.variables.items():
        print(f"\n{name}: dims={da.dims} shape={da.shape} dtype={da.dtype}")
        for k, v in da.attrs.items():
            print(f"  {k}: {v}")
    ds.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
