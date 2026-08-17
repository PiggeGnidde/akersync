#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0d — geography robustness for clay/TWI.

Purpose
-------
Keep the 2020-07-01+ 56-case sample fixed and test whether the strongest
physical signals from v0b/v0c survive a more flexible geographic baseline.

Baselines
---------
G1 linear geography:
  year + log(area) + lat + lon

G2 quadratic geography:
  G1 + lat^2 + lon^2 + lat*lon

Physical candidates are tested on exactly the same complete-case rows as their
baseline. Main decision metric remains delta LOO R^2.

Pre-declared physical candidates:
  clay point
  clay 100 m mean
  TWI point
  TWI 100 m P90
  clay point + TWI point

Delete-one robustness is also reported for the three main single predictors:
clay point, clay 100 m mean and TWI point.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


G1 = ["year_centered", "log_area_20", "lat_centered", "lon_centered"]
G2 = G1 + ["lat2", "lon2", "lat_lon"]
SINGLE = ["soil_clay_point", "soil_clay_100m_mean", "twi_point", "twi_100m_p90"]
ROBUST = ["soil_clay_point", "soil_clay_100m_mean", "twi_point"]
COMBO = ["soil_clay_point", "twi_point"]


def load_v0a(root: Path):
    p = root / "src" / "20_value_regression_v0a.py"
    spec = importlib.util.spec_from_file_location("akersync_value_v0a", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def add_geo_terms(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["lat2"] = pd.to_numeric(out["lat_centered"], errors="coerce") ** 2
    out["lon2"] = pd.to_numeric(out["lon_centered"], errors="coerce") ** 2
    out["lat_lon"] = (
        pd.to_numeric(out["lat_centered"], errors="coerce")
        * pd.to_numeric(out["lon_centered"], errors="coerce")
    )
    return out


def complete(df: pd.DataFrame, terms: list[str]) -> pd.DataFrame:
    cols = ["log_kr_per_aker_ha"] + terms
    mask = np.ones(len(df), dtype=bool)
    for c in cols:
        if c not in df.columns:
            return df.iloc[0:0].copy()
        mask &= pd.to_numeric(df[c], errors="coerce").notna().to_numpy()
    return df.loc[mask].copy().reset_index(drop=True)


def design(df: pd.DataFrame, terms: list[str]):
    y = pd.to_numeric(df["log_kr_per_aker_ha"], errors="coerce").to_numpy(float)
    X = np.column_stack(
        [np.ones(len(df), dtype=float)]
        + [pd.to_numeric(df[t], errors="coerce").to_numpy(float) for t in terms]
    )
    return X, y, ["intercept"] + list(terms)


def eval_model(v0a, df: pd.DataFrame, baseline: list[str], extras: list[str]) -> dict | None:
    x = complete(df, baseline + extras)
    if len(x) < max(12, len(baseline) + len(extras) + 4):
        return None
    X0, y, _ = design(x, baseline)
    X1, _, names = design(x, baseline + extras)
    if np.linalg.matrix_rank(X1) < X1.shape[1]:
        return None
    p0 = v0a.loo_predictions(X0, y)
    p1 = v0a.loo_predictions(X1, y)
    b, pred, train_r2, adj_r2, rank, se, pv = v0a.fit_ols(X1, y)
    base_loo = v0a.r2_score(y, p0)
    aug_loo = v0a.r2_score(y, p1)
    return {
        "n": len(x),
        "baseline_loo_r2_same_n": base_loo,
        "augmented_loo_r2": aug_loo,
        "delta_loo_r2": aug_loo - base_loo,
        "train_r2_augmented": train_r2,
        "adj_r2_augmented": adj_r2,
        "median_abs_pct_error_loo": 100.0 * float(np.median(v0a.pct_error_from_log(y, p1))),
        "beta": b,
        "se": se,
        "p_value": pv,
        "names": names,
        "data": x,
    }


def eval_baseline(v0a, df: pd.DataFrame, label: str, terms: list[str]) -> dict:
    x = complete(df, terms)
    X, y, names = design(x, terms)
    b, pred, train_r2, adj_r2, rank, se, pv = v0a.fit_ols(X, y)
    lp = v0a.loo_predictions(X, y)
    return {
        "baseline": label,
        "n": len(x),
        "terms": " + ".join(terms),
        "train_r2": train_r2,
        "adj_r2": adj_r2,
        "loo_r2": v0a.r2_score(y, lp),
        "median_abs_pct_error_loo": 100.0 * float(np.median(v0a.pct_error_from_log(y, lp))),
        "beta": b,
        "se": se,
        "p_value": pv,
        "names": names,
    }


def physics_comparison(v0a, df: pd.DataFrame, outdir: Path) -> pd.DataFrame:
    rows = []
    specs = [("G1_linear_geo", G1), ("G2_quadratic_geo", G2)]
    for blabel, bterms in specs:
        for f in SINGLE:
            r = eval_model(v0a, df, bterms, [f])
            if r is None:
                continue
            j = r["names"].index(f)
            rows.append({
                "baseline": blabel,
                "physical_model": f,
                "n": r["n"],
                "baseline_loo_r2_same_n": r["baseline_loo_r2_same_n"],
                "augmented_loo_r2": r["augmented_loo_r2"],
                "delta_loo_r2": r["delta_loo_r2"],
                "feature_coefficient": r["beta"][j],
                "feature_std_error": r["se"][j],
                "feature_p_value": r["p_value"][j],
                "median_abs_pct_error_loo": r["median_abs_pct_error_loo"],
            })
        r = eval_model(v0a, df, bterms, COMBO)
        if r is not None:
            i1 = r["names"].index(COMBO[0])
            i2 = r["names"].index(COMBO[1])
            rows.append({
                "baseline": blabel,
                "physical_model": "clay_point + twi_point_PREDECLARED",
                "n": r["n"],
                "baseline_loo_r2_same_n": r["baseline_loo_r2_same_n"],
                "augmented_loo_r2": r["augmented_loo_r2"],
                "delta_loo_r2": r["delta_loo_r2"],
                "feature_coefficient": np.nan,
                "feature_std_error": np.nan,
                "feature_p_value": np.nan,
                "clay_coefficient": r["beta"][i1],
                "clay_p_value": r["p_value"][i1],
                "twi_coefficient": r["beta"][i2],
                "twi_p_value": r["p_value"][i2],
                "median_abs_pct_error_loo": r["median_abs_pct_error_loo"],
            })
    z = pd.DataFrame(rows)
    if len(z):
        z = z.sort_values(["baseline", "delta_loo_r2"], ascending=[True, False])
    z.to_csv(outdir / "physics_model_comparison.csv", index=False, encoding="utf-8-sig")
    return z


def delete_one_robustness(v0a, df: pd.DataFrame, outdir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for blabel, bterms in [("G1_linear_geo", G1), ("G2_quadratic_geo", G2)]:
        for f in ROBUST:
            full = complete(df, bterms + [f])
            for k in range(len(full)):
                d = full.drop(index=k).reset_index(drop=True)
                r = eval_model(v0a, d, bterms, [f])
                if r is None:
                    continue
                j = r["names"].index(f)
                rows.append({
                    "baseline": blabel,
                    "feature": f,
                    "deleted_sale_id": full.iloc[k].get("sale_id", ""),
                    "deleted_date": full.iloc[k].get("datum", ""),
                    "n_after_delete": r["n"],
                    "feature_coefficient": r["beta"][j],
                    "feature_p_value": r["p_value"][j],
                    "delta_loo_r2_after_delete": r["delta_loo_r2"],
                    "augmented_loo_r2_after_delete": r["augmented_loo_r2"],
                    "median_abs_pct_error_loo": r["median_abs_pct_error_loo"],
                })
    d1 = pd.DataFrame(rows)
    d1.to_csv(outdir / "delete1_robustness.csv", index=False, encoding="utf-8-sig")

    summary = []
    if len(d1):
        for (blabel, f), x in d1.groupby(["baseline", "feature"], sort=False):
            beta = pd.to_numeric(x.feature_coefficient, errors="coerce")
            delta = pd.to_numeric(x.delta_loo_r2_after_delete, errors="coerce")
            full_r = eval_model(v0a, df, G1 if blabel == "G1_linear_geo" else G2, [f])
            full_beta = np.nan
            full_delta = np.nan
            if full_r is not None:
                j = full_r["names"].index(f)
                full_beta = full_r["beta"][j]
                full_delta = full_r["delta_loo_r2"]
            sign = np.sign(full_beta) if np.isfinite(full_beta) and full_beta != 0 else 0
            summary.append({
                "baseline": blabel,
                "feature": f,
                "n_full": full_r["n"] if full_r else np.nan,
                "full_coefficient": full_beta,
                "full_delta_loo_r2": full_delta,
                "delete1_runs": len(x),
                "beta_min": beta.min(),
                "beta_median": beta.median(),
                "beta_max": beta.max(),
                "share_same_sign_as_full_pct": 100.0 * float((np.sign(beta) == sign).mean()) if sign else np.nan,
                "delta_min": delta.min(),
                "delta_median": delta.median(),
                "delta_max": delta.max(),
                "share_delta_positive_pct": 100.0 * float((delta > 0).mean()),
            })
    sm = pd.DataFrame(summary)
    sm.to_csv(outdir / "robustness_summary.csv", index=False, encoding="utf-8-sig")
    return d1, sm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--atl", help="ATL_AkerSync_*_v03.csv; om utelämnad öppnas filväljare")
    ap.add_argument("--radius-m", type=float, default=100.0)
    ap.add_argument("--since", default="2020-07-01")
    ap.add_argument("--baseline-only", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    v0a = load_v0a(root)
    cfg_path = root / args.config
    if not cfg_path.exists():
        raise RuntimeError(f"Saknar {cfg_path}")
    cfg = v0a.load_config(cfg_path)

    atl = args.atl or v0a.choose_atl_csv()
    if not atl:
        print("Avbrutet: ingen ATL CSV vald.")
        return 2
    atl = Path(atl)
    since = pd.Timestamp(args.since)
    outdir = root / cfg.get("build_dir", "data/derived") / "value_regression_v0d"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("ÅkerSync · Value Regression v0d · geography robustness")
    print("=" * 88)
    print("ATL:", atl)
    print("Output:", outdir)
    print("Sample start:", since.date())
    print("G1: year + log(area) + lat + lon")
    print("G2: G1 + lat^2 + lon^2 + lat*lon")
    print()

    audit, all_clean = v0a.load_and_select_clean(atl)
    clean = all_clean.loc[
        pd.to_datetime(all_clean["datum"], errors="coerce").ge(since)
    ].copy().reset_index(drop=True)
    clean = add_geo_terms(clean)
    audit.to_csv(outdir / "selection_audit.csv", index=False, encoding="utf-8-sig")
    clean.to_csv(outdir / "clean_cases.csv", index=False, encoding="utf-8-sig")

    print(f"ATL-rader: {len(pd.read_csv(atl, sep=';', encoding='utf-8-sig')):,}")
    print(f"Unika transaktioner: {len(audit):,}")
    print(f"Rena före datumfilter: {len(all_clean):,}")
    print(f"Rena v0d-case: {len(clean):,}")
    print()

    enriched = clean.copy()
    if not args.baseline_only:
        print("[1/2] Jord punkt + 100 m...")
        enriched = v0a.add_soil_features(enriched, cfg, args.radius_m)
        print("[2/2] TWI/topografi punkt + 100 m...")
        enriched = v0a.add_hydro_topo_features(enriched, cfg, args.radius_m)
        enriched = add_geo_terms(enriched)
    enriched.to_csv(outdir / "point_features.csv", index=False, encoding="utf-8-sig")

    baselines = [eval_baseline(v0a, enriched, "G1_linear_geo", G1),
                 eval_baseline(v0a, enriched, "G2_quadratic_geo", G2)]
    bdf = pd.DataFrame([{k: v for k, v in r.items() if k not in {"beta", "se", "p_value", "names"}}
                        for r in baselines])
    bdf.to_csv(outdir / "geography_baseline_comparison.csv", index=False, encoding="utf-8-sig")

    coef_rows = []
    for r in baselines:
        for n, b, se, p in zip(r["names"], r["beta"], r["se"], r["p_value"]):
            coef_rows.append({"baseline": r["baseline"], "term": n,
                              "coefficient": b, "std_error": se, "p_value": p})
    pd.DataFrame(coef_rows).to_csv(outdir / "geography_baseline_coefficients.csv", index=False, encoding="utf-8-sig")

    comp = pd.DataFrame()
    robust = pd.DataFrame()
    if not args.baseline_only:
        comp = physics_comparison(v0a, enriched, outdir)
        _, robust = delete_one_robustness(v0a, enriched, outdir)

    lines = []
    lines.append("ÅkerSync Value Regression v0d — geography robustness")
    lines.append("=" * 76)
    lines.append(f"ATL source: {atl}")
    lines.append(f"Unique transactions after dedup: {len(audit)}")
    lines.append(f"Clean cases before date window: {len(all_clean)}")
    lines.append(f"Sample start: {since.date()}")
    lines.append(f"Clean v0d cases: {len(clean)}")
    lines.append("")
    lines.append("GEOGRAPHY BASELINES")
    for r in baselines:
        lines.append(
            f"  {r['baseline']}: n={r['n']}, train R2={r['train_r2']:.4f}, "
            f"LOO R2={r['loo_r2']:.4f}, medianAPE={r['median_abs_pct_error_loo']:.1f}%"
        )
    if len(comp):
        lines.append("")
        lines.append("PHYSICAL SIGNALS — delta LOO versus same-row baseline")
        for _, r in comp.sort_values(["baseline", "delta_loo_r2"], ascending=[True, False]).iterrows():
            lines.append(
                f"  {r.baseline} + {r.physical_model}: n={int(r.n)}, "
                f"LOO={r.augmented_loo_r2:.4f}, delta={r.delta_loo_r2:+.4f}, "
                f"medianAPE={r.median_abs_pct_error_loo:.1f}%"
            )
    if len(robust):
        lines.append("")
        lines.append("DELETE-ONE ROBUSTNESS")
        for _, r in robust.iterrows():
            lines.append(
                f"  {r.baseline} / {r.feature}: beta full={r.full_coefficient:+.5g}, "
                f"beta delete1 [{r.beta_min:+.5g}, {r.beta_max:+.5g}], "
                f"same-sign={r.share_same_sign_as_full_pct:.0f}%, "
                f"delta full={r.full_delta_loo_r2:+.4f}, "
                f"delta delete1 [{r.delta_min:+.4f}, {r.delta_max:+.4f}], "
                f"positive={r.share_delta_positive_pct:.0f}%"
            )
    lines.append("")
    lines.append("G2 is deliberately only a modest quadratic geography expansion; with n=56 it is a robustness test, not a search for the best spatial surface.")
    lines.append("Primary metric: delta LOO R2 versus baseline on the SAME rows.")
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
