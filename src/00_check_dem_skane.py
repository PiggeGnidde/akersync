#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan",default="data/derived/dem_plan_skane.csv")
    ap.add_argument("--dem",default=r"C:\AkerSyncRaw\dem_skane_2p5km")
    a=ap.parse_args()

    root=Path(__file__).resolve().parents[1]
    plan=Path(a.plan)
    if not plan.is_absolute(): plan=root/plan
    dem=Path(a.dem)
    if not plan.exists(): raise SystemExit(f"Plan saknas: {plan}")
    if not dem.exists(): raise SystemExit(f"DEM-mapp saknas: {dem}")

    df=pd.read_csv(plan,dtype={"filename":str})
    expected={str(x).lower() for x in df.filename}
    present_paths=list(dem.glob("*.tif"))
    present={p.name.lower() for p in present_paths}

    missing=expected-present
    extra=present-expected

    mdf=df[df.filename.str.lower().isin(missing)].copy()
    missing_core_rows=mdf[mdf.core_farmland.fillna(False).astype(bool)].copy() if len(mdf) else mdf.copy()
    missing_ring_rows=mdf[mdf.one_ring.fillna(False).astype(bool)].copy() if len(mdf) else mdf.copy()
    missing_core=len(missing_core_rows)
    missing_ring=len(missing_ring_rows)

    print("="*72)
    print("ÅkerSync · kontroll Skåne DEM 2.5 km")
    print("="*72)
    print(f"Planerade rectangle-rutor: {len(expected):,}")
    print(f"GeoTIFF i DEM-mappen:      {len(present):,}")
    print(f"Planerade filer hittade:   {len(expected & present):,}")
    print(f"Planerade filer saknas:    {len(missing):,}")
    print(f"  varav core farmland:     {missing_core:,}")
    print(f"  varav one-ring:          {missing_ring:,}")
    print(f"Extra .tif utanför planen: {len(extra):,}")

    out=root/"data"/"derived"/"dem_still_missing_skane.csv"
    mdf.to_csv(out,index=False,encoding="utf-8-sig")
    print("\nÅterstående lista:",out)

    if missing_core:
        print("\nSAKNADE CORE-RUTOR:")
        for name in missing_core_rows.filename:
            print("  ",name)

    if missing_ring:
        print("\nSAKNADE ONE-RING-RUTOR:")
        for name in missing_ring_rows.filename:
            marker=" [CORE]" if str(name).lower() in {str(x).lower() for x in missing_core_rows.filename} else ""
            print("  ",str(name)+marker)

    if not missing:
        print(f"\nDEM CHECK: KOMPLETT {len(expected):,}/{len(expected):,}")
        return 0
    if missing_core==0:
        print("\nDEM CHECK: all farmland-core finns.")
        print("Återstående one-ring/rectangle-rutor kan vara hav eller verkliga luckor;")
        print("granska topologin innan BUILD_ALL.")
        return 0

    print("\nDEM CHECK: DATA SAKNAS I FARMLAND-CORE — kör inte BUILD_ALL ännu.")
    return 1


if __name__=="__main__":
    raise SystemExit(main())
