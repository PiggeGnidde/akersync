#!/usr/bin/env python3
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "akervatten_mvp_v0a" / "f_component_candidates"
SOIL = Path(r"C:\AkerSyncRepo\data\derived\soil_features_skiften.csv")
KEY = ["blockid","skiftesbeteckning"]

def hurdle_percentile(s: pd.Series) -> pd.Series:
    """Zero-aware percentile for a zero-inflated nonnegative feature.

    Missing stays missing.
    Raw zero -> 0 (no organic evidence).
    Positive values are ranked only against other positive values using an
    empirical CDF, so every positive observation receives a value > 0.
    """
    x = pd.to_numeric(s, errors="coerce")
    out = pd.Series(np.nan, index=s.index, dtype=float)
    valid = x.notna()
    if (x[valid] < 0).any():
        raise RuntimeError("organic share contains negative values")
    out.loc[valid & (x == 0)] = 0.0
    pos = valid & (x > 0)
    n = int(pos.sum())
    if n:
        ranks = x.loc[pos].rank(method="average", ascending=True)
        out.loc[pos] = 100.0 * ranks / n
    return out.clip(0.0, 100.0)

def top_overlap(a: pd.Series, b: pd.Series, fraction: float = 0.10):
    q = pd.DataFrame({
        "a":pd.to_numeric(a,errors="coerce"),
        "b":pd.to_numeric(b,errors="coerce")
    }).dropna()
    if q.empty:
        return None
    ra=q["a"].rank(method="average",pct=True)
    rb=q["b"].rank(method="average",pct=True)
    aa=set(q.index[ra>=1.0-fraction])
    bb=set(q.index[rb>=1.0-fraction])
    d=min(len(aa),len(bb))
    return None if d == 0 else float(len(aa&bb)/d)

def describe(name: str, score: pd.Series, torka: pd.Series) -> dict:
    q = pd.DataFrame({"score":pd.to_numeric(score,errors="coerce"),
                      "torka":pd.to_numeric(torka,errors="coerce")}).dropna()
    qq=q["score"].quantile([.01,.10,.25,.50,.75,.90,.99])
    return {
        "variant":name,
        "n":int(len(q)),
        "spearman_vs_MarkTorka":float(q["score"].corr(q["torka"],method="spearman")),
        "top10_overlap_with_MarkTorka":top_overlap(q["score"],q["torka"],.10),
        "both_ge80_fraction":float(((q["score"]>=80)&(q["torka"]>=80)).mean()),
        "p01":float(qq.loc[.01]),
        "p10":float(qq.loc[.10]),
        "p25":float(qq.loc[.25]),
        "p50":float(qq.loc[.50]),
        "p75":float(qq.loc[.75]),
        "p90":float(qq.loc[.90]),
        "p99":float(qq.loc[.99]),
        "mean":float(q["score"].mean()),
        "std":float(q["score"].std()),
        "unique_values":int(q["score"].nunique())
    }

def main():
    print("="*122)
    print("ÅkerVatten MVP v0a · STOPPUNKT F4 · ZERO-AWARE ORGANIC WETNESS REVIEW")
    print("="*122)
    print("No component score is frozen.")

    f = pd.read_parquet(WORK/"akervatten_f_candidate_components_skane.parquet")
    soil = pd.read_csv(SOIL,dtype={"blockid":str,"skiftesbeteckning":str},low_memory=False)
    if soil[KEY].duplicated().any():
        raise RuntimeError("soil feature table has duplicate field keys")

    needed = KEY + [c for c in ["organic_ge20_share_pct","organic_mode_label"] if c in soil.columns]
    q = f.merge(soil[needed],on=KEY,how="left",validate="one_to_one")

    org_raw = pd.to_numeric(q["organic_ge20_share_pct"],errors="coerce")
    org_h = hurdle_percentile(org_raw)
    clay = pd.to_numeric(q["mark_vata__clay_mean__pct"],errors="coerce")
    twi = pd.to_numeric(q["mark_vata__twi_mean__pct"],errors="coerce")
    torka = pd.to_numeric(q["mark_torka_candidate_0_100"],errors="coerce")
    min_and = pd.concat([clay,twi],axis=1).min(axis=1).where(clay.notna()&twi.notna())

    # Raw share is already a transparent 0..100 quantity, so retain it as a
    # second diagnostic beside the hurdle ECDF.
    org_raw_0_100 = org_raw.clip(0,100)

    wet_hurdle = pd.concat([min_and,org_h],axis=1).max(axis=1).where(min_and.notna()|org_h.notna())
    wet_rawshare = pd.concat([min_and,org_raw_0_100],axis=1).max(axis=1).where(min_and.notna()|org_raw_0_100.notna())

    print("\n[1/5] Verify zero-aware organic transform")
    z = org_raw.eq(0) & org_raw.notna()
    p = org_raw.gt(0)
    print(f"  valid organic observations : {int(org_raw.notna().sum()):,}")
    print(f"  raw zero observations      : {int(z.sum()):,}")
    print(f"  positive observations      : {int(p.sum()):,}")
    print(f"  hurdle score for raw zero  : min={org_h[z].min():.1f}, max={org_h[z].max():.1f}")
    if p.any():
        qp=org_h[p].quantile([.01,.10,.50,.90,.99])
        print(f"  positive hurdle P01/P10/P50/P90/P99: {qp.loc[.01]:.2f}/{qp.loc[.10]:.2f}/{qp.loc[.50]:.2f}/{qp.loc[.90]:.2f}/{qp.loc[.99]:.2f}")

    print("\n[2/5] Compare MarkVäta variants")
    variants={
        "F_arithmetic_50_50":pd.to_numeric(q["mark_vata_candidate_0_100"],errors="coerce"),
        "minimum_AND":min_and,
        "organic_OR_min_hurdle":wet_hurdle,
        "organic_OR_min_rawshare":wet_rawshare
    }
    rows=[]
    for name,s in variants.items():
        rec=describe(name,s,torka)
        rows.append(rec)
        print(
            f"  {name:25s}: rho={rec['spearman_vs_MarkTorka']:+.3f} · "
            f"P10/P50/P90={rec['p10']:.1f}/{rec['p50']:.1f}/{rec['p90']:.1f} · "
            f"both>=80={100*rec['both_ge80_fraction']:.3f}% · "
            f"top10 overlap={rec['top10_overlap_with_MarkTorka']:.3f}"
        )
    comp=pd.DataFrame(rows)
    comp.to_csv(WORK/"f4_markvata_variant_comparison.csv",index=False)

    print("\n[3/5] What does the organic branch actually add?")
    high_org = org_h >= 90
    high_min = min_and >= 80
    high_hurdle = wet_hurdle >= 80
    newly_high = high_hurdle & ~high_min
    print(f"  high organic evidence (hurdle >=90)       : {int(high_org.sum()):,}")
    print(f"  minimum_AND >=80                          : {int(high_min.sum()):,}")
    print(f"  final hurdle-OR wetness >=80              : {int(high_hurdle.sum()):,}")
    print(f"  newly >=80 due to organic branch          : {int(newly_high.sum()):,}")
    print(f"  among new-high, organic raw share median  : {org_raw[newly_high].median():.2f}%")
    print(f"  among new-high, organic raw share P10/P90 : {org_raw[newly_high].quantile(.1):.2f}/{org_raw[newly_high].quantile(.9):.2f}%")

    print("\n[4/5] Missing-data behavior")
    print(f"  min_AND coverage      : {100*min_and.notna().mean():.3f}%")
    print(f"  organic hurdle cover  : {100*org_h.notna().mean():.3f}%")
    print(f"  OR-union coverage     : {100*wet_hurdle.notna().mean():.3f}%")
    print("  NOTE: union coverage is diagnostic only; freeze must choose explicit missing-data policy.")

    print("\n[5/5] Candidate decision evidence")
    # Prefer hurdle over raw-share only if it fixes the zero artefact and still
    # provides a useful, non-degenerate distribution. No automatic freeze.
    hurdle_rec=comp[comp.variant.eq("organic_OR_min_hurdle")].iloc[0]
    raw_rec=comp[comp.variant.eq("organic_OR_min_rawshare")].iloc[0]
    print(f"  hurdle-OR rho vs MarkTorka   : {hurdle_rec.spearman_vs_MarkTorka:+.3f}")
    print(f"  raw-share-OR rho vs MarkTorka: {raw_rec.spearman_vs_MarkTorka:+.3f}")
    print(f"  hurdle-OR unique score values: {int(hurdle_rec.unique_values):,}")
    print(f"  raw-share-OR unique values   : {int(raw_rec.unique_values):,}")

    out=q[KEY].copy()
    out["organic_ge20_share_pct"]=org_raw
    out["organic_hurdle_pct"]=org_h
    out["markvata_minimum_and"]=min_and
    out["markvata_hurdle_or"]=wet_hurdle
    out["markvata_rawshare_or"]=wet_rawshare
    out.to_parquet(WORK/"f4_markvata_review_fields.parquet",index=False)

    summary={
        "status":"PASS_WITH_REVIEW",
        "zero_transform_contract":"missing->missing; zero->0; positive->ECDF rank among positives",
        "variants":comp.to_dict("records"),
        "high_organic_hurdle_ge90":int(high_org.sum()),
        "newly_high_due_to_organic_branch":int(newly_high.sum()),
        "coverage":{
            "minimum_AND_pct":float(100*min_and.notna().mean()),
            "organic_hurdle_pct":float(100*org_h.notna().mean()),
            "OR_union_pct":float(100*wet_hurdle.notna().mean())
        },
        "freeze_status":"NOT_FROZEN"
    }
    (WORK/"f4_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("="*122)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
