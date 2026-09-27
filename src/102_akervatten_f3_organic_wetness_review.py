#!/usr/bin/env python3
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "akervatten_mvp_v0a" / "f_component_candidates"
SOIL = Path(r"C:\AkerSyncRepo\data\derived\soil_features_skiften.csv")
KEY = ["blockid","skiftesbeteckning"]

def pct(s, direction=1):
    x = pd.to_numeric(s, errors="coerce")
    out = pd.Series(np.nan, index=s.index, dtype=float)
    ok = x.notna()
    n = int(ok.sum())
    if n == 0:
        return out
    if n == 1:
        out.loc[ok] = 50.0
        return out
    r = x.loc[ok].rank(method="average", ascending=True)
    p = 100.0*(r-1.0)/(n-1.0)
    if direction < 0:
        p = 100.0-p
    out.loc[ok] = p.clip(0,100)
    return out

def top_overlap(a,b,fraction=.10):
    q = pd.DataFrame({"a":pd.to_numeric(a,errors="coerce"),
                      "b":pd.to_numeric(b,errors="coerce")}).dropna()
    if q.empty:
        return None
    ra=q.a.rank(method="average",pct=True)
    rb=q.b.rank(method="average",pct=True)
    aa=set(q.index[ra>=1-fraction])
    bb=set(q.index[rb>=1-fraction])
    d=min(len(aa),len(bb))
    return None if d==0 else len(aa&bb)/d

def main():
    print("="*120)
    print("ÅkerVatten MVP v0a · STOPPUNKT F3 · ORGANIC-SOIL WETNESS REVIEW")
    print("="*120)
    print("No score is frozen.")

    f = pd.read_parquet(WORK / "akervatten_f_candidate_components_skane.parquet")
    soil = pd.read_csv(SOIL, dtype={"blockid":str,"skiftesbeteckning":str}, low_memory=False)
    if soil[KEY].duplicated().any():
        raise RuntimeError("soil feature table has duplicate field keys")

    wanted = KEY + [c for c in [
        "organic_ge20_share_pct","organic_mode_code","organic_mode_label",
        "organic_coverage_pct","silt_mean","clay_mean","sand_mean"
    ] if c in soil.columns]
    q = f.merge(soil[wanted], on=KEY, how="left", validate="one_to_one", suffixes=("","_soil"))

    required = ["organic_ge20_share_pct","organic_mode_label"]
    for c in required:
        if c not in q.columns:
            raise RuntimeError(f"Required review column missing: {c}")

    org = pd.to_numeric(q["organic_ge20_share_pct"], errors="coerce")
    clayp = pd.to_numeric(q["mark_vata__clay_mean__pct"], errors="coerce")
    twip = pd.to_numeric(q["mark_vata__twi_mean__pct"], errors="coerce")
    torka = pd.to_numeric(q["mark_torka_candidate_0_100"], errors="coerce")
    vata_f = pd.to_numeric(q["mark_vata_candidate_0_100"], errors="coerce")
    vata_min = pd.concat([clayp,twip],axis=1).min(axis=1).where(clayp.notna()&twip.notna())
    orgp = pct(org, +1)

    print("\n[1/5] Organic coverage and prevalence")
    print(f"  coverage organic_ge20_share_pct: {100*org.notna().mean():.3f}%")
    print(f"  nonzero organic share          : {100*(org.fillna(0)>0).mean():.3f}% of all fields")
    for threshold in (1,5,10,20,50,80):
        print(f"  organic share >= {threshold:2d}%          : {100*(org.fillna(0)>=threshold).mean():.3f}%")
    if org.notna().any():
        qq=org.dropna().quantile([.1,.5,.9,.95,.99])
        print(f"  raw share P10/P50/P90/P95/P99  : {qq.loc[.1]:.2f}/{qq.loc[.5]:.2f}/{qq.loc[.9]:.2f}/{qq.loc[.95]:.2f}/{qq.loc[.99]:.2f}")

    print("\n[2/5] Organic mode labels")
    labels = (
        q["organic_mode_label"].fillna("(missing)").astype(str)
        .value_counts(dropna=False)
        .rename_axis("label").reset_index(name="n")
    )
    labels["pct_fields"] = 100.0*labels["n"]/len(q)
    for r in labels.head(30).itertuples(index=False):
        print(f"  {r.label[:45]:45s} : {r.n:7,d} · {r.pct_fields:6.3f}%")
    labels.to_csv(WORK/"f3_organic_mode_label_distribution.csv", index=False)

    print("\n[3/5] Independence / complementarity")
    metrics = {
        "clay_pct":clayp,
        "twi_pct":twip,
        "MarkTorka":torka,
        "MarkVata_F_arithmetic":vata_f,
        "MarkVata_minimum_AND":vata_min,
    }
    corr_rows=[]
    for name,s in metrics.items():
        z=pd.DataFrame({"org":orgp,"x":s}).dropna()
        rho=float(z.org.corr(z.x,method="spearman")) if len(z)>=3 else np.nan
        ov=top_overlap(orgp,s,.10)
        corr_rows.append({"metric":name,"spearman_vs_organic_pct":rho,"top10_overlap":ov})
        print(f"  organic pct vs {name:22s}: rho={rho:+.3f} · top10 overlap={ov:.3f}")
    pd.DataFrame(corr_rows).to_csv(WORK/"f3_organic_correlations.csv", index=False)

    print("\n[4/5] Does organic soil identify new wetness candidates?")
    high_org = orgp >= 90
    high_min = vata_min >= 80
    high_twi = twip >= 80
    high_clay = clayp >= 80
    print(f"  top10 organic percentile fields              : {int(high_org.sum()):,}")
    print(f"  ... also MarkVata minimum_AND >=80            : {int((high_org&high_min).sum()):,} ({100*(high_org&high_min).sum()/max(1,high_org.sum()):.1f}%)")
    print(f"  ... TWI >=80 but clay <80                     : {int((high_org&high_twi&~high_clay).sum()):,}")
    print(f"  ... clay >=80 but TWI <80                     : {int((high_org&high_clay&~high_twi).sum()):,}")
    print(f"  ... neither clay nor TWI >=80                 : {int((high_org&~high_clay&~high_twi).sum()):,}")

    # Transparent OR extension diagnostic:
    # wetness evidence can come from either joint mineral-soil/topography evidence
    # or strong organic-soil evidence.
    organic_or_min = pd.concat([vata_min,orgp],axis=1).max(axis=1)
    valid = vata_min.notna() | orgp.notna()
    organic_or_min = organic_or_min.where(valid)

    print("\n[5/5] Diagnostic extended wetness variant")
    z=pd.DataFrame({"torka":torka,"vata":organic_or_min}).dropna()
    rho=float(z.torka.corr(z.vata,method="spearman"))
    both=float(((z.torka>=80)&(z.vata>=80)).mean())
    qv=z.vata.quantile([.1,.5,.9])
    print(f"  max(min(clay_pct,twi_pct), organic_pct): rho vs MarkTorka={rho:+.3f}")
    print(f"  P10/P50/P90={qv.loc[.1]:.1f}/{qv.loc[.5]:.1f}/{qv.loc[.9]:.1f}")
    print(f"  both MarkTorka>=80 and wetness>=80: {100*both:.3f}%")

    ext = q.loc[high_org, [c for c in KEY+["kommun","organic_ge20_share_pct","organic_mode_code","organic_mode_label"] if c in q.columns]].copy()
    ext["organic_percentile"]=orgp.loc[high_org]
    ext["clay_percentile"]=clayp.loc[high_org]
    ext["twi_percentile"]=twip.loc[high_org]
    ext["markvata_minimum_AND"]=vata_min.loc[high_org]
    ext["markvata_organic_OR_min"]=organic_or_min.loc[high_org]
    ext.sort_values(["organic_percentile","organic_ge20_share_pct"],ascending=False).head(500).to_csv(
        WORK/"f3_high_organic_fields_sample.csv",index=False
    )

    summary = {
        "status":"PASS_WITH_REVIEW",
        "organic_coverage_pct":float(100*org.notna().mean()),
        "organic_nonzero_field_pct":float(100*(org.fillna(0)>0).mean()),
        "top10_organic_fields":int(high_org.sum()),
        "top10_organic_also_minimum_and_ge80":int((high_org&high_min).sum()),
        "top10_organic_neither_clay_nor_twi_ge80":int((high_org&~high_clay&~high_twi).sum()),
        "extended_variant":{
            "definition":"max(min(clay_pct,twi_pct), organic_pct)",
            "spearman_vs_MarkTorka":rho,
            "both_ge80_fraction":both
        }
    }
    (WORK/"f3_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("="*120)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
