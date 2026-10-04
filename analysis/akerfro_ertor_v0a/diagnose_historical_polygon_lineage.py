#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trace historical ÅkerMinne crop polygons into selected current fields.

Read-only diagnostic for boundary drift / sliver lineage. It reports the
historical field IDs and overlap fractions that caused a current-field crop
component. No data or model files are modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]

def norm_field(token:str)->str:
    t=token.strip()
    if ":" in t and "|" not in t:
        a,b=t.split(":",1)
        return a.strip()+"|"+b.strip()
    return t

def candidate_minne_roots():
    roots=[
        ROOT.parent/"AkerSync-Minne",
        Path(r"C:\AkerSync-Minne"),
    ]
    seen=set()
    for p in roots:
        try:p=p.resolve()
        except OSError:continue
        if p.exists() and p not in seen:
            seen.add(p);yield p

def municipality_dirs():
    for root in candidate_minne_roots():
        d=root/"data"/"derived"/"akerminne_v1a"/"skane"/"municipalities"
        if d.is_dir():
            yield from sorted(p for p in d.iterdir() if p.is_dir())

def load_selected(ids:set[str],year:int)->pd.DataFrame:
    pieces=[]
    for d in municipality_dirs():
        p=d/"akerminne_components.parquet"
        if not p.is_file():continue
        # Read only needed columns when possible.
        cols=[
            "municipality","history_year","current_field_id",
            "historical_field_id","historical_block_id","historical_skiftesbeteckning",
            "crop_name","crop_group","crop_code_raw","crop_subcategory_raw",
            "intersection_m2","share_current","share_historical",
            "same_admin_key","is_current_primary","is_historical_primary","is_mutual_primary",
        ]
        try:
            q=pd.read_parquet(p,columns=cols)
        except Exception:
            q=pd.read_parquet(p)
        if "current_field_id" not in q.columns:continue
        mask=q["current_field_id"].astype(str).isin(ids)
        if "history_year" in q.columns:
            mask &= pd.to_numeric(q["history_year"],errors="coerce").eq(year)
        q=q.loc[mask].copy()
        if len(q):
            q["_source"]=str(p)
            pieces.append(q)
    if not pieces:return pd.DataFrame()
    return pd.concat(pieces,ignore_index=True)

def is_conservart(row)->bool:
    name=str(row.get("crop_name") or "").lower()
    group=str(row.get("crop_group") or "").upper()
    return "konserv" in name or "CONSERVART" in group

def fmt_bool(v):
    if pd.isna(v):return "—"
    return "Y" if bool(v) else "N"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",type=int,default=2021)
    ap.add_argument("fields",nargs="+")
    args=ap.parse_args()
    ids=[norm_field(x) for x in args.fields]
    q=load_selected(set(ids),args.year)
    if q.empty:
        raise RuntimeError("No matching ÅkerMinne component rows found")

    print("="*132)
    print(f"ÅkerMinne HISTORICAL POLYGON LINEAGE · READ ONLY · {args.year}")
    print("="*132)
    for fid in ids:
        g=q[q["current_field_id"].astype(str).eq(fid)].copy()
        print("\n"+"-"*132)
        print("CURRENT FIELD",fid)
        if g.empty:
            print("  No component rows")
            continue
        g["is_conservart"]=g.apply(is_conservart,axis=1)
        g=g.sort_values(["is_conservart","intersection_m2"],ascending=[False,False],kind="mergesort")
        show=[c for c in [
            "crop_name","historical_field_id","historical_block_id","historical_skiftesbeteckning",
            "intersection_m2","share_current","share_historical",
            "same_admin_key","is_current_primary","is_historical_primary","is_mutual_primary"
        ] if c in g.columns]
        print(g[show].to_string(index=False,formatters={
            "intersection_m2":lambda x:f"{float(x):.6f}",
            "share_current":lambda x:f"{100*float(x):.8f}%",
            "share_historical":lambda x:f"{100*float(x):.8f}%",
            "same_admin_key":fmt_bool,
            "is_current_primary":fmt_bool,
            "is_historical_primary":fmt_bool,
            "is_mutual_primary":fmt_bool,
        }))

    cons=q[q.apply(is_conservart,axis=1)].copy()
    print("\n"+"="*132)
    print("CONSERVÄRT HISTORICAL-FIELD LINEAGE ACROSS SELECTED CURRENT FIELDS")
    print("="*132)
    if cons.empty:
        print("No CONSERVART components found.")
    else:
        cons["historical_field_id"]=cons["historical_field_id"].astype(str)
        for hid,g in cons.groupby("historical_field_id",sort=True):
            print(f"\nHISTORICAL FIELD {hid}")
            hblock=str(g["historical_block_id"].iloc[0]) if "historical_block_id" in g else ""
            hsk=str(g["historical_skiftesbeteckning"].iloc[0]) if "historical_skiftesbeteckning" in g else ""
            print(f"  historical block/skifte: {hblock} / {hsk}")
            for r in g.sort_values("intersection_m2",ascending=False).itertuples(index=False):
                print(
                    f"  -> {r.current_field_id}: "
                    f"intersection={float(r.intersection_m2):.6f} m² · "
                    f"current_share={100*float(r.share_current):.8f}% · "
                    f"historical_share={100*float(r.share_historical):.8f}%"
                )
            if len(g)>=2:
                print("  >>> SAME HISTORICAL CONSERVÄRT POLYGON reaches multiple selected current fields")

    print("\nNo files changed.")
    print("="*132)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
