#!/usr/bin/env python3
"""STOPPUNKT B0: select a compact, fully-covered 2025 geometry pilot. Public STAC only."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_v0.json"

def stac(url,collection,bbox,day):
    d=date.fromisoformat(day); e=d+timedelta(days=1)
    p={"collections":[collection],"bbox":bbox,"datetime":f"{d}T00:00:00Z/{e}T00:00:00Z","limit":100}
    q=urllib.request.Request(url,data=json.dumps(p).encode(),method="POST",headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(q,timeout=90) as r: return json.loads(r.read().decode())["features"]

def infer_ids(g):
    import pandas as pd
    cols={c.lower():c for c in g.columns}
    if "blockid" in cols and "skiftesbeteckning" in cols:
        return ("2025|"+g[cols["blockid"]].astype(str)+"|"+g[cols["skiftesbeteckning"]].astype(str)).astype(str), "blockid+skiftesbeteckning"
    for key in ("current_field_id","skiftesid","skifte_id","objectid","id"):
        if key in cols:
            return g[cols[key]].astype(str), cols[key]
    vals=[]
    for geom in g.geometry:
        vals.append("G2025_"+hashlib.sha256(geom.wkb).hexdigest()[:20])
    return pd.Series(vals,index=g.index,dtype=str), "geometry_sha256_20"

def main():
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import shape
    from shapely.ops import unary_union

    ap=argparse.ArgumentParser()
    ap.add_argument("--local-paths",default=str(ROOT/"config"/"local_paths.json"))
    ap.add_argument("--output-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopb0_selection")
    ap.add_argument("--target-fields",type=int,default=220)
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    lp=json.loads(Path(args.local_paths).read_text(encoding="utf-8-sig"))
    src=Path(lp["skiften"])
    g=gpd.read_file(src)
    if len(g)!=cfg["upstream_freeze"]["expected_2025_fields"]: raise RuntimeError("Frozen field count mismatch")
    if g.crs is None: raise RuntimeError("2025 geometry has no CRS")
    ids,id_basis=infer_ids(g); g=g.copy(); g["parent_field_id_2025"]=ids
    g=g[g.geometry.notna() & ~g.geometry.is_empty & g.geometry.is_valid].copy().to_crs(32633)
    g["area_ha_2025"]=g.geometry.area/10000.0
    bbox=list(map(float,g.to_crs(4326).total_bounds))

    cover={}
    for snap,days in cfg["snapshots"].items():
        fps=[]
        for day in days:
            fps += [shape(i["geometry"]) for i in stac(cfg["sentinel2"]["stac_search_url"],cfg["sentinel2"]["collection"],bbox,day)]
        u=unary_union(fps)
        cover[snap]=gpd.GeoSeries([u],crs=4326).to_crs(32633).iloc[0]

    # B0 should be a clean four-snapshot baseline: >=99.5% footprint coverage for every frozen snapshot.
    eligible=(g["area_ha_2025"]>=1.0) & (g["area_ha_2025"]<=80.0)
    for snap,u in cover.items():
        frac=g.geometry.intersection(u).area/g.geometry.area
        g[f"footprint_{snap.lower()}"]=frac
        eligible &= frac>=0.995
    e=g[eligible].copy()
    if len(e)<args.target_fields: raise RuntimeError(f"Only {len(e)} fully-covered eligible fields")

    # Deterministic compact cluster near the spatial median of eligible agriculture.
    c=e.geometry.centroid
    mx=float(c.x.median()); my=float(c.y.median())
    e["_cx"]=c.x; e["_cy"]=c.y
    e["_dist2"]=(e["_cx"]-mx)**2+(e["_cy"]-my)**2
    pilot=e.nsmallest(args.target_fields,"_dist2").copy()

    # Add a one-ring of directly adjacent eligible neighbors, capped at 320 total.
    sidx=e.sindex
    selected=set(pilot.index.tolist())
    for idx,row in pilot.iterrows():
        q=row.geometry.buffer(3.0)
        for j in sidx.query(q,predicate="intersects"):
            j=e.index[int(j)]
            if j==idx: continue
            if row.geometry.distance(e.loc[j].geometry)<=3.0:
                selected.add(j)
    expanded=e.loc[list(selected)].copy()
    if len(expanded)>320:
        expanded=expanded.nsmallest(320,"_dist2").copy()
    pilot=expanded

    # Adjacency pairs inside pilot; near-touch <=3 m, with shared boundary length when exact topology touches.
    ps=pilot.sindex; pairs=[]; seen=set()
    for idx,row in pilot.iterrows():
        for pos in ps.query(row.geometry.buffer(3.0),predicate="intersects"):
            j=pilot.index[int(pos)]
            if j==idx: continue
            key=tuple(sorted((str(row["parent_field_id_2025"]),str(pilot.loc[j,"parent_field_id_2025"]))))
            if key in seen: continue
            d=float(row.geometry.distance(pilot.loc[j].geometry))
            if d>3.0: continue
            seen.add(key)
            shared=float(row.geometry.boundary.intersection(pilot.loc[j].geometry.boundary).length)
            pairs.append({"field_a":key[0],"field_b":key[1],"distance_m":round(d,3),"shared_boundary_m":round(shared,3)})

    drop=["_cx","_cy","_dist2"]
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    pilot.drop(columns=drop,errors="ignore").to_file(out/"pilot_fields_2025.gpkg",layer="pilot_fields",driver="GPKG")
    pd.DataFrame(pairs).to_csv(out/"pilot_adjacency.csv",index=False)
    b=pilot.to_crs(4326).total_bounds
    summary={
      "schema_version":"akerpuls-prelim-fields-2026-stopb0-v1",
      "status":"PASS",
      "generated_utc":datetime.now(timezone.utc).isoformat(),
      "frozen_dates":cfg["snapshots"],
      "rescue_dates_used":False,
      "id_basis":id_basis,
      "eligible_four_snapshot_fields":int(len(e)),
      "pilot_fields":int(len(pilot)),
      "adjacency_pairs":int(len(pairs)),
      "pilot_area_ha":round(float(pilot["area_ha_2025"].sum()),3),
      "pilot_bbox_wgs84":[round(float(x),6) for x in b],
      "area_ha_p10":round(float(pilot["area_ha_2025"].quantile(.1)),3),
      "area_ha_p50":round(float(pilot["area_ha_2025"].median()),3),
      "area_ha_p90":round(float(pilot["area_ha_2025"].quantile(.9)),3),
      "next_step":"bounded 10 m Sentinel-2 tile download and split/merge baseline for these fields only"
    }
    (out/"pilot_selection_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT B0 PILOT SELECTION")
    for k,v in summary.items():
        if k not in ("frozen_dates",): print(f"{k.upper()}={v}")
    print("SENTINEL_HUB_PU_USED=0")
    return 0

if __name__=="__main__": raise SystemExit(main())
