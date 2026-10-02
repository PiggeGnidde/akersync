#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D6a — NVDB Slitlager enrichment + exact field diagnostic.

Purpose:
1) fetch/cache Slitlager for the same Skåne bbox used by D0,
2) classify paved ("Belagd") road segments,
3) intersect that evidence with statlig/kommunal road-keeper geometry,
4) compute field distance to nearest *paved statlig/kommunal* NVDB road,
5) print an exact diagnostic for one field.

No existing D0/D5 freeze/output is overwritten.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"src"
for p in (ROOT,SRC):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from akerpass_secrets import get_secret
from analysis.akeraccess_v0a.entry_discovery_v0a import discover_field_inputs
from analysis.akeraccess_v0a.nvdb_anchor_match_c2 import parse_object
from analysis.akeraccess_v0a.skane_road_features_d0 import (
    load_skane_fields,
    nvdb_request_xml,
    nvdb_post,
    nvdb_extract,
    drop_deleted,
)

DEFAULT_D0=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_road_features_d0.parquet"
DEFAULT_D0_REPORT=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_d0_report.json"
DEFAULT_KEEPER_RAW=ROOT/"data"/"raw"/"akeraccess_nvdb_skane_d0"/"Väghållare_v12_skane_d0.json"
DEFAULT_SURFACE_RAW=ROOT/"data"/"raw"/"akeraccess_nvdb_skane_d6a"/"Slitlager_v12_skane_d6a.json"
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"surface_d6a"
DEFAULT_FIELD="62263103013|20A"


def read_json(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fetch_slitlager(raw_path:Path,bbox:str,refresh:bool)->Path:
    if raw_path.exists() and not refresh:
        print(f"Slitlager: reuse cached {raw_path.relative_to(ROOT)}")
        return raw_path
    raw_path.parent.mkdir(parents=True,exist_ok=True)
    key=get_secret("TRAFIKVERKET_API_KEY",ROOT)
    print("NVDB credential: FOUND locally; value is never printed")
    limit=5000
    rows=[]; skip=0; page=0; info={}
    while True:
        page+=1
        payload=nvdb_post(nvdb_request_xml(key,"Slitlager",bbox,limit,skip))
        part,info=nvdb_extract(payload,"Slitlager")
        rows.extend(part)
        print(f"  Slitlager page {page}: {len(part):,} rows (total {len(rows):,})")
        if len(part)<limit:
            break
        skip+=limit
        if page>500:
            raise RuntimeError("Slitlager pagination guard hit")
    wrapper={"RESPONSE":{"RESULT":[{"Slitlager":rows,"INFO":info}]}}
    raw_path.write_text(json.dumps(wrapper,ensure_ascii=False),encoding="utf-8")
    print(f"  saved {raw_path.relative_to(ROOT)} ({raw_path.stat().st_size/1024/1024:.1f} MiB)")
    return raw_path


def surface_label_series(g:gpd.GeoDataFrame)->pd.Series:
    if "Slitlagertyp" not in g.columns:
        raise RuntimeError(f"Slitlager API response lacks Slitlagertyp. Columns={list(g.columns)}")
    return g["Slitlagertyp"].fillna("").astype(str).str.strip().str.casefold()


def keeper_label_series(g:gpd.GeoDataFrame)->pd.Series:
    if "Väghållartyp" not in g.columns:
        raise RuntimeError(f"Väghållare raw lacks Väghållartyp. Columns={list(g.columns)}")
    return g["Väghållartyp"].fillna("").astype(str).str.strip().str.casefold()


def nearest_feature(one:gpd.GeoDataFrame,right:gpd.GeoDataFrame,distance_col:str)->pd.DataFrame:
    if one.empty or right.empty:
        return pd.DataFrame()
    j=gpd.sjoin_nearest(one,right,how="left",distance_col=distance_col)
    j=j.sort_values(distance_col,kind="mergesort").head(1).copy()
    return j


def build_public_paved(slit:gpd.GeoDataFrame,keeper:gpd.GeoDataFrame,tol_m:float=2.0)->gpd.GeoDataFrame:
    st=surface_label_series(slit)
    paved=slit[st.str.contains("belagd",regex=False)].copy().reset_index(drop=True)
    paved["_slit_idx"]=np.arange(len(paved))
    kt=keeper_label_series(keeper)
    public=keeper[kt.isin({"statlig","kommunal"})].copy().reset_index(drop=True)
    if paved.empty or public.empty:
        return paved.head(0).copy()

    # Classify each paved NVDB link by the road-keeper geometry at the line midpoint.
    # Both products are carried on the same NVDB network; <=2 m is a deliberately
    # tight linkage tolerance. This avoids treating a crossing private paved road
    # as public merely because it touches a public road at one endpoint.
    mid=paved[["_slit_idx","geometry"]].copy()
    mid["geometry"]=mid.geometry.interpolate(0.5,normalized=True)
    pubcols=[c for c in ["Väghållartyp","Väghållarnamn","geometry"] if c in public.columns]
    public_match=public[pubcols].copy()
    j=gpd.sjoin_nearest(mid,public_match,how="left",distance_col="_keeper_link_m")
    j=j[pd.to_numeric(j["_keeper_link_m"],errors="coerce").le(tol_m)].copy()
    if j.empty:
        return paved.head(0).copy()
    keep=set(pd.to_numeric(j["_slit_idx"],errors="coerce").dropna().astype(int))
    out=paved[paved["_slit_idx"].isin(keep)].copy()
    out=out.drop(columns=["_slit_idx"],errors="ignore")
    return gpd.GeoDataFrame(out,geometry="geometry",crs=slit.crs)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--field-id",default=DEFAULT_FIELD)
    ap.add_argument("--d0",default=str(DEFAULT_D0))
    ap.add_argument("--d0-report",default=str(DEFAULT_D0_REPORT))
    ap.add_argument("--keeper-raw",default=str(DEFAULT_KEEPER_RAW))
    ap.add_argument("--surface-raw",default=str(DEFAULT_SURFACE_RAW))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    ap.add_argument("--refresh",action="store_true")
    args=ap.parse_args()

    d0_path=Path(args.d0)
    report_path=Path(args.d0_report)
    keeper_path=Path(args.keeper_raw)
    if not d0_path.exists() or not report_path.exists() or not keeper_path.exists():
        raise FileNotFoundError("D6a requires completed D0 and cached Väghållare raw data")

    d0=pd.read_parquet(d0_path)
    rep=read_json(report_path)
    bbox=str(rep["nvdb_bbox_wgs84"])
    surface_path=fetch_slitlager(Path(args.surface_raw),bbox,args.refresh)

    slit=drop_deleted(parse_object(surface_path,"Slitlager"))
    keeper=drop_deleted(parse_object(keeper_path,"Väghållare"))
    print(f"Slitlager rows with geometry: {len(slit):,}")
    print("Slitlager values:",{str(k):int(v) for k,v in slit["Slitlagertyp"].fillna("(missing)").astype(str).value_counts().items()})
    print(f"Väghållare rows with geometry: {len(keeper):,}")

    public_paved=build_public_paved(slit,keeper,2.0)
    print(f"Belagd + statlig/kommunal linked NVDB segments: {len(public_paved):,}")

    blocks_path,skiften_path,_=discover_field_inputs()
    fields=load_skane_fields(blocks_path,skiften_path)
    eligible_ids=set(d0["field_id"].astype(str))
    fields=fields[fields["field_id"].astype(str).isin(eligible_ids)].copy()

    # Whole-Skåne feature: polygon distance to nearest paved public-roadkeeper link.
    j=gpd.sjoin_nearest(
        fields[["field_id","geometry"]],
        public_paved[["geometry"]],
        how="left",
        distance_col="nearest_belagd_statlig_kommunal_nvdb_m",
    )
    j["nearest_belagd_statlig_kommunal_nvdb_m"]=pd.to_numeric(
        j["nearest_belagd_statlig_kommunal_nvdb_m"],errors="coerce"
    )
    nearest=(
        j.sort_values(["field_id","nearest_belagd_statlig_kommunal_nvdb_m"],kind="mergesort")
         .drop_duplicates("field_id",keep="first")
         [["field_id","nearest_belagd_statlig_kommunal_nvdb_m"]]
         .copy()
    )

    outdir=Path(args.out);outdir.mkdir(parents=True,exist_ok=True)
    fp=outdir/"skane_paved_public_road_distance_d6a.parquet"
    nearest.to_parquet(fp,index=False)

    # Exact diagnostic.
    fid=str(args.field_id)
    one=fields[fields["field_id"].astype(str).eq(fid)][["field_id","geometry"]].copy()
    if one.empty:
        raise RuntimeError(f"Diagnostic field not found in D0 eligible population: {fid}")

    public=keeper[keeper_label_series(keeper).isin({"statlig","kommunal"})].copy()
    near_keeper=nearest_feature(
        one,
        public[[c for c in ["Väghållartyp","Väghållarnamn","Förvaltningsform","geometry"] if c in public.columns]],
        "_dist_keeper_m",
    )
    near_surface=nearest_feature(
        one,
        slit[[c for c in ["Slitlagertyp","geometry"] if c in slit.columns]],
        "_dist_surface_m",
    )
    near_paved=nearest_feature(
        one,
        public_paved[[c for c in ["Slitlagertyp","geometry"] if c in public_paved.columns]],
        "_dist_paved_public_m",
    )

    row=d0[d0["field_id"].astype(str).eq(fid)].iloc[0]
    print("\n"+"="*112)
    print(f"D6a EXACT FIELD DIAGNOSTIC · {fid}")
    print("="*112)
    print(f"Municipality: {row.get('municipality')}")
    print(f"D0 nearest mapped drivable OSM: {row.get('nearest_drivable_osm_m')} m")
    print(f"D0 nearest statlig/kommunal NVDB: {row.get('nearest_statlig_kommunal_nvdb_m')} m")
    print(f"OSM selected candidate highway: {row.get('path_candidate_highway')}")
    print(f"OSM selected path surface values: {row.get('path_surface_values')}")
    if len(near_keeper):
        r=near_keeper.iloc[0]
        print(f"Nearest public roadkeeper geometry: {float(r['_dist_keeper_m']):.2f} m")
        print(f"  Väghållartyp: {r.get('Väghållartyp')}")
        print(f"  Väghållarnamn: {r.get('Väghållarnamn')}")
        print(f"  Förvaltningsform: {r.get('Förvaltningsform')}")
    if len(near_surface):
        r=near_surface.iloc[0]
        print(f"Nearest NVDB Slitlager geometry: {float(r['_dist_surface_m']):.2f} m")
        print(f"  Slitlagertyp: {r.get('Slitlagertyp')}")
    if len(near_paved):
        r=near_paved.iloc[0]
        print(f"Nearest BELAGD statlig/kommunal NVDB geometry: {float(r['_dist_paved_public_m']):.2f} m")
    else:
        print("Nearest BELAGD statlig/kommunal NVDB geometry: none")

    old=float(pd.to_numeric(pd.Series([row.get("nearest_statlig_kommunal_nvdb_m")]),errors="coerce").iloc[0])
    new=float(nearest.loc[nearest["field_id"].astype(str).eq(fid),"nearest_belagd_statlig_kommunal_nvdb_m"].iloc[0])
    print(f"\nOld UI metric: {old:.2f} m to statlig/kommunal")
    print(f"Candidate replacement metric: {new:.2f} m to BELAGD statlig/kommunal")
    print("="*112)

    diag={
        "field_id":fid,
        "old_nearest_statlig_kommunal_m":old,
        "nearest_belagd_statlig_kommunal_m":new,
        "nearest_keeper":(
            {k:near_keeper.iloc[0].get(k) for k in ["Väghållartyp","Väghållarnamn","Förvaltningsform","_dist_keeper_m"]}
            if len(near_keeper) else None
        ),
        "nearest_surface":(
            {k:near_surface.iloc[0].get(k) for k in ["Slitlagertyp","_dist_surface_m"]}
            if len(near_surface) else None
        ),
        "note":"Slitlager is NVDB data, not visual ground truth. Municipal Slitlager may retain legacy/assumed values if not updated."
    }
    (outdir/"field_diagnostic_d6a.json").write_text(
        json.dumps(diag,ensure_ascii=False,indent=2,default=str),encoding="utf-8"
    )
    print(f"Whole-Skåne feature: {fp}")
    print(f"Diagnostic JSON: {outdir/'field_diagnostic_d6a.json'}")
    print("D6a SURFACE CHECK: PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
