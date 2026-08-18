#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0i — K/T with tax-assessment regimes.

Purpose
-------
v0h expanded the pricing sample by modelling log(K/T), where K/T is purchase
price divided by total tax assessment.  v0i fixes one deliberate simplification
in v0h: calendar year was treated as one continuous linear trend even though
Swedish agricultural tax assessment is reset in discrete valuation regimes.

This step reuses the LOCKED v0h enriched transaction table; no GIS, sale-block
reconstruction or DSMS sampling is repeated.

Predeclared time structures
---------------------------
LINEAR: v0h's year_centered.
REGIME: level dummies for 2023–25 and 2026+, with 2020–22 as reference.
REGIME_TREND: REGIME + a common year-within-regime trend (0,1,2,...).

The common within-regime trend lets market prices drift between tax resets while
allowing the denominator's valuation level to jump at the regime boundary.

Modern-soil residual
--------------------
For rows with transaction FerrariScore, v0i also constructs an exact-LOO
``soil_surprise_besk_geo``:

  observed FerrariScore - expected FerrariScore from
  beskaffenhet + beskaffenhet-mixed flag + latitude + longitude.

This asks whether modern soil is unusually class-10-like relative to the
administrative quality label and geography.  The surprise is then tested as an
incremental predictor of log(K/T) on the SAME rows.

Guardrails
----------
- K/T remains a whole-property market-premium target, not pure arable kr/ha.
- Tax-regime coding assumes ATL's reported tax assessment is the assessment
  relevant to the transaction record; v0i cannot independently verify that.
- FerrariScore is the frozen prior soil-only diagnostic and DSMS is modeled soil.
- All incremental comparisons refit the baseline on exactly the augmented rows.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

FERRARI = "tx_ferrari_score"
SURPRISE = "soil_surprise_besk_geo"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def n(s):
    return pd.to_numeric(s, errors="coerce")


def add_tax_regime_terms(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    year = n(out["year"])
    out["taxreg_2023_25"] = year.between(2023, 2025, inclusive="both").astype(float)
    out["taxreg_2026plus"] = year.ge(2026).astype(float)

    start = np.where(year.ge(2026), 2026.0, np.where(year.ge(2023), 2023.0, 2020.0))
    out["year_within_taxreg"] = year - start
    out.loc[year.isna(), ["taxreg_2023_25", "taxreg_2026plus", "year_within_taxreg"]] = np.nan
    out["tax_regime"] = np.select(
        [year.between(2020, 2022, inclusive="both"), year.between(2023, 2025, inclusive="both"), year.ge(2026)],
        ["R2020_22", "R2023_25", "R2026plus"],
        default="other",
    )
    return out


def mix_without_time(v0h):
    return [x for x in v0h.MIX if x != "year_centered"]


def besk_without_time(v0h):
    return [x for x in v0h.BESK if x != "year_centered"]


def terms(v0h):
    mix0 = mix_without_time(v0h)
    besk0 = besk_without_time(v0h)
    reg = ["taxreg_2023_25", "taxreg_2026plus"]
    regtrend = reg + ["year_within_taxreg"]
    return {
        "LINEAR_GEO": v0h.GEO,
        "LINEAR_MIX": v0h.MIX,
        "LINEAR_MIX_BESK": v0h.BESK,
        "REGIME_GEO": ["lat_centered", "lon_centered"] + reg,
        "REGIME_MIX": mix0 + reg,
        "REGIME_MIX_BESK": besk0 + reg,
        "REGTREND_GEO": ["lat_centered", "lon_centered"] + regtrend,
        "REGTREND_MIX": mix0 + regtrend,
        "REGTREND_MIX_BESK": besk0 + regtrend,
    }


def add_fit_rows(rows, coef_rows, sample, label, model_terms, fit):
    if fit is None:
        return
    rows.append({
        "sample": sample,
        "model": label,
        "terms": " + ".join(model_terms),
        "n": len(fit["data"]),
        "loo_r2": fit["loo_r2"],
        "train_r2": fit["train_r2"],
        "adj_r2": fit["adj_r2"],
        "median_abs_pct_error_loo": fit["median_ape"],
    })
    for nm, b, se, p in zip(fit["names"], fit["beta"], fit["se"], fit["p_value"]):
        coef_rows.append({
            "sample": sample,
            "model": label,
            "term": nm,
            "coefficient": b,
            "std_error": se,
            "p_value": p,
        })


def same_row_delta(v0g, v0a, df, base_terms, aug_terms):
    aug = v0g.fit_loo(v0a, df, "log_kt_exact", aug_terms)
    if aug is None:
        return None
    base = v0g.fit_loo(v0a, aug["data"], "log_kt_exact", base_terms)
    if base is None or len(base["data"]) != len(aug["data"]):
        return None
    return {
        "n": len(aug["data"]),
        "baseline_loo_r2_same_n": base["loo_r2"],
        "augmented_loo_r2": aug["loo_r2"],
        "delta_loo_r2": aug["loo_r2"] - base["loo_r2"],
        "baseline_median_ape": base["median_ape"],
        "augmented_median_ape": aug["median_ape"],
    }


def add_soil_surprise(v0g, v0a, df: pd.DataFrame) -> tuple[pd.DataFrame, dict | None]:
    out = df.copy()
    out[SURPRISE] = np.nan
    out[SURPRISE + "_expected"] = np.nan
    soil_terms = [
        "aker_beskaffenhet_score",
        "aker_beskaffenhet_mixed",
        "lat_centered",
        "lon_centered",
    ]
    fit = v0g.fit_loo(v0a, out, FERRARI, soil_terms)
    if fit is None:
        return out, None
    d = fit["data"]
    pred = dict(zip(d["sale_id"].astype(str), fit["loo"]))
    obs = dict(zip(d["sale_id"].astype(str), fit["y"]))
    for idx, sid in out["sale_id"].astype(str).items():
        if sid in pred:
            out.at[idx, SURPRISE + "_expected"] = float(pred[sid])
            out.at[idx, SURPRISE] = float(obs[sid] - pred[sid])
    meta = {
        "terms": " + ".join(soil_terms),
        "n": len(d),
        "loo_r2": fit["loo_r2"],
        "train_r2": fit["train_r2"],
    }
    return out, meta


def run_models(v0h, v0g, v0a, df: pd.DataFrame, outdir: Path):
    specs0 = terms(v0h)
    model_rows, coef_rows, inc_rows = [], [], []

    for sample, mask in v0h.sample_masks(df).items():
        x = df.loc[mask].copy().reset_index(drop=True)
        specs = dict(specs0)
        specs["REGTREND_MIX_BESK_FERRARI"] = specs0["REGTREND_MIX_BESK"] + [FERRARI]
        specs["REGTREND_MIX_BESK_SURPRISE"] = specs0["REGTREND_MIX_BESK"] + [SURPRISE]
        for label, tt in specs.items():
            add_fit_rows(model_rows, coef_rows, sample, label, tt, v0g.fit_loo(v0a, x, "log_kt_exact", tt))

        comparisons = [
            ("LINEAR_MIX", specs["LINEAR_MIX"], "REGIME_MIX", specs["REGIME_MIX"]),
            ("LINEAR_MIX", specs["LINEAR_MIX"], "REGTREND_MIX", specs["REGTREND_MIX"]),
            ("REGIME_MIX", specs["REGIME_MIX"], "REGTREND_MIX", specs["REGTREND_MIX"]),
            ("REGTREND_MIX", specs["REGTREND_MIX"], "REGTREND_MIX_BESK", specs["REGTREND_MIX_BESK"]),
            ("REGTREND_MIX_BESK", specs["REGTREND_MIX_BESK"], "REGTREND_MIX_BESK_FERRARI", specs["REGTREND_MIX_BESK_FERRARI"]),
            ("REGTREND_MIX_BESK", specs["REGTREND_MIX_BESK"], "REGTREND_MIX_BESK_SURPRISE", specs["REGTREND_MIX_BESK_SURPRISE"]),
        ]
        for base_label, base_terms, aug_label, aug_terms in comparisons:
            if any(c not in x.columns for c in aug_terms):
                continue
            rr = same_row_delta(v0g, v0a, x, base_terms, aug_terms)
            if rr is not None:
                inc_rows.append({"sample": sample, "baseline": base_label, "augmented": aug_label, **rr})

    comp = pd.DataFrame(model_rows)
    coef = pd.DataFrame(coef_rows)
    inc = pd.DataFrame(inc_rows)
    comp.to_csv(outdir / "kt_regime_model_comparison.csv", index=False, encoding="utf-8-sig")
    coef.to_csv(outdir / "kt_regime_model_coefficients.csv", index=False, encoding="utf-8-sig")
    inc.to_csv(outdir / "kt_regime_incremental_tests.csv", index=False, encoding="utf-8-sig")
    return comp, coef, inc


def regime_summary(v0h, df: pd.DataFrame, outdir: Path):
    rows = []
    for sample, mask in v0h.sample_masks(df).items():
        x = df.loc[mask].copy()
        for regime, g in x.groupby("tax_regime", dropna=False):
            rows.append({
                "sample": sample,
                "tax_regime": regime,
                "n": len(g),
                "median_kt_exact": n(g["kt_exact"]).median(),
                "mean_kt_exact": n(g["kt_exact"]).mean(),
                "median_tax_value_msek": n(g["taxeringsvarde_kr_n"]).median() / 1_000_000.0,
                "median_purchase_price_msek": n(g["kopeskilling_kr_n"]).median() / 1_000_000.0,
            })
    z = pd.DataFrame(rows)
    z.to_csv(outdir / "tax_regime_summary.csv", index=False, encoding="utf-8-sig")
    return z


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    v0a = load_module(root / "src" / "20_value_regression_v0a.py", "value_v0a")
    v0g = load_module(root / "src" / "20g_value_soil_price_surprise_v0g.py", "value_v0g")
    v0h = load_module(root / "src" / "20h_value_kt_expanded_v0h.py", "value_v0h")
    cfg = v0a.load_config(root / args.config)
    build = root / cfg.get("build_dir", "data/derived")
    src = build / "value_regression_v0h_kt_expanded" / "expanded_kt_features.csv"
    if not src.exists():
        raise FileNotFoundError(
            "v0h output saknas: " + str(src) + "\nKör RUN_VALUE_KT_EXPANDED_V0H.bat först."
        )

    outdir = build / "value_regression_v0i_kt_taxregime"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("ÅkerSync · Value Regression v0i · K/T tax-regime correction")
    print("=" * 100)
    print("Locked input:", src)
    print("Output:", outdir)
    print("No GIS/DSMS reconstruction is repeated in v0i.")
    print()

    d = pd.read_csv(src, encoding="utf-8-sig")
    d = add_tax_regime_terms(d)
    d, soil_meta = add_soil_surprise(v0g, v0a, d)
    d.to_csv(outdir / "kt_regime_features.csv", index=False, encoding="utf-8-sig")
    regime = regime_summary(v0h, d, outdir)
    if soil_meta is not None:
        pd.DataFrame([soil_meta]).to_csv(outdir / "soil_surprise_besk_geo_model.csv", index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["terms", "n", "loo_r2", "train_r2"]).to_csv(
            outdir / "soil_surprise_besk_geo_model.csv", index=False, encoding="utf-8-sig"
        )

    comp, coef, inc = run_models(v0h, v0g, v0a, d, outdir)

    lines = [
        "ÅkerSync Value Regression v0i — K/T tax-regime correction",
        "=" * 84,
        f"Locked v0h rows: {len(d)}",
        "",
        "TIME STRUCTURE",
        "Reference regime: 2020–2022.",
        "Level dummies: 2023–2025 and 2026+.",
        "REGTREND additionally uses one common year-within-regime trend.",
        "",
        "TAX REGIME COUNTS / K/T",
    ]
    allrows = regime.loc[regime["sample"].eq("ALL_ARABLE")]
    for _, r in allrows.iterrows():
        lines.append(
            f"  {r['tax_regime']}: n={int(r['n'])}, median K/T={r['median_kt_exact']:.3f}, mean={r['mean_kt_exact']:.3f}"
        )
    if soil_meta is not None:
        lines += [
            "",
            "SOIL SURPRISE vs BESKAFFENHET + GEO",
            f"  n={int(soil_meta['n'])}, FerrariScore LOO R2={soil_meta['loo_r2']:.4f}",
            "  surprise = observed transaction FerrariScore - exact-LOO expected FerrariScore.",
        ]
    if len(comp):
        lines += ["", "MODEL LADDER — sorted within sample by LOO R2"]
        order = ["S80_NOFOREST", "S70_NOFOREST", "S50_ALL", "ALL_ARABLE"]
        for sample in order:
            xx = comp.loc[comp["sample"].eq(sample)].sort_values("loo_r2", ascending=False)
            for _, r in xx.iterrows():
                lines.append(
                    f"  {sample} / {r['model']}: n={int(r['n'])}, LOO={r['loo_r2']:.4f}, medianAPE={r['median_abs_pct_error_loo']:.1f}%"
                )
    if len(inc):
        lines += ["", "SAME-ROW INCREMENTAL TESTS"]
        for _, r in inc.iterrows():
            lines.append(
                f"  {r['sample']} / {r['baseline']} -> {r['augmented']}: n={int(r['n'])}, "
                f"LOO {r['baseline_loo_r2_same_n']:.4f}->{r['augmented_loo_r2']:.4f}, delta={r['delta_loo_r2']:+.4f}"
            )
    lines += [
        "",
        "INTERPRETATION GUARDRAILS",
        "- K/T is whole-property market premium/discount to total tax assessment, not pure arable kr/ha.",
        "- Regime terms are a time-structure correction; they do not prove why tax values or market prices changed.",
        "- Ferrari / soil-surprise increments are judged out-of-sample on exact same rows.",
        "- A negative increment is evidence against predictive pricing signal in this dataset, not against productive soil value.",
    ]
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
