#!/usr/bin/env python3
"""Zero-PU combination ranking from already downloaded local-cloud daily statistics."""
from __future__ import annotations
import argparse, itertools, json, math
from datetime import date
from pathlib import Path

def qtile(vals,q):
    x=sorted(float(v) for v in vals)
    if not x: return None
    p=(len(x)-1)*q; lo=int(math.floor(p)); hi=int(math.ceil(p))
    return x[lo] if lo==hi else x[lo]+(x[hi]-x[lo])*(p-lo)

def main():
    import pandas as pd
    ap=argparse.ArgumentParser()
    ap.add_argument("--local-cloud-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_local_cloud")
    ap.add_argument("--rescue-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_rescue_dates")
    ap.add_argument("--output-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_combo_diag")
    args=ap.parse_args()

    lc=Path(args.local_cloud_dir); rd=Path(args.rescue_dir); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    daily=pd.read_csv(lc/"local_cloud_daily_samples.csv")
    rescue=pd.read_csv(rd/"rescue_date_ranking.csv")
    frozen={"S2_2026_APRIL":["2026-04-08","2026-04-09"],"S2_2026_JUNE":["2026-06-26","2026-06-27"]}

    rows=[]; summaries=[]
    for snap in frozen:
        cand=rescue[(rescue["snapshot"]==snap)&(rescue["gap_rescue_percent"]>=90.0)&(rescue["stac_items"]>0)]["candidate_date"].astype(str).tolist()
        sub=daily[daily["field_key"].astype(str).str.startswith(snap)].copy()
        piv=sub.pivot_table(index="field_key",columns="date",values="clear_fraction",aggfunc="first")
        fdates=[date.fromisoformat(x) for x in frozen[snap]]
        snaprows=[]
        for k in (1,2,3):
            for combo in itertools.combinations(sorted(set(cand)),k):
                cols=[c for c in combo if c in piv.columns]
                if len(cols)!=k: continue
                best=piv[cols].max(axis=1,skipna=True)
                vals=best.dropna().astype(float).tolist()
                if not vals: continue
                med=float(pd.Series(vals).median()); p10=float(qtile(vals,0.10))
                ge70=sum(v>=0.70 for v in vals)/len(vals); ge90=sum(v>=0.90 for v in vals)/len(vals); zero=sum(v<=0.01 for v in vals)/len(vals)
                ds=[date.fromisoformat(c) for c in combo]
                span=(max(ds)-min(ds)).days
                maxdist=max(min(abs((d-f).days) for f in fdates) for d in ds)
                # Quality first. Small penalties prefer fewer/closer dates only when clear-sky performance is similar.
                score=0.55*ge70+0.20*ge90+0.15*p10+0.10*med-0.008*(k-1)-0.003*maxdist-0.001*span
                r={
                    "snapshot":snap,"n_dates":k,"dates":"+".join(combo),
                    "sample_fields":len(vals),
                    "median_best_clear_fraction":round(med,4),
                    "p10_best_clear_fraction":round(p10,4),
                    "fraction_fields_ge70pct_clear":round(ge70,4),
                    "fraction_fields_ge90pct_clear":round(ge90,4),
                    "fraction_fields_le1pct_clear":round(zero,4),
                    "date_span_days":span,
                    "max_distance_days_to_frozen":maxdist,
                    "score":round(score,6),
                }
                rows.append(r); snaprows.append(r)
        sr=pd.DataFrame(snaprows).sort_values(
            ["n_dates","fraction_fields_ge70pct_clear","p10_best_clear_fraction","median_best_clear_fraction","score"],
            ascending=[True,False,False,False,False]
        )
        best={}
        for k in (1,2,3):
            x=sr[sr["n_dates"]==k].sort_values(
                ["fraction_fields_ge70pct_clear","fraction_fields_ge90pct_clear","p10_best_clear_fraction","median_best_clear_fraction","score"],
                ascending=False
            )
            best[str(k)]=x.head(5).to_dict(orient="records")
        summaries.append({"snapshot":snap,"top_by_number_of_dates":best})

    allr=pd.DataFrame(rows).sort_values(["snapshot","n_dates","score"],ascending=[True,True,False])
    allr.to_csv(out/"combination_ranking.csv",index=False)
    (out/"combination_summary.json").write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("AKERPULS PRELIM FIELDS 2026 - RESCUE COMBINATION DIAGNOSTIC - ZERO PU")
    for s in summaries:
        print(s["snapshot"])
        for k in ("1","2","3"):
            top=s["top_by_number_of_dates"][k]
            if not top: continue
            r=top[0]
            print(f'  BEST_{k}_DATE={r["dates"]} GE70={r["fraction_fields_ge70pct_clear"]:.4f} GE90={r["fraction_fields_ge90pct_clear"]:.4f} P10={r["p10_best_clear_fraction"]:.4f} MED={r["median_best_clear_fraction"]:.4f} ZERO={r["fraction_fields_le1pct_clear"]:.4f} MAXDIST={r["max_distance_days_to_frozen"]}d')
    print("OUTPUT="+str(out))
    print("SENTINEL_HUB_PU_USED=0")
    print("NOTE=Field-level max(clear_fraction) is a conservative date-selection diagnostic, not a pixel-union estimate.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
