#!/usr/bin/env python3
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
from common import load_config, MUN_CODES, CSV_MUN_TO_UI

REF_SOIL = {
    "Lomma": {"clay":15.995,"sand":53.595,"silt":30.550,"coverage":99.76},
    "Kävlinge": {"clay":10.315,"sand":65.665,"silt":24.135,"coverage":99.70},
    "Eslöv": {"clay":13.920,"sand":52.670,"silt":32.800,"coverage":99.84},
}
LEGACY_MUN={"Lomma","Kävlinge","Eslöv"}


def ui_name(v):
    return CSV_MUN_TO_UI.get(str(v),str(v))


def close(name,val,ref,tol):
    ok=np.isfinite(val) and abs(val-ref)<=tol
    print(f"{name}: {val:.6g} ref {ref:.6g} tol {tol} -> {'OK' if ok else 'VARNING'}")
    return ok


def check_range(name,series,lo,hi):
    x=pd.to_numeric(series,errors="coerce").dropna()
    ok=(len(x)>0 and bool(((x>=lo)&(x<=hi)).all()))
    print(f"{name}: n={len(x)} range [{x.min() if len(x) else '–'}, {x.max() if len(x) else '–'}] -> {'OK' if ok else 'VARNING'}")
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
    topo=pd.read_csv(d/"topography_features_blocks.csv",dtype={"blockid":str,"region_kod":str})
    hyd=pd.read_csv(d/"hydrology_features_final.csv",dtype={"blockid":str,"region_kod":str})
    payload=json.loads((d/"geometry_payload.json").read_text(encoding="utf-8"))

    ok=True
    expected=set(MUN_CODES)
    actual_geo=set(geo.kommun.astype(str))
    actual_payload=set(payload)
    mok=(actual_geo==expected and actual_payload==expected)
    ok &= mok
    print(f"Skånekommuner geometry/payload: {len(actual_geo)}/{len(actual_payload)} av {len(expected)} -> {'OK' if mok else 'VARNING'}")
    if not mok:
        print("  saknas geometry:",sorted(expected-actual_geo))
        print("  saknas payload:",sorted(expected-actual_payload))
        print("  oväntade:",sorted((actual_geo|actual_payload)-expected))

    blocks=int(pd.to_numeric(geo.blocks,errors="coerce").fillna(0).sum())
    skiften=int(pd.to_numeric(geo.skiften,errors="coerce").fillna(0).sum())
    gok=(blocks>5919 and skiften>7364)
    ok &= gok
    print("Geometry blocks/skiften:",blocks,skiften,"->","OK" if gok else "VARNING")

    tok=(len(topo)==blocks and len(hyd)==blocks and topo.blockid.nunique()==blocks and hyd.blockid.nunique()==blocks)
    ok &= tok
    print("Topography/Hydrology rows:",len(topo),len(hyd),"expected",blocks,"->","OK" if tok else "VARNING")

    # Absolute terrain features for the original three municipalities should
    # remain unchanged even though the reference population is now all Skåne.
    topo_ui=topo.municipality.map(ui_name)
    legacy_topo=topo[topo_ui.isin(LEGACY_MUN)]
    lok=len(legacy_topo)>0
    ok &= lok
    print("Legacy topography subset rows:",len(legacy_topo),"->","OK" if lok else "VARNING")
    if lok:
        ok &= close("Legacy median elevation",float(legacy_topo.elev_mean_m.median()),59.40,0.25)
        ok &= close("Legacy median mean slope",float(legacy_topo.slope_mean_deg.median()),1.540,0.03)
        ok &= close("Legacy median relief",float(legacy_topo.relief_p95_p05_m.median()),3.16,0.08)

    # Soil regression checks are municipality-local and should be invariant.
    for mun,refs in REF_SOIL.items():
        sub=soil[soil.kommun==mun]
        if len(sub)!=1:
            print(f"{mun} soil summary row saknas/dubbel -> VARNING")
            ok=False
            continue
        r=sub.iloc[0]
        ok &= close(f"{mun} median clay",float(r.median_clay_mean_pct),refs["clay"],0.011)
        ok &= close(f"{mun} median sand",float(r.median_sand_mean_pct),refs["sand"],0.011)
        ok &= close(f"{mun} median silt",float(r.median_silt_mean_pct),refs["silt"],0.011)
        ok &= close(f"{mun} median texture sum",float(r.median_texture_sum_pct),100.0,0.011)
        ok &= close(f"{mun} median clay coverage",float(r.median_clay_coverage_pct),refs["coverage"],0.06)

    # Full-Skåne completeness / sanity. Relative TWI thresholds are expected to
    # change versus v0.92, so verify ordering and finite coverage, not old values.
    topo_complete=int(pd.to_numeric(topo.elev_mean_m,errors="coerce").notna().sum())==blocks
    hydro_complete=int(pd.to_numeric(hyd.twi_mean,errors="coerce").notna().sum())==blocks
    ok &= topo_complete and hydro_complete
    print("Topography complete:",topo_complete,"Hydrology complete:",hydro_complete,
          "->","OK" if topo_complete and hydro_complete else "VARNING")

    ok &= check_range("DEM coverage %",topo.dem_coverage_pct,0,100.0001)
    ok &= check_range("TWI coverage %",hyd.twi_coverage_pct,0,100.0001)
    ok &= check_range("Farmland P90 share %",hyd.twi_ge_farmland_p90_pct,0,100.0001)
    ok &= check_range("Farmland P95 share %",hyd.twi_ge_farmland_p95_pct,0,100.0001)

    p90s=pd.to_numeric(hyd.farmland_twi_p90_threshold,errors="coerce").dropna()
    p95s=pd.to_numeric(hyd.farmland_twi_p95_threshold,errors="coerce").dropna()
    th_ok=(len(p90s)==blocks and len(p95s)==blocks and p90s.nunique()==1 and p95s.nunique()==1 and float(p95s.iloc[0])>float(p90s.iloc[0]))
    ok &= th_ok
    if len(p90s) and len(p95s):
        print(f"Skåne farmland TWI: P90={p90s.iloc[0]:.6f}, P95={p95s.iloc[0]:.6f} -> {'OK' if th_ok else 'VARNING'}")
    else:
        print("Skåne farmland TWI thresholds saknas -> VARNING")

    # Web is intentionally split into one page per municipality.  This is a
    # scalability check: no giant all-Skåne HTML is required in the browser.
    dist=root/cfg.get("dist_dir","dist")
    idx=dist/"index.html";manifest_path=dist/"municipalities.json";page_dir=dist/"municipalities"
    pages=sorted(page_dir.glob("*.html")) if page_dir.exists() else []
    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except Exception:
        manifest={}
    web_ok=(idx.exists() and len(pages)==len(expected) and set(manifest)==expected and all(p.stat().st_size>100_000 for p in pages))
    ok &= web_ok
    max_mb=max((p.stat().st_size for p in pages),default=0)/1024/1024
    total_mb=sum((p.stat().st_size for p in pages),0)/1024/1024
    print(f"Web: landing={idx.exists()} pages={len(pages)}/{len(expected)} manifest={len(manifest)} total={total_mb:.1f} MB max={max_mb:.1f} MB -> {'OK' if web_ok else 'VARNING'}")

    print("\nSKÅNE BUILD VERIFICATION:", "PASS" if ok else "CHECK WARNINGS")
    raise SystemExit(0 if ok else 1)


if __name__=="__main__":
    main()
