#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/"config"/"akervatten_h1_ystad_loderup_review_v0a.json"
KEY=["blockid","skiftesbeteckning"]

_spec=importlib.util.spec_from_file_location(
    "akervatten_h0",ROOT/"src"/"108_akervatten_h0_large_groundwater_inventory.py"
)
assert _spec and _spec.loader
H0=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H0)

def read_json(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def norm_id(v:Any)->str|None:
    if pd.isna(v):
        return None
    s=str(v).strip()
    if s.endswith(".0"):
        s=s[:-2]
    return s.upper()

def sj_contains(points:gpd.GeoDataFrame,polys:gpd.GeoDataFrame,cols:list[str])->tuple[pd.DataFrame,gpd.GeoDataFrame]:
    use=[c for c in cols if c in polys.columns]
    q=polys[use+["geometry"]].copy()
    if q.crs is None:
        raise RuntimeError("Polygon layer lacks CRS")
    if q.crs.to_epsg()!=3006:
        q=q.to_crs(3006)
    j=gpd.sjoin(points[["label","geometry"]],q,how="left",predicate="within")
    out=pd.DataFrame(j.drop(columns=["geometry"],errors="ignore"))
    hit_idx=sorted({int(v) for v in j["index_right"].dropna().tolist()})
    selected=q.loc[hit_idx].copy() if hit_idx else q.iloc[0:0].copy()
    return out,selected

def join_text(series:pd.Series)->str|None:
    vals=sorted({str(v).strip() for v in series if pd.notna(v) and str(v).strip()})
    return " | ".join(vals) if vals else None

def pair_distance_km(a:pd.Series,b:pd.Series)->float:
    dx=float(a["x3006"])-float(b["x3006"])
    dy=float(a["y3006"])-float(b["y3006"])
    return math.hypot(dx,dy)/1000.0

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CONFIG))
    args=ap.parse_args()
    cfg=read_json(Path(args.config))
    work=ROOT/cfg["output"]["work_dir"]
    work.mkdir(parents=True,exist_ok=True)

    print("="*126)
    print("ÅkerVatten · H1 · YSTAD / LÖDERUP HYDROLOGY REVIEW")
    print("="*126)
    print("Diagnostic only. No frozen score is modified and no new score is created.")

    print("\n[1/7] Build three focus points")
    c=pd.read_parquet(ROOT/cfg["paths"]["c_links"])
    for k in KEY:
        c[k]=c[k].astype(str)
    if c[KEY].duplicated().any():
        raise RuntimeError("C links contain duplicate field keys")
    if not {"x3006","y3006"}.issubset(c.columns):
        raise RuntimeError("C links lack x3006/y3006")

    cases=pd.read_csv(ROOT/cfg["paths"]["external_cases"],dtype={"blockid":str,"skiftesbeteckning":str})
    tr_to3006=Transformer.from_crs(4326,3006,always_xy=True)
    tr_to4326=Transformer.from_crs(3006,4326,always_xy=True)

    rows=[]
    for spec in cfg["focus_fields"]:
        mask=(c["blockid"]==str(spec["blockid"]))&(c["skiftesbeteckning"]==str(spec["skiftesbeteckning"]))
        if mask.sum()!=1:
            raise RuntimeError(f"Focus field not uniquely found: {spec}")
        r=c.loc[mask].iloc[0]
        x=float(r["x3006"]); y=float(r["y3006"])
        lon,lat=tr_to4326.transform(x,y)
        e=cases[
            (cases["blockid"].astype(str)==str(spec["blockid"]))&
            (cases["skiftesbeteckning"].astype(str)==str(spec["skiftesbeteckning"]))
        ]
        score=float(e.iloc[0]["actual_score"]) if len(e)==1 and "actual_score" in e.columns else np.nan
        rows.append({
            "label":spec["label"],"kind":"FIELD",
            "blockid":str(spec["blockid"]),"skiftesbeteckning":str(spec["skiftesbeteckning"]),
            "score_context":score,
            "x3006":x,"y3006":y,"lat":lat,"lon":lon,
            "c_omrade_id":r.get("omrade_id"),
            "c_ARO_UUID":r.get("ARO_UUID"),
            "c_Subid":r.get("Subid"),
            "nearest_field_blockid":str(spec["blockid"]),
            "nearest_field_skifte":str(spec["skiftesbeteckning"]),
            "nearest_field_distance_m":0.0
        })

    xy=c[["x3006","y3006"]].to_numpy(dtype=float)
    for spec in cfg["external_reference_points"]:
        x,y=tr_to3006.transform(float(spec["lon"]),float(spec["lat"]))
        d2=(xy[:,0]-x)**2+(xy[:,1]-y)**2
        idx=int(np.nanargmin(d2))
        nearest=c.iloc[idx]
        rows.append({
            "label":spec["label"],"kind":"EXTERNAL_ADDRESS_REFERENCE",
            "blockid":None,"skiftesbeteckning":None,
            "score_context":np.nan,
            "x3006":x,"y3006":y,"lat":float(spec["lat"]),"lon":float(spec["lon"]),
            "c_omrade_id":None,"c_ARO_UUID":None,"c_Subid":None,
            "nearest_field_blockid":str(nearest["blockid"]),
            "nearest_field_skifte":str(nearest["skiftesbeteckning"]),
            "nearest_field_distance_m":float(math.sqrt(d2[idx])),
            "address":spec.get("address"),
            "semantic":spec.get("semantic")
        })

    focus=pd.DataFrame(rows)
    gfocus=gpd.GeoDataFrame(
        focus.copy(),
        geometry=gpd.points_from_xy(focus["x3006"],focus["y3006"]),
        crs=3006
    )
    for r in focus.itertuples(index=False):
        d=r._asdict()
        print(
            f"  {d['label']:30s} · {d['kind']:26s} · "
            f"lat={float(d['lat']):.6f}, lon={float(d['lon']):.6f} · "
            f"nearest field={d['nearest_field_blockid']}/{d['nearest_field_skifte']} "
            f"({float(d['nearest_field_distance_m']):.0f} m)"
        )

    print("\n[2/7] SGU large-magazine / subarea / recharge intersections")
    gpkg=ROOT/cfg["paths"]["h0_gpkg"]
    mag=gpd.read_file(gpkg,layer="grundvattenmagasin")
    sub=gpd.read_file(gpkg,layer="magasinsdelomraden")
    rech=gpd.read_file(gpkg,layer="tillrinningsomraden")
    for name,g in (("mag",mag),("sub",sub),("rech",rech)):
        if g.crs is None:
            raise RuntimeError(f"{name} layer missing CRS")
        if g.crs.to_epsg()!=3006:
            if name=="mag": mag=g.to_crs(3006)
            elif name=="sub": sub=g.to_crs(3006)
            else: rech=g.to_crs(3006)

    mag_cols=[
        "unik_magasinsidentitet","magasinsidentitet","magasinsnamn",
        "magasinsposition","magasinsposition_kod","akvifertyp","bergart",
        "geologisk_period","grvbildningstyp","lank_magasinsbeskrivning"
    ]
    sub_cols=[
        "unik_delomradesidentitet","delomradesidentitet","unik_magasinsidentitet",
        "magasinsidentitet","magasinsposition","magasinsposition_kod",
        "uttagsmojligheter_kod","uttagsmojligheter","kornstorlek","artesiskt"
    ]
    rech_cols=[
        "unik_tillrinningsomradesidentitet","tillrinningsomradesidentitet",
        "unik_magasinsidentitet","magasinsidentitet","magasinsposition",
        "magasinsposition_kod","tillrinningsomradestyp",
        "tillrinning_till_magasinet_l_per_s","tillrinningsandel",
        "potentiell_grvbildning_mm_per_aar"
    ]
    jm,sel_mag=sj_contains(gfocus,mag,mag_cols)
    js,sel_sub=sj_contains(gfocus,sub,sub_cols)
    jr,sel_rech=sj_contains(gfocus,rech,rech_cols)

    # Attach readable magazine metadata to subarea/recharge matches.
    meta_cols=[c for c in ["unik_magasinsidentitet","magasinsnamn","akvifertyp","bergart","magasinsposition"] if c in mag.columns]
    meta=mag[meta_cols].drop_duplicates("unik_magasinsidentitet")
    for name,frame in (("subarea",js),("recharge",jr)):
        if "unik_magasinsidentitet" in frame.columns:
            add=[c for c in meta.columns if c=="unik_magasinsidentitet" or c not in frame.columns]
            merged=frame.merge(meta[add],on="unik_magasinsidentitet",how="left",validate="many_to_one")
            if name=="subarea": js=merged
            else: jr=merged

    if "uttagsmojligheter_kod" in js.columns:
        infos=[
            H0.withdrawal_info(c,l)
            for c,l in zip(js["uttagsmojligheter_kod"],js.get("uttagsmojligheter",pd.Series([None]*len(js))))
        ]
        js["withdrawal_lower_lps"]=[v[0] for v in infos]
        js["withdrawal_upper_lps"]=[v[1] for v in infos]
        js["withdrawal_label_norm"]=[v[2] for v in infos]

    for label in focus["label"]:
        print(f"\n  {label}")
        a=jm[(jm["label"]==label)&jm["unik_magasinsidentitet"].notna()] if "unik_magasinsidentitet" in jm.columns else pd.DataFrame()
        if a.empty:
            print("    magazine: NONE")
        else:
            for r in a.itertuples(index=False):
                d=r._asdict()
                print(
                    f"    magazine: uid={d.get('unik_magasinsidentitet')} · "
                    f"name={d.get('magasinsnamn')} · pos={d.get('magasinsposition')} · "
                    f"aquifer={d.get('akvifertyp')} · rock={d.get('bergart')}"
                )
        b=js[(js["label"]==label)&js["unik_delomradesidentitet"].notna()] if "unik_delomradesidentitet" in js.columns else pd.DataFrame()
        if b.empty:
            print("    subarea : NONE")
        else:
            for r in b.itertuples(index=False):
                d=r._asdict()
                print(
                    f"    subarea : uid={d.get('unik_delomradesidentitet')} · "
                    f"mag_uid={d.get('unik_magasinsidentitet')} · "
                    f"withdrawal={d.get('withdrawal_label_norm')} · "
                    f"lower={d.get('withdrawal_lower_lps')} l/s · upper={d.get('withdrawal_upper_lps')} l/s"
                )
        z=jr[(jr["label"]==label)&jr["unik_tillrinningsomradesidentitet"].notna()] if "unik_tillrinningsomradesidentitet" in jr.columns else pd.DataFrame()
        if z.empty:
            print("    recharge: NONE")
        else:
            for r in z.itertuples(index=False):
                d=r._asdict()
                print(
                    f"    recharge: uid={d.get('unik_tillrinningsomradesidentitet')} · "
                    f"mag_uid={d.get('unik_magasinsidentitet')} · "
                    f"type={d.get('tillrinningsomradestyp')} · "
                    f"potential={d.get('potentiell_grvbildning_mm_per_aar')} mm/year"
                )

    print("\n[3/7] SGU-HYPE groundwater-area intersection")
    hype=gpd.read_file(ROOT/cfg["paths"]["c_sgu_hype"])
    if hype.crs is None:
        raise RuntimeError("SGU-HYPE layer missing CRS")
    if hype.crs.to_epsg()!=3006:
        hype=hype.to_crs(3006)
    hype_cols=[c for c in ["omrade_id","url_tidsserie"] if c in hype.columns]
    jh,sel_hype=sj_contains(gfocus,hype,hype_cols)
    hype_map={}
    for label in focus["label"]:
        q=jh[(jh["label"]==label)&jh["omrade_id"].notna()] if "omrade_id" in jh.columns else pd.DataFrame()
        ids=sorted({str(v) for v in q.get("omrade_id",pd.Series(dtype=object)).dropna()})
        hype_map[label]=" | ".join(ids) if ids else None
        print(f"  {label:30s}: omrade_id={hype_map[label]}")

    print("\n[4/7] SVAR2022 / S-HYPE catchment intersection")
    tile_dir=ROOT/cfg["paths"]["c_svar_tiles"]
    tile_paths=sorted(tile_dir.glob("tile_*.geojson"))
    if not tile_paths:
        raise RuntimeError(f"No SVAR tiles found in {tile_dir}")
    pieces=[gpd.read_file(p) for p in tile_paths]
    svar=gpd.GeoDataFrame(pd.concat(pieces,ignore_index=True),crs=pieces[0].crs)
    aro_col=next((c for c in svar.columns if str(c).upper()=="ARO_UUID"),None)
    if aro_col is None:
        raise RuntimeError("SVAR polygons lack ARO_UUID")
    svar=svar.drop_duplicates(subset=[aro_col]).reset_index(drop=True)
    if svar.crs is None:
        raise RuntimeError("SVAR layer missing CRS")
    if svar.crs.to_epsg()!=3006:
        svar=svar.to_crs(3006)

    svar_cols=[c for c in [aro_col,"HARO","MAINDOWN","BARONR","AREA","AREA_UPSTREAM"] if c in svar.columns]
    ja,sel_svar=sj_contains(gfocus,svar,svar_cols)

    amap=c[[aro_col,"Subid"]].dropna().copy()
    amap["_aro_norm"]=amap[aro_col].map(norm_id)
    amap["_sub_norm"]=amap["Subid"].map(norm_id)
    conflict=amap.groupby("_aro_norm")["_sub_norm"].nunique()
    if (conflict>1).any():
        raise RuntimeError("C links contain ARO_UUID -> multiple Subid conflict")
    aro_to_sub=amap.drop_duplicates("_aro_norm").set_index("_aro_norm")["_sub_norm"].to_dict()

    surface={}
    for label in focus["label"]:
        q=ja[(ja["label"]==label)&ja[aro_col].notna()] if aro_col in ja.columns else pd.DataFrame()
        aros=sorted({norm_id(v) for v in q.get(aro_col,pd.Series(dtype=object)).dropna()})
        subs=sorted({aro_to_sub.get(a) for a in aros if aro_to_sub.get(a)})
        surface[label]={
            "ARO_UUID":" | ".join(aros) if aros else None,
            "Subid":" | ".join(subs) if subs else None
        }
        print(
            f"  {label:30s}: ARO_UUID={surface[label]['ARO_UUID']} · "
            f"Subid={surface[label]['Subid']}"
        )

    print("\n[5/7] Comparison table")
    summary_rows=[]
    for r in focus.itertuples(index=False):
        d=r._asdict(); label=d["label"]
        mq=jm[(jm["label"]==label)&jm.get("unik_magasinsidentitet",pd.Series(index=jm.index,dtype=object)).notna()]
        sq=js[(js["label"]==label)&js.get("unik_delomradesidentitet",pd.Series(index=js.index,dtype=object)).notna()]
        rq=jr[(jr["label"]==label)&jr.get("unik_tillrinningsomradesidentitet",pd.Series(index=jr.index,dtype=object)).notna()]
        summary_rows.append({
            **{k:d.get(k) for k in [
                "label","kind","blockid","skiftesbeteckning","score_context",
                "lat","lon","x3006","y3006","nearest_field_blockid",
                "nearest_field_skifte","nearest_field_distance_m","address","semantic"
            ] if k in d},
            "omrade_id":hype_map.get(label),
            "ARO_UUID":surface[label]["ARO_UUID"],
            "Subid":surface[label]["Subid"],
            "magazine_uids":join_text(mq["unik_magasinsidentitet"]) if len(mq) else None,
            "magazine_names":join_text(mq["magasinsnamn"]) if len(mq) and "magasinsnamn" in mq.columns else None,
            "magazine_positions":join_text(mq["magasinsposition"]) if len(mq) and "magasinsposition" in mq.columns else None,
            "subarea_uids":join_text(sq["unik_delomradesidentitet"]) if len(sq) else None,
            "withdrawal_classes":join_text(sq["withdrawal_label_norm"]) if len(sq) and "withdrawal_label_norm" in sq.columns else None,
            "recharge_uids":join_text(rq["unik_tillrinningsomradesidentitet"]) if len(rq) else None,
            "recharge_types":join_text(rq["tillrinningsomradestyp"]) if len(rq) and "tillrinningsomradestyp" in rq.columns else None,
        })
    summary=pd.DataFrame(summary_rows)
    summary.to_csv(work/"h1_focus_comparison.csv",index=False)
    for r in summary.itertuples(index=False):
        d=r._asdict()
        print(
            f"  {d['label']:30s} · omrade={d.get('omrade_id')} · "
            f"Subid={d.get('Subid')} · pos={d.get('magazine_positions')} · "
            f"withdrawal={d.get('withdrawal_classes')}"
        )

    print("\n[6/7] Pairwise hydrological identity")
    pairs=[]
    for i in range(len(summary)):
        for j in range(i+1,len(summary)):
            a=summary.iloc[i]; b=summary.iloc[j]
            rec={
                "a":a["label"],"b":b["label"],
                "distance_km":pair_distance_km(focus.iloc[i],focus.iloc[j]),
                "same_omrade_id":bool(pd.notna(a["omrade_id"]) and a["omrade_id"]==b["omrade_id"]),
                "same_ARO_UUID":bool(pd.notna(a["ARO_UUID"]) and a["ARO_UUID"]==b["ARO_UUID"]),
                "same_Subid":bool(pd.notna(a["Subid"]) and a["Subid"]==b["Subid"]),
                "same_magazine_uid_set":bool(pd.notna(a["magazine_uids"]) and a["magazine_uids"]==b["magazine_uids"])
            }
            pairs.append(rec)
            print(
                f"  {rec['a']}  <->  {rec['b']} · {rec['distance_km']:.2f} km · "
                f"same SGU-HYPE={rec['same_omrade_id']} · "
                f"same ARO={rec['same_ARO_UUID']} · same Subid={rec['same_Subid']} · "
                f"same large-magazine set={rec['same_magazine_uid_set']}"
            )
    pd.DataFrame(pairs).to_csv(work/"h1_pairwise_hydrology.csv",index=False)

    print("\n[7/7] Map-ready exports")
    points_wgs=gfocus.to_crs(4326)
    points_wgs.to_file(work/"h1_focus_points.geojson",driver="GeoJSON")
    if len(sel_mag): sel_mag.to_crs(4326).to_file(work/"h1_focus_magazines.geojson",driver="GeoJSON")
    if len(sel_sub): sel_sub.to_crs(4326).to_file(work/"h1_focus_subareas.geojson",driver="GeoJSON")
    if len(sel_rech): sel_rech.to_crs(4326).to_file(work/"h1_focus_recharge_areas.geojson",driver="GeoJSON")
    if len(sel_hype): sel_hype.to_crs(4326).to_file(work/"h1_focus_sgu_hype.geojson",driver="GeoJSON")
    if len(sel_svar): sel_svar.to_crs(4326).to_file(work/"h1_focus_svar_catchments.geojson",driver="GeoJSON")
    print(f"  outputs: {work}")

    result={
        "schema_version":"akervatten-h1-ystad-loderup-hydrology-review-result",
        "status":"PASS_WITH_REVIEW",
        "focus_points":summary.to_dict(orient="records"),
        "pairwise":pairs,
        "score_created":False,
        "guardrails":cfg["guardrails"]
    }
    (work/"h1_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")

    print("\n"+"="*126)
    print("ÅKERVATTEN H1 YSTAD / LÖDERUP REVIEW: PASS_WITH_REVIEW")
    print("="*126)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
