#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0j — anchored additive property decomposition.

This model goes back to purchase price in SEK. Tax-assessed value is NOT used
as the target or as a predictor.

Observed total purchase price is decomposed into positive components:

    P_total = P_arable + P_house + P_econ + P_pasture
              + P_forest + P_impediment + P_other

The arable component is the scientific target. It is modeled as hectares times
a positive SEK/ha rate. ATL arable "beskaffenhet" and drainage are explicitly
attached to the arable rate, not to nuisance components.

Strict/near-pure arable transactions naturally anchor identification because
their nuisance quantities are zero. Mixed transactions then help estimate
property components jointly.

Primary validation is deterministic 10-fold spatial-group CV (10 km sale cells
stay in one fold). The model is nonlinear/additive, so exact OLS LOO formulas do
not apply. Same-row incremental tests are therefore done with the identical
spatial folds. The strict-anchor subset receives separate held-out diagnostics.
"""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

FERRARI = "tx_ferrari_score"

ARABLE_BASE = ["year_centered", "log_area_20", "lat_centered", "lon_centered"]
ARABLE_BESK = ARABLE_BASE + ["aker_beskaffenhet_score0", "aker_beskaffenhet_mixed0"]
ARABLE_DRAIN = ARABLE_BESK + [
    "drain_unsatisfactory",
    "drain_legacy_system_tiled",
    "drain_missing_other",
]

DRAIN_REFERENCE = "satisfactory_other"

COMPONENT_SEEDS = {
    "house": 15_000.0,
    "econ": 1_500.0,
    "pasture": 80_000.0,
    "forest": 100_000.0,
    "imped": 10_000.0,
    "other": 30_000.0,
}
ARABLE_SEED = 300_000.0
MIN_COMPONENT_ACTIVE = 20
MIN_GEO_COMPONENT_ACTIVE = 80


def num(s):
    return pd.to_numeric(s, errors="coerce")


def safe_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return (
        s.astype("string").str.strip().str.casefold()
        .isin({"1", "true", "yes", "ja"})
    )


def stable_fold(value, k=10):
    h = hashlib.sha1(str(value).encode("utf-8")).hexdigest()
    return int(h[:8], 16) % k


def r2_log(y, pred):
    y = np.asarray(y, float)
    pred = np.asarray(pred, float)
    ok = np.isfinite(y) & np.isfinite(pred) & (y > 0) & (pred > 0)
    y = np.log(y[ok])
    p = np.log(pred[ok])
    if len(y) < 3:
        return np.nan
    den = np.sum((y - y.mean()) ** 2)
    return float(1.0 - np.sum((y - p) ** 2) / den) if den > 0 else np.nan


def medape(y, pred):
    y = np.asarray(y, float)
    pred = np.asarray(pred, float)
    ok = np.isfinite(y) & np.isfinite(pred) & (y > 0)
    if not np.any(ok):
        return np.nan
    return float(100.0 * np.median(np.abs(pred[ok] / y[ok] - 1.0)))


def choose_csv(title: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    p = filedialog.askopenfilename(
        title=title,
        filetypes=[("CSV", "*.csv"), ("Alla filer", "*.*")],
    )
    root.destroy()
    return p or None


def find_input(root: Path, explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        root / "data" / "derived" / "value_regression_v0i_kt_taxregime" / "kt_regime_features.csv",
        root / "data" / "derived" / "value_regression_v0h_kt_expanded" / "expanded_kt_features.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    chosen = choose_csv("Välj kt_regime_features.csv (v0i) eller expanded_kt_features.csv (v0h)")
    if chosen:
        return Path(chosen)
    raise FileNotFoundError("Hittar inte v0i/v0h featurefil. Kör v0h/v0i först.")


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    required = [
        "sale_id", "kopeskilling_kr_n", "akermark_ha_n",
        "total_areal_ha_n", "lat_n", "lon_n", "year",
        "aker_share_frac", "drainage_state",
        "aker_beskaffenhet_score", "aker_beskaffenhet_mixed",
    ]
    missing = [c for c in required if c not in d.columns]
    if missing:
        raise RuntimeError("Featurefil saknar kolumner: " + ", ".join(missing))

    qty = [
        "smahus_kvm_total_n", "ekonomibyggnad_kvm_total_n",
        "betesmark_ha_n", "skogsmark_ha_n", "skogsimpediment_ha_n",
        "smahusmark_kvm_total_n",
    ]
    for c in qty:
        if c not in d.columns:
            d[c] = 0.0
        d[c] = num(d[c]).fillna(0.0).clip(lower=0.0)

    for c in [
        "kopeskilling_kr_n", "akermark_ha_n", "total_areal_ha_n",
        "lat_n", "lon_n", "year", "aker_share_frac",
    ]:
        d[c] = num(d[c])

    # Actual purchase-price model: use market time, not tax-assessment regimes.
    d["year_centered"] = d["year"] - 2024.0
    d["lat_centered"] = d["lat_n"] - 55.5
    d["lon_centered"] = d["lon_n"] - 13.0
    d["log_area_20"] = np.log(d["akermark_ha_n"] / 20.0)

    d["aker_beskaffenhet_score0"] = num(d["aker_beskaffenhet_score"]).fillna(0.0)
    d["aker_beskaffenhet_mixed0"] = num(d["aker_beskaffenhet_mixed"]).fillna(0.0)
    d["aker_beskaffenhet_missing"] = num(d["aker_beskaffenhet_score"]).isna().astype(float)

    state = d["drainage_state"].fillna("missing").astype(str)
    d["drain_unsatisfactory"] = state.eq("unsatisfactory").astype(float)
    d["drain_legacy_system_tiled"] = state.eq("legacy_system_tiled").astype(float)
    d["drain_missing_other"] = (~state.isin([
        "satisfactory_other", "unsatisfactory", "legacy_system_tiled"
    ])).astype(float)

    component_area = (
        d["akermark_ha_n"].fillna(0)
        + d["betesmark_ha_n"]
        + d["skogsmark_ha_n"]
        + d["skogsimpediment_ha_n"]
    )
    d["other_ha"] = (d["total_areal_ha_n"].fillna(0) - component_area).clip(lower=0.0)

    if "sale_spatial_cell" not in d.columns:
        d["sale_spatial_cell"] = d["sale_id"].astype(str)
    groupkey = d["sale_spatial_cell"].fillna(d["sale_id"]).astype(str)
    d["spatial_fold10"] = groupkey.map(lambda x: stable_fold(x, 10)).astype(int)

    # Conservative near-pure arable anchor.
    d["anchor_strict"] = (
        d["smahus_kvm_total_n"].eq(0)
        & d["ekonomibyggnad_kvm_total_n"].eq(0)
        & d["skogsmark_ha_n"].eq(0)
        & d["betesmark_ha_n"].eq(0)
        & d["skogsimpediment_ha_n"].eq(0)
        & d["other_ha"].le(0.5)
    )

    if "expanded_main_eligible" in d.columns:
        eligible = safe_bool(d["expanded_main_eligible"])
    else:
        eligible = pd.Series(True, index=d.index)

    d["v0j_eligible"] = (
        eligible
        & d["kopeskilling_kr_n"].gt(0)
        & d["akermark_ha_n"].gt(0)
        & d["total_areal_ha_n"].gt(0)
        & d["lat_n"].notna()
        & d["lon_n"].notna()
        & d["year"].notna()
    )
    return d


def sample_masks(d: pd.DataFrame):
    e = d["v0j_eligible"].fillna(False).astype(bool)
    forest0 = d["skogsmark_ha_n"].eq(0)
    return {
        "S70_NOFOREST": e & d["aker_share_frac"].ge(0.70) & forest0,
        "S50_ALL": e & d["aker_share_frac"].ge(0.50),
        "ALL_ARABLE": e,
    }


def nuisance_specs(df: pd.DataFrame):
    """Choose nuisance component parameterization from support in this sample."""
    specs = []

    def add(name, qty, terms):
        active = int(num(df[qty]).fillna(0).gt(0).sum())
        if active >= MIN_COMPONENT_ACTIVE:
            specs.append((name, qty, terms, COMPONENT_SEEDS[name], active))

    n_house = int(df["smahus_kvm_total_n"].gt(0).sum())
    add(
        "house", "smahus_kvm_total_n",
        ["year_centered", "lat_centered", "lon_centered"]
        if n_house >= MIN_GEO_COMPONENT_ACTIVE else [],
    )

    n_econ = int(df["ekonomibyggnad_kvm_total_n"].gt(0).sum())
    add("econ", "ekonomibyggnad_kvm_total_n", ["year_centered"] if n_econ >= 50 else [])

    n_past = int(df["betesmark_ha_n"].gt(0).sum())
    add("pasture", "betesmark_ha_n", ["year_centered"] if n_past >= 50 else [])

    n_for = int(df["skogsmark_ha_n"].gt(0).sum())
    if n_for >= MIN_COMPONENT_ACTIVE:
        terms = ["year_centered", "lat_centered", "lon_centered"] if n_for >= MIN_GEO_COMPONENT_ACTIVE else []
        add("forest", "skogsmark_ha_n", terms)

    add("imped", "skogsimpediment_ha_n", [])
    add("other", "other_ha", [])
    return specs


def param_names(arable_terms, nuis):
    names = ["arable_log_rate0"] + [f"arable_{t}" for t in arable_terms]
    for name, qty, terms, seed, active in nuis:
        names += [f"{name}_log_rate0"] + [f"{name}_{t}" for t in terms]
    return names


def initial_params(arable_terms, nuis):
    p = [math.log(ARABLE_SEED)] + [0.0] * len(arable_terms)
    for name, qty, terms, seed, active in nuis:
        p += [math.log(seed)] + [0.0] * len(terms)
    return np.asarray(p, float)


def parameter_bounds(arable_terms, nuis):
    names = param_names(arable_terms, nuis)
    lo = np.full(len(names), -3.0, float)
    hi = np.full(len(names), +3.0, float)
    for i, n in enumerate(names):
        if n.endswith("log_rate0"):
            lo[i] = math.log(10.0)
            hi[i] = math.log(50_000_000.0)
    return lo, hi


def predict_components(df, p, arable_terms, nuis):
    n = len(df)
    i = 0

    eta = np.full(n, p[i], float)
    i += 1
    for t in arable_terms:
        eta += p[i] * num(df[t]).to_numpy(float)
        i += 1
    arable_rate = np.exp(np.clip(eta, -20.0, 25.0))
    arable = num(df["akermark_ha_n"]).to_numpy(float) * arable_rate

    total = arable.copy()
    comps = {"arable": arable}
    rates = {"arable_rate_per_ha": arable_rate}

    for name, qty, terms, seed, active in nuis:
        eta = np.full(n, p[i], float)
        i += 1
        for t in terms:
            eta += p[i] * num(df[t]).to_numpy(float)
            i += 1
        rate = np.exp(np.clip(eta, -20.0, 25.0))
        value = num(df[qty]).fillna(0).to_numpy(float) * rate
        total += value
        comps[name] = value
        rates[name + "_rate"] = rate

    return total, comps, rates


def complete(df, arable_terms, nuis):
    cols = ["kopeskilling_kr_n", "akermark_ha_n", *arable_terms]
    for name, qty, terms, seed, active in nuis:
        cols += [qty, *terms]
    cols = list(dict.fromkeys(cols))
    mask = pd.Series(True, index=df.index)
    for c in cols:
        if c not in df.columns:
            return df.iloc[0:0].copy()
        mask &= num(df[c]).notna()
    mask &= num(df["kopeskilling_kr_n"]).gt(0)
    mask &= num(df["akermark_ha_n"]).gt(0)
    return df.loc[mask].copy()


def fit_model(df, arable_terms, nuis=None, p0=None, max_nfev=800):
    if nuis is None:
        nuis = nuisance_specs(df)
    x = complete(df, arable_terms, nuis).reset_index(drop=True)
    if len(x) < max(30, len(param_names(arable_terms, nuis)) + 10):
        return None

    y = num(x["kopeskilling_kr_n"]).to_numpy(float)
    if p0 is None or len(p0) != len(param_names(arable_terms, nuis)):
        p0 = initial_params(arable_terms, nuis)
    lo, hi = parameter_bounds(arable_terms, nuis)

    def residual(p):
        pred, _, _ = predict_components(x, p, arable_terms, nuis)
        return np.log(np.maximum(pred, 1.0)) - np.log(y)

    res = least_squares(
        residual,
        p0,
        bounds=(lo, hi),
        loss="soft_l1",
        f_scale=0.20,
        max_nfev=max_nfev,
        xtol=1e-8,
        ftol=1e-8,
        gtol=1e-8,
    )

    pred, comps, rates = predict_components(x, res.x, arable_terms, nuis)
    return {
        "data": x,
        "params": res.x,
        "names": param_names(arable_terms, nuis),
        "nuis": nuis,
        "success": bool(res.success),
        "nfev": int(res.nfev),
        "train_r2_log_total": r2_log(y, pred),
        "train_median_ape_total": medape(y, pred),
        "pred": pred,
        "components": comps,
        "rates": rates,
    }


def spatial_cv10(df, arable_terms):
    """Same 10 km sale cell stays in one deterministic fold."""
    nuis = nuisance_specs(df)
    full = fit_model(df, arable_terms, nuis=nuis)
    if full is None:
        return None

    x = full["data"].copy().reset_index(drop=True)
    y = num(x["kopeskilling_kr_n"]).to_numpy(float)
    pred = np.full(len(x), np.nan, float)

    folds = sorted(x["spatial_fold10"].dropna().astype(int).unique().tolist())
    for f in folds:
        train = x.loc[x["spatial_fold10"].ne(f)].copy()
        test_idx = x.index[x["spatial_fold10"].eq(f)].to_numpy()
        if len(test_idx) == 0:
            continue
        fit = fit_model(
            train,
            arable_terms,
            nuis=nuis,
            p0=full["params"],
            max_nfev=250,
        )
        if fit is None:
            continue
        test = x.loc[test_idx]
        pp, _, _ = predict_components(test, fit["params"], arable_terms, nuis)
        pred[test_idx] = pp

    ok = np.isfinite(pred)
    anchor = x["anchor_strict"].fillna(False).astype(bool).to_numpy() & ok
    return {
        "full": full,
        "data": x,
        "cv_pred": pred,
        "cv_n": int(ok.sum()),
        "cv10_r2_log_total": r2_log(y[ok], pred[ok]),
        "cv10_median_ape_total": medape(y[ok], pred[ok]),
        "anchor_n": int(anchor.sum()),
        "anchor_cv10_r2_log_total": r2_log(y[anchor], pred[anchor]) if anchor.sum() >= 5 else np.nan,
        "anchor_cv10_median_ape_total": medape(y[anchor], pred[anchor]) if anchor.sum() else np.nan,
    }


def fit_ladder(d: pd.DataFrame, outdir: Path):
    rows = []
    coef_rows = []
    incr_rows = []
    prediction_frames = []
    component_rows = []

    samples = sample_masks(d)
    for sample, mask in samples.items():
        x = d.loc[mask].copy().reset_index(drop=True)
        print(f"\n[{sample}] n={len(x):,}; strict anchors={int(x['anchor_strict'].sum()):,}")

        specs = [
            ("BASE", ARABLE_BASE),
            ("BASE_BESK", ARABLE_BESK),
            ("BASE_BESK_DRAIN", ARABLE_DRAIN),
        ]
        results = {}

        for label, terms in specs:
            print(f"  fitting {label} ...", flush=True)
            r = spatial_cv10(x, terms)
            if r is None:
                continue
            results[label] = r
            full = r["full"]
            rows.append({
                "sample": sample,
                "model": label,
                "n": len(full["data"]),
                "n_params": len(full["params"]),
                "train_r2_log_total": full["train_r2_log_total"],
                "cv10_r2_log_total": r["cv10_r2_log_total"],
                "train_median_ape_total": full["train_median_ape_total"],
                "cv10_median_ape_total": r["cv10_median_ape_total"],
                "anchor_n": r["anchor_n"],
                "anchor_cv10_r2_log_total": r["anchor_cv10_r2_log_total"],
                "anchor_cv10_median_ape_total": r["anchor_cv10_median_ape_total"],
            })
            for nm, val in zip(full["names"], full["params"]):
                effect = np.nan
                if nm.startswith("arable_") and not nm.endswith("log_rate0"):
                    effect = 100.0 * (math.exp(float(val)) - 1.0)
                coef_rows.append({
                    "sample": sample,
                    "model": label,
                    "term": nm,
                    "coefficient": float(val),
                    "multiplicative_effect_pct_per_unit": effect,
                })

        for base, aug in [("BASE", "BASE_BESK"), ("BASE_BESK", "BASE_BESK_DRAIN")]:
            if base in results and aug in results:
                b, a = results[base], results[aug]
                incr_rows.append({
                    "sample": sample,
                    "baseline": base,
                    "augmented": aug,
                    "n": len(a["full"]["data"]),
                    "baseline_cv10_r2": b["cv10_r2_log_total"],
                    "augmented_cv10_r2": a["cv10_r2_log_total"],
                    "delta_cv10_r2": a["cv10_r2_log_total"] - b["cv10_r2_log_total"],
                    "baseline_cv10_median_ape": b["cv10_median_ape_total"],
                    "augmented_cv10_median_ape": a["cv10_median_ape_total"],
                })

        ferr = x.loc[num(x.get(FERRARI, pd.Series(np.nan, index=x.index))).notna()].copy()
        if len(ferr) >= 80:
            base_label = "BASE_BESK_DRAIN_sameFerrariRows"
            aug_label = "BASE_BESK_DRAIN_FERRARI"
            print(f"  fitting Ferrari same-row pair n={len(ferr):,} ...", flush=True)
            b = spatial_cv10(ferr, ARABLE_DRAIN)
            a = spatial_cv10(ferr, ARABLE_DRAIN + [FERRARI])
            if b is not None and a is not None:
                for label, r in [(base_label, b), (aug_label, a)]:
                    full = r["full"]
                    rows.append({
                        "sample": sample,
                        "model": label,
                        "n": len(full["data"]),
                        "n_params": len(full["params"]),
                        "train_r2_log_total": full["train_r2_log_total"],
                        "cv10_r2_log_total": r["cv10_r2_log_total"],
                        "train_median_ape_total": full["train_median_ape_total"],
                        "cv10_median_ape_total": r["cv10_median_ape_total"],
                        "anchor_n": r["anchor_n"],
                        "anchor_cv10_r2_log_total": r["anchor_cv10_r2_log_total"],
                        "anchor_cv10_median_ape_total": r["anchor_cv10_median_ape_total"],
                    })
                    for nm, val in zip(full["names"], full["params"]):
                        effect = np.nan
                        if nm.startswith("arable_") and not nm.endswith("log_rate0"):
                            effect = 100.0 * (math.exp(float(val)) - 1.0)
                        coef_rows.append({
                            "sample": sample,
                            "model": label,
                            "term": nm,
                            "coefficient": float(val),
                            "multiplicative_effect_pct_per_unit": effect,
                        })
                incr_rows.append({
                    "sample": sample,
                    "baseline": base_label,
                    "augmented": aug_label,
                    "n": len(a["full"]["data"]),
                    "baseline_cv10_r2": b["cv10_r2_log_total"],
                    "augmented_cv10_r2": a["cv10_r2_log_total"],
                    "delta_cv10_r2": a["cv10_r2_log_total"] - b["cv10_r2_log_total"],
                    "baseline_cv10_median_ape": b["cv10_median_ape_total"],
                    "augmented_cv10_median_ape": a["cv10_median_ape_total"],
                })

        if sample == "S70_NOFOREST" and "BASE_BESK_DRAIN" in results:
            r = results["BASE_BESK_DRAIN"]
            full = r["full"]
            q = full["data"].copy()
            q["v0j_cv10_pred_total_kr"] = r["cv_pred"]
            q["v0j_cv10_observed_to_pred_ratio"] = num(q["kopeskilling_kr_n"]) / q["v0j_cv10_pred_total_kr"]
            total, comps, rates = predict_components(q, full["params"], ARABLE_DRAIN, full["nuis"])
            q["v0j_fullfit_pred_total_kr"] = total
            for name, val in comps.items():
                q[f"v0j_fullfit_{name}_value_kr"] = val
                q[f"v0j_fullfit_{name}_share_pct"] = 100.0 * val / total
            for name, val in rates.items():
                q[f"v0j_fullfit_{name}"] = val
            prediction_frames.append(q)

            for name, val in comps.items():
                share = np.asarray(val, float) / np.asarray(total, float)
                component_rows.append({
                    "sample": sample,
                    "model": "BASE_BESK_DRAIN",
                    "component": name,
                    "n_nonzero": int(np.sum(np.asarray(val) > 0)),
                    "median_value_kr": float(np.median(np.asarray(val))),
                    "median_share_pct": float(100.0 * np.median(share)),
                    "p90_share_pct": float(100.0 * np.percentile(share, 90)),
                })

    comp = pd.DataFrame(rows)
    coef = pd.DataFrame(coef_rows)
    inc = pd.DataFrame(incr_rows)
    pred = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    cs = pd.DataFrame(component_rows)

    comp.to_csv(outdir / "v0j_model_comparison.csv", index=False, encoding="utf-8-sig")
    coef.to_csv(outdir / "v0j_model_coefficients.csv", index=False, encoding="utf-8-sig")
    inc.to_csv(outdir / "v0j_incremental_tests.csv", index=False, encoding="utf-8-sig")
    pred.to_csv(outdir / "v0j_primary_predictions.csv", index=False, encoding="utf-8-sig")
    cs.to_csv(outdir / "v0j_component_summary.csv", index=False, encoding="utf-8-sig")
    return comp, coef, inc, pred, cs


def write_report(source: Path, d: pd.DataFrame, comp, coef, inc, outdir: Path):
    masks = sample_masks(d)
    lines = [
        "ÅkerSync Value Regression v0j — anchored additive property decomposition",
        "=" * 88,
        f"Feature source: {source}",
        "",
        "TARGET / MODEL",
        "Observed purchase price in SEK. Tax-assessed value is not used as target or predictor.",
        "P_total = positive arable + house + economic-building + pasture + forest + impediment + other components.",
        "Arable beskaffenhet and drainage act only on the arable SEK/ha component.",
        "",
        "VALIDATION",
        "Deterministic 10-fold spatial-group CV; all sales in the same 10 km cell stay in one fold.",
        "Metrics are computed on log(total purchase price) plus median absolute percentage error.",
        "Strict-anchor rows are reported separately inside the primary held-out predictions.",
        "",
        "DRAINAGE CODING",
        "Reference = satisfactory_other.",
        "Separate arable effects: unsatisfactory; legacy_system_tiled; missing/other/mixed.",
        "The legacy drainage field is noisy administrative information, not drainage ground truth.",
        "",
        "SAMPLES",
    ]
    for name, mask in masks.items():
        x = d.loc[mask]
        lines.append(
            f"  {name}: n={len(x)}, strict anchors={int(x['anchor_strict'].sum())}, "
            f"Ferrari={int(num(x.get(FERRARI, pd.Series(np.nan, index=x.index))).notna().sum())}"
        )

    if len(comp):
        lines += ["", "MODEL LADDER — spatial CV"]
        for sample in comp["sample"].drop_duplicates():
            q = comp.loc[comp["sample"].eq(sample)].sort_values("cv10_r2_log_total", ascending=False)
            for _, r in q.iterrows():
                lines.append(
                    f"  {sample} / {r['model']}: n={int(r['n'])}, "
                    f"train R2={r['train_r2_log_total']:.4f}, "
                    f"CV10 R2={r['cv10_r2_log_total']:.4f}, "
                    f"CV10 medianAPE={r['cv10_median_ape_total']:.1f}%, "
                    f"anchors={int(r['anchor_n'])}"
                )

    if len(inc):
        lines += ["", "SAME-ROW INCREMENTAL TESTS"]
        for _, r in inc.iterrows():
            lines.append(
                f"  {r['sample']} / {r['baseline']} -> {r['augmented']}: "
                f"n={int(r['n'])}, CV10 {r['baseline_cv10_r2']:.4f} -> "
                f"{r['augmented_cv10_r2']:.4f}, delta={r['delta_cv10_r2']:+.4f}"
            )

    q = coef.loc[
        coef["sample"].eq("S70_NOFOREST")
        & coef["model"].eq("BASE_BESK_DRAIN")
        & coef["term"].str.startswith("arable_", na=False)
    ].copy()
    if len(q):
        lines += ["", "PRIMARY S70 ARABLE COEFFICIENTS — full fit, descriptive"]
        for _, r in q.iterrows():
            eff = r["multiplicative_effect_pct_per_unit"]
            if pd.notna(eff):
                lines.append(f"  {r['term']}: beta={r['coefficient']:+.5f}, exp(beta)-1={eff:+.2f}% per unit")
            else:
                lines.append(f"  {r['term']}: {r['coefficient']:+.5f}")

    lines += [
        "",
        "GUARDRAILS",
        "- This is an identified-component experiment, not cadastral appraisal truth.",
        "- Building and forest values are nuisance models; unobserved condition/rights can remain in residuals.",
        "- Beskaffenhet is an administrative production/cultivation quality factor, not laboratory soil chemistry.",
        "- Drainage is retained because it may carry price information, but ATL missingness and legacy wording are substantial.",
        "- FerrariScore uses modeled DSMS texture and remains a diagnostic modern-soil feature.",
        "- A better total-price R2 can partly come from explaining houses/area mix; inspect strict-anchor metrics before claiming better arable valuation.",
    ]
    text = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(text, encoding="utf-8")
    print("\n" + text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="v0i kt_regime_features.csv or v0h expanded_kt_features.csv")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    source = find_input(root, args.input)
    outdir = root / "data" / "derived" / "value_regression_v0j_additive"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("ÅkerSync · Value Regression v0j · anchored additive property decomposition")
    print("=" * 100)
    print("Input:", source)
    print("Output:", outdir)
    print("Tax-assessed value is NOT used in the price model.")
    print("Primary additions: ATL beskaffenhet + categorical drainage on the arable component.")
    print()

    raw = pd.read_csv(source, encoding="utf-8-sig")
    d = prepare(raw)
    d.to_csv(outdir / "v0j_features.csv", index=False, encoding="utf-8-sig")

    comp, coef, inc, pred, cs = fit_ladder(d, outdir)
    write_report(source, d, comp, coef, inc, outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
