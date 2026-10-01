#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    ap=argparse.ArgumentParser();ap.add_argument("--dist",default=str(root/"dist_akerfro_access_v0b"));args=ap.parse_args()
    d=Path(args.dist);idx=d/"index.html";geo=d/"data"/"akerfro_bestmatch"/"skane_screening.geojson";meta=d/"data"/"akerfro_bestmatch"/"skane_index.json"
    if not idx.exists() or not geo.exists() or not meta.exists():raise FileNotFoundError("Whole-Skåne web artifacts missing")
    html=idx.read_text(encoding="utf-8")
    required=["AKERFRO_ERTOR_WEB_UI_V0A","AKERFRO_ACCESS_WEB_UI_V0B",'id="akfSkaneButton"','id="akfxRanking"','id="akfxTopN"',"assets/akerfro_access_v0b.css","assets/akerfro_access_v0b.js","BestMatch v0b – balanserad","Hela Skåne"]
    miss=[x for x in required if x not in html]
    if miss:raise RuntimeError("index missing: "+", ".join(miss))
    g=json.loads(geo.read_text(encoding="utf-8"))
    if g.get("type")!="FeatureCollection":raise RuntimeError("screening file is not GeoJSON FeatureCollection")
    feats=g.get("features") or []
    if len(feats)<5000:raise RuntimeError("too few screening fields")
    reqprops={"field_id","municipality","artkandidat_class","artmatch_score","road_access_score","road_area_logistics_score","rank_d5_balanced","rank_d5_match_first","rank_d5_logistics_forward","nearest_drivable_osm_m","nearest_statlig_kommunal_nvdb_m"}
    sample=(feats[0].get("properties") or {}) if feats else {}
    missing=sorted(reqprops-set(sample))
    if missing:raise RuntimeError("GeoJSON properties missing: "+", ".join(missing))
    if not (d/"data"/"akerfro"/"skane_index.json").exists():raise RuntimeError("existing municipality ÅkerFrö sidecars were not preserved")
    print("="*96);print("ÅkerFrö × ÅkerAccess WEB v0b VERIFY: PASS");print("="*96)
    print(f"Whole-Skåne screening union: {len(feats):,} fields");print("Existing municipality ÅkerFrö: preserved");print("Candidate status: NOT FROZEN");print("="*96)
    return 0
if __name__=="__main__":raise SystemExit(main())
