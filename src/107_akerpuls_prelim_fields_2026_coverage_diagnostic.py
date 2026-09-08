#!/usr/bin/env python3
"""Coverage-gap diagnostic for frozen ÅkerPuls 2026 snapshots. Public STAC only; zero Sentinel Hub PU."""
from __future__ import annotations
import argparse, json, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_v0.json"

def stac(search_url, collection, bbox, day):
    d=date.fromisoformat(day); e=d+timedelta(days=1)
    payload={"collections":[collection],"bbox":bbox,"datetime":f"{d}T00:00:00Z/{e}T00:00:00Z","limit":100}
    req=urllib.request.Request(search_url,data=json.dumps(payload).encode(),method="POST",headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))["features"]

def main():
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import shape
    from shapely.ops import unary_union

    ap=argparse.ArgumentParser()
    ap.add_argument("--local-paths",default=str(ROOT/"config"/"local_paths.json"))
    ap.add_argument("--output-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_coverage_diag")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    lp=json.loads(Path(args.local_paths).read_text(encoding="utf-8-sig"))
    fp=Path(lp["skiften"])
    g=gpd.read_file(fp)
    if len(g)!=cfg["upstream_freeze"]["expected_2025_fields"]:
        raise RuntimeError(f"Unexpected field count: {len(g)}")
    g32633=g.to_crs(32633)
    g4326=g.to_crs(4326)
    bbox=list(map(float,g4326.total_bounds))
    field_area=g32633.geometry.area
    total_area=float(field_area.sum())
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)

    rows=[]
    for snap in ("S2_2026_APRIL","S2_2026_JUNE"):
        fps=[]
        item_ids=[]
        for day in cfg["snapshots"][snap]:
            items=stac(cfg["sentinel2"]["stac_search_url"],cfg["sentinel2"]["collection"],bbox,day)
            item_ids += [str(i.get("id","")) for i in items]
            fps += [shape(i["geometry"]) for i in items]
        cov4326=unary_union(fps)
        cov32633=gpd.GeoSeries([cov4326],crs=4326).to_crs(32633).iloc[0]

        # Vectorized intersection area; preserve source columns for easy QGIS inspection.
        covered_area=g32633.geometry.intersection(cov32633).area
        uncovered=(field_area-covered_area).clip(lower=0)
        frac=(uncovered/field_area.where(field_area>0)).fillna(0.0)
        any_gap=frac>0.001
        major_gap=frac>0.10
        full_gap=frac>0.999

        diag=g.copy()
        diag["field_area_ha_2025"]=(field_area/10000).round(6)
        diag["uncovered_ha"]= (uncovered/10000).round(6)
        diag["uncovered_fraction"]=frac.round(6)
        diag=diag.loc[any_gap].copy()
        diag.to_file(out/f"{snap.lower()}_gap_fields.gpkg",layer="gap_fields",driver="GPKG")

        gap_area=float(uncovered.sum())
        rows.append({
            "snapshot":snap,
            "dates":"+".join(cfg["snapshots"][snap]),
            "stac_items":len(item_ids),
            "fields_any_gap_gt_0p1pct":int(any_gap.sum()),
            "fields_major_gap_gt_10pct":int(major_gap.sum()),
            "fields_full_gap_gt_99p9pct":int(full_gap.sum()),
            "uncovered_area_ha":round(gap_area/10000,3),
            "uncovered_percent_of_summed_field_area":round(100*gap_area/total_area,4),
            "west_min_lon_gap":round(float(diag.to_crs(4326).total_bounds[0]),6) if len(diag) else None,
            "south_min_lat_gap":round(float(diag.to_crs(4326).total_bounds[1]),6) if len(diag) else None,
            "east_max_lon_gap":round(float(diag.to_crs(4326).total_bounds[2]),6) if len(diag) else None,
            "north_max_lat_gap":round(float(diag.to_crs(4326).total_bounds[3]),6) if len(diag) else None,
        })

    df=pd.DataFrame(rows)
    df.to_csv(out/"coverage_gap_summary.csv",index=False)
    (out/"coverage_gap_summary.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - COVERAGE DIAGNOSTIC")
    for r in rows:
        print(f'{r["snapshot"]}: ITEMS={r["stac_items"]} ANY_GAP={r["fields_any_gap_gt_0p1pct"]} MAJOR_GAP={r["fields_major_gap_gt_10pct"]} FULL_GAP={r["fields_full_gap_gt_99p9pct"]} UNCOVERED_HA={r["uncovered_area_ha"]} UNCOVERED_PCT={r["uncovered_percent_of_summed_field_area"]}%')
        print(f'  GAP_BBOX_WGS84={r["west_min_lon_gap"]},{r["south_min_lat_gap"]},{r["east_max_lon_gap"]},{r["north_max_lat_gap"]}')
    print("OUTPUT="+str(out))
    print("SENTINEL_HUB_PU_USED=0")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
