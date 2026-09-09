#!/usr/bin/env python3
"""STOPPUNKT C0: select a larger geographically independent pilot. Public STAC only, zero PU."""
from __future__ import annotations
import argparse, json, math, urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MASTER=ROOT/"config"/"akerpuls_prelim_fields_2026_v0.json"
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_c0.json"

def stac(url,collection,bbox,day):
    d=date.fromisoformat(day); e=d+timedelta(days=1)
    p={"collections":[collection],"bbox":bbox,"datetime":f"{d}T00:00:00Z/{e}T00:00:00Z","limit":100}
    req=urllib.request.Request(url,data=json.dumps(p).encode(),method="POST",headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))["features"]

def main():
    import geopandas as gpd, pandas as pd
    from shapely.geometry import shape, box
    from shapely.ops import unary_union

    ap=argparse.ArgumentParser()
    ap.add_argument("--local-paths",default=str(ROOT/"config"/"local_paths.json"))
    ap.add_argument("--output-dir")
    args=ap.parse_args()

    master=json.loads(MASTER.read_text(encoding="utf-8"))
    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    selcfg=cfg["selection"]
    out=Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True,exist_ok=True)
    lp=json.loads(Path(args.local_paths).read_text(encoding="utf-8-sig"))
    g=gpd.read_file(Path(lp["skiften"]))
    if len(g)!=master["upstream_freeze"]["expected_2025_fields"]:
        raise RuntimeError(f"Frozen field count mismatch: {len(g)}")
    g=g[g.geometry.notna() & ~g.geometry.is_empty & g.geometry.is_valid].copy().to_crs(32633)
    g["area_ha_2025"]=g.geometry.area/10000.0
    if "blockid" in g.columns and "skiftesbeteckning" in g.columns:
        g["parent_field_id_2025"]="2025|"+g["blockid"].astype(str)+"|"+g["skiftesbeteckning"].astype(str)
    else:
        raise RuntimeError("C0 requires blockid + skiftesbeteckning for stable IDs")

    b0=gpd.read_file(Path(cfg["b0_pilot_dir"])/"pilot_fields_2025.gpkg").to_crs(32633)
    bcent=b0.geometry.union_all().centroid if hasattr(b0.geometry,"union_all") else b0.geometry.unary_union.centroid

    bbox4326=list(map(float,g.to_crs(4326).total_bounds))
    cover={}
    for snap,days in master["snapshots"].items():
        fps=[]
        for day in days:
            fps += [shape(i["geometry"]) for i in stac(master["sentinel2"]["stac_search_url"],master["sentinel2"]["collection"],bbox4326,day)]
        u=unary_union(fps)
        cover[snap]=gpd.GeoSeries([u],crs=4326).to_crs(32633).iloc[0]

    eligible=(g["area_ha_2025"]>=float(selcfg["minimum_area_ha"])) & (g["area_ha_2025"]<=float(selcfg["maximum_area_ha"]))
    for snap,u in cover.items():
        frac=g.geometry.intersection(u).area/g.geometry.area
        g[f"footprint_{snap.lower()}"]=frac
        eligible &= frac>=float(selcfg["minimum_four_snapshot_footprint_fraction"])
    e=g[eligible].copy()
    cent=e.geometry.centroid
    e["_cx"]=cent.x; e["_cy"]=cent.y
    e["_dist_b"]=((e["_cx"]-bcent.x)**2+(e["_cy"]-bcent.y)**2)**0.5
    e=e[e["_dist_b"]>=float(selcfg["minimum_distance_from_b_pilot_m"])].copy()
    if len(e)<int(selcfg["minimum_fields"]):
        raise RuntimeError(f"Only {len(e)} geographically independent fully covered fields")

    grid=float(selcfg["grid_size_m"])
    minx,miny,maxx,maxy=e.total_bounds
    cells=[]
    ix0=math.floor(minx/grid); ix1=math.floor(maxx/grid)
    iy0=math.floor(miny/grid); iy1=math.floor(maxy/grid)
    sidx=e.sindex
    for ix in range(ix0,ix1+1):
        for iy in range(iy0,iy1+1):
            cell=box(ix*grid,iy*grid,(ix+1)*grid,(iy+1)*grid)
            ids=list(sidx.query(cell,predicate="intersects"))
            if not ids: continue
            sub=e.iloc[ids]
            n=len(sub)
            if n<int(selcfg["minimum_fields"]): continue
            cc=cell.centroid
            dist=((cc.x-bcent.x)**2+(cc.y-bcent.y)**2)**0.5
            cells.append({"ix":ix,"iy":iy,"n":n,"area_ha":float(sub["area_ha_2025"].sum()),"dist_b_m":dist,"geometry":cell})
    if not cells:
        raise RuntimeError("No 20 km independent cell satisfies minimum field count")
    cdf=gpd.GeoDataFrame(cells,geometry="geometry",crs=32633)
    # Prefer density, then distance from B as tie-break.
    cdf=cdf.sort_values(["n","dist_b_m"],ascending=[False,False]).reset_index(drop=True)
    best=cdf.iloc[0]
    cell=best.geometry
    ids=list(e.sindex.query(cell,predicate="intersects"))
    cand=e.iloc[ids].copy()
    cand["_dcell"]=cand.geometry.centroid.distance(cell.centroid)
    target=min(int(selcfg["target_fields"]),int(selcfg["maximum_fields"]),len(cand))
    if target<int(selcfg["minimum_fields"]):
        raise RuntimeError(f"Selected cell only has {len(cand)} fields")
    pilot=cand.nsmallest(target,"_dcell").copy()
    pilot=pilot.drop(columns=["_cx","_cy","_dist_b","_dcell"],errors="ignore")

    pilot.to_file(out/"c0_pilot_fields_2025.gpkg",layer="pilot_fields",driver="GPKG")
    cdf.head(20).to_file(out/"c0_candidate_cells.gpkg",layer="candidate_cells",driver="GPKG")
    b=pilot.to_crs(4326).total_bounds
    pcent=pilot.geometry.union_all().centroid if hasattr(pilot.geometry,"union_all") else pilot.geometry.unary_union.centroid
    summary={
      "schema_version":"akerpuls-prelim-fields-2026-c0-independent-pilot-v1",
      "status":"PASS",
      "generated_utc":datetime.now(timezone.utc).isoformat(),
      "eligible_independent_four_snapshot_fields":int(len(e)),
      "selected_cell_fields_available":int(len(cand)),
      "pilot_fields":int(len(pilot)),
      "pilot_area_ha":round(float(pilot["area_ha_2025"].sum()),3),
      "pilot_bbox_wgs84":[round(float(x),6) for x in b],
      "distance_from_b_pilot_centroid_km":round(float(pcent.distance(bcent))/1000.0,2),
      "selected_grid_cell_ix":int(best["ix"]),
      "selected_grid_cell_iy":int(best["iy"]),
      "selected_grid_cell_available_fields":int(best["n"]),
      "validation_rule_locked_for_c":cfg["validation_rule_locked_for_c"],
      "merge_policy":cfg["merge_policy"],
      "sentinel_hub_pu_used":0,
      "thresholds_tuned":False,
      "next_step":"C1 bounded raster download on independent pilot, then apply locked split rule without tuning."
    }
    (out/"c0_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C0 INDEPENDENT GEOGRAPHIC PILOT")
    for k,v in summary.items():
        if k!="validation_rule_locked_for_c":
            print(f"{k.upper()}={v}")
    print("VALIDATION_RULE_LOCKED_FOR_C="+json.dumps(cfg["validation_rule_locked_for_c"],separators=(",",":")))
    print("SENTINEL_HUB_PU_USED=0")
    print("C0_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
