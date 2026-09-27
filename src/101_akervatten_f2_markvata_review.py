#!/usr/bin/env python3
from pathlib import Path
import json
import re
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "akervatten_mvp_v0a" / "f_component_candidates"

def top_overlap(a, b, fraction=0.10):
    q = pd.DataFrame({"a": pd.to_numeric(a, errors="coerce"),
                      "b": pd.to_numeric(b, errors="coerce")}).dropna()
    ra = q["a"].rank(method="average", pct=True)
    rb = q["b"].rank(method="average", pct=True)
    aa = set(q.index[ra >= 1.0-fraction])
    bb = set(q.index[rb >= 1.0-fraction])
    d = min(len(aa), len(bb))
    return None if d == 0 else len(aa & bb) / d

def harmonic(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    out = pd.Series(np.nan, index=a.index, dtype=float)
    ok = a.notna() & b.notna()
    den = a + b
    z = ok & (den > 0)
    out.loc[z] = 2.0*a.loc[z]*b.loc[z]/den.loc[z]
    out.loc[ok & (den == 0)] = 0.0
    return out

def main():
    print("="*118)
    print("ÅkerVatten MVP v0a · STOPPUNKT F2 · MARKVÄTA DISTINCTNESS REVIEW")
    print("="*118)
    df = pd.read_parquet(WORK / "akervatten_f_candidate_components_skane.parquet")
    mt = pd.to_numeric(df["mark_torka_candidate_0_100"], errors="coerce")
    mv = pd.to_numeric(df["mark_vata_candidate_0_100"], errors="coerce")
    clay = pd.to_numeric(df["mark_vata__clay_mean__pct"], errors="coerce")
    twi = pd.to_numeric(df["mark_vata__twi_mean__pct"], errors="coerce")
    complete = clay.notna() & twi.notna()

    variants = {
        "arithmetic_50_50_F": mv,
        "geometric_AND": np.sqrt(clay*twi),
        "minimum_AND": pd.concat([clay,twi], axis=1).min(axis=1).where(complete),
        "harmonic_AND": harmonic(clay,twi),
        "clay25_twi75": 0.25*clay + 0.75*twi,
        "clay75_twi25": 0.75*clay + 0.25*twi,
    }

    print("\n[1/4] Variant comparison against MarkTorka")
    rows = []
    for name, s in variants.items():
        q = pd.DataFrame({"torka":mt, "vata":s}).dropna()
        rho = float(q["torka"].corr(q["vata"], method="spearman"))
        ov = top_overlap(q["torka"], q["vata"])
        qq = q["vata"].quantile([.1,.5,.9])
        both = float(((q["torka"] >= 80) & (q["vata"] >= 80)).mean())
        rec = {"variant":name, "rho":rho, "top10_overlap":ov,
               "p10":float(qq.loc[.1]), "p50":float(qq.loc[.5]), "p90":float(qq.loc[.9]),
               "both_ge80_fraction":both, "sum_std":float((q["torka"]+q["vata"]).std())}
        rows.append(rec)
        print(f"  {name:20s}: rho={rho:+.3f} · P10/P50/P90={rec['p10']:.1f}/{rec['p50']:.1f}/{rec['p90']:.1f} · both>=80={100*both:.2f}% · top10={ov:.3f}")

    result = pd.DataFrame(rows)
    result.to_csv(WORK / "f2_markvata_variant_comparison.csv", index=False)

    print("\n[2/4] Joint-evidence behavior")
    discord = complete & (((clay>=80)&(twi<=20)) | ((twi>=80)&(clay<=20)))
    concord = complete & (clay>=80) & (twi>=80)
    for name in ("arithmetic_50_50_F","geometric_AND","minimum_AND","harmonic_AND"):
        s = variants[name]
        print(f"  {name:20s}: median discordant={s[discord].median():.2f} · median both-high={s[concord].median():.2f} · both-high n={int(concord.sum()):,}")

    print("\n[3/4] Soil schema scan for independent wetness candidates")
    cols = list(pd.read_csv(r"C:\AkerSyncRepo\data\derived\soil_features_skiften.csv", nrows=0).columns)
    pattern = re.compile(r"organic|organisk|mull|torv|peat|humus|drain|silt|soil_class|jordklass|jordart", re.I)
    hits = [c for c in cols if pattern.search(str(c))]
    print("  " + (", ".join(hits) if hits else "(none)"))

    print("\n[4/4] Review status")
    eligible = result[result["variant"].isin(["geometric_AND","minimum_AND","harmonic_AND"])].copy()
    eligible["abs_rho"] = eligible["rho"].abs()
    choice = eligible.sort_values(["abs_rho","sum_std"], ascending=[True,False]).iloc[0]
    print(f"  least anti-correlated AND variant: {choice['variant']} (rho={choice['rho']:+.3f})")
    (WORK / "f2_summary.json").write_text(json.dumps({
        "status":"PASS_WITH_REVIEW",
        "variants":result.to_dict("records"),
        "soil_candidate_like_columns":hits,
        "least_anticorrelated_AND_variant":str(choice["variant"])
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
