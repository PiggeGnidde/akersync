#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT E2 · focused review before feature freeze.

Questions:
1) Is the groundwater situation-vs-fill sign tension physically explainable?
2) Which surface-water candidates are genuinely worth keeping?
3) Are slope/relief-like local columns present but missed by E aliases?
4) Is the exact TWI anti-correlation simply by construction? (yes, verify metadata)

No component score is created.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
E_CFG = ROOT / "config" / "akervatten_mvp_v0a_e.json"
D_CFG = ROOT / "config" / "akervatten_mvp_v0a_d.json"
WORK = ROOT / "work" / "akervatten_mvp_v0a" / "e_feature_validation"

_spec = importlib.util.spec_from_file_location(
    "akervatten_d", ROOT / "src" / "97_akervatten_d_history_features.py"
)
assert _spec and _spec.loader
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def max_true_run_event(dates: pd.Series, values: pd.Series, threshold: float) -> dict[str, Any]:
    q = pd.DataFrame({
        "date": pd.to_datetime(dates, errors="coerce"),
        "v": pd.to_numeric(values, errors="coerce"),
    }).dropna().sort_values("date")
    q["hit"] = q["v"] <= threshold

    best_len = 0
    best_start = None
    best_end = None
    run_len = 0
    run_start = None
    prev = None

    for r in q.itertuples(index=False):
        continuous = prev is not None and (r.date - prev).days == 1
        if r.hit:
            if run_len == 0 or not continuous:
                run_len = 1
                run_start = r.date
            else:
                run_len += 1
            if run_len > best_len:
                best_len = run_len
                best_start = run_start
                best_end = r.date
        else:
            run_len = 0
            run_start = None
        prev = r.date

    return {
        "days": int(best_len),
        "start": None if best_start is None else str(best_start.date()),
        "end": None if best_end is None else str(best_end.date()),
        "start_year": None if best_start is None else int(best_start.year),
        "end_year": None if best_end is None else int(best_end.year),
    }


def groundwater_review(gw: pd.DataFrame, hist_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    total = len(gw)
    for i, r in enumerate(gw.itertuples(index=False), start=1):
        oid = str(r.omrade_id)
        path = hist_dir / f"sgu_hype_{oid}.csv"
        df = D.read_sgu_csv(path)
        dates = pd.to_datetime(df["datum"], errors="coerce")
        situation = pd.to_numeric(df["grundvattensituation_sma"], errors="coerce")
        fill = pd.to_numeric(df["fyllnadsgrad_sma"], errors="coerce")
        valid = dates.notna()

        month_med = (
            pd.DataFrame({"date":dates[valid], "fill":fill[valid]})
            .dropna()
            .assign(month=lambda x: x["date"].dt.month)
            .groupby("month")["fill"].median()
        )
        seasonal_amp = float(month_med.max() - month_med.min()) if len(month_med) else np.nan
        summer = dates.dt.month.isin([5,6,7,8,9])

        s_event = max_true_run_event(dates, situation, 10.0)
        f_event = max_true_run_event(dates, fill, 10.0)

        rows.append({
            "omrade_id":oid,
            "situation_le10_max_run_days":s_event["days"],
            "situation_le10_max_run_start":s_event["start"],
            "situation_le10_max_run_end":s_event["end"],
            "situation_le10_start_year":s_event["start_year"],
            "fill_le10_max_run_days":f_event["days"],
            "fill_le10_max_run_start":f_event["start"],
            "fill_le10_max_run_end":f_event["end"],
            "fill_le10_start_year":f_event["start_year"],
            "fill_monthly_median_amplitude":seasonal_amp,
            "fill_summer_p10_recalc":float(fill[summer].quantile(.10)),
            "situation_summer_p10_recalc":float(situation[summer].quantile(.10)),
        })
        if i % 50 == 0 or i == total:
            print(f"  [GW REVIEW] {i:4d}/{total:4d}")

    q = pd.DataFrame(rows)
    merged = gw.merge(q, on="omrade_id", how="left", validate="one_to_one")

    corr_cols = [
        "gw_small_situation_le10_max_run_days",
        "gw_small_fill_summer_p10",
        "gw_small_situation_summer_p10",
        "gw_small_fill_le10_max_run_days",
        "fill_monthly_median_amplitude",
    ]
    corr = merged[corr_cols].apply(pd.to_numeric, errors="coerce").corr(method="spearman")

    # Does the situation-run vs fill-P10 relation change by seasonal-amplitude quartile?
    amp = pd.to_numeric(merged["fill_monthly_median_amplitude"], errors="coerce")
    try:
        bins = pd.qcut(amp, 4, labels=["Q1_low_seasonality","Q2","Q3","Q4_high_seasonality"], duplicates="drop")
    except Exception:
        bins = pd.Series(["all"]*len(merged), index=merged.index)

    strat = []
    for name, sub in merged.groupby(bins, observed=True):
        a = pd.to_numeric(sub["gw_small_situation_le10_max_run_days"], errors="coerce")
        b = -pd.to_numeric(sub["gw_small_fill_summer_p10"], errors="coerce")
        z = pd.DataFrame({"a":a,"b":b}).dropna()
        strat.append({
            "seasonality_group":str(name),
            "n":int(len(z)),
            "rho_oriented_situationrun_vs_lowfill":(
                float(z["a"].corr(z["b"], method="spearman")) if len(z)>=3 else None
            ),
            "median_fill_monthly_amplitude":float(
                pd.to_numeric(sub["fill_monthly_median_amplitude"], errors="coerce").median()
            ),
        })

    start_years_s = Counter(int(x) for x in q["situation_le10_start_year"].dropna())
    start_years_f = Counter(int(x) for x in q["fill_le10_start_year"].dropna())

    summary = {
        "spearman_raw": {
            a:{b:(None if pd.isna(corr.loc[a,b]) else float(corr.loc[a,b])) for b in corr.columns}
            for a in corr.index
        },
        "seasonality_strata":strat,
        "most_common_situation_maxrun_start_years":start_years_s.most_common(15),
        "most_common_fill_maxrun_start_years":start_years_f.most_common(15),
    }
    return merged, summary


def schema_audit(paths: dict[str,str]) -> dict[str,Any]:
    patt = re.compile(r"slope|lut|incl|relief|elev|dem|flow|acc|sca|twi|wet|height|hojd|höjd", re.I)
    out={}
    for label,path in paths.items():
        p=Path(path)
        if p.suffix.lower()==".csv":
            cols=list(pd.read_csv(p,nrows=0).columns)
        elif p.suffix.lower()==".parquet":
            cols=list(pd.read_parquet(p).columns)
        else:
            continue
        hits=[c for c in cols if patt.search(str(c))]
        out[label]={"n_columns":len(cols),"candidate_like_columns":hits}
    return out


def surface_review(pair_path: Path) -> dict[str,Any]:
    p=pd.read_csv(pair_path)
    s=p[p["family"].eq("YtvattenTorka")].copy()
    rows=s.to_dict("records")
    return {
        "pairs":rows,
        "provisional_primary":["mlq_mq_total","specific_mlq_total"],
        "provisional_diagnostics":["mlq_mq_natural","specific_mlq_natural"],
        "rationale":[
            "total metrics represent the modelled actual-flow context used by the field",
            "MLQ/MQ is dimensionless low-flow persistence relative to mean flow",
            "specific MLQ retains absolute low-flow intensity per catchment area",
            "natural counterparts are strongly rank-redundant with total counterparts in E"
        ]
    }


def main()->int:
    ecfg=load_json(E_CFG)
    dcfg=load_json(D_CFG)
    WORK.mkdir(parents=True,exist_ok=True)

    print("="*122)
    print("ÅkerVatten MVP v0a · STOPPUNKT E2 · FOCUSED REVIEW")
    print("="*122)
    print("No score is frozen.")

    print("\n[1/4] Groundwater situation vs fill review")
    gw=pd.read_parquet(ROOT/dcfg["output"]["work_dir"]/ "groundwater_history_features.parquet")
    hist=ROOT/dcfg["output"]["raw_dir"]/ "sgu_hype_history"
    gw_review,gw_summary=groundwater_review(gw,hist)
    gw_review.to_parquet(WORK/"e2_groundwater_review.parquet",index=False)

    print("  key unit-level oriented correlations:")
    a=pd.to_numeric(gw_review["gw_small_situation_le10_max_run_days"],errors="coerce")
    b=-pd.to_numeric(gw_review["gw_small_fill_summer_p10"],errors="coerce")
    c=-pd.to_numeric(gw_review["gw_small_situation_summer_p10"],errors="coerce")
    print(f"    long situation<=10 run vs low summer fill P10: rho={a.corr(b,method='spearman'):+.3f}")
    print(f"    long situation<=10 run vs low summer situation P10: rho={a.corr(c,method='spearman'):+.3f}")
    print("  situation max-run common start years:")
    for y,n in gw_summary["most_common_situation_maxrun_start_years"][:8]:
        print(f"    {y}: {n} units")
    print("  fill max-run common start years:")
    for y,n in gw_summary["most_common_fill_maxrun_start_years"][:8]:
        print(f"    {y}: {n} units")
    print("  seasonality strata:")
    for r in gw_summary["seasonality_strata"]:
        print(
            f"    {r['seasonality_group']}: n={r['n']} · "
            f"rho={r['rho_oriented_situationrun_vs_lowfill']:+.3f} · "
            f"median monthly-fill amplitude={r['median_fill_monthly_amplitude']:.2f}"
        )

    print("\n[2/4] Local schema audit for missed slope/relief variables")
    schema=schema_audit({
        "soil":ecfg["paths"]["soil"],
        "hydrology":ecfg["paths"]["hydrology"],
        "D_fields":str(ROOT/ecfg["paths"]["d_fields"]),
    })
    for label,info in schema.items():
        print(f"  {label}: {', '.join(info['candidate_like_columns']) or '(none)'}")

    print("\n[3/4] Surface-water redundancy review")
    surf=surface_review(WORK/"e_within_family_pair_diagnostics.csv")
    for r in surf["pairs"]:
        print(
            f"  {r['candidate_a']} vs {r['candidate_b']}: "
            f"rho={r['spearman_oriented']:+.3f}, top10 overlap={r['top_overlap_fraction']:.3f}"
        )
    print("  provisional primary: mlq_mq_total + specific_mlq_total")
    print("  provisional diagnostics: natural-flow counterparts")

    print("\n[4/4] Review status")
    # Exact TWI inverse is metadata-by-construction, not a data failure.
    torka_twi=ecfg["candidates"]["MarkTorka"][1]
    vata_twi=ecfg["candidates"]["MarkVata"][1]
    twi_expected=(
        "twi_mean" in [x.lower() for x in torka_twi["aliases"]]
        and "twi_mean" in [x.lower() for x in vata_twi["aliases"]]
        and int(torka_twi["direction"])==-int(vata_twi["direction"])
    )
    summary={
        "schema_version":"akervatten-mvp-v0a-e2-review",
        "status":"PASS_WITH_REVIEW",
        "twi_exact_inverse_expected_by_construction":twi_expected,
        "groundwater_review":gw_summary,
        "schema_audit":schema,
        "surface_review":surf,
        "interpretation":{
            "groundwater":"Situation and fill use different historical reference frames; sign tension is reviewed as physical complementarity unless event/date diagnostics indicate otherwise.",
            "mark":"TWI is intentionally shared with opposite directions; MarkTorka and MarkVata are not otherwise forced to be inverses.",
            "surface":"Prefer total MLQ/MQ plus total specific MLQ as primary candidates; retain natural-flow versions as diagnostics pending freeze."
        }
    }
    (WORK/"e2_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("  TWI inverse expected by construction:", twi_expected)
    print("  status: PASS_WITH_REVIEW")
    print("\nOutputs:",WORK)
    print("="*122)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
