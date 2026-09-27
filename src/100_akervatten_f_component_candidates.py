#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT F · transparent candidate component transforms.

F creates five separate candidate 0-100 component scales.
It deliberately does NOT create a combined ÅkerVatten index.

Key statistical contract:
- local soil/TWI and small-aquifer percentiles are field-weighted;
- groundwater-history percentiles are defined over unique SGU-HYPE units;
- surface-water percentiles are defined over unique S-HYPE units;
- hydrological-unit scores are joined to fields only after the unit percentile
  transform, preventing field-density from defining the hydrological scale;
- multi-input components use explicit 50/50 weights as a reviewable baseline;
- no silent reweighting when a frozen primary input is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_f.json"
KEY = ["blockid", "skiftesbeteckning"]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def atomic_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)


def norm_id(v: Any) -> str | None:
    if pd.isna(v):
        return None
    return re.sub(r"\.0$", "", str(v).strip()).upper()


def norm_id_series(s: pd.Series) -> pd.Series:
    return s.map(norm_id).astype("string")


def empirical_percentile(
    s: pd.Series,
    direction: int,
    tie_method: str = "average",
) -> pd.Series:
    """Map valid observations to empirical 0..100 percentile.

    Average ranks are used for ties. With n>1 the smallest distinct ranked
    observation can reach 0 and the largest 100. For n==1 use neutral 50.
    direction=+1 means high raw value -> high percentile.
    direction=-1 means low raw value -> high percentile.
    """
    x = numeric(s)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    valid = x.notna()
    n = int(valid.sum())
    if n == 0:
        return out
    if n == 1:
        out.loc[valid] = 50.0
        return out

    ranks = x.loc[valid].rank(method=tie_method, ascending=True)
    pct = 100.0 * (ranks - 1.0) / (n - 1.0)
    if int(direction) < 0:
        pct = 100.0 - pct
    out.loc[valid] = pct.clip(0.0, 100.0)
    return out


def direction_sign(direction_text: str) -> int:
    d = str(direction_text).lower()
    if d.startswith("higher_"):
        return +1
    if d.startswith("lower_"):
        return -1
    raise ValueError(f"Unrecognized direction: {direction_text!r}")


def freeze_primary_map(e_freeze: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for component, spec in e_freeze["components"].items():
        fam = {}
        for x in spec.get("primary", []):
            fam[str(x["column"])] = direction_sign(str(x["direction"]))
        out[component] = fam
    return out


def validate_aggregation(
    primary: dict[str, dict[str, int]],
    weights: dict[str, dict[str, float]],
) -> None:
    if set(primary) != set(weights):
        raise RuntimeError(
            f"F aggregation components differ from E freeze: "
            f"E={sorted(primary)} F={sorted(weights)}"
        )
    for component in primary:
        if set(primary[component]) != set(weights[component]):
            raise RuntimeError(
                f"{component}: aggregation inputs differ from frozen E primary set; "
                f"E={sorted(primary[component])}, F={sorted(weights[component])}"
            )
        vals = [float(v) for v in weights[component].values()]
        if any(v < 0 for v in vals):
            raise RuntimeError(f"{component}: negative weight")
        if not np.isclose(sum(vals), 1.0, atol=1e-12):
            raise RuntimeError(f"{component}: weights sum to {sum(vals)}, expected 1")


def component_slug(component: str) -> str:
    mapping = {
        "MarkTorka":"mark_torka",
        "MarkVata":"mark_vata",
        "GrundvattenTillgang":"grundvatten_tillgang",
        "GrundvattenTorka":"grundvatten_torka",
        "YtvattenTorka":"ytvatten_torka",
    }
    return mapping[component]


def build_component(
    df: pd.DataFrame,
    component: str,
    inputs: dict[str, int],
    weights: dict[str, float],
    tie_method: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    q = df.copy()
    slug = component_slug(component)
    pct_cols = []
    for col, direction in inputs.items():
        if col not in q.columns:
            raise RuntimeError(f"{component}: required frozen input missing: {col}")
        pcol = f"{slug}__{col}__pct"
        q[pcol] = empirical_percentile(q[col], direction, tie_method)
        pct_cols.append(pcol)

    complete = q[pct_cols].notna().all(axis=1)
    score = pd.Series(np.nan, index=q.index, dtype=float)
    if complete.any():
        acc = pd.Series(0.0, index=q.index, dtype=float)
        for col, pcol in zip(inputs, pct_cols):
            acc = acc + float(weights[col]) * q[pcol]
        score.loc[complete] = acc.loc[complete]

    scol = f"{slug}_candidate_0_100"
    q[scol] = score
    q[f"{slug}_quality"] = np.where(complete, "FULL", "MISSING_PRIMARY")

    info = {
        "component":component,
        "score_column":scol,
        "quality_column":f"{slug}_quality",
        "input_percentile_columns":pct_cols,
        "n_total":int(len(q)),
        "n_complete":int(complete.sum()),
        "coverage_pct":float(100.0 * complete.mean()),
        "n_unique_score":int(score.nunique(dropna=True)),
    }
    return q, info


def describe_score(s: pd.Series, component: str, weighting: str) -> dict[str, Any]:
    x = numeric(s).dropna()
    out = {
        "component":component,
        "weighting":weighting,
        "n":int(len(x)),
        "unique_values":int(x.nunique()),
    }
    if x.empty:
        for k in ("min","p01","p10","p25","p50","p75","p90","p99","max","mean","std"):
            out[k] = None
        return out
    qq = x.quantile([.01,.10,.25,.50,.75,.90,.99])
    out.update({
        "min":float(x.min()),
        "p01":float(qq.loc[.01]),
        "p10":float(qq.loc[.10]),
        "p25":float(qq.loc[.25]),
        "p50":float(qq.loc[.50]),
        "p75":float(qq.loc[.75]),
        "p90":float(qq.loc[.90]),
        "p99":float(qq.loc[.99]),
        "max":float(x.max()),
        "mean":float(x.mean()),
        "std":float(x.std()),
    })
    return out


def top_overlap(a: pd.Series, b: pd.Series, fraction: float) -> float | None:
    q = pd.DataFrame({"a":numeric(a),"b":numeric(b)}).dropna()
    if q.empty:
        return None
    ra = q["a"].rank(method="average", pct=True)
    rb = q["b"].rank(method="average", pct=True)
    aa = set(q.index[ra >= 1.0-fraction])
    bb = set(q.index[rb >= 1.0-fraction])
    denom = min(len(aa),len(bb))
    return None if denom == 0 else float(len(aa & bb)/denom)


def input_diagnostics(
    df: pd.DataFrame,
    component: str,
    info: dict[str, Any],
    top_fraction: float,
) -> list[dict[str, Any]]:
    rows = []
    score = numeric(df[info["score_column"]])
    for pcol in info["input_percentile_columns"]:
        p = numeric(df[pcol])
        q = pd.DataFrame({"score":score,"p":p}).dropna()
        rows.append({
            "component":component,
            "input_percentile":pcol,
            "n":int(len(q)),
            "spearman_score_vs_input":(
                None if len(q)<3 else float(q["score"].corr(q["p"],method="spearman"))
            ),
            "top_overlap_fraction":top_overlap(score,p,top_fraction),
        })
    return rows


def component_correlations(fields: pd.DataFrame, score_cols: dict[str,str]) -> pd.DataFrame:
    z = pd.DataFrame({k:numeric(fields[v]) for k,v in score_cols.items()})
    corr = z.corr(method="spearman")
    rows=[]
    names=list(corr.columns)
    for i in range(len(names)):
        for j in range(i+1,len(names)):
            a,b=names[i],names[j]
            rows.append({
                "component_a":a,
                "component_b":b,
                "spearman":None if pd.isna(corr.loc[a,b]) else float(corr.loc[a,b]),
            })
    return pd.DataFrame(rows)


def component_extremes(
    df: pd.DataFrame,
    score_cols: dict[str,str],
    n_tail: int,
) -> pd.DataFrame:
    rows=[]
    ids=[c for c in ("blockid","skiftesbeteckning","kommun","omrade_id","ARO_UUID","Subid") if c in df.columns]
    for component,scol in score_cols.items():
        q=df[df[scol].notna()].copy()
        for tail,part in (
            ("HIGH",q.nlargest(n_tail,scol)),
            ("LOW",q.nsmallest(n_tail,scol)),
        ):
            for rank,(_,r) in enumerate(part.iterrows(),start=1):
                rec={"component":component,"tail":tail,"rank":rank,"score":float(r[scol])}
                for c in ids:
                    rec[c]=r[c]
                rows.append(rec)
    return pd.DataFrame(rows)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CONFIG))
    args=ap.parse_args()

    cfg=load_json(Path(args.config))
    ef=load_json(ROOT/cfg["paths"]["e_freeze"])
    primary=freeze_primary_map(ef)
    weights=cfg["aggregation"]
    validate_aggregation(primary,weights)

    work=ROOT/cfg["output"]["work_dir"]
    work.mkdir(parents=True,exist_ok=True)
    tie_method=str(cfg["transform"]["tie_method"])

    print("="*124)
    print("ÅkerVatten MVP v0a · STOPPUNKT F · TRANSPARENT CANDIDATE COMPONENTS")
    print("="*124)
    print("No combined ÅkerVatten index is created.")

    print("\n[1/6] Load frozen inputs")
    fields=pd.read_parquet(ROOT/cfg["paths"]["d_fields"])
    gw=pd.read_parquet(ROOT/cfg["paths"]["d_groundwater_units"])
    sw=pd.read_parquet(ROOT/cfg["paths"]["d_surface_units"])
    soil=pd.read_csv(cfg["paths"]["soil"],dtype={"blockid":str,"skiftesbeteckning":str},low_memory=False)
    hydro=pd.read_csv(cfg["paths"]["hydrology"],dtype={"blockid":str,"skiftesbeteckning":str},low_memory=False)

    for x,name in ((fields,"D fields"),(soil,"soil"),(hydro,"hydrology")):
        if x[KEY].duplicated().any():
            raise RuntimeError(f"{name} duplicate field keys")

    fields=fields.merge(
        soil[KEY+["sand_mean","clay_mean"]],
        on=KEY,how="left",validate="one_to_one"
    )
    fields=fields.merge(
        hydro[KEY+["twi_mean"]],
        on=KEY,how="left",validate="one_to_one"
    )
    print(f"  fields             : {len(fields):,}")
    print(f"  SGU-HYPE units     : {len(gw):,}")
    print(f"  S-HYPE units       : {len(sw):,}")

    print("\n[2/6] Unit-weighted historical component transforms")
    gw_inputs=primary["GrundvattenTorka"]
    gw_score,gw_info=build_component(
        gw,"GrundvattenTorka",gw_inputs,weights["GrundvattenTorka"],tie_method
    )
    sw_inputs=primary["YtvattenTorka"]
    sw_score,sw_info=build_component(
        sw,"YtvattenTorka",sw_inputs,weights["YtvattenTorka"],tie_method
    )
    atomic_parquet(gw_score,work/"f_groundwater_unit_candidate_scores.parquet")
    atomic_parquet(sw_score,work/"f_surfacewater_unit_candidate_scores.parquet")
    print(
        f"  GrundvattenTorka: {gw_info['n_complete']:,}/{gw_info['n_total']:,} units · "
        f"{gw_info['coverage_pct']:.3f}%"
    )
    print(
        f"  YtvattenTorka    : {sw_info['n_complete']:,}/{sw_info['n_total']:,} units · "
        f"{sw_info['coverage_pct']:.3f}%"
    )

    # Join UNIT-DERIVED score and input percentiles to fields.
    gw_keep=["omrade_id",gw_info["score_column"],gw_info["quality_column"]]+gw_info["input_percentile_columns"]
    gmap=gw_score[gw_keep].copy()
    gmap["_oid"]=norm_id_series(gmap["omrade_id"])
    gmap=gmap.drop(columns="omrade_id").drop_duplicates("_oid")
    fields["_oid"]=norm_id_series(fields["omrade_id"])
    fields=fields.merge(gmap,on="_oid",how="left",validate="many_to_one").drop(columns="_oid")

    sw_keep=["Subid",sw_info["score_column"],sw_info["quality_column"]]+sw_info["input_percentile_columns"]
    smap=sw_score[sw_keep].copy()
    smap["_sid"]=norm_id_series(smap["Subid"])
    smap=smap.drop(columns="Subid").drop_duplicates("_sid")
    fields["_sid"]=norm_id_series(fields["Subid"])
    fields=fields.merge(smap,on="_sid",how="left",validate="many_to_one").drop(columns="_sid")

    print("\n[3/6] Field-weighted local component transforms")
    infos={}
    for component in ("MarkTorka","MarkVata","GrundvattenTillgang"):
        fields,info=build_component(
            fields,component,primary[component],weights[component],tie_method
        )
        infos[component]=info
        print(
            f"  {component:23s}: {info['n_complete']:,}/{info['n_total']:,} · "
            f"{info['coverage_pct']:.3f}% · unique score values={info['n_unique_score']:,}"
        )
    infos["GrundvattenTorka"]=gw_info
    infos["YtvattenTorka"]=sw_info

    print("\n[4/6] Score distributions + input contribution diagnostics")
    stat_rows=[]
    diag_rows=[]
    top_fraction=float(cfg["validation"]["top_fraction"])
    for component,info in infos.items():
        scol=info["score_column"]
        stat_rows.append(describe_score(fields[scol],component,"field_output"))

        # Unit-weighted distributions remain explicit for historical components.
        if component=="GrundvattenTorka":
            stat_rows.append(describe_score(gw_score[scol],component,"hydrological_unit"))
            diag_rows.extend(input_diagnostics(gw_score,component,info,top_fraction))
        elif component=="YtvattenTorka":
            stat_rows.append(describe_score(sw_score[scol],component,"hydrological_unit"))
            diag_rows.extend(input_diagnostics(sw_score,component,info,top_fraction))
        else:
            diag_rows.extend(input_diagnostics(fields,component,info,top_fraction))

    stats=pd.DataFrame(stat_rows)
    diags=pd.DataFrame(diag_rows)
    atomic_csv(stats,work/"f_component_distributions.csv")
    atomic_csv(diags,work/"f_component_input_diagnostics.csv")

    for r in stats[stats["weighting"].eq("field_output")].itertuples(index=False):
        print(
            f"  {r.component:23s} · coverage n={r.n:,} · "
            f"P10={r.p10:.2f} P50={r.p50:.2f} P90={r.p90:.2f}"
        )
    print("  score-vs-input:")
    for r in diags.itertuples(index=False):
        print(
            f"    {r.component:23s} · {r.input_percentile.split('__')[-2]:38s} · "
            f"rho={r.spearman_score_vs_input:+.3f} · top10 overlap={r.top_overlap_fraction:.3f}"
        )

    print("\n[5/6] Cross-component behavior + extremes")
    score_cols={c:i["score_column"] for c,i in infos.items()}
    cross=component_correlations(fields,score_cols)
    atomic_csv(cross,work/"f_cross_component_spearman.csv")
    for r in cross.sort_values(
        "spearman",key=lambda s:pd.to_numeric(s,errors="coerce").abs(),ascending=False
    ).itertuples(index=False):
        print(f"  {r.component_a:23s} vs {r.component_b:23s}: rho={r.spearman:+.3f}")

    mt=fields[score_cols["MarkTorka"]]
    mv=fields[score_cols["MarkVata"]]
    both=mt.notna()&mv.notna()
    inverse_sum_std=float((mt[both]+mv[both]).std()) if both.any() else None
    inverse_sum_range=(
        float((mt[both]+mv[both]).max()-(mt[both]+mv[both]).min())
        if both.any() else None
    )
    print(
        f"  MarkTorka + MarkVata diagnostic: std={inverse_sum_std:.3f}, "
        f"range={inverse_sum_range:.3f} (0 would indicate exact inverse scores)"
    )

    ex=component_extremes(
        fields,score_cols,int(cfg["validation"]["extremes_per_component"])
    )
    atomic_csv(ex,work/"f_component_extremes.csv")
    print(f"  extreme rows written: {len(ex):,}")

    print("\n[6/6] QA / review status")
    problems=[]
    expected=cfg["validation"]["min_expected_coverage"]
    for component,info in infos.items():
        if component in {"GrundvattenTorka","YtvattenTorka"}:
            actual=(
                fields[info["score_column"]].notna().mean()
            )
        else:
            actual=info["n_complete"]/info["n_total"]
        minimum=float(expected[component])
        print(
            f"  {component:23s}: coverage={100*actual:.3f}% · "
            f"minimum={100*minimum:.3f}%"
        )
        if actual<minimum:
            problems.append(
                f"{component} score coverage {actual:.3%} below expected {minimum:.3%}"
            )

    final_cols=list(fields.columns)
    atomic_parquet(fields,work/"akervatten_f_candidate_components_skane.parquet")

    status="PASS_WITH_REVIEW" if not problems else "FAIL"
    summary={
        "schema_version":"akervatten-mvp-v0a-f-component-candidate-result",
        "status":status,
        "component_info":infos,
        "semantics":cfg["semantics"],
        "aggregation":cfg["aggregation"],
        "percentile_weighting":{
            "MarkTorka":"field",
            "MarkVata":"field",
            "GrundvattenTillgang":"field",
            "GrundvattenTorka":"SGU-HYPE unit before field join",
            "YtvattenTorka":"S-HYPE unit before field join"
        },
        "mark_torka_vata_exact_inverse_diagnostic":{
            "sum_std":inverse_sum_std,
            "sum_range":inverse_sum_range
        },
        "problems":problems,
        "guardrails":cfg["guardrails"],
        "outputs":{
            "fields":str(work/"akervatten_f_candidate_components_skane.parquet"),
            "groundwater_units":str(work/"f_groundwater_unit_candidate_scores.parquet"),
            "surface_units":str(work/"f_surfacewater_unit_candidate_scores.parquet"),
            "distributions":str(work/"f_component_distributions.csv"),
            "input_diagnostics":str(work/"f_component_input_diagnostics.csv"),
            "cross_component":str(work/"f_cross_component_spearman.csv"),
            "extremes":str(work/"f_component_extremes.csv")
        }
    }
    atomic_json(work/"f_summary.json",summary)

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -",p)

    print("\nOutputs:",work)
    print("="*124)
    print(f"AKERVATTEN STOPPUNKT F CANDIDATE COMPONENTS: {status}")
    print("No combined ÅkerVatten index has been created.")
    print("="*124)
    return 0 if not problems else 2


if __name__=="__main__":
    raise SystemExit(main())
