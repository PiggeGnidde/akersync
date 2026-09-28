#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/"config"/"akervatten_h0_large_groundwater_v0a.json"
KEY=["blockid","skiftesbeteckning"]

# SGU Grundvattenmagasin product-description value domain.
# Numeric bounds are converted to l/s where the legacy label is in l/h.
WITHDRAWAL={
    -2: (None,None,"ospecificerat/okänt"),
    -1: (None,None,"bedömning ej utförd"),
    2007:(None,None,"okända uttagsmöjligheter"),
    2001:(0.0,1.0,"<1 l/s"),
    2002:(1.0,5.0,"1–5 l/s"),
    2003:(5.0,25.0,"5–25 l/s"),
    2004:(25.0,125.0,"25–125 l/s"),
    2005:(125.0,None,">125 l/s"),
    1050:(0.0,20000.0/3600.0,"begränsade grundvattentillgångar i berg 0–20 000 l/h"),
    1009:(0.0,200.0/3600.0,"kristallint berg <200 l/h"),
    1006:(0.0,600.0/3600.0,"kristallint berg <600 l/h"),
    1008:(200.0/3600.0,600.0/3600.0,"kristallint berg 200–600 l/h"),
    1005:(600.0/3600.0,2000.0/3600.0,"kristallint berg 600–2 000 l/h"),
    1004:(2000.0/3600.0,6000.0/3600.0,"kristallint berg 2 000–6 000 l/h"),
    1003:(6000.0/3600.0,20000.0/3600.0,"kristallint berg 6 000–20 000 l/h"),
    1002:(20000.0/3600.0,60000.0/3600.0,"kristallint berg 20 000–60 000 l/h"),
    1001:(60000.0/3600.0,200000.0/3600.0,"kristallint berg 60 000–200 000 l/h"),
    1015:(0.0,600.0/3600.0,"sedimentärt berg <600 l/h"),
    1014:(600.0/3600.0,2000.0/3600.0,"sedimentärt berg 600–2 000 l/h"),
    1013:(2000.0/3600.0,6000.0/3600.0,"sedimentärt berg 2 000–6 000 l/h"),
    1012:(6000.0/3600.0,20000.0/3600.0,"sedimentärt berg 6 000–20 000 l/h"),
    1011:(20000.0/3600.0,60000.0/3600.0,"sedimentärt berg 20 000–60 000 l/h"),
    1010:(60000.0/3600.0,200000.0/3600.0,"sedimentärt berg 60 000–200 000 l/h"),
    1016:(None,None,"okänd mediankapacitet"),
}

def read_json(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def download(url:str,path:Path)->Path:
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.stat().st_size>0:
        print(f"  cache: {path} ({path.stat().st_size/1024/1024:.1f} MB)")
        return path
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.unlink(missing_ok=True)
    print(f"  downloading: {url}")
    with requests.get(url,stream=True,timeout=180) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:
                    f.write(chunk)
    os.replace(tmp,path)
    print(f"  saved: {path} ({path.stat().st_size/1024/1024:.1f} MB)")
    return path

def extract_gpkg(zip_path:Path,out_dir:Path)->Path:
    out_dir.mkdir(parents=True,exist_ok=True)
    cached=list(out_dir.rglob("*.gpkg"))
    if cached:
        return cached[0]
    with zipfile.ZipFile(zip_path) as z:
        members=[m for m in z.namelist() if m.lower().endswith(".gpkg")]
        if len(members)!=1:
            raise RuntimeError(f"Expected exactly one GeoPackage in archive, got {members}")
        member=members[0]
        z.extract(member,out_dir)
        gpkg=out_dir/member
        if not gpkg.exists():
            raise RuntimeError("GeoPackage extraction failed")
        return gpkg

def list_layers(path:Path)->list[str]:
    try:
        import pyogrio
        x=pyogrio.list_layers(path)
        return [str(v) for v in x[:,0]]
    except Exception:
        import fiona
        return list(fiona.listlayers(path))

def withdrawal_info(code:Any,label:Any=None)->tuple[float|None,float|None,str|None]:
    try:
        c=int(float(code))
    except Exception:
        c=None
    if c in WITHDRAWAL:
        lo,hi,canonical=WITHDRAWAL[c]
        return lo,hi,str(label) if pd.notna(label) and str(label).strip() else canonical
    return None,None,None if pd.isna(label) else str(label)

def norm_key(s:pd.Series)->pd.Series:
    return s.astype("string").str.strip().str.replace(r"\.0$","",regex=True)

def string_join(values:pd.Series)->str|None:
    vals=sorted({str(v).strip() for v in values if pd.notna(v) and str(v).strip()})
    return " | ".join(vals) if vals else None

def read_layer(gpkg:Path,layer:str,bbox:tuple[float,float,float,float])->gpd.GeoDataFrame:
    g=gpd.read_file(gpkg,layer=layer,bbox=bbox)
    if g.crs is None:
        raise RuntimeError(f"{layer}: missing CRS")
    if g.crs.to_epsg()!=3006:
        g=g.to_crs(3006)
    g=g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    return g

def point_join(points:gpd.GeoDataFrame,polys:gpd.GeoDataFrame,cols:list[str])->pd.DataFrame:
    use=[c for c in cols if c in polys.columns]
    q=polys[use+["geometry"]].copy()
    j=gpd.sjoin(points[KEY+["field_seq","geometry"]],q,how="inner",predicate="within")
    return pd.DataFrame(j.drop(columns=["geometry","index_right"],errors="ignore"))

def add_magazine_metadata(matches:pd.DataFrame,mag:gpd.GeoDataFrame)->pd.DataFrame:
    if matches.empty or "unik_magasinsidentitet" not in matches.columns:
        return matches
    meta_cols=[
        "unik_magasinsidentitet","magasinsnamn","lank_magasinsbeskrivning",
        "akvifertyp","genes","bergart","geologisk_period",
        "grvbildningstyp","magasinsposition","magasinsposition_kod",
        "geometrikvalitet","karteringsprocess",
        "tillrinning_fran_tillrinningsomraden_l_per_s"
    ]
    meta=mag[[c for c in meta_cols if c in mag.columns]].drop_duplicates("unik_magasinsidentitet")
    # Avoid duplicate columns already supplied by the matched layer.
    add=[c for c in meta.columns if c=="unik_magasinsidentitet" or c not in matches.columns]
    return matches.merge(meta[add],on="unik_magasinsidentitet",how="left",validate="many_to_one")

def aggregate_fields(base:pd.DataFrame,direct:pd.DataFrame,sub:pd.DataFrame,recharge:pd.DataFrame)->pd.DataFrame:
    out=base.copy()

    if not direct.empty:
        d=direct.groupby(KEY,dropna=False).agg(
            large_gw_magazine_count=("unik_magasinsidentitet","nunique"),
            large_gw_magazine_names=("magasinsnamn",string_join),
            large_gw_positions=("magasinsposition",string_join),
            large_gw_aquifer_types=("akvifertyp",string_join),
            large_gw_rock_types=("bergart",string_join),
        ).reset_index()
        out=out.merge(d,on=KEY,how="left",validate="one_to_one")

    if not sub.empty:
        s=sub.copy()
        code_col="uttagsmojligheter_kod"
        label_col="uttagsmojligheter"
        infos=[
            withdrawal_info(c,l)
            for c,l in zip(
                s[code_col] if code_col in s.columns else [None]*len(s),
                s[label_col] if label_col in s.columns else [None]*len(s)
            )
        ]
        s["withdrawal_lower_lps"]=[x[0] for x in infos]
        s["withdrawal_upper_lps"]=[x[1] for x in infos]
        s["withdrawal_label_norm"]=[x[2] for x in infos]
        rows=[]
        for key,q in s.groupby(KEY,dropna=False):
            known=q[q["withdrawal_lower_lps"].notna()].copy()
            best=None
            if len(known):
                best=known.sort_values(
                    ["withdrawal_lower_lps","withdrawal_upper_lps"],
                    ascending=[False,False],na_position="first",kind="mergesort"
                ).iloc[0]
            rows.append({
                KEY[0]:key[0],KEY[1]:key[1],
                "large_gw_subarea_count":int(q["unik_delomradesidentitet"].nunique()) if "unik_delomradesidentitet" in q.columns else int(len(q)),
                "large_gw_withdrawal_classes":string_join(q["withdrawal_label_norm"]),
                "large_gw_best_withdrawal_class":None if best is None else best["withdrawal_label_norm"],
                "large_gw_best_withdrawal_lower_lps":np.nan if best is None else best["withdrawal_lower_lps"],
                "large_gw_best_withdrawal_upper_lps":np.nan if best is None else best["withdrawal_upper_lps"],
            })
        out=out.merge(pd.DataFrame(rows),on=KEY,how="left",validate="one_to_one")

    if not recharge.empty:
        r=recharge.groupby(KEY,dropna=False).agg(
            large_gw_recharge_count=("unik_tillrinningsomradesidentitet","nunique"),
            large_gw_recharge_magazine_names=("magasinsnamn",string_join),
            large_gw_recharge_types=("tillrinningsomradestyp",string_join),
        ).reset_index()
        out=out.merge(r,on=KEY,how="left",validate="one_to_one")

    for c in ("large_gw_magazine_count","large_gw_subarea_count","large_gw_recharge_count"):
        if c not in out.columns:
            out[c]=0
        out[c]=pd.to_numeric(out[c],errors="coerce").fillna(0).astype(int)

    direct_mask=out["large_gw_magazine_count"]>0
    recharge_mask=out["large_gw_recharge_count"]>0
    out["large_gw_relation"]=np.select(
        [direct_mask,recharge_mask],
        ["DIRECT_MAGAZINE","RECHARGE_AREA_ONLY"],
        default="NONE"
    )

    pos=out.get("large_gw_positions",pd.Series(index=out.index,dtype="object")).fillna("").astype(str)
    out["large_gw_has_sedimentary"]=pos.str.contains(r"(^|\| )S[123]",regex=True)
    out["large_gw_has_soil_magazine"]=pos.str.contains(r"(^|\| )J[123]",regex=True)
    out["large_gw_has_crystalline"]=pos.str.contains(r"(^|\| )K1",regex=True)
    return out

def pct(n:int,total:int)->float:
    return 100.0*n/total if total else float("nan")

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CONFIG))
    args=ap.parse_args()
    cfg=read_json(Path(args.config))

    raw=ROOT/cfg["output"]["raw_dir"]
    work=ROOT/cfg["output"]["work_dir"]
    work.mkdir(parents=True,exist_ok=True)

    print("="*124)
    print("ÅkerVatten · H0 · STORA GRUNDVATTENMAGASIN · SKÅNE INVENTORY")
    print("="*124)
    print("No 0-100 score is created. This is a source inventory / spatial screening step.")

    print("\n[1/7] Canonical field representative points")
    pts=pd.read_parquet(ROOT/cfg["paths"]["field_points"])
    for k in KEY:
        pts[k]=pts[k].astype(str)
    if len(pts)!=int(cfg["expected_fields"]):
        raise RuntimeError(f"Expected {cfg['expected_fields']} fields, got {len(pts)}")
    if pts[KEY].duplicated().any():
        raise RuntimeError("Duplicate field keys")
    if not {"x3006","y3006"}.issubset(pts.columns):
        raise RuntimeError("C field-point cache lacks x3006/y3006")
    gpts=gpd.GeoDataFrame(
        pts.copy(),
        geometry=gpd.points_from_xy(pts["x3006"],pts["y3006"]),
        crs=3006
    )
    print(f"  fields: {len(gpts):,}")

    print("\n[2/7] SGU Grundvattenmagasin source")
    zip_path=download(cfg["source"]["bulk_zip_url"],raw/"grundvattenmagasin.zip")
    gpkg=extract_gpkg(zip_path,raw/"extracted")
    layers=list_layers(gpkg)
    needed=list(cfg["source"]["layers"].values())
    missing=[x for x in needed if x not in layers]
    if missing:
        raise RuntimeError(f"Missing expected SGU layer(s) {missing}; available={layers}")
    print(f"  source sha256: {sha256(zip_path)}")
    print(f"  GeoPackage: {gpkg}")
    print(f"  layers: {', '.join(layers)}")

    minx,miny,maxx,maxy=(float(v) for v in gpts.total_bounds)
    bbox=(minx-5000,miny-5000,maxx+5000,maxy+5000)

    print("\n[3/7] Read Skåne-window source layers")
    mag=read_layer(gpkg,cfg["source"]["layers"]["magazine"],bbox)
    sub=read_layer(gpkg,cfg["source"]["layers"]["subarea"],bbox)
    recharge=read_layer(gpkg,cfg["source"]["layers"]["recharge"],bbox)
    print(f"  magazine polygons      : {len(mag):,}")
    print(f"  subarea polygons       : {len(sub):,}")
    print(f"  recharge-area polygons : {len(recharge):,}")

    print("\n[4/7] Representative-point spatial joins")
    direct_cols=[
        "unik_magasinsidentitet","magasinsidentitet","magasinsnamn",
        "lank_magasinsbeskrivning","akvifertyp","genes","bergart",
        "geologisk_period","grvbildningstyp","magasinsposition",
        "magasinsposition_kod","geometrikvalitet","karteringsprocess",
        "tillrinning_fran_tillrinningsomraden_l_per_s"
    ]
    sub_cols=[
        "unik_delomradesidentitet","delomradesidentitet","unik_magasinsidentitet",
        "magasinsidentitet","uttagsmojligheter_kod","uttagsmojligheter",
        "kornstorlek","artesiskt","delomradeskvalitet","magasinsposition",
        "magasinsposition_kod"
    ]
    recharge_cols=[
        "unik_tillrinningsomradesidentitet","tillrinningsomradesidentitet",
        "unik_magasinsidentitet","magasinsidentitet","tillrinningsomradestyp",
        "tillrinning_till_magasinet_l_per_s","tillrinningsandel",
        "potentiell_grvbildning_mm_per_aar","magasinsposition","magasinsposition_kod"
    ]

    direct=point_join(gpts,mag,direct_cols)
    submatch=add_magazine_metadata(point_join(gpts,sub,sub_cols),mag)
    rechmatch=add_magazine_metadata(point_join(gpts,recharge,recharge_cols),mag)

    print(f"  direct point×magazine matches : {len(direct):,}")
    print(f"  point×subarea matches         : {len(submatch):,}")
    print(f"  point×recharge matches        : {len(rechmatch):,}")

    direct.to_parquet(work/"h0_direct_magazine_matches.parquet",index=False)
    submatch.to_parquet(work/"h0_subarea_matches.parquet",index=False)
    rechmatch.to_parquet(work/"h0_recharge_matches.parquet",index=False)

    print("\n[5/7] Field-level inventory")
    basecols=KEY+[c for c in ("field_seq","kommun","area_ha") if c in pts.columns]
    fields=aggregate_fields(pts[basecols],direct,submatch,rechmatch)
    if len(fields)!=len(pts) or fields[KEY].duplicated().any():
        raise RuntimeError("Field summary identity changed")
    fields.to_parquet(work/"akervatten_h0_large_groundwater_fields_skane.parquet",index=False)

    total=len(fields)
    n_direct=int((fields["large_gw_relation"]=="DIRECT_MAGAZINE").sum())
    n_recharge=int((fields["large_gw_relation"]=="RECHARGE_AREA_ONLY").sum())
    n_none=int((fields["large_gw_relation"]=="NONE").sum())
    n_sed=int(fields["large_gw_has_sedimentary"].sum())
    n_soil=int(fields["large_gw_has_soil_magazine"].sum())
    n_crys=int(fields["large_gw_has_crystalline"].sum())
    n_withdraw=int(fields.get("large_gw_best_withdrawal_class",pd.Series(index=fields.index,dtype=object)).notna().sum())

    print(f"  DIRECT_MAGAZINE   : {n_direct:,} ({pct(n_direct,total):.2f}%)")
    print(f"  RECHARGE_AREA_ONLY: {n_recharge:,} ({pct(n_recharge,total):.2f}%)")
    print(f"  NONE              : {n_none:,} ({pct(n_none,total):.2f}%)")
    print(f"  sedimentary S1-S3 : {n_sed:,} ({pct(n_sed,total):.2f}%)")
    print(f"  soil J1-J3        : {n_soil:,} ({pct(n_soil,total):.2f}%)")
    print(f"  crystalline K1    : {n_crys:,} ({pct(n_crys,total):.2f}%)")
    print(f"  direct + known withdrawal class: {n_withdraw:,} ({pct(n_withdraw,total):.2f}%)")

    print("\n[6/7] Withdrawal classes + municipality inventory")
    class_counts=(
        fields["large_gw_best_withdrawal_class"].fillna("(none)")
        .value_counts().rename_axis("withdrawal_class").reset_index(name="fields")
    )
    class_counts["pct_fields"]=100*class_counts["fields"]/total
    class_counts.to_csv(work/"h0_withdrawal_class_counts.csv",index=False)
    for r in class_counts.head(20).itertuples(index=False):
        print(f"  {str(r.withdrawal_class):58s} {int(r.fields):7,d} · {r.pct_fields:6.2f}%")

    mun_rows=[]
    if "kommun" in fields.columns:
        for mun,q in fields.groupby("kommun",dropna=False):
            mun_rows.append({
                "kommun":None if pd.isna(mun) else str(mun),
                "fields":int(len(q)),
                "direct_magazine_fields":int((q["large_gw_relation"]=="DIRECT_MAGAZINE").sum()),
                "direct_magazine_pct":100*(q["large_gw_relation"]=="DIRECT_MAGAZINE").mean(),
                "recharge_only_fields":int((q["large_gw_relation"]=="RECHARGE_AREA_ONLY").sum()),
                "recharge_only_pct":100*(q["large_gw_relation"]=="RECHARGE_AREA_ONLY").mean(),
                "sedimentary_fields":int(q["large_gw_has_sedimentary"].sum()),
                "sedimentary_pct":100*q["large_gw_has_sedimentary"].mean(),
                "known_withdrawal_fields":int(q["large_gw_best_withdrawal_class"].notna().sum()),
                "known_withdrawal_pct":100*q["large_gw_best_withdrawal_class"].notna().mean(),
            })
        pd.DataFrame(mun_rows).to_csv(work/"h0_municipality_summary.csv",index=False)

    print("\n[7/7] External-validation focus + Ystad magazine names")
    focus_path=ROOT/cfg["paths"]["external_validation_cases"]
    focus_out=pd.DataFrame()
    if focus_path.exists():
        focus=pd.read_csv(focus_path,dtype={"blockid":str,"skiftesbeteckning":str})
        focus_out=focus.merge(fields,on=KEY,how="left",validate="one_to_one")
        focus_out.to_csv(work/"h0_external_validation_10_extremes.csv",index=False)
        for r in focus_out.itertuples(index=False):
            d=r._asdict()
            print(
                f"  {str(d.get('component','?')):23s} {str(d.get('extreme','?')):3s} · "
                f"{d.get('kommun','?')} · {d['blockid']}/{d['skiftesbeteckning']} · "
                f"relation={d.get('large_gw_relation')} · "
                f"mag={d.get('large_gw_magazine_names')} · "
                f"pos={d.get('large_gw_positions')} · "
                f"withdrawal={d.get('large_gw_best_withdrawal_class')}"
            )
    else:
        print("  external-validation case file not found; focus join skipped")

    if "kommun" in fields.columns:
        y=fields[fields["kommun"].astype(str).str.casefold()=="ystad".casefold()]
        if len(y):
            print("\n  Ystad · direct magazine names by field count")
            tmp=y[y["large_gw_relation"]=="DIRECT_MAGAZINE"]["large_gw_magazine_names"].dropna()
            counts={}
            for value in tmp:
                for name in str(value).split(" | "):
                    counts[name]=counts.get(name,0)+1
            for name,n in sorted(counts.items(),key=lambda kv:(-kv[1],kv[0]))[:20]:
                print(f"    {name:45s} {n:6,d} fields")

    summary={
        "schema_version":"akervatten-h0-large-groundwater-inventory-result",
        "status":"PASS_WITH_REVIEW",
        "fields_total":total,
        "source":{
            "zip_url":cfg["source"]["bulk_zip_url"],
            "zip_sha256":sha256(zip_path),
            "gpkg":str(gpkg),
            "layers":layers
        },
        "coverage":{
            "direct_magazine":{"n":n_direct,"pct":pct(n_direct,total)},
            "recharge_area_only":{"n":n_recharge,"pct":pct(n_recharge,total)},
            "none":{"n":n_none,"pct":pct(n_none,total)},
            "sedimentary":{"n":n_sed,"pct":pct(n_sed,total)},
            "soil_magazine":{"n":n_soil,"pct":pct(n_soil,total)},
            "crystalline":{"n":n_crys,"pct":pct(n_crys,total)},
            "known_withdrawal":{"n":n_withdraw,"pct":pct(n_withdraw,total)}
        },
        "spatial_rule":cfg["spatial_rule"],
        "guardrails":cfg["guardrails"],
        "score_created":False
    }
    (work/"h0_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("\n" + "="*124)
    print("ÅKERVATTEN H0 LARGE GROUNDWATER INVENTORY: PASS_WITH_REVIEW")
    print("="*124)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
