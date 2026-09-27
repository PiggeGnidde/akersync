#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
from pyproj import Transformer

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"work"/"akervatten_mvp_v0a"/"g_sanity_validation"
C=ROOT/"work"/"akervatten_mvp_v0a"/"c_full_linkage"
OUT=ROOT/"work"/"akervatten_mvp_v0a"/"external_validation"
KEY=["blockid","skiftesbeteckning"]

def main():
    OUT.mkdir(parents=True,exist_ok=True)

    reps=pd.read_csv(G/"g_representative_25_cases.csv",dtype={"blockid":str,"skiftesbeteckning":str})
    pts=pd.read_parquet(C/"field_points_3006.parquet")
    for k in KEY:
        pts[k]=pts[k].astype(str)

    # Exactly min/max for each frozen component = 10 intended validation cases.
    q=reps[reps["target_quantile"].round(8).isin([0.0,1.0])].copy()
    q["extreme"]=q["target_quantile"].map({0.0:"MIN",1.0:"MAX"})
    q=q.merge(pts[KEY+["x3006","y3006"]],on=KEY,how="left",validate="many_to_one")
    if q[["x3006","y3006"]].isna().any().any():
        raise RuntimeError("Missing coordinates for one or more extreme fields")

    tr=Transformer.from_crs("EPSG:3006","EPSG:4326",always_xy=True)
    ll=[tr.transform(float(x),float(y)) for x,y in zip(q["x3006"],q["y3006"])]
    q["lon"]=[x for x,y in ll]
    q["lat"]=[y for x,y in ll]

    keep=[
        "component","extreme","actual_score","kommun",
        "blockid","skiftesbeteckning","x3006","y3006","lat","lon"
    ]
    keep=[c for c in keep if c in q.columns]
    q=q[keep].sort_values(["component","extreme"]).reset_index(drop=True)

    out=OUT/"akervatten_external_validation_10_extremes.csv"
    q.to_csv(out,index=False)

    print("="*118)
    print("ÅkerVatten · EXACT 10 EXTREME FIELDS FOR EXTERNAL VALIDATION")
    print("="*118)
    for r in q.itertuples(index=False):
        d=r._asdict()
        print(
            f"{d['component']:23s} {d['extreme']:3s} "
            f"score={float(d['actual_score']):6.2f} · "
            f"{d.get('kommun','?')} · "
            f"{d['blockid']}/{d['skiftesbeteckning']} · "
            f"lat={float(d['lat']):.6f}, lon={float(d['lon']):.6f}"
        )
    print()
    print("Output:",out)
    print("="*118)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
