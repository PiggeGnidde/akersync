#!/usr/bin/env python3
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/"work"/"akervatten_mvp_v0a"/"g_sanity_validation"

def fmt(v):
    if pd.isna(v): return "NA"
    if abs(float(v))>=100: return f"{float(v):.1f}"
    return f"{float(v):.3f}"

def main():
    print("="*122)
    print("ÅkerVatten MVP v0a · STOPPUNKT G2 · SANITY REVIEW")
    print("="*122)

    prof=pd.read_csv(WORK/"g_extreme_driver_profiles.csv")
    enrich=pd.read_csv(WORK/"g_group_enrichment_top_bottom10.csv")
    reps=pd.read_csv(WORK/"g_representative_25_cases.csv")

    print("\n[1/3] Top vs bottom 10% raw-driver profiles")
    for comp in prof["component"].drop_duplicates():
        print(f"\n  {comp}")
        q=prof[(prof["component"]==comp)&(prof["fraction"].round(6)==0.10)]
        hi=q[q["tail"]=="HIGH"]
        lo=q[q["tail"]=="LOW"]
        if hi.empty or lo.empty:
            print("    missing top/bottom 10% profile")
            continue
        hi=hi.iloc[0]; lo=lo.iloc[0]
        medcols=[c for c in prof.columns if c.endswith("__median")]
        anyrow=False
        for c in medcols:
            if pd.notna(hi.get(c)) or pd.notna(lo.get(c)):
                name=c[:-8]
                print(f"    {name:42s} · LOW={fmt(lo.get(c))} · HIGH={fmt(hi.get(c))}")
                anyrow=True
        if not anyrow:
            print("    no raw-driver columns available in G table")

    print("\n[2/3] Municipality enrichment · top/bottom 10%")
    if enrich.empty or "group_value" not in enrich.columns:
        print("  no enrichment rows")
    else:
        for comp in enrich["component"].drop_duplicates():
            q=enrich[(enrich["component"]==comp)&(enrich["group_column"].astype(str).str.lower()=="kommun")].copy()
            if q.empty:
                continue
            qhi=q[q["high_n"]>=20].sort_values(["high_enrichment","high_n"],ascending=[False,False]).head(5)
            qlo=q[q["low_n"]>=20].sort_values(["low_enrichment","low_n"],ascending=[False,False]).head(5)
            print(f"\n  {comp} · enriched in HIGH 10%")
            for x in qhi.itertuples(index=False):
                print(f"    {str(x.group_value):24s} · enrichment={x.high_enrichment:.2f}x · n={int(x.high_n):,}")
            print(f"  {comp} · enriched in LOW 10%")
            for x in qlo.itertuples(index=False):
                print(f"    {str(x.group_value):24s} · enrichment={x.low_enrichment:.2f}x · n={int(x.low_n):,}")

    print("\n[3/3] Representative minimum / median / maximum cases")
    for comp in reps["component"].drop_duplicates():
        q=reps[reps["component"]==comp].copy()
        wanted=q[q["target_quantile"].round(6).isin([0.0,0.5,1.0])]
        print(f"\n  {comp}")
        for x in wanted.itertuples(index=False):
            d=x._asdict()
            label={0.0:"MIN",0.5:"P50",1.0:"MAX"}.get(round(float(d["target_quantile"]),6),str(d["target_quantile"]))
            ident=f"{d.get('blockid','?')}/{d.get('skiftesbeteckning','?')}"
            kommun=d.get("kommun","?")
            print(f"    {label:3s} score={float(d['actual_score']):6.2f} · {kommun} · {ident}")

    print("\n" + "="*122)
    print("RUN_AKERVATTEN_G2_REVIEW: PASS")
    print("="*122)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
