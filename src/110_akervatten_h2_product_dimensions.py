#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/"config"/"akervatten_h2_product_dimensions_v0a.json"
KEY=["blockid","skiftesbeteckning"]

_spec=importlib.util.spec_from_file_location(
    "akervatten_h0",ROOT/"src"/"108_akervatten_h0_large_groundwater_inventory.py"
)
assert _spec and _spec.loader
H0=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H0)

SCORE_COLUMNS={
    "mark_torka":"mark_torka_candidate_0_100",
    "mark_vata":"mark_vata_candidate_f5_0_100",
    "groundwater_small_availability":"grundvatten_tillgang_candidate_0_100",
    "groundwater_drought_history":"grundvatten_torka_candidate_0_100",
    "surfacewater_drought_history":"ytvatten_torka_candidate_0_100",
}

def read_json(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def norm_keys(df:pd.DataFrame)->pd.DataFrame:
    q=df.copy()
    for k in KEY:
        q[k]=q[k].astype(str)
    return q

def score_band(x:Any)->str|None:
    if pd.isna(x):
        return None
    x=float(x)
    if x < 20: return "Mycket låg"
    if x < 40: return "Låg"
    if x < 60: return "Måttlig"
    if x < 80: return "Hög"
    return "Mycket hög"

def normalize_subarea_layers(sub:pd.DataFrame)->pd.DataFrame:
    q=norm_keys(sub)
    code=q["uttagsmojligheter_kod"] if "uttagsmojligheter_kod" in q.columns else pd.Series([None]*len(q),index=q.index)
    label=q["uttagsmojligheter"] if "uttagsmojligheter" in q.columns else pd.Series([None]*len(q),index=q.index)
    infos=[H0.withdrawal_info(c,l) for c,l in zip(code,label)]
    q["withdrawal_lower_lps"]=[x[0] for x in infos]
    q["withdrawal_upper_lps"]=[x[1] for x in infos]
    q["withdrawal_label_norm"]=[x[2] for x in infos]
    keep=KEY+[
        c for c in [
            "unik_magasinsidentitet","magasinsidentitet","magasinsnamn",
            "unik_delomradesidentitet","delomradesidentitet",
            "magasinsposition","magasinsposition_kod","akvifertyp","bergart",
            "geologisk_period","kornstorlek","artesiskt",
            "withdrawal_label_norm","withdrawal_lower_lps","withdrawal_upper_lps"
        ] if c in q.columns
    ]
    q=q[keep].copy()
    q["legal_water_right"]="NOT_ASSESSED"
    q["capacity_semantic"]="HYDROGEOLOGICAL_SCREENING_ONLY"
    return q

def choose_highest_mapped_capacity(q:pd.DataFrame)->pd.Series|None:
    """
    Product convenience summary only.
    Selects the row with highest KNOWN lower bound in l/s.
    Unknown/not-assessed rows are ignored.
    This is not a legal or sustainability verdict.
    """
    if q.empty or "withdrawal_lower_lps" not in q.columns:
        return None
    known=q[pd.to_numeric(q["withdrawal_lower_lps"],errors="coerce").notna()].copy()
    if known.empty:
        return None
    known["_lo"]=pd.to_numeric(known["withdrawal_lower_lps"],errors="coerce")
    known["_hi"]=pd.to_numeric(known.get("withdrawal_upper_lps"),errors="coerce")
    # Deterministic tie-break: highest lower bound, then upper bound, then IDs.
    for c in ("unik_magasinsidentitet","unik_delomradesidentitet"):
        if c not in known.columns:
            known[c]=""
    known["_hi_sort"]=known["_hi"].fillna(float("inf"))
    known=known.sort_values(
        ["_lo","_hi_sort","unik_magasinsidentitet","unik_delomradesidentitet"],
        ascending=[False,False,True,True],
        kind="mergesort"
    )
    return known.iloc[0]

def build_capacity_summary(layers:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for key,q in layers.groupby(KEY,dropna=False,sort=False):
        best=choose_highest_mapped_capacity(q)
        rows.append({
            KEY[0]:key[0],KEY[1]:key[1],
            "large_gw_layer_count":int(len(q)),
            "large_gw_known_capacity_layer_count":int(q["withdrawal_lower_lps"].notna().sum()),
            "large_gw_highest_mapped_capacity_class":None if best is None else best.get("withdrawal_label_norm"),
            "large_gw_highest_mapped_capacity_lower_lps":np.nan if best is None else best.get("withdrawal_lower_lps"),
            "large_gw_highest_mapped_capacity_upper_lps":np.nan if best is None else best.get("withdrawal_upper_lps"),
            "large_gw_highest_mapped_capacity_magazine_uid":None if best is None else best.get("unik_magasinsidentitet"),
            "large_gw_highest_mapped_capacity_subarea_uid":None if best is None else best.get("unik_delomradesidentitet"),
            "large_gw_highest_mapped_capacity_position":None if best is None else best.get("magasinsposition"),
            "large_gw_highest_mapped_capacity_aquifer":None if best is None else best.get("akvifertyp"),
            "large_gw_highest_mapped_capacity_rock":None if best is None else best.get("bergart"),
        })
    return pd.DataFrame(rows)

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CONFIG))
    args=ap.parse_args()
    cfg=read_json(Path(args.config))
    work=ROOT/cfg["output"]["work_dir"]
    work.mkdir(parents=True,exist_ok=True)

    print("="*126)
    print("ÅkerVatten · H2 · PRODUCT DIMENSIONS WITHOUT COMPOSITE WATER SCORE")
    print("="*126)
    print("ÅkerPass presents the cards on the table. It does not make the legal water-withdrawal decision.")

    print("\n[1/6] Load frozen component and large-groundwater sources")
    f=norm_keys(pd.read_parquet(ROOT/cfg["paths"]["f5_components"]))
    h0=norm_keys(pd.read_parquet(ROOT/cfg["paths"]["h0_fields"]))
    sub=normalize_subarea_layers(pd.read_parquet(ROOT/cfg["paths"]["h0_subarea"]))
    if len(f)!=128636 or len(h0)!=128636:
        raise RuntimeError(f"Unexpected population: F5={len(f)}, H0={len(h0)}")
    if f[KEY].duplicated().any() or h0[KEY].duplicated().any():
        raise RuntimeError("Duplicate field keys in source table")
    print(f"  fields: {len(f):,}")
    print(f"  large-groundwater field×subarea rows: {len(sub):,}")

    print("\n[2/6] Build six non-aggregated product dimensions")
    base_cols=KEY+[c for c in ("kommun","area_ha") if c in f.columns]
    out=f[base_cols].copy()
    for dim,col in SCORE_COLUMNS.items():
        if col not in f.columns:
            raise RuntimeError(f"Missing frozen score column: {col}")
        out[dim+"_score_0_100"]=pd.to_numeric(f[col],errors="coerce")
        out[dim+"_band"]=out[dim+"_score_0_100"].map(score_band)

    h0_keep=KEY+[c for c in [
        "large_gw_relation",
        "large_gw_magazine_count",
        "large_gw_magazine_names",
        "large_gw_positions",
        "large_gw_aquifer_types",
        "large_gw_rock_types",
        "large_gw_subarea_count",
        "large_gw_withdrawal_classes",
        "large_gw_recharge_count",
        "large_gw_recharge_magazine_names",
        "large_gw_recharge_types"
    ] if c in h0.columns]
    out=out.merge(h0[h0_keep],on=KEY,how="left",validate="one_to_one")

    cap=build_capacity_summary(sub)
    out=out.merge(cap,on=KEY,how="left",validate="one_to_one")

    out["water_legal_status"]="NOT_ASSESSED"
    out["water_overall_score"]=pd.NA
    out["water_overall_verdict"]="NOT_CREATED"
    out["large_gw_capacity_semantic"]="HYDROGEOLOGICAL_SCREENING_ONLY"

    print("  frozen relative scores : 5")
    print("  source-class dimensions: 1 (large groundwater magazines)")
    print("  overall water score    : NOT CREATED")
    print("  legal status           : NOT ASSESSED")

    print("\n[3/6] QA: no legal/composite leakage")
    problems=[]
    if out["water_overall_score"].notna().any():
        problems.append("overall water score unexpectedly populated")
    if set(out["water_overall_verdict"].dropna().astype(str))!={"NOT_CREATED"}:
        problems.append("overall verdict contains unexpected values")
    if set(out["water_legal_status"].dropna().astype(str))!={"NOT_ASSESSED"}:
        problems.append("legal status contains unexpected values")
    if len(out)!=128636 or out[KEY].duplicated().any():
        problems.append("field identity/population changed")

    for dim in SCORE_COLUMNS:
        s=out[dim+"_score_0_100"]
        bad=s.dropna()[(s.dropna()<0)|(s.dropna()>100)]
        if len(bad):
            problems.append(f"{dim}: score outside 0..100")
    print(f"  problems: {len(problems)}")
    for p in problems:
        print("   -",p)

    print("\n[4/6] Large-groundwater capacity source summary")
    direct=(out["large_gw_relation"]=="DIRECT_MAGAZINE")
    known=out["large_gw_highest_mapped_capacity_class"].notna()
    print(f"  direct mapped magazine: {int(direct.sum()):,} ({100*direct.mean():.2f}%)")
    print(f"  highest mapped capacity class available: {int(known.sum()):,} ({100*known.mean():.2f}%)")
    cc=out.loc[known,"large_gw_highest_mapped_capacity_class"].value_counts()
    for label,n in cc.head(20).items():
        print(f"  {str(label):62s} {int(n):7,d}")

    print("\n[5/6] Write product-ready field table + inspectable large-magazine layers")
    field_path=work/"akervatten_h2_field_water_dimensions_skane.parquet"
    layer_path=work/"akervatten_h2_large_groundwater_layers.parquet"
    out.to_parquet(field_path,index=False)
    sub.to_parquet(layer_path,index=False)

    schema={
        "schema_version":"akervatten-h2-product-schema-v0a",
        "philosophy":"show evidence and context; do not make the water-withdrawal decision",
        "dimensions":cfg["product_dimensions"],
        "future_context_dimensions":cfg["future_context_dimensions"],
        "ui_policy":cfg["ui_policy"],
        "field_table":str(field_path.relative_to(ROOT)),
        "large_groundwater_layer_table":str(layer_path.relative_to(ROOT)),
        "legal_status_field":"water_legal_status",
        "legal_status_value":"NOT_ASSESSED",
        "overall_score":"NOT_CREATED",
        "overall_verdict":"NOT_CREATED"
    }
    (work/"h2_product_schema.json").write_text(
        json.dumps(schema,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print(f"  field table : {field_path}")
    print(f"  layer table : {layer_path}")

    print("\n[6/6] Product wording")
    copy={
      "header":"Vatten",
      "intro":"Flera separata vattenegenskaper visas. De beskriver mark, hydrologi och kartlagda grundvattenmagasin men avgör inte om vattenuttag kan tillåtas.",
      "dimensions":{
        "MarkTorka":"Relativ strukturell torkkänslighet i marken.",
        "MarkVäta":"Relativ strukturell våthetsbenägenhet i marken.",
        "GrundvattenTillgång – små magasin":"Relativ SGU-baserad screening av små grundvattenmagasin.",
        "GrundvattenTorka – historik":"Historisk relativ känslighet för ovanligt låga grundvattennivåer.",
        "YtvattenTorka – historik":"Historisk relativ känslighet för låga ytvattenflöden.",
        "Stora grundvattenmagasin":"SGU-kartlagda magasin och kapacitetsklasser. Flera magasin kan finnas under samma fält."
      },
      "large_groundwater_summary_label":cfg["ui_policy"]["highest_summary_label"],
      "large_groundwater_warning":cfg["ui_policy"]["highest_summary_warning"],
      "legal_warning":"Hydrologiskt underlag är inte en juridisk bedömning. Vattenuttag kan bero på bland annat andra uttag, allmän och enskild vattenförsörjning, miljöpåverkan och gällande tillstånd.",
      "future_context":"Framtida ÅkerKontext · VattenTryck kan beskriva konkurrerande efterfrågan separat, utan att omvandlas till ett juridiskt beslut."
    }
    (work/"h2_product_copy.json").write_text(
        json.dumps(copy,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    status="PASS_WITH_REVIEW" if not problems else "FAIL"
    summary={
        "schema_version":"akervatten-h2-product-dimensions-result",
        "status":status,
        "fields":int(len(out)),
        "overall_score_created":False,
        "overall_verdict_created":False,
        "legal_status":"NOT_ASSESSED",
        "large_groundwater":{
            "direct_magazine_fields":int(direct.sum()),
            "highest_mapped_capacity_available_fields":int(known.sum())
        },
        "future_water_pressure":"NOT_IMPLEMENTED",
        "problems":problems,
        "guardrails":cfg["guardrails"]
    }
    (work/"h2_summary.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    print("\n"+"="*126)
    print(f"ÅKERVATTEN H2 PRODUCT DIMENSIONS: {status}")
    print("="*126)
    return 0 if not problems else 2

if __name__=="__main__":
    raise SystemExit(main())
