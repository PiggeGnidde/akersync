#!/usr/bin/env python3
from pathlib import Path
import argparse,pandas as pd
from common import load_config

REF_SOIL = {
    "Lomma": {
        "clay": 15.995,
        "sand": 53.595,
        "silt": 30.550,
    },
    "Kävlinge": {
        "clay": 10.315,
        "sand": 65.665,
        "silt": 24.135,
    },
    "Eslöv": {
        "clay": 13.920,
        "sand": 52.670,
        "silt": 32.800,
    },
}

def close(name,val,ref,tol):
    ok=abs(val-ref)<=tol
    print(f"{name}: {val:.6g} ref {ref:.6g} tol {tol} -> {'OK' if ok else 'VARNING'}")
    return ok

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default="config/local_paths.json")
    a=ap.parse_args()

    root=Path(__file__).resolve().parents[1]
    cfg=load_config(root/a.config)
    d=root/cfg.get("build_dir","data/derived")

    geo=pd.read_csv(d/"geometry_summary.csv")
    soil=pd.read_csv(d/"soil_summary.csv")
    topo=pd.read_csv(d/"topography_features_blocks.csv")
    hyd=pd.read_csv(d/"hydrology_features_final.csv")

    ok=True

    # Geometry
    blocks=int(geo.blocks.sum())
    skiften=int(geo.skiften.sum())
    gok=(blocks==5919 and skiften==7364)
    ok &= gok
    print("Geometry blocks/skiften:",blocks,skiften,"->","OK" if gok else "VARNING")

    # Derived table sizes
    tok=(len(topo)==5919 and len(hyd)==5919)
    ok &= tok
    print("Topography/Hydrology rows:",len(topo),len(hyd),"->","OK" if tok else "VARNING")

    # Soil: exact medians extracted from the validated v0.92 embedded SOIL payload.
    # Tolerance is intentionally tight because the same raw raster + polygons
    # should reproduce the same zonal statistics.
    for mun in ("Lomma","Kävlinge","Eslöv"):
        r=soil[soil.kommun==mun].iloc[0]
        refs=REF_SOIL[mun]
        ok &= close(f"{mun} median clay",float(r.median_clay_mean_pct),refs["clay"],0.011)
        ok &= close(f"{mun} median sand",float(r.median_sand_mean_pct),refs["sand"],0.011)
        ok &= close(f"{mun} median silt",float(r.median_silt_mean_pct),refs["silt"],0.011)
        ok &= close(f"{mun} median texture sum",float(r.median_texture_sum_pct),100.0,0.011)
        ok &= close(f"{mun} median clay coverage",float(r.median_clay_coverage_pct),
                    {"Lomma":99.76,"Kävlinge":99.70,"Eslöv":99.84}[mun],0.06)

    # Topography / hydrology reference values from validated v0.92 pipeline.
    ok &= close("Median elevation",float(topo.elev_mean_m.median()),59.40,0.25)
    ok &= close("Median mean slope",float(topo.slope_mean_deg.median()),1.540,0.03)
    ok &= close("Farmland TWI P90",float(hyd.farmland_twi_p90_threshold.iloc[0]),11.750808,0.03)
    ok &= close("Farmland TWI P95",float(hyd.farmland_twi_p95_threshold.iloc[0]),14.565125,0.05)

    idx=root/cfg.get("dist_dir","dist")/"index.html"
    iok=idx.exists() and idx.stat().st_size>1_000_000
    ok &= iok
    print("index.html:",idx.exists(),
          f"{idx.stat().st_size/1024/1024:.1f} MB" if idx.exists() else "",
          "->","OK" if iok else "VARNING")

    print("\nBUILD VERIFICATION:", "PASS" if ok else "CHECK WARNINGS")
    raise SystemExit(0 if ok else 1)

if __name__=="__main__":
    main()
