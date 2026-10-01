#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess D0 — build a reusable Skåne road-feature layer.

Design goals
------------
* One command, resumable per municipality.
* OSM is downloaded/cached municipality by municipality.
* NVDB is downloaded ONCE for one padded Skåne bbox, not 33 times.
* API key is loaded from .env/environment and is never printed.
* D0 produces descriptive features only. No ÅkerAccess score is fitted.

The output is designed for D1 historical conservärt replication and later
ÅkerKombinatorik/logistics ranking.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"src"
for p in (ROOT,SRC):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from common import MUN_CODES
from akerpass_secrets import get_secret
from analysis.akeraccess_v0a.core import DRIVABLE_HIGHWAYS, field_key, text_id
from analysis.akeraccess_v0a.entry_discovery_v0a import (
    build_field_summary,
    detect_candidates,
    discover_field_inputs,
    load_json,
    load_or_download_osm,
    osm_geodataframes,
    repair_polygon,
    slug,
)
from analysis.akeraccess_v0a.network_core import ANCHOR_HIGHWAYS
from analysis.akeraccess_v0a.path_profile_core import (
    build_tagged_graph,
    dijkstra_to_anchors,
    summarize_candidate_path,
)
from analysis.akeraccess_v0a.prepare_review_b2 import is_pasture_name
from analysis.akeraccess_v0a.nvdb_anchor_match_c2 import parse_object, nearest_one

DEFAULT_CFG=ROOT/"config"/"akeraccess_skane_d0.json"
DEFAULT_OSM_CFG=ROOT/"config"/"akeraccess_v0a.json"
DEFAULT_AKERMINNE=Path(r"C:\AkerSync-Minne")
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"skane_d0"
DEFAULT_NVDB_RAW=ROOT/"data"/"raw"/"akeraccess_nvdb_skane_d0"

NVDB_API="https://api.trafikinfo.trafikverket.se/v2/data.json"
NVDB_NS="Vägdata.NVDB_DK_O"
NVDB_SCHEMA="1.2"
NVDB_GEOM_FILTER="Geometry.WKT-WGS84-3D"

NVDB_ATTRS={
    "Vägbredd":["Bredd","Mätmetod"],
    "Bärighet":["Bärighetsklass"],
    "FunktionellVägklass":["Klass"],
    "Höjdhinder_upp_till_45_dm":["Fri_höjd","Höjdhindertyp","Höjdhinderidentitet"],
    "Väghållare":["Väghållartyp","Väghållarnamn","Organisationsnummer","Förvaltningsform"],
}


def cfg_json(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm_id(x:Any)->str:
    return text_id(x)


def load_skane_fields(blocks_path:Path,skiften_path:Path)->gpd.GeoDataFrame:
    print("Loading Skåne block/skifte geometry once...")
    blocks=gpd.read_file(blocks_path).to_crs(3006)
    fields=gpd.read_file(skiften_path).to_crs(3006)

    need_b={"blockid","region_kod"}
    need_f={"blockid","skiftesbeteckning"}
    if not need_b.issubset(blocks.columns):
        raise RuntimeError("Block source lacks blockid/region_kod")
    if not need_f.issubset(fields.columns):
        raise RuntimeError("Skifte source lacks blockid/skiftesbeteckning")

    blocks=blocks[["blockid","region_kod"]].copy()
    blocks["blockid"]=blocks["blockid"].map(text_id)
    blocks["municipality_code"]=blocks["region_kod"].astype(str).str.slice(0,4)
    valid_codes=set(MUN_CODES.values())
    blocks=blocks[blocks["municipality_code"].isin(valid_codes)].copy()
    blocks=blocks.drop_duplicates("blockid",keep="first")

    fields=fields.copy()
    fields["blockid"]=fields["blockid"].map(text_id)
    fields["skiftesbeteckning"]=fields["skiftesbeteckning"].map(text_id)
    fields=fields.merge(
        blocks[["blockid","municipality_code"]],
        on="blockid",how="inner",validate="many_to_one"
    )
    fields["geometry"]=fields.geometry.map(repair_polygon)
    fields=fields[fields.geometry.notna()].copy()
    fields["field_id"]=[
        field_key(b,s) for b,s in zip(fields["blockid"],fields["skiftesbeteckning"])
    ]
    fields["area_ha"]=fields.geometry.area/10000.0
    code_to_name={v:k for k,v in MUN_CODES.items()}
    fields["municipality"]=fields["municipality_code"].map(code_to_name)
    fields=fields.drop_duplicates("field_id",keep="first")
    return gpd.GeoDataFrame(
        fields[[
            "field_id","blockid","skiftesbeteckning","municipality_code",
            "municipality","area_ha","geometry"
        ]],
        geometry="geometry",crs=3006
    ).reset_index(drop=True)


def load_akerminne_2025(root:Path)->pd.DataFrame:
    munroot=root/"data"/"derived"/"akerminne_v1a"/"skane"/"municipalities"
    if not munroot.exists():
        raise FileNotFoundError(munroot)
    rows=[]
    cols=["history_year","current_field_id","dominant_crop_name","status"]
    for municipality,code in MUN_CODES.items():
        dirs=sorted(munroot.glob(f"{code}_*"))
        if len(dirs)!=1:
            raise RuntimeError(
                f"Expected exactly one ÅkerMinne municipality directory for {municipality} ({code}); got {len(dirs)}"
            )
        p=dirs[0]/"akerminne_year_summary_classified.parquet"
        if not p.exists():
            raise FileNotFoundError(p)
        q=pd.read_parquet(p,columns=cols)
        q=q[pd.to_numeric(q["history_year"],errors="coerce").eq(2025)].copy()
        q["field_id"]=q["current_field_id"].map(norm_id)
        q["municipality"]=municipality
        rows.append(q[["field_id","municipality","dominant_crop_name","status"]])
    out=pd.concat(rows,ignore_index=True)
    out=out.drop_duplicates("field_id",keep="first")
    return out


def apply_eligibility(fields:gpd.GeoDataFrame,crop:pd.DataFrame,cfg:dict[str,Any])->gpd.GeoDataFrame:
    d=fields.merge(
        crop.rename(columns={"status":"crop2025_status"}),
        on=["field_id","municipality"],how="left",validate="one_to_one"
    )
    d["crop2025_name"]=d["dominant_crop_name"].fillna("").astype(str)
    tokens=list(cfg["pasture_name_tokens"])
    d["is_pasture_2025"]=d["crop2025_name"].map(lambda x:is_pasture_name(x,tokens))
    d["eligible_d0"]=pd.to_numeric(d["area_ha"],errors="coerce").ge(float(cfg["minimum_area_ha"])) & ~d["is_pasture_2025"]
    return gpd.GeoDataFrame(d,geometry="geometry",crs=fields.crs)


def nearest_distance(fields:gpd.GeoDataFrame,roads:gpd.GeoDataFrame,name:str)->pd.DataFrame:
    if roads.empty:
        return pd.DataFrame({"field_id":fields["field_id"].astype(str),name:np.nan})
    j=gpd.sjoin_nearest(
        fields[["field_id","geometry"]],
        roads[["geometry"]],
        how="left",
        distance_col=name,
    )
    j[name]=pd.to_numeric(j[name],errors="coerce")
    j=j.sort_values(["field_id",name],kind="mergesort").drop_duplicates("field_id",keep="first")
    return pd.DataFrame(j[["field_id",name]])


def profile_osm_municipality(
    municipality:str,
    fields:gpd.GeoDataFrame,
    cfg:dict[str,Any],
    osm_cfg:dict[str,Any],
    out_dir:Path,
    refresh_osm:bool,
)->pd.DataFrame:
    out_dir.mkdir(parents=True,exist_ok=True)
    p=out_dir/"osm_road_features_d0.parquet"
    report_path=out_dir/"osm_road_features_d0_report.json"
    if p.exists() and bool(cfg.get("resume_municipal_osm_features",True)) and not refresh_osm:
        print(f"  {municipality}: reuse {p}")
        return pd.read_parquet(p)

    cache=ROOT/"data"/"raw"/"akeraccess_osm"/f"{slug(municipality)}_roads_gates.json"
    payload,meta=load_or_download_osm(fields,osm_cfg,cache,refresh_osm)
    roads,gates=osm_geodataframes(payload)
    candidates=detect_candidates(fields,roads,gates,osm_cfg)
    summary=build_field_summary(fields,candidates)

    near=nearest_distance(fields,roads,"nearest_drivable_osm_m")
    ordinary=roads[roads["highway"].astype(str).isin(ANCHOR_HIGHWAYS)].copy()
    near_ord=nearest_distance(fields,ordinary,"nearest_ordinary_osm_m")
    major_set=set(cfg["osm_major_highways"])
    major=roads[roads["highway"].astype(str).isin(major_set)].copy()
    near_major=nearest_distance(fields,major,"nearest_major_osm_m")

    tr=Transformer.from_crs(4326,3006,always_xy=True)
    graph,xy,ways,node_tags,anchors=build_tagged_graph(
        payload,tr,set(DRIVABLE_HIGHWAYS),set(ANCHOR_HIGHWAYS)
    )
    dist,parent=dijkstra_to_anchors(graph,anchors)

    prows=[]
    for r in candidates.itertuples(index=False):
        if r.geometry is None or r.geometry.is_empty:
            continue
        prof=summarize_candidate_path(
            (float(r.geometry.x),float(r.geometry.y)),
            int(r.osm_way_id),ways,xy,node_tags,dist,parent
        )
        prows.append({
            "field_id":str(r.field_id),
            "candidate_rank":int(r.candidate_rank),
            "candidate_kind":str(r.candidate_kind),
            "geom_evidence":float(r.confidence),
            "candidate_osm_way_id":int(r.osm_way_id),
            "candidate_highway":str(r.highway),
            **prof,
        })
    cand_prof=pd.DataFrame(prows)
    if len(cand_prof):
        connected=cand_prof[cand_prof["path_status"].eq("CONNECTED")].copy()
    else:
        connected=pd.DataFrame()

    if len(connected):
        for c,default in [
            ("has_bad_access",False),
            ("explicit_height_lt_4_5",False),
            ("explicit_width_lt_4_5",False),
            ("last_mile_to_anchor_m",np.inf),
        ]:
            if c not in connected:
                connected[c]=default
        best=(
            connected.sort_values(
                ["field_id","has_bad_access","explicit_height_lt_4_5",
                 "explicit_width_lt_4_5","last_mile_to_anchor_m","candidate_rank"],
                kind="mergesort"
            )
            .groupby("field_id",sort=False).head(1).copy()
        )
        keep=[
            "field_id","candidate_rank","candidate_kind","geom_evidence",
            "candidate_osm_way_id","candidate_highway","anchor_node",
            "last_mile_to_anchor_m","track_m","service_m","other_local_m",
            "n_path_ways","path_highways","surface_values","tracktype_values",
            "min_known_width_m","min_known_maxheight_m",
            "explicit_width_lt_4_5","explicit_height_lt_4_5",
            "bad_access_values","soft_access_values","ag_access_values",
            "has_bad_access","has_soft_access","n_barriers","barrier_values",
        ]
        keep=[c for c in keep if c in best.columns]
        best=best[keep].copy()
        best=best.rename(columns={c:"path_"+c for c in best.columns if c!="field_id"})
        best["anchor_x"]=best["path_anchor_node"].map(
            lambda n: xy.get(int(n),(np.nan,np.nan))[0] if pd.notna(n) else np.nan
        )
        best["anchor_y"]=best["path_anchor_node"].map(
            lambda n: xy.get(int(n),(np.nan,np.nan))[1] if pd.notna(n) else np.nan
        )
    else:
        best=pd.DataFrame({"field_id":pd.Series(dtype=str)})

    base=summary[[
        "field_id","area_ha","entry_status","best_confidence","n_candidates"
    ]].copy()
    out=base.merge(near,on="field_id",how="left",validate="one_to_one")
    out=out.merge(near_ord,on="field_id",how="left",validate="one_to_one")
    out=out.merge(near_major,on="field_id",how="left",validate="one_to_one")
    out=out.merge(best,on="field_id",how="left",validate="one_to_one")
    out["network_access_status"]=np.where(
        out.get("path_last_mile_to_anchor_m",pd.Series(index=out.index,dtype=float)).notna(),
        "CONNECTED_TO_ROAD_NETWORK",
        np.where(out["n_candidates"].gt(0),"LOCAL_OR_UNCONNECTED_OSM_CANDIDATE","NO_ENTRY_CANDIDATE")
    )
    out["no_drivable_50m"]=pd.to_numeric(out["nearest_drivable_osm_m"],errors="coerce").gt(50.0)
    out["municipality"]=municipality
    out["municipality_code"]=MUN_CODES[municipality]
    out["schema_version"]=cfg["schema_version"]

    out.to_parquet(p,index=False)
    report={
        "schema_version":cfg["schema_version"],
        "municipality":municipality,
        "municipality_code":MUN_CODES[municipality],
        "eligible_fields":int(len(out)),
        "osm_source":meta,
        "osm_drivable_ways":int(len(roads)),
        "osm_gates":int(len(gates)),
        "entry_status":{str(k):int(v) for k,v in out["entry_status"].value_counts().items()},
        "network_status":{str(k):int(v) for k,v in out["network_access_status"].value_counts().items()},
        "no_drivable_50m_n":int(out["no_drivable_50m"].sum()),
    }
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(
        f"  {municipality}: fields={len(out):,}, roads={len(roads):,}, "
        f"connected={(out['network_access_status']=='CONNECTED_TO_ROAD_NETWORK').sum():,}, "
        f"no-road-50m={out['no_drivable_50m'].sum():,}"
    )
    return out


def skane_wgs84_box(fields:gpd.GeoDataFrame,pad_m:float)->str:
    minx,miny,maxx,maxy=fields.total_bounds
    geom=box(minx-pad_m,miny-pad_m,maxx+pad_m,maxy+pad_m)
    wgs=gpd.GeoSeries([geom],crs=3006).to_crs(4326).iloc[0]
    west,south,east,north=wgs.bounds
    return f"{west:.7f} {south:.7f}, {east:.7f} {north:.7f}"


def nvdb_request_xml(key:str,obj:str,bbox:str,limit:int,skip:int)->bytes:
    return (
        "<REQUEST>"
        f"<LOGIN authenticationkey={quoteattr(key)}/>"
        f"<QUERY objecttype={quoteattr(obj)} namespace={quoteattr(NVDB_NS)} "
        f"schemaversion={quoteattr(NVDB_SCHEMA)} limit={quoteattr(str(limit))} "
        f"skip={quoteattr(str(skip))}>"
        "<FILTER>"
        f"<WITHIN name={quoteattr(NVDB_GEOM_FILTER)} shape=\"box\" value={quoteattr(bbox)}/>"
        "</FILTER>"
        "</QUERY></REQUEST>"
    ).encode("utf-8")


def nvdb_post(body:bytes,attempts:int=6)->dict[str,Any]:
    last=None
    for i in range(attempts):
        req=urllib.request.Request(
            NVDB_API,data=body,method="POST",
            headers={
                "Content-Type":"text/xml; charset=utf-8",
                "User-Agent":"AkerSync-AkerAccess-D0/0a",
            },
        )
        try:
            with urllib.request.urlopen(req,timeout=120) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            err=e.read().decode("utf-8",errors="replace")
            raise RuntimeError(f"Trafikverket HTTP {e.code}: {err[:1600]}") from e
        except Exception as e:
            last=e
            if i+1<attempts:
                time.sleep(min(2**i,20))
    raise RuntimeError(
        f"Trafikverket request failed after {attempts} attempts: {type(last).__name__}: {last}"
    )


def nvdb_extract(payload:dict[str,Any],obj:str)->tuple[list[dict[str,Any]],dict[str,Any]]:
    rr=(payload.get("RESPONSE") or {}).get("RESULT") or []
    if not rr:
        raise RuntimeError(f"{obj}: empty RESPONSE.RESULT")
    block=rr[0]
    if block.get("ERROR"):
        err=block["ERROR"]
        raise RuntimeError(f"{obj}: API ERROR {err.get('SOURCE')}: {err.get('MESSAGE')}")
    return list(block.get(obj) or []),dict(block.get("INFO") or {})


def ensure_nvdb_skane(
    fields:gpd.GeoDataFrame,
    cfg:dict[str,Any],
    raw_dir:Path,
    refresh:bool,
)->tuple[dict[str,Path],str]:
    raw_dir.mkdir(parents=True,exist_ok=True)
    bbox=skane_wgs84_box(fields,float(cfg["nvdb_bbox_pad_m"]))
    limit=int(cfg["nvdb_limit"])
    key=get_secret("TRAFIKVERKET_API_KEY",ROOT)
    print("NVDB credential: FOUND locally; value is never printed")
    print(f"NVDB Skåne WGS84 box (+{float(cfg['nvdb_bbox_pad_m'])/1000:.1f} km): {bbox}")

    paths={}
    for obj in cfg["nvdb_objects"]:
        path=raw_dir/f"{obj}_v12_skane_d0.json"
        paths[obj]=path
        if path.exists() and not refresh:
            print(f"  {obj}: reuse cached {path.relative_to(ROOT)}")
            continue
        all_rows=[]
        skip=0
        page=0
        info={}
        while True:
            page+=1
            payload=nvdb_post(nvdb_request_xml(key,obj,bbox,limit,skip))
            rows,info=nvdb_extract(payload,obj)
            all_rows.extend(rows)
            print(f"  {obj}: page {page} -> {len(rows):,} rows (total {len(all_rows):,})")
            if len(rows)<limit:
                break
            skip+=limit
            if page>=500:
                raise RuntimeError(f"{obj}: pagination guard hit after {page} pages")
        wrapper={"RESPONSE":{"RESULT":[{obj:all_rows,"INFO":info}]}}
        path.write_text(json.dumps(wrapper,ensure_ascii=False),encoding="utf-8")
        print(f"    saved {path.relative_to(ROOT)} ({path.stat().st_size/1024/1024:.1f} MiB)")
    return paths,bbox


def drop_deleted(g:gpd.GeoDataFrame)->gpd.GeoDataFrame:
    if "Deleted" not in g.columns:
        return g
    s=g["Deleted"].astype(str).str.strip().str.casefold()
    return g[~s.isin({"true","1","yes"})].copy()


def build_anchor_gdf(features:pd.DataFrame)->gpd.GeoDataFrame:
    q=features[
        pd.to_numeric(features.get("anchor_x"),errors="coerce").notna()
        & pd.to_numeric(features.get("anchor_y"),errors="coerce").notna()
    ].copy()
    geom=[
        Point(float(x),float(y))
        for x,y in zip(q["anchor_x"],q["anchor_y"])
    ]
    return gpd.GeoDataFrame(q[["field_id"]].copy(),geometry=geom,crs=3006)


def add_nvdb_features(
    features:pd.DataFrame,
    eligible_fields:gpd.GeoDataFrame,
    raw_paths:dict[str,Path],
    cfg:dict[str,Any],
)->tuple[pd.DataFrame,dict[str,Any]]:
    out=features.copy()
    anchors=build_anchor_gdf(out)
    report={}
    close_m=float(cfg["nvdb_match_max_m"])

    rename_map={
        "Vägbredd_distance_m":"nvdb_width_match_m",
        "Vägbredd_Bredd":"nvdb_width_m",
        "Vägbredd_Mätmetod":"nvdb_width_method",
        "Bärighet_distance_m":"nvdb_bearing_match_m",
        "Bärighet_Bärighetsklass":"nvdb_bearing_class",
        "FunktionellVägklass_distance_m":"nvdb_functional_class_match_m",
        "FunktionellVägklass_Klass":"nvdb_functional_class",
        "Väghållare_distance_m":"nvdb_roadkeeper_match_m",
        "Väghållare_Väghållartyp":"nvdb_roadkeeper",
        "Väghållare_Väghållarnamn":"nvdb_roadkeeper_name",
        "Höjdhinder_upp_till_45_dm_distance_m":"height_obstacle_anchor_distance_m",
        "Höjdhinder_upp_till_45_dm_Fri_höjd":"height_obstacle_free_height_m",
        "Höjdhinder_upp_till_45_dm_Höjdhindertyp":"height_obstacle_type",
    }

    for obj in cfg["nvdb_objects"]:
        g=drop_deleted(parse_object(raw_paths[obj],obj))
        attrs=NVDB_ATTRS[obj]
        near=nearest_one(anchors,g,obj,attrs)
        near=near.rename(columns={k:v for k,v in rename_map.items() if k in near.columns})
        out=out.merge(near,on="field_id",how="left",validate="one_to_one")
        dist_col=rename_map.get(f"{obj}_distance_m",f"{obj}_distance_m")
        dist=pd.to_numeric(out.get(dist_col),errors="coerce")
        report[obj]={
            "rows_with_geometry_non_deleted":int(len(g)),
            "anchor_matches_within_20m":int(dist.le(close_m).sum()) if dist is not None else 0,
        }

        if obj=="Väghållare":
            keeper=g.get("Väghållartyp",pd.Series(index=g.index,dtype=object)).fillna("").astype(str).str.casefold()
            public_like=g[keeper.isin({"statlig","kommunal"})].copy()
            if len(public_like):
                j=gpd.sjoin_nearest(
                    eligible_fields[["field_id","geometry"]],
                    public_like[["geometry"]],
                    how="left",
                    distance_col="nearest_statlig_kommunal_nvdb_m",
                )
                j=j.sort_values(
                    ["field_id","nearest_statlig_kommunal_nvdb_m"],kind="mergesort"
                ).drop_duplicates("field_id",keep="first")
                out=out.merge(
                    pd.DataFrame(j[["field_id","nearest_statlig_kommunal_nvdb_m"]]),
                    on="field_id",how="left",validate="one_to_one"
                )
            else:
                out["nearest_statlig_kommunal_nvdb_m"]=np.nan
            report[obj]["statlig_kommunal_rows"]=int(len(public_like))
        del g

    # Attribute values are trusted only when the nearest NVDB feature is close to
    # the C1 OSM ordinary-road anchor.
    guards=[
        ("nvdb_width_match_m",["nvdb_width_m","nvdb_width_method"]),
        ("nvdb_bearing_match_m",["nvdb_bearing_class"]),
        ("nvdb_functional_class_match_m",["nvdb_functional_class"]),
        ("nvdb_roadkeeper_match_m",["nvdb_roadkeeper","nvdb_roadkeeper_name"]),
    ]
    for dcol,cols in guards:
        d=pd.to_numeric(out.get(dcol),errors="coerce")
        bad=~d.le(close_m)
        for c in cols:
            if c in out:
                out.loc[bad,c]=np.nan

    pub=pd.to_numeric(out.get("nearest_statlig_kommunal_nvdb_m"),errors="coerce")
    out["statlig_kommunal_within_50m"]=pub.le(50)
    out["statlig_kommunal_within_100m"]=pub.le(100)
    out["statlig_kommunal_within_250m"]=pub.le(250)
    return out,report


def qdict(s:pd.Series)->dict[str,float|None]:
    x=pd.to_numeric(s,errors="coerce").dropna()
    if not len(x):
        return {"p10":None,"p50":None,"p90":None}
    return {"p10":float(x.quantile(.1)),"p50":float(x.quantile(.5)),"p90":float(x.quantile(.9))}


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CFG))
    ap.add_argument("--osm-config",default=str(DEFAULT_OSM_CFG))
    ap.add_argument("--akerminne-root",default=str(DEFAULT_AKERMINNE))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    ap.add_argument("--nvdb-raw",default=str(DEFAULT_NVDB_RAW))
    ap.add_argument("--refresh-osm",action="store_true")
    ap.add_argument("--refresh-nvdb",action="store_true")
    ap.add_argument("--municipality",default=None,help="Optional single-municipality D0 smoke/debug run")
    args=ap.parse_args()

    cfg=cfg_json(Path(args.config))
    osm_cfg=cfg_json(Path(args.osm_config))
    out_dir=Path(args.out)
    out_dir.mkdir(parents=True,exist_ok=True)

    blocks_path,skiften_path,local_cfg=discover_field_inputs()
    fields=load_skane_fields(blocks_path,skiften_path)
    expected=int(cfg["expected_skane_current_fields"])
    print("="*112)
    print("ÅkerAccess D0 - SKÅNE ROAD FEATURE BUILD")
    print("="*112)
    print(f"Field geometry config: {local_cfg}")
    print(f"Current Skåne fields: {len(fields):,}")
    if len(fields)!=expected:
        print(f"WARNING: expected anchor {expected:,}, got {len(fields):,}")

    crop=load_akerminne_2025(Path(args.akerminne_root))
    fields=apply_eligibility(fields,crop,cfg)
    missing_crop=int(fields["dominant_crop_name"].isna().sum())
    eligible=fields[fields["eligible_d0"]].copy()
    print(f"Eligible >=1 ha, excluding explicit pasture/slåtteräng: {len(eligible):,}")
    print(f"2025 crop-name missing after join: {missing_crop:,}")

    municipalities=list(MUN_CODES)
    if args.municipality:
        aliases={slug(k):k for k in MUN_CODES}
        municipality=aliases.get(slug(args.municipality),args.municipality)
        if municipality not in MUN_CODES:
            raise ValueError(f"Unknown Skåne municipality: {args.municipality}")
        municipalities=[municipality]

    parts=[]
    summaries=[]
    mun_root=out_dir/"municipalities"
    print("\n[1/3] OSM municipality feature build")
    for i,municipality in enumerate(municipalities,1):
        mf=eligible[eligible["municipality"].eq(municipality)].copy()
        print(f"[{i:02d}/{len(municipalities):02d}] {municipality}: eligible={len(mf):,}")
        if mf.empty:
            continue
        part=profile_osm_municipality(
            municipality,mf,cfg,osm_cfg,mun_root/slug(municipality),args.refresh_osm
        )
        cent=mf[["field_id","geometry"]].copy()
        c=cent.geometry.centroid
        xy=pd.DataFrame({"field_id":cent["field_id"].astype(str),"centroid_x":c.x,"centroid_y":c.y})
        meta=mf[[
            "field_id","blockid","skiftesbeteckning","municipality","municipality_code",
            "area_ha","crop2025_name"
        ]].copy()
        part=meta.merge(part.drop(columns=["area_ha","municipality","municipality_code"],errors="ignore"),
                        on="field_id",how="left",validate="one_to_one")
        part=part.merge(xy,on="field_id",how="left",validate="one_to_one")
        parts.append(part)
        summaries.append({
            "municipality":municipality,
            "municipality_code":MUN_CODES[municipality],
            "eligible_fields":int(len(part)),
            "connected_fields":int(part["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK").sum()),
            "no_drivable_50m":int(part["no_drivable_50m"].sum()),
        })

    if not parts:
        raise RuntimeError("No municipality D0 features were built")
    osm_features=pd.concat(parts,ignore_index=True)
    if args.municipality:
        # Single-municipality mode is intentionally OSM-only: useful for smoke
        # testing without downloading county-wide NVDB.
        sp=out_dir/f"{slug(municipalities[0])}_d0_smoke.parquet"
        osm_features.to_parquet(sp,index=False)
        print(f"\nSingle-municipality D0 smoke output: {sp}")
        print("="*112)
        print("ÅkerAccess D0 MUNICIPALITY SMOKE: PASS")
        print("="*112)
        return 0

    if len(osm_features)!=len(eligible):
        raise RuntimeError(
            f"Skåne municipality concat mismatch: features={len(osm_features):,}, eligible={len(eligible):,}"
        )

    print("\n[2/3] NVDB county-wide fetch/cache")
    raw_paths,bbox=ensure_nvdb_skane(
        eligible,cfg,Path(args.nvdb_raw),args.refresh_nvdb
    )

    print("\n[3/3] NVDB joins + final Skåne feature table")
    final,nvdb_report=add_nvdb_features(osm_features,eligible,raw_paths,cfg)
    final["schema_version"]=cfg["schema_version"]

    final_path=out_dir/"skane_akeraccess_road_features_d0.parquet"
    final.to_parquet(final_path,index=False)

    summary=pd.DataFrame(summaries)
    summary_path=out_dir/"skane_akeraccess_d0_municipality_summary.csv"
    summary.to_csv(summary_path,index=False,encoding="utf-8-sig")

    report={
        "schema_version":cfg["schema_version"],
        "source_current_fields":int(len(fields)),
        "eligible_fields":int(len(eligible)),
        "municipalities":int(len(municipalities)),
        "eligibility":{
            "minimum_area_ha":cfg["minimum_area_ha"],
            "pasture_name_tokens":cfg["pasture_name_tokens"],
            "crop2025_missing":missing_crop,
        },
        "osm":{
            "connected_fields":int(final["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK").sum()),
            "no_drivable_50m_n":int(final["no_drivable_50m"].sum()),
            "nearest_drivable_m_quantiles":qdict(final["nearest_drivable_osm_m"]),
            "last_mile_m_quantiles":qdict(final["path_last_mile_to_anchor_m"]),
        },
        "nvdb_bbox_wgs84":bbox,
        "nvdb":nvdb_report,
        "statlig_kommunal_geometry":{
            "definition":"straight-line polygon-to-nearest NVDB Väghållare geometry where Väghållartyp is statlig or kommunal; this is not a legal allmän-väg classification and not network route distance",
            "distance_quantiles_m":qdict(final["nearest_statlig_kommunal_nvdb_m"]),
            "within_50m_n":int(final["statlig_kommunal_within_50m"].sum()),
            "within_100m_n":int(final["statlig_kommunal_within_100m"].sum()),
            "within_250m_n":int(final["statlig_kommunal_within_250m"].sum()),
        },
        "feature_semantics":{
            "nearest_drivable_osm_m":"straight-line field polygon to nearest mapped drivable OSM way, including track/service",
            "nearest_ordinary_osm_m":"straight-line field polygon to nearest non-track/non-service OSM anchor road",
            "nearest_major_osm_m":"straight-line field polygon to nearest OSM primary/secondary/tertiary way",
            "path_last_mile_to_anchor_m":"mapped OSM path from selected field-entry candidate to first ordinary-road anchor",
            "nvdb_*":"attribute of nearest NVDB object to the C1 ordinary-road anchor, retained only if match <=20 m",
            "nearest_statlig_kommunal_nvdb_m":"straight-line field polygon distance to nearest NVDB road segment with statlig/kommunal road keeper",
        },
        "guardrails":[
            "D0 is a feature layer, not an ÅkerAccess score.",
            "No OSM evidence means unknown/check, not physical FAIL.",
            "NVDB width is road width, not field-entry width.",
            "Missing bearing class is unknown.",
            "Statlig/kommunal road keeper is not asserted to equal the legal category allmän väg.",
            "Functional road class 0-9 is stored raw; no post-hoc 4/7 grouping is frozen in D0."
        ],
        "outputs":{
            "feature_table":str(final_path),
            "municipality_summary":str(summary_path),
        },
    }
    rp=out_dir/"skane_akeraccess_d0_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("\n"+"="*112)
    print("ÅkerAccess D0 - RESULT")
    print("="*112)
    print(f"Eligible fields: {len(final):,}")
    print(f"Connected mapped entry -> ordinary road: {report['osm']['connected_fields']:,}")
    print(f"No mapped drivable OSM way within 50 m: {report['osm']['no_drivable_50m_n']:,}")
    print("Nearest drivable OSM m:",report["osm"]["nearest_drivable_m_quantiles"])
    print("Mapped last-mile m:",report["osm"]["last_mile_m_quantiles"])
    print("Nearest statlig/kommunal NVDB geometry m:",report["statlig_kommunal_geometry"]["distance_quantiles_m"])
    print(f"<=50 m statlig/kommunal: {report['statlig_kommunal_geometry']['within_50m_n']:,}")
    print(f"<=100 m statlig/kommunal: {report['statlig_kommunal_geometry']['within_100m_n']:,}")
    print(f"<=250 m statlig/kommunal: {report['statlig_kommunal_geometry']['within_250m_n']:,}")
    print(f"\nFeature table: {final_path}")
    print(f"Report: {rp}")
    print("="*112)
    print("ÅkerAccess D0 SKÅNE: PASS")
    print("="*112)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
