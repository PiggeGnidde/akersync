#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a whole-Skåne ÅkerFrö × ÅkerAccess screening view on top of the real ÅkerFrö web app."""
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path
import geopandas as gpd
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_D5=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d5"/"bestmatch_d5_fields.parquet"
DEFAULT_D6C=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d6c"/"bestmatch_d6c_fields.parquet"
DEFAULT_TARGET=ROOT/"dist_akerfro_access_v0b"
MARKER_BASE="AKERFRO_ERTOR_WEB_UI_V0A"
MARKER_NEW="AKERFRO_ACCESS_WEB_UI_V0B"
BASE_CANDIDATES=[Path(r"C:\AkerSync-AkerFroWeb\dist"),Path(r"C:\AkerSyncRepo\dist"),Path(r"C:\AkerSync-AkerFro\dist")]
RANKINGS_D5=[
    ("BestMatch v0b – balanserad (vägavstånd)","rank_d5_balanced"),
    ("BestMatch v0b – match först","rank_d5_match_first"),
    ("BestMatch v0b – logistik fram","rank_d5_logistics_forward"),
    ("BestMatch v0a – balanserad","rank_bestmatch_balanced"),
    ("ÅkerFrö C10 baseline","rank_c10_baseline"),
]
RANKINGS_D6C=[
    ("BestMatch v0c – balanserad (belagd väg)","rank_d6c_balanced"),
    ("BestMatch v0c – match först","rank_d6c_match_first"),
    ("BestMatch v0c – logistik fram","rank_d6c_logistics_forward"),
    ("BestMatch v0b – balanserad (vägavstånd)","rank_d5_balanced"),
    ("ÅkerFrö C10 baseline","rank_c10_baseline"),
]
TOP_CHOICES=[200,500,800,1000,2000,5000]

def norm_id(x):
    if x is None:return ""
    s=str(x).strip()
    if s.endswith(".0"):
        try:return str(int(float(s)))
        except Exception:pass
    return s

def discover_base(explicit):
    candidates=[Path(explicit)] if explicit else BASE_CANDIDATES
    checked=[]
    for p in candidates:
        checked.append(str(p))
        idx=p/"index.html"
        if not idx.exists():continue
        text=idx.read_text(encoding="utf-8",errors="replace")
        if MARKER_BASE in text and (p/"data"/"akerfro"/"skane_index.json").exists():return p.resolve()
    raise FileNotFoundError("Could not find existing ÅkerFrö real-web dist. Checked:\n  "+"\n  ".join(checked))

def replace_once(text,old,new,label):
    n=text.count(old)
    if n!=1:raise RuntimeError(f"{label}: expected one occurrence, got {n}")
    return text.replace(old,new,1)

def build_geojson(d5,nmax,rankings):
    from analysis.akeraccess_v0a.entry_discovery_v0a import discover_field_inputs
    from analysis.akeraccess_v0a.skane_road_features_d0 import load_skane_fields
    ids=set()
    for _label,col in rankings:
        q=d5[pd.to_numeric(d5[col],errors="coerce").notna()].copy()
        q[col]=pd.to_numeric(q[col],errors="coerce")
        ids.update(q.nsmallest(min(nmax,len(q)),col)["field_id"].astype(str))
    d=d5[d5["field_id"].astype(str).isin(ids)].copy()
    blocks_path,skiften_path,_=discover_field_inputs()
    geom=load_skane_fields(blocks_path,skiften_path)
    geom["field_id"]=geom["field_id"].map(norm_id)
    geom=geom[geom["field_id"].isin(ids)][["field_id","geometry"]].copy()
    g=geom.merge(d,on="field_id",how="inner",validate="one_to_one")
    g=gpd.GeoDataFrame(g,geometry="geometry",crs=3006).to_crs(4326)
    g["geometry"]=g.geometry.simplify(0.000015,preserve_topology=True)
    props=[
        "field_id","municipality","field_area_ha","artkandidat_class","artmatch_score",
        "area_fit_score","road_access_score","road_area_logistics_score",
        "bestmatch_balanced_score","bestmatch_d5_match_first_score","bestmatch_d5_balanced_score",
        "bestmatch_d5_logistics_forward_score",
        "bestmatch_d6c_match_first_score","bestmatch_d6c_balanced_score","bestmatch_d6c_logistics_forward_score",
        "rank_c10_baseline","rank_bestmatch_balanced",
        "rank_d5_match_first","rank_d5_balanced","rank_d5_logistics_forward",
        "rank_d6c_match_first","rank_d6c_balanced","rank_d6c_logistics_forward",
        "nearest_drivable_osm_m","nearest_statlig_kommunal_nvdb_m",
        "nearest_belagd_statlig_kommunal_nvdb_m","road_access_score_paved",
        "field_to_bjuv_road_km",
        "distance_bjuv_km","bjuv_proximity_d5_source","bjuv_route_status",
        "rotation_status","predecessor_prior","historical_conservart_positive",
    ]
    props=[c for c in props if c in g.columns]
    gg=g[props+["geometry"]].copy()
    for _label,col in rankings:
        if col in gg.columns:gg[col]=pd.to_numeric(gg[col],errors="coerce").astype("Int64")
    return json.loads(gg.to_json(drop_id=True))

def patch_html(text,geojson_rel,rankings):
    if MARKER_BASE not in text:raise RuntimeError("Existing ÅkerFrö web marker missing")
    if MARKER_NEW in text:raise RuntimeError("Target already patched; rebuild from clean base")
    text=replace_once(text,"</head>",'<link rel="stylesheet" href="assets/akerfro_access_v0b.css">\n<!-- '+MARKER_NEW+' -->\n</head>',"CSS hook")
    old='<button id="akfTopButton" class="akf-top-btn" type="button">🏆 Top 1000</button>'
    new=old+'<button id="akfSkaneButton" class="akf-skane-btn" type="button">🗺 Hela Skåne</button>'
    text=replace_once(text,old,new,"Skåne button")
    history='<label class="akf-history"><input id="akfHistoryOutline" type="checkbox"> Markera historiska konservärtsfält 2015–2025</label>'
    options="\n".join(f'<option value="{col}">{label}</option>' for label,col in rankings)
    screening=history+f'''
   <div id="akfSkaneControls" class="akf-skane-controls">
    <div class="akf-skane-grid">
     <label><span class="akf-mini-label">Ranking</span><select id="akfxRanking" class="akf-select">{options}</select></label>
     <label><span class="akf-mini-label">Visa topp</span><select id="akfxTopN" class="akf-select"><option>200</option><option>500</option><option selected>800</option><option>1000</option><option>2000</option><option>5000</option></select></label>
    </div>
    <button id="akfxZoom" class="akf-top-btn" type="button" style="width:100%;margin-top:5px">Zooma till valt urval</button>
    <div id="akfxStats" class="akf-skane-stat"></div>
    <div class="akf-rank-gradient"></div>
    <div class="akf-rank-labels"><span>Bäst rank</span><span>Längre ned i urvalet</span></div>
   </div>'''
    text=replace_once(text,history,screening,"Skåne controls")
    config={"geojson":geojson_rel,"rankings":[list(x) for x in rankings],"top_choices":TOP_CHOICES,"status":"CANDIDATE_NOT_FROZEN"}
    scripts='<script>window.AKERFRO_ACCESS_WEB_CONFIG='+json.dumps(config,ensure_ascii=False,separators=(",",":"))+';</script>\n<script src="assets/akerfro_access_v0b.js"></script>\n'
    return replace_once(text,"</body>",scripts+"</body>","JS hook")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-dist",default=None)
    ap.add_argument("--d5",default=None)
    ap.add_argument("--target",default=str(DEFAULT_TARGET))
    args=ap.parse_args()
    base=discover_base(args.base_dist)
    if args.d5:
        d5_path=Path(args.d5)
    else:
        d5_path=DEFAULT_D5
    target=Path(args.target).resolve()
    if not d5_path.exists():raise FileNotFoundError(f"Run D5/D6c first: {d5_path}")
    if target==base:raise RuntimeError("Target must differ from existing real-web base")
    print("="*112);print("ÅkerFrö × ÅkerAccess WEB v0b - WHOLE-SKÅNE SCREENING");print("="*112)
    print(f"Base real web: {base}");print(f"D5: {d5_path}");print(f"Target preview: {target}")
    d5=pd.read_parquet(d5_path);d5["field_id"]=d5["field_id"].map(norm_id)
    rankings=RANKINGS_D5
    required=[col for _label,col in rankings]+["field_id"]
    missing=[c for c in required if c not in d5.columns]
    if missing:raise RuntimeError("D5 missing: "+", ".join(missing))
    gj=build_geojson(d5,max(TOP_CHOICES),rankings);n=len(gj.get("features") or [])
    if n<5000:raise RuntimeError(f"Unexpectedly small whole-Skåne screening union: {n}")
    if target.exists():shutil.rmtree(target)
    shutil.copytree(base,target)
    data_dir=target/"data"/"akerfro_bestmatch";data_dir.mkdir(parents=True,exist_ok=True)
    geo_path=data_dir/"skane_screening.geojson"
    geo_path.write_text(json.dumps(gj,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    meta={"schema_version":"akerfro-access-web-v0b","status":"CANDIDATE_NOT_FROZEN","field_union_count":n,"rankings":[{"label":a,"column":b} for a,b in rankings],"top_choices":TOP_CHOICES,"screening_source":str(d5_path),"route_coverage_note":"D5/D6c has explicit straight-line fallback where D4 route is missing.","geojson":"data/akerfro_bestmatch/skane_screening.geojson"}
    (data_dir/"skane_index.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    assets=target/"assets";assets.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/"web"/"akerfro_access_v0b.css",assets/"akerfro_access_v0b.css")
    shutil.copy2(ROOT/"web"/"akerfro_access_v0b.js",assets/"akerfro_access_v0b.js")
    index=target/"index.html"
    index.write_text(patch_html(index.read_text(encoding="utf-8"),"data/akerfro_bestmatch/skane_screening.geojson",rankings),encoding="utf-8")
    print(f"Whole-Skåne field union: {n:,}")
    print(f"GeoJSON: {geo_path} ({geo_path.stat().st_size/1024/1024:.1f} MiB)")
    print(f"Index: {index}")
    print("="*112);print("ÅkerFrö × ÅkerAccess WEB v0b BUILD: PASS");print("="*112)
    return 0
if __name__=="__main__":raise SystemExit(main())
