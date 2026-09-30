#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess C2: parse locally downloaded NVDB Open API JSON and match to C1 anchors.

No network access and no credential handling in this module.
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
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import Point

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_WORK=ROOT/"work"/"akeraccess_v0a"/"sjobo"
DEFAULT_RAW=ROOT/"data"/"raw"/"akeraccess_nvdb_sjobo_c2"
DEFAULT_OSM=ROOT/"data"/"raw"/"akeraccess_osm"/"sjobo_roads_gates.json"

OBJECTS={
    "Vägbredd":{"attrs":["Bredd","Mätmetod"],"geom":"line"},
    "Bärighet":{"attrs":["Bärighetsklass"],"geom":"line"},
    "FunktionellVägklass":{"attrs":["Klass"],"geom":"line"},
    "Väghållare":{"attrs":["Väghållartyp","Väghållarnamn","Organisationsnummer","Förvaltningsform"],"geom":"line"},
    "Vägtrafiknät":{"attrs":["Nättyp"],"geom":"line"},
    "Höjdhinder_upp_till_45_dm":{"attrs":["Fri_höjd","Höjdhindertyp","Höjdhinderidentitet"],"geom":"point"},
}


def load_json(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_raw(raw:Path,obj:str)->Path:
    candidates=[
        raw/f"{obj}_v12_sjobo.json",
        raw/f"{obj}_sjobo_v12.json",
        raw/f"{obj}_v12.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"Saknar NVDB raw för {obj}. Förväntade någon av: "
        + ", ".join(str(p) for p in candidates)
    )


def parse_object(path:Path,obj:str)->gpd.GeoDataFrame:
    payload=load_json(path)
    result=(payload.get("RESPONSE") or {}).get("RESULT") or []
    if not result:
        raise RuntimeError(f"{path}: no RESPONSE.RESULT")
    block=result[0]
    if block.get("ERROR"):
        raise RuntimeError(f"{path}: API ERROR {block['ERROR']}")
    rows=block.get(obj) or []
    records=[]
    for row in rows:
        geom_block=row.get("Geometry") or {}
        text=geom_block.get("WKT-SWEREF99TM-3D")
        if not text:
            continue
        try:
            geom=wkt.loads(text)
        except Exception:
            continue
        rec={k:v for k,v in row.items() if k!="Geometry"}
        rec["geometry"]=geom
        records.append(rec)
    return gpd.GeoDataFrame(records,geometry="geometry",crs=3006)


def osm_nodes_xy(osm_path:Path)->dict[int,tuple[float,float]]:
    payload=load_json(osm_path)
    ids=[]; lons=[]; lats=[]
    for el in payload.get("elements") or []:
        if el.get("type")=="node" and "id" in el and "lon" in el and "lat" in el:
            ids.append(int(el["id"])); lons.append(float(el["lon"])); lats.append(float(el["lat"]))
    tr=Transformer.from_crs(4326,3006,always_xy=True)
    xs,ys=tr.transform(lons,lats)
    return {i:(float(x),float(y)) for i,x,y in zip(ids,xs,ys)}


def anchor_points(fields:pd.DataFrame,nodes:dict[int,tuple[float,float]])->gpd.GeoDataFrame:
    rows=[]
    for r in fields.itertuples(index=False):
        node=getattr(r,"path_anchor_node",None)
        try:
            if pd.isna(node): continue
            node=int(float(node))
        except Exception:
            continue
        xy=nodes.get(node)
        if xy is None: continue
        rows.append({
            "field_id":str(r.field_id),
            "anchor_node":node,
            "last_mile_m":getattr(r,"path_last_mile_to_anchor_m",None),
            "candidate_highway":getattr(r,"path_candidate_highway",None),
            "geometry":Point(xy),
        })
    return gpd.GeoDataFrame(rows,geometry="geometry",crs=3006)


def nearest_one(anchors:gpd.GeoDataFrame,features:gpd.GeoDataFrame,obj:str,attrs:list[str])->pd.DataFrame:
    if features.empty:
        out=anchors[["field_id"]].copy()
        out[f"{obj}_distance_m"]=np.nan
        return out
    cols=[c for c in attrs if c in features.columns]+["geometry"]
    right=features[cols].copy().reset_index(drop=True)
    joined=gpd.sjoin_nearest(
        anchors[["field_id","geometry"]],
        right,
        how="left",
        distance_col="_distance_m",
    )
    joined=joined.sort_values(["field_id","_distance_m"],kind="mergesort").drop_duplicates("field_id",keep="first")
    out=joined[["field_id","_distance_m"]+[c for c in attrs if c in joined.columns]].copy()
    rename={"_distance_m":f"{obj}_distance_m"}
    rename.update({c:f"{obj}_{c}" for c in attrs if c in out.columns})
    return pd.DataFrame(out.rename(columns=rename))


def coverage(dist:pd.Series,thresholds=(5,10,20,30,50))->dict[str,Any]:
    x=pd.to_numeric(dist,errors="coerce")
    return {
        f"within_{m}m":int(x.le(m).sum()) for m in thresholds
    } | {
        f"within_{m}m_pct":float(100*x.le(m).mean()) for m in thresholds
    }


def value_counts_dict(s:pd.Series,n=20)->dict[str,int]:
    return {str(k):int(v) for k,v in s.fillna("(missing)").astype(str).value_counts().head(n).items()}


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--raw",default=str(DEFAULT_RAW))
    ap.add_argument("--osm",default=str(DEFAULT_OSM))
    args=ap.parse_args()
    work=Path(args.work); raw=Path(args.raw); osm=Path(args.osm)

    c1=work/"path_c1"/"sjobo_field_path_profile_c1.csv"
    if not c1.exists():
        raise FileNotFoundError("Run STOPPUNKT C1 first")
    fields=pd.read_csv(c1,low_memory=False)
    fields=fields[fields["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK")].copy()

    nodes=osm_nodes_xy(osm)
    anchors=anchor_points(fields,nodes)
    if len(anchors)!=len(fields):
        raise RuntimeError(f"Anchor geometry mismatch: fields={len(fields):,}, anchors={len(anchors):,}")

    loaded={}
    sources={}
    for obj in OBJECTS:
        p=find_raw(raw,obj)
        sources[obj]=str(p)
        loaded[obj]=parse_object(p,obj)

    out=work/"nvdb_c2"
    out.mkdir(parents=True,exist_ok=True)

    merged=anchors.drop(columns="geometry").copy()
    reports={}
    for obj,spec in OBJECTS.items():
        g=loaded[obj]
        reports[obj]={
            "rows_with_geometry":int(len(g)),
            "geometry_type_counts":value_counts_dict(g.geometry.geom_type) if len(g) else {},
            "source":sources[obj],
        }
        near=nearest_one(anchors,g,obj,spec["attrs"])
        merged=merged.merge(near,on="field_id",how="left",validate="one_to_one")
        reports[obj]["anchor_distance_coverage"]=coverage(merged[f"{obj}_distance_m"])

    # Useful distributions only where geometry actually matches the anchor closely.
    def close(obj,m=20):
        return pd.to_numeric(merged[f"{obj}_distance_m"],errors="coerce").le(m)

    if "Vägbredd_Bredd" in merged:
        w=pd.to_numeric(merged.loc[close("Vägbredd"),"Vägbredd_Bredd"],errors="coerce").dropna()
        reports["Vägbredd"]["matched_20m_width_n"]=int(len(w))
        reports["Vägbredd"]["width_m_quantiles"]={
            "p10":float(w.quantile(.10)) if len(w) else None,
            "p50":float(w.quantile(.50)) if len(w) else None,
            "p90":float(w.quantile(.90)) if len(w) else None,
        }
        reports["Vägbredd"]["width_lt_4_5m_n"]=int(w.lt(4.5).sum())

    for obj,col in [
        ("Bärighet","Bärighet_Bärighetsklass"),
        ("FunktionellVägklass","FunktionellVägklass_Klass"),
        ("Väghållare","Väghållare_Väghållartyp"),
        ("Vägtrafiknät","Vägtrafiknät_Nättyp"),
    ]:
        if col in merged:
            reports[obj]["matched_20m_value_counts"]=value_counts_dict(merged.loc[close(obj),col])

    # Height obstacles: proximity to the ordinary-road anchor only. This is a warning
    # screen, NOT proof that the obstacle lies on the future logistics route.
    hd="Höjdhinder_upp_till_45_dm"
    hdist=pd.to_numeric(merged[f"{hd}_distance_m"],errors="coerce")
    reports[hd]["near_anchor_counts"]={
        "within_30m":int(hdist.le(30).sum()),
        "within_100m":int(hdist.le(100).sum()),
        "within_500m":int(hdist.le(500).sum()),
    }

    merged.to_csv(out/"sjobo_field_nvdb_anchor_match_c2.csv",index=False,encoding="utf-8-sig")
    for obj,g in loaded.items():
        g.to_file(out/f"sjobo_{obj}_c2.geojson",driver="GeoJSON")

    report={
        "schema_version":"akeraccess-nvdb-anchor-match-c2-v0a",
        "fields_with_c1_anchor":int(len(anchors)),
        "match_reference":"C1 OSM ordinary-road anchor node",
        "crs":"EPSG:3006",
        "objects":reports,
        "interpretation":(
            "C2 measures NVDB coverage and attributes at the first ordinary-road anchor. "
            "It does not yet validate field-entrance width or prove that nearby height obstacles lie on a chosen logistics route. "
            "No ÅkerAccess score is frozen."
        ),
    }
    rp=out/"sjobo_nvdb_c2_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("="*104)
    print("ÅkerAccess STOPPUNKT C2 - NVDB COVERAGE AT C1 ROAD ANCHOR")
    print("="*104)
    print(f"C1 connected fields/anchors: {len(anchors):,}")
    print()
    for obj in OBJECTS:
        r=reports[obj]
        c=r["anchor_distance_coverage"]
        print(f"{obj}: raw rows={r['rows_with_geometry']:,} · anchors within 20 m={c['within_20m']:,} ({c['within_20m_pct']:.1f}%) · within 50 m={c['within_50m']:,} ({c['within_50m_pct']:.1f}%)")
        if obj=="Vägbredd" and r.get("matched_20m_width_n"):
            q=r["width_m_quantiles"]
            print(f"  width @<=20m: n={r['matched_20m_width_n']:,} · p10/p50/p90={q['p10']:.2f}/{q['p50']:.2f}/{q['p90']:.2f} m · <4.5m={r['width_lt_4_5m_n']:,}")
        if r.get("matched_20m_value_counts"):
            print("  values @<=20m:",r["matched_20m_value_counts"])
        if obj==hd:
            print("  height obstacles near anchor:",r["near_anchor_counts"])
    print(f"\nReport: {rp}")
    print("="*104)
    print("STOPPUNKT C2: PASS")
    print("="*104)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
