#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only ÅkerFrö rotation diagnosis for selected current fields.

Finds existing frozen/local products under known AkerSync worktrees and prints
the exact recent pea/faba trigger plus any CONSERVART component shares.
No files are modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve()
ROOT=HERE.parents[2]
YEARS=range(2021,2026)

def norm_field(token:str)->str:
    t=token.strip()
    if ":" in t and "|" not in t:
        a,b=t.split(":",1); return a.strip()+"|"+b.strip()
    return t

def roots():
    seen=set()
    for p in [ROOT, ROOT.parent/"AkerSync-AkerFro", ROOT.parent/"AkerSync-AkerFroWeb",
              Path(r"C:\AkerSync-AkerFro"), Path(r"C:\AkerSync-AkerFroWeb"),
              Path(r"C:\AkerSync-AkerAccess")]:
        try:p=p.resolve()
        except OSError:continue
        if p not in seen and p.exists():
            seen.add(p); yield p
    try:
        for p in Path("C:/").glob("AkerSync*"):
            p=p.resolve()
            if p not in seen:
                seen.add(p); yield p
    except OSError:pass

def find_named(name:str):
    hits=[]
    for r in roots():
        direct=[
            r/"data"/"derived"/"akerfro_ertor_v0a"/name,
            r/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0b"/name,
            r/"work"/"akerfro_ertor_v0a"/"rotation_predecessor_c7"/name,
            r/"work"/"akeraccess_v0a"/"bestmatch_d5"/name,
        ]
        for p in direct:
            if p.is_file() and p not in hits:hits.append(p)
    return hits

def choose_rotation_product():
    # Prefer full-population products (128,636 fields). BestMatch/D5 contain
    # only the A/B candidate universe, so C_ROTATION_CAUTION fields would be absent.
    names=[
        "artkandidat_v0a_fields.parquet",
        "artkandidat_v0a_operational_fields.parquet",
        "rotation_eligibility_2026.parquet",
        "bestmatch_d5_fields.parquet",
        "bestmatch_v0b_fields.parquet",
    ]
    for n in names:
        hits=find_named(n)
        for p in hits:
            try:
                cols=set(pd.read_parquet(p).columns)
            except Exception:
                continue
            if ("field_id" in cols or "current_field_id" in cols) and (
                "rotation_status" in cols or "last_conservart_any_component_year" in cols
            ):
                return p
    return None

def row_for(df,fid):
    idcol="field_id" if "field_id" in df.columns else "current_field_id"
    ids=df[idcol].astype(str)
    q=df.loc[ids.eq(fid)]
    return None if q.empty else q.iloc[0]

def show_value(row,name):
    if row is None or name not in row.index:return "—"
    v=row[name]
    return "—" if pd.isna(v) else str(v)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("fields",nargs="+",help="block:skifte or field_id")
    args=ap.parse_args()
    fids=[norm_field(x) for x in args.fields]

    rot_path=choose_rotation_product()
    if not rot_path:
        raise FileNotFoundError("Could not find a local frozen rotation/product parquet")
    rot=pd.read_parquet(rot_path)

    mixed_hits=find_named("pea_mixed_or_complex_target_field_years.parquet")
    mixed=pd.read_parquet(mixed_hits[0]) if mixed_hits else pd.DataFrame()

    print("="*116)
    print("ÅkerFrö ROTATION DIAGNOSIS · READ ONLY")
    print("="*116)
    print("Rotation product:",rot_path)
    print("Mixed/complex CONSERVART:",mixed_hits[0] if mixed_hits else "NOT FOUND")
    print()

    cols=[
        "artkandidat_class","rotation_status",
        "last_conservart_clean_year","last_conservart_any_component_year",
        "last_other_pea_clean_year","last_faba_bean_clean_year",
        "last_any_pea_clean_year","last_pea_or_faba_clean_year",
    ]
    for fid in fids:
        row=row_for(rot,fid)
        print("-"*116)
        print("FIELD",fid)
        if row is None:
            print("  Not present in selected rotation product")
            continue
        for c in cols:
            print(f"  {c:40s} {show_value(row,c)}")
        if not mixed.empty and "current_field_id" in mixed.columns:
            q=mixed[mixed["current_field_id"].astype(str).eq(fid)].copy()
            if "history_year" in q.columns:
                q=q[pd.to_numeric(q["history_year"],errors="coerce").isin(YEARS)]
            if q.empty:
                print("  recent CONSERVART mixed/partial components: NONE")
            else:
                print("  recent CONSERVART mixed/partial components:")
                show=[c for c in [
                    "history_year","status","target_crop_area_m2",
                    "target_crop_share_current","target_component_rows",
                    "identity_match_confidence"
                ] if c in q.columns]
                print(q[show].sort_values("history_year").to_string(index=False))
                if "target_crop_share_current" in q.columns:
                    s=pd.to_numeric(q["target_crop_share_current"],errors="coerce")
                    tiny=q.loc[s.lt(.01)]
                    if len(tiny):
                        print("  >>> SLIVER <1% PRESENT: this is below ÅkerMinne web component visibility threshold.")
    print("="*116)
    print("No files changed.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
