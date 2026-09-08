#!/usr/bin/env python3
"""Rank nearby Sentinel-2 dates that could rescue frozen April/June footprint gaps.
Public CDSE STAC only: zero Sentinel Hub Processing Units.
"""
from __future__ import annotations
import argparse, csv, json, math, urllib.request
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"

SEARCH_WINDOWS = {
    "S2_2026_APRIL": ("2026-04-01", "2026-04-16"),
    "S2_2026_JUNE": ("2026-06-19", "2026-07-04"),
}

def daterange(a: str, b: str):
    d = date.fromisoformat(a); end = date.fromisoformat(b)
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)

def stac(search_url, collection, bbox, day):
    d = date.fromisoformat(day); e = d + timedelta(days=1)
    payload = {
        "collections": [collection],
        "bbox": bbox,
        "datetime": f"{d}T00:00:00Z/{e}T00:00:00Z",
        "limit": 100,
    }
    req = urllib.request.Request(
        search_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))["features"]

def geom_union(items, gpd, shape):
    if not items:
        return None
    s = gpd.GeoSeries([shape(i["geometry"]) for i in items], crs=4326).to_crs(32633)
    return s.union_all() if hasattr(s, "union_all") else s.unary_union

def weighted_cloud(items, gap_union, gpd, shape):
    vals=[]; weights=[]
    for item in items:
        cc=item.get("properties",{}).get("eo:cloud_cover")
        if cc is None:
            continue
        geom=gpd.GeoSeries([shape(item["geometry"])],crs=4326).to_crs(32633).iloc[0]
        w=float(geom.intersection(gap_union).area)
        if w > 0:
            vals.append(float(cc)); weights.append(w)
    if not weights or sum(weights)<=0:
        return None
    return sum(v*w for v,w in zip(vals,weights))/sum(weights)

def write_csv(path, rows):
    if not rows:
        return
    with open(path,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

def main():
    import geopandas as gpd
    from shapely.geometry import shape
    from shapely.ops import unary_union

    ap=argparse.ArgumentParser()
    ap.add_argument("--coverage-dir", default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_coverage_diag")
    ap.add_argument("--output-dir", default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_rescue_dates")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    covdir=Path(args.coverage_dir)

    all_rank=[]; summary=[]
    for snap in ("S2_2026_APRIL","S2_2026_JUNE"):
        gpkg=covdir/f"{snap.lower()}_gap_fields.gpkg"
        if not gpkg.exists():
            raise FileNotFoundError(f"Run coverage diagnostic first: {gpkg}")
        gaps=gpd.read_file(gpkg).to_crs(32633)
        bbox=list(map(float,gaps.to_crs(4326).total_bounds))

        current_items=[]
        for d in cfg["snapshots"][snap]:
            current_items.extend(stac(cfg["sentinel2"]["stac_search_url"],cfg["sentinel2"]["collection"],bbox,d))
        current_union=geom_union(current_items,gpd,shape)
        if current_union is None:
            raise RuntimeError(f"No frozen-scene footprint for {snap}")

        missing=gaps.geometry.difference(current_union)
        missing=missing[~missing.is_empty]
        missing=missing[missing.area > 1.0]
        gap_union=unary_union(list(missing))
        gap_area=float(gap_union.area)
        if gap_area <= 0:
            raise RuntimeError(f"No footprint gap left for {snap}")

        candidates=[]
        frozen=set(cfg["snapshots"][snap])
        day_to_union={}
        for d in daterange(*SEARCH_WINDOWS[snap]):
            if d in frozen:
                continue
            items=stac(cfg["sentinel2"]["stac_search_url"],cfg["sentinel2"]["collection"],bbox,d)
            u=geom_union(items,gpd,shape)
            day_to_union[d]=u
            rescue=0.0 if u is None else float(gap_union.intersection(u).area)
            coverage=100.0*rescue/gap_area
            cloud=weighted_cloud(items,gap_union,gpd,shape) if items else None
            score=(coverage/100.0)*(1.0-(cloud/100.0 if cloud is not None else 1.0))
            row={
                "snapshot":snap,
                "candidate_date":d,
                "stac_items":len(items),
                "gap_rescue_percent":round(coverage,4),
                "gap_rescue_ha":round(rescue/10000.0,3),
                "weighted_scene_cloud_percent":None if cloud is None else round(cloud,3),
                "heuristic_clear_rescue_score":round(score,6),
            }
            candidates.append(row); all_rank.append(row)

        # Rank primarily by footprint rescue; cloud is only a tie-break heuristic.
        ordered=sorted(candidates,key=lambda r:(r["gap_rescue_percent"],r["heuristic_clear_rescue_score"]),reverse=True)
        best_single=ordered[0] if ordered else None

        # Best two-date footprint combination, independent of cloud score.
        best_pair=None
        dates=[r["candidate_date"] for r in candidates if r["stac_items"]>0]
        for a,b in combinations(dates,2):
            ua=day_to_union[a]; ub=day_to_union[b]
            if ua is None or ub is None:
                continue
            uu=unary_union([ua,ub])
            pct=100.0*float(gap_union.intersection(uu).area)/gap_area
            if best_pair is None or pct>best_pair["gap_rescue_percent"]:
                best_pair={"dates":[a,b],"gap_rescue_percent":round(pct,4)}

        summary.append({
            "snapshot":snap,
            "frozen_dates":cfg["snapshots"][snap],
            "gap_area_ha":round(gap_area/10000.0,3),
            "search_window":list(SEARCH_WINDOWS[snap]),
            "best_single":best_single,
            "best_two_date_footprint_pair":best_pair,
            "note":"Cloud cover is scene-level metadata, not a local cloud mask. Candidate dates require visual or Process API validation before changing the frozen snapshot.",
        })

    write_csv(out/"rescue_date_ranking.csv", sorted(all_rank,key=lambda r:(r["snapshot"],-r["gap_rescue_percent"],r["candidate_date"])))
    (out/"rescue_date_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("AKERPULS PRELIM FIELDS 2026 - RESCUE DATE SEARCH - PUBLIC STAC ONLY")
    for s in summary:
        print(s["snapshot"])
        print(f'  GAP_AREA_HA={s["gap_area_ha"]}')
        b=s["best_single"]
        if b:
            print(f'  BEST_SINGLE={b["candidate_date"]} RESCUE={b["gap_rescue_percent"]}% CLOUD_META={b["weighted_scene_cloud_percent"]}% ITEMS={b["stac_items"]}')
        p=s["best_two_date_footprint_pair"]
        if p:
            print(f'  BEST_PAIR={"+".join(p["dates"])} RESCUE={p["gap_rescue_percent"]}%')
    print("OUTPUT="+str(out))
    print("SENTINEL_HUB_PU_USED=0")
    print("FROZEN_SNAPSHOT_DATES_CHANGED=FALSE")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
