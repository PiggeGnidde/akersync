#!/usr/bin/env python3
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/"work"/"akervatten_mvp_v0a"/"f_component_candidates"
SOIL=Path(r"C:\AkerSyncRepo\data\derived\soil_features_skiften.csv")
KEY=["blockid","skiftesbeteckning"]

def hurdle_percentile(s):
    x=pd.to_numeric(s,errors="coerce")
    out=pd.Series(np.nan,index=s.index,dtype=float)
    valid=x.notna()
    if (x[valid] < 0).any():
        raise RuntimeError("organic share contains negative values")
    out.loc[valid & (x==0)] = 0.0
    pos=valid & (x>0)
    n=int(pos.sum())
    if n:
        ranks=x.loc[pos].rank(method="average",ascending=True)
        out.loc[pos]=100.0*ranks/n
    return out.clip(0,100)

def top_overlap(a,b,f=.10):
    q=pd.DataFrame({"a":pd.to_numeric(a,errors="coerce"),
                    "b":pd.to_numeric(b,errors="coerce")}).dropna()
    if q.empty: return None
    ra=q.a.rank(method="average",pct=True)
    rb=q.b.rank(method="average",pct=True)
    aa=set(q.index[ra>=1-f]); bb=set(q.index[rb>=1-f])
    d=min(len(aa),len(bb))
    return None if d==0 else len(aa&bb)/d

def describe(s):
    x=pd.to_numeric(s,errors="coerce").dropna()
    q=x.quantile([.1,.5,.9])
    return {"n":int(len(x)),"p10":float(q.loc[.1]),"p50":float(q.loc[.5]),"p90":float(q.loc[.9]),
            "mean":float(x.mean()),"std":float(x.std()),"unique":int(x.nunique())}

def main():
    print("="*122)
    print("ÅkerVatten MVP v0a · STOPPUNKT F5 · FINAL COMPONENT CANDIDATE")
    print("="*122)
    print("No combined ÅkerVatten index is created.")

    f=pd.read_parquet(WORK/"akervatten_f_candidate_components_skane.parquet")
    soil=pd.read_csv(SOIL,dtype={"blockid":str,"skiftesbeteckning":str},low_memory=False)
    if soil[KEY].duplicated().any():
        raise RuntimeError("soil feature table has duplicate field keys")
    need=KEY+["organic_ge20_share_pct"]
    q=f.merge(soil[need],on=KEY,how="left",validate="one_to_one")

    clay=pd.to_numeric(q["mark_vata__clay_mean__pct"],errors="coerce")
    twi=pd.to_numeric(q["mark_vata__twi_mean__pct"],errors="coerce")
    org_raw=pd.to_numeric(q["organic_ge20_share_pct"],errors="coerce")
    org_h=hurdle_percentile(org_raw)

    mineral=pd.concat([clay,twi],axis=1).min(axis=1)
    mineral_full=clay.notna() & twi.notna()
    mineral=mineral.where(mineral_full)

    full=mineral.notna() & org_h.notna()
    final=pd.concat([mineral,org_h],axis=1).max(axis=1).where(full)

    lower_bound=pd.concat([mineral,org_h],axis=1).max(axis=1)
    quality=np.select(
        [
            mineral.notna() & org_h.notna(),
            mineral.notna() & org_h.isna(),
            mineral.isna() & org_h.notna()
        ],
        [
            "FULL",
            "MISSING_ORGANIC_BRANCH",
            "MISSING_MINERAL_BRANCH"
        ],
        default="MISSING_BOTH"
    )

    q["mark_vata_mineral_branch_0_100"]=mineral
    q["mark_vata_organic_branch_0_100"]=org_h
    q["mark_vata_candidate_f5_0_100"]=final
    q["mark_vata_lower_bound_diagnostic_0_100"]=lower_bound
    q["mark_vata_f5_quality"]=quality

    print("\n[1/5] Strict MarkVäta coverage")
    counts=pd.Series(quality).value_counts()
    for k in ["FULL","MISSING_ORGANIC_BRANCH","MISSING_MINERAL_BRANCH","MISSING_BOTH"]:
        print(f"  {k:24s}: {int(counts.get(k,0)):,}")
    coverage=float(full.mean())
    print(f"  strict FULL coverage       : {100*coverage:.3f}%")

    print("\n[2/5] Final MarkVäta distribution")
    d=describe(final)
    print(f"  n={d['n']:,} · P10={d['p10']:.2f} · P50={d['p50']:.2f} · P90={d['p90']:.2f} · unique={d['unique']:,}")
    print(f"  mineral branch P50        : {pd.to_numeric(mineral,errors='coerce').median():.2f}")
    print(f"  organic branch P50 valid  : {pd.to_numeric(org_h,errors='coerce').median():.2f}")

    print("\n[3/5] Distinctness from MarkTorka")
    mt=pd.to_numeric(q["mark_torka_candidate_0_100"],errors="coerce")
    z=pd.DataFrame({"torka":mt,"vata":final}).dropna()
    rho=float(z.torka.corr(z.vata,method="spearman"))
    ov=top_overlap(z.torka,z.vata,.10)
    both=float(((z.torka>=80)&(z.vata>=80)).mean())
    print(f"  Spearman MarkTorka vs final MarkVäta: {rho:+.3f}")
    print(f"  top10-high overlap                  : {ov:.3f}")
    print(f"  both >=80                           : {100*both:.3f}%")
    print(f"  sum std                             : {(z.torka+z.vata).std():.3f}")
    print(f"  sum range                           : {(z.torka+z.vata).max()-(z.torka+z.vata).min():.3f}")

    print("\n[4/5] Cross-component correlations")
    score_cols={
        "MarkTorka":"mark_torka_candidate_0_100",
        "MarkVata":"mark_vata_candidate_f5_0_100",
        "GrundvattenTillgang":"grundvatten_tillgang_candidate_0_100",
        "GrundvattenTorka":"grundvatten_torka_candidate_0_100",
        "YtvattenTorka":"ytvatten_torka_candidate_0_100",
    }
    s=pd.DataFrame({k:pd.to_numeric(q[v],errors="coerce") for k,v in score_cols.items()})
    corr=s.corr(method="spearman")
    rows=[]
    names=list(corr.columns)
    for i in range(len(names)):
        for j in range(i+1,len(names)):
            a,b=names[i],names[j]
            val=float(corr.loc[a,b])
            rows.append({"component_a":a,"component_b":b,"spearman":val})
    cr=pd.DataFrame(rows).sort_values("spearman",key=lambda x:x.abs(),ascending=False)
    for r in cr.itertuples(index=False):
        print(f"  {r.component_a:23s} vs {r.component_b:23s}: rho={r.spearman:+.3f}")
    cr.to_csv(WORK/"f5_cross_component_spearman.csv",index=False)

    print("\n[5/5] QA")
    problems=[]
    if coverage < .95:
        problems.append(f"MarkVata strict coverage {coverage:.3%} < 95%")
    if abs(rho) >= .90:
        problems.append(f"MarkTorka/MarkVata abs rho {abs(rho):.3f} >= 0.90")
    other_coverage={
        "MarkTorka":q["mark_torka_candidate_0_100"].notna().mean(),
        "GrundvattenTillgang":q["grundvatten_tillgang_candidate_0_100"].notna().mean(),
        "GrundvattenTorka":q["grundvatten_torka_candidate_0_100"].notna().mean(),
        "YtvattenTorka":q["ytvatten_torka_candidate_0_100"].notna().mean(),
    }
    for name,val in other_coverage.items():
        print(f"  {name:23s}: {100*val:.3f}%")
    print(f"  {'MarkVata':23s}: {100*coverage:.3f}%")
    print(f"  problems               : {len(problems)}")

    out=WORK/"akervatten_f5_final_candidate_components_skane.parquet"
    q.to_parquet(out,index=False)
    status="PASS_WITH_REVIEW" if not problems else "FAIL"
    summary={
        "schema_version":"akervatten-mvp-v0a-f5-final-candidate",
        "status":status,
        "markvata":{
            "formula":"max(min(clay_pct,twi_pct),organic_hurdle_pct)",
            "missing_policy":"strict: score only when mineral and organic branches are both known",
            "coverage_pct":100*coverage,
            "spearman_vs_MarkTorka":rho,
            "top10_overlap_vs_MarkTorka":ov,
            "both_ge80_fraction":both
        },
        "problems":problems,
        "output":str(out)
    }
    (WORK/"f5_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"  status                 : {status}")
    print("="*122)
    print(f"AKERVATTEN STOPPUNKT F5 FINAL CANDIDATE: {status}")
    print("="*122)
    return 0 if not problems else 2

if __name__=="__main__":
    raise SystemExit(main())
