#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0g — modern soil surprise vs market price.

Goal
----
Test whether modern class-10-like soil information is already reflected in
observed farmland prices, after the historic 1971 class and simple market
geography have been separated.

This step deliberately reuses the LOCKED outputs from v0f:
  * value_regression_v0f_class1971/class1971_main_sample.csv
  * value_regression_v0f_class1971/multiblock_members.csv

No sale geometry is re-selected here. Soil is sampled over the same reconstructed
blocks using value_transaction_soil.py.

Modern soil score
-----------------
The class-10 reference is read from the already-computed agri-class v0c
``skifte_ferrari_scores.csv``. For each sale, class-10 reference skiften in the
same 10x10 km cell are excluded before the transaction is scored, mirroring the
spatial holdout logic used by the original Ferrari experiment.

Transaction FerrariScore combines:
  1. distance of clay+silt mean from the class-10 reference cloud; and
  2. within-transaction texture heterogeneity.

The transaction soil helper reports sqrt(sum(sd^2)) while agri v0c used
sqrt(mean(sd^2)); transaction heterogeneity is therefore divided by sqrt(3)
before comparison so the scales are identical.

Primary pricing question
------------------------
Two simple market baselines are carried forward from v0f:
  MARKET_YLL = year + latitude + longitude  (best v0f LOO among tested ladder)
  MARKET_G1  = year + log(area) + latitude + longitude (economic sensitivity)

Then test whether frozen modern soil information adds out-of-sample price signal.
The same-row exact leave-one-out R2 is the primary metric.

Interpretation guardrail
------------------------
A positive soil surprise + negative price residual is a *candidate pricing
anomaly*, not proof of arbitrage. Drainage, climate, parcel identity, local buyer
competition, buildings/rights and other omitted factors can rationally explain it.
"""
from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

import value_transaction_soil as txsoil

CLASS = "class1971_tx_mean_aw"
FERRARI = "tx_ferrari_score"
CENTER_SCORE = "tx_texture_center_score"
HOMOG_SCORE = "tx_homogeneity_score"
HET = "tx_texture_heterogeneity_rms_v0c_scale"
GRID_M = 10_000.0
REGULARIZATION = 0.20
MIN_REF_N = 30

MARKET_YLL = ["year_centered", "lat_centered", "lon_centered"]
MARKET_G1 = ["year_centered", "log_area_20", "lat_centered", "lon_centered"]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def num(x):
    return pd.to_numeric(x, errors="coerce")


def bool_series(s: pd.Series) -> pd.Series:
    # Avoid pandas FutureWarning / silent object downcast dependency.
    return s.map(lambda x: bool(x) if pd.notna(x) else False).astype(bool)


def choose_csv(title: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    p = filedialog.askopenfilename(title=title, filetypes=[("CSV", "*.csv"), ("Alla filer", "*.*")])
    root.destroy()
    return p or None


def find_ferrari_reference(root: Path, explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        root.parent / "AkerSyncClass910" / "data" / "derived" / "agri_class5_10_v0c_ferrari" / "skifte_ferrari_scores.csv",
        Path(r"C:\AkerSyncClass910\data\derived\agri_class5_10_v0c_ferrari\skifte_ferrari_scores.csv"),
        root / "data" / "derived" / "agri_class5_10_v0c_ferrari" / "skifte_ferrari_scores.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    chosen = choose_csv("Välj skifte_ferrari_scores.csv från ÅkerSyncClass910 v0c")
    if chosen:
        return Path(chosen)
    raise FileNotFoundError(
        "Hittar inte skifte_ferrari_scores.csv från agri-class v0c. "
        "Kör v0c i C:\\AkerSyncClass910 eller välj filen när dialogen öppnas."
    )


def safe_scale(x):
    x = np.asarray(x, float)
    med = np.nanmedian(x, axis=0)
    mad = np.nanmedian(np.abs(x - med), axis=0) * 1.4826
    std = np.nanstd(x, axis=0, ddof=0)
    scale = np.where(np.isfinite(mad) & (mad > 1e-9), mad, std)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return med, scale


def build_reference(train: pd.DataFrame):
    X = train[["clay_mean_pct", "silt_mean_pct"]].to_numpy(float)
    center, scale = safe_scale(X)
    Z = (X - center) / scale
    cov = np.cov(Z, rowvar=False, ddof=1) if len(Z) >= 3 else np.eye(2)
    if cov.shape != (2, 2) or not np.all(np.isfinite(cov)):
        cov = np.eye(2)
    cov = (1.0 - REGULARIZATION) * cov + REGULARIZATION * np.eye(2)
    inv_cov = np.linalg.pinv(cov)
    d_train = np.sqrt(np.einsum("ij,jk,ik->i", Z, inv_cov, Z))
    h_train = num(train["texture_heterogeneity_rms"]).to_numpy(float)
    return {
        "center": center,
        "scale": scale,
        "inv_cov": inv_cov,
        "d_train": d_train[np.isfinite(d_train)],
        "h_train": h_train[np.isfinite(h_train)],
        "n": len(train),
    }


def survival_score(ref_values, value):
    a = np.asarray(ref_values, float)
    a = a[np.isfinite(a)]
    if not len(a) or not np.isfinite(value):
        return np.nan
    gt = np.sum(a > value)
    eq = np.sum(np.isclose(a, value, rtol=1e-10, atol=1e-12))
    return float(100.0 * (gt + 0.5 * eq) / len(a))


def score_one(clay, silt, heterogeneity, ref):
    if not all(np.isfinite(x) for x in (clay, silt, heterogeneity)):
        return (np.nan,) * 4
    x = np.array([clay, silt], float)
    z = (x - ref["center"]) / ref["scale"]
    dist = float(np.sqrt(z @ ref["inv_cov"] @ z))
    cs = survival_score(ref["d_train"], dist)
    hs = survival_score(ref["h_train"], heterogeneity)
    fs = float(math.sqrt(max(cs, 0.0) * max(hs, 0.0))) if np.isfinite(cs) and np.isfinite(hs) else np.nan
    return dist, cs, hs, fs


def prepare_class10_reference(path: Path) -> pd.DataFrame:
    r = pd.read_csv(path, encoding="utf-8-sig")
    needed = [
        "historic_class", "clay_mean_pct", "silt_mean_pct",
        "texture_heterogeneity_rms", "spatial_cell",
    ]
    missing = [c for c in needed if c not in r.columns]
    if missing:
        raise RuntimeError("Ferrari-reference saknar kolumner: " + ", ".join(missing))
    if "score_eligible" in r.columns:
        elig = bool_series(r["score_eligible"])
    else:
        elig = pd.Series(True, index=r.index)
    q = r.loc[elig & num(r["historic_class"]).eq(10)].copy()
    for c in ["clay_mean_pct", "silt_mean_pct", "texture_heterogeneity_rms"]:
        q[c] = num(q[c])
    q = q.dropna(subset=["clay_mean_pct", "silt_mean_pct", "texture_heterogeneity_rms", "spatial_cell"])
    if len(q) < 100:
        raise RuntimeError(f"För få class-10 reference skiften: {len(q)}")
    return q.reset_index(drop=True)


def add_sale_spatial_cell(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    pts = gpd.GeoSeries(gpd.points_from_xy(num(out["lon_n"]), num(out["lat_n"])), crs=4326).to_crs(3006)
    out["sale_x_3006"] = pts.x.to_numpy(float)
    out["sale_y_3006"] = pts.y.to_numpy(float)
    gx = np.floor(out["sale_x_3006"] / GRID_M).astype("Int64")
    gy = np.floor(out["sale_y_3006"] / GRID_M).astype("Int64")
    out["sale_spatial_cell"] = gx.astype(str) + "_" + gy.astype(str)
    return out


def add_transaction_ferrari(df: pd.DataFrame, ref10: pd.DataFrame) -> pd.DataFrame:
    out = add_sale_spatial_cell(df)
    out[HET] = num(out["tx_soil_texture_pixel_rms_sd_pct"]) / math.sqrt(3.0)
    for c in ["tx_texture_center_distance", CENTER_SCORE, HOMOG_SCORE, FERRARI, "tx_ferrari_reference_n"]:
        out[c] = np.nan
    out["tx_ferrari_reference_mode"] = ""

    cache = {}
    for idx, r in out.iterrows():
        clay = float(num(pd.Series([r.get("tx_soil_clay_mean_pct")])).iloc[0])
        silt = float(num(pd.Series([r.get("tx_soil_silt_mean_pct")])).iloc[0])
        h = float(num(pd.Series([r.get(HET)])).iloc[0])
        if not all(np.isfinite(x) for x in (clay, silt, h)):
            continue
        cell = str(r["sale_spatial_cell"])
        if cell not in cache:
            train = ref10[ref10["spatial_cell"].astype(str).ne(cell)].copy()
            mode = "leave_10km_cell_out"
            if len(train) < MIN_REF_N:
                train = ref10.copy()
                mode = "fallback_all_class10"
            cache[cell] = (build_reference(train), mode)
        ref, mode = cache[cell]
        dist, cs, hs, fs = score_one(clay, silt, h, ref)
        out.at[idx, "tx_texture_center_distance"] = dist
        out.at[idx, CENTER_SCORE] = cs
        out.at[idx, HOMOG_SCORE] = hs
        out.at[idx, FERRARI] = fs
        out.at[idx, "tx_ferrari_reference_n"] = ref["n"]
        out.at[idx, "tx_ferrari_reference_mode"] = mode
    return out


def complete(df: pd.DataFrame, ycol: str, terms: list[str]) -> pd.DataFrame:
    cols = [ycol] + terms
    if any(c not in df.columns for c in cols):
        return df.iloc[0:0].copy()
    mask = np.ones(len(df), dtype=bool)
    for c in cols:
        mask &= num(df[c]).notna().to_numpy()
    return df.loc[mask].copy().reset_index(drop=True)


def design(df: pd.DataFrame, ycol: str, terms: list[str]):
    y = num(df[ycol]).to_numpy(float)
    X = np.column_stack([np.ones(len(df), float)] + [num(df[t]).to_numpy(float) for t in terms])
    return X, y, ["intercept"] + terms


def fit_loo(v0a, df: pd.DataFrame, ycol: str, terms: list[str]):
    d = complete(df, ycol, terms)
    min_n = max(12, len(terms) + 5)
    if len(d) < min_n:
        return None
    X, y, names = design(d, ycol, terms)
    if np.linalg.matrix_rank(X) < X.shape[1]:
        return None
    beta, pred, train_r2, adj, rank, se, pv = v0a.fit_ols(X, y)
    loo = v0a.loo_predictions(X, y)
    return {
        "data": d, "y": y, "loo": loo, "names": names, "beta": beta,
        "se": se, "p_value": pv, "train_r2": train_r2, "adj_r2": adj,
        "loo_r2": v0a.r2_score(y, loo),
        "median_ape": 100.0 * float(np.median(np.abs(np.exp(loo - y) - 1.0))),
    }


def add_soil_surprises(v0a, df: pd.DataFrame, outdir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    specs = [
        ("SOIL_CLASS", [CLASS], "soil_surprise_class"),
        ("SOIL_CLASS_GEO", [CLASS, "lat_centered", "lon_centered"], "soil_surprise_class_geo"),
    ]
    rows = []
    for label, terms, col in specs:
        r = fit_loo(v0a, out, FERRARI, terms)
        out[col] = np.nan
        out[col + "_expected"] = np.nan
        if r is None:
            continue
        d = r["data"]
        # Map by stable sale_id, not positional index in the parent dataframe.
        pred_map = dict(zip(d["sale_id"].astype(str), r["loo"]))
        obs_map = dict(zip(d["sale_id"].astype(str), r["y"]))
        for i, sid in out["sale_id"].astype(str).items():
            if sid in pred_map:
                out.at[i, col + "_expected"] = pred_map[sid]
                out.at[i, col] = obs_map[sid] - pred_map[sid]
        rows.append({
            "model": label,
            "terms": " + ".join(terms),
            "n": len(d),
            "loo_r2": r["loo_r2"],
            "train_r2": r["train_r2"],
        })
    sm = pd.DataFrame(rows)
    sm.to_csv(outdir / "soil_surprise_models.csv", index=False, encoding="utf-8-sig")
    return out, sm


def run_price_models(v0a, df: pd.DataFrame, outdir: Path):
    specs = [
        ("MARKET_YLL", MARKET_YLL),
        ("MARKET_YLL_PLUS_FERRARI", MARKET_YLL + [FERRARI]),
        ("MARKET_YLL_PLUS_SOIL_SURPRISE", MARKET_YLL + ["soil_surprise_class"]),
        ("MARKET_G1", MARKET_G1),
        ("MARKET_G1_PLUS_FERRARI", MARKET_G1 + [FERRARI]),
        ("MARKET_G1_PLUS_SOIL_SURPRISE", MARKET_G1 + ["soil_surprise_class"]),
    ]
    rows, coef_rows = [], []
    fits = {}
    for label, terms in specs:
        r = fit_loo(v0a, df, "log_kr_per_aker_ha", terms)
        if r is None:
            continue
        fits[label] = r
        rows.append({
            "model": label,
            "terms": " + ".join(terms),
            "n": len(r["data"]),
            "loo_r2": r["loo_r2"],
            "train_r2": r["train_r2"],
            "adj_r2": r["adj_r2"],
            "median_abs_pct_error_loo": r["median_ape"],
        })
        for nm, b, se, p in zip(r["names"], r["beta"], r["se"], r["p_value"]):
            coef_rows.append({"model": label, "term": nm, "coefficient": b, "std_error": se, "p_value": p})
    comp = pd.DataFrame(rows)
    if len(comp):
        comp = comp.sort_values("loo_r2", ascending=False)
    comp.to_csv(outdir / "price_model_comparison.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(outdir / "price_model_coefficients.csv", index=False, encoding="utf-8-sig")

    nested = []
    for base, aug in [
        ("MARKET_YLL", "MARKET_YLL_PLUS_FERRARI"),
        ("MARKET_YLL", "MARKET_YLL_PLUS_SOIL_SURPRISE"),
        ("MARKET_G1", "MARKET_G1_PLUS_FERRARI"),
        ("MARKET_G1", "MARKET_G1_PLUS_SOIL_SURPRISE"),
    ]:
        if base not in fits or aug not in fits:
            continue
        # Refit baseline on exact augmented rows for fair delta.
        augdata = fits[aug]["data"]
        baseterms = MARKET_YLL if base == "MARKET_YLL" else MARKET_G1
        b = fit_loo(v0a, augdata, "log_kr_per_aker_ha", baseterms)
        a = fits[aug]
        if b is None or len(b["data"]) != len(a["data"]):
            continue
        nested.append({
            "baseline": base,
            "augmented": aug,
            "n": len(a["data"]),
            "baseline_loo_r2_same_n": b["loo_r2"],
            "augmented_loo_r2": a["loo_r2"],
            "delta_loo_r2": a["loo_r2"] - b["loo_r2"],
            "baseline_median_ape": b["median_ape"],
            "augmented_median_ape": a["median_ape"],
        })
    nest = pd.DataFrame(nested)
    nest.to_csv(outdir / "price_incremental_soil_tests.csv", index=False, encoding="utf-8-sig")
    return fits, comp, nest


def attach_price_residual(df: pd.DataFrame, fit, prefix: str) -> pd.DataFrame:
    out = df.copy()
    out[prefix + "_loo_pred_log"] = np.nan
    out[prefix + "_loo_log_residual"] = np.nan
    out[prefix + "_observed_to_pred_ratio"] = np.nan
    if fit is None:
        return out
    d = fit["data"]
    for sid, y, pred in zip(d["sale_id"].astype(str), fit["y"], fit["loo"]):
        mask = out["sale_id"].astype(str).eq(sid)
        out.loc[mask, prefix + "_loo_pred_log"] = float(pred)
        out.loc[mask, prefix + "_loo_log_residual"] = float(y - pred)
        out.loc[mask, prefix + "_observed_to_pred_ratio"] = float(np.exp(y - pred))
    return out


def spearman_descriptive(a, b):
    x = pd.DataFrame({"a": num(a), "b": num(b)}).dropna()
    if len(x) < 5:
        return np.nan, len(x)
    return float(x["a"].rank().corr(x["b"].rank())), len(x)


def candidate_ranking(df: pd.DataFrame, outdir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = df.copy()
    soil = num(d["soil_surprise_class"])
    ratio = num(d["market_yll_observed_to_pred_ratio"])
    valid = soil.notna() & ratio.notna()
    v = d.loc[valid].copy()
    if v.empty:
        v.to_csv(outdir / "pricing_soil_candidate_ranking.csv", index=False, encoding="utf-8-sig")
        return v, pd.DataFrame()

    q_soil25, q_soil75 = num(v["soil_surprise_class"]).quantile([0.25, 0.75])
    q_price25, q_price75 = num(v["market_yll_observed_to_pred_ratio"]).quantile([0.25, 0.75])
    v["candidate_group"] = "middle"
    v.loc[(num(v["soil_surprise_class"]) >= q_soil75) & (num(v["market_yll_observed_to_pred_ratio"]) <= q_price25), "candidate_group"] = "high_soil_low_price"
    v.loc[(num(v["soil_surprise_class"]) <= q_soil25) & (num(v["market_yll_observed_to_pred_ratio"]) >= q_price75), "candidate_group"] = "low_soil_high_price"
    v.loc[(num(v["soil_surprise_class"]) >= q_soil75) & (num(v["market_yll_observed_to_pred_ratio"]) >= q_price75), "candidate_group"] = "high_soil_high_price"
    v.loc[(num(v["soil_surprise_class"]) <= q_soil25) & (num(v["market_yll_observed_to_pred_ratio"]) <= q_price25), "candidate_group"] = "low_soil_low_price"

    # Diagnostic ranking only: large positive soil surprise + cheap versus local market.
    soil_z = (num(v["soil_surprise_class"]) - num(v["soil_surprise_class"]).median()) / max(1e-9, num(v["soil_surprise_class"]).mad() if hasattr(num(v["soil_surprise_class"]), 'mad') else num(v["soil_surprise_class"]).std())
    # pandas Series.mad was removed in recent versions; robust fallback below.
    med = num(v["soil_surprise_class"]).median()
    mad = (num(v["soil_surprise_class"]) - med).abs().median() * 1.4826
    if not np.isfinite(mad) or mad <= 1e-9:
        mad = num(v["soil_surprise_class"]).std(ddof=0)
    soil_z = (num(v["soil_surprise_class"]) - med) / (mad if np.isfinite(mad) and mad > 1e-9 else 1.0)
    price_adv = -np.log(num(v["market_yll_observed_to_pred_ratio"]))
    pmed = price_adv.median()
    pmad = (price_adv - pmed).abs().median() * 1.4826
    if not np.isfinite(pmad) or pmad <= 1e-9:
        pmad = price_adv.std(ddof=0)
    price_z = (price_adv - pmed) / (pmad if np.isfinite(pmad) and pmad > 1e-9 else 1.0)
    v["candidate_underpricing_index"] = soil_z + price_z

    keep_front = [
        "sale_id", "datum", "fastighetsbeteckningar", "lat_n", "lon_n",
        "akermark_ha_n", "kr_per_aker_ha", CLASS, FERRARI,
        "soil_surprise_class", "soil_surprise_class_geo",
        "market_yll_observed_to_pred_ratio", "market_g1_observed_to_pred_ratio",
        "candidate_group", "candidate_underpricing_index",
    ]
    cols = [c for c in keep_front if c in v.columns] + [c for c in v.columns if c not in keep_front]
    v = v[cols].sort_values("candidate_underpricing_index", ascending=False)
    v.to_csv(outdir / "pricing_soil_candidate_ranking.csv", index=False, encoding="utf-8-sig")

    rho1, n1 = spearman_descriptive(v["soil_surprise_class"], v["market_yll_loo_log_residual"])
    rho2, n2 = spearman_descriptive(v[FERRARI], v["market_yll_loo_log_residual"])
    corr = pd.DataFrame([
        {"x": "soil_surprise_class", "y": "market_yll_price_residual", "n": n1, "spearman_rho": rho1},
        {"x": FERRARI, "y": "market_yll_price_residual", "n": n2, "spearman_rho": rho2},
    ])
    corr.to_csv(outdir / "soil_price_correlations.csv", index=False, encoding="utf-8-sig")
    return v, corr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--ferrari-reference", help="Path to agri v0c skifte_ferrari_scores.csv")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    v0a = load_module(root / "src" / "20_value_regression_v0a.py", "value_v0a")
    cfg = v0a.load_config(root / args.config)
    build = root / cfg.get("build_dir", "data/derived")
    v0f_dir = build / "value_regression_v0f_class1971"
    main_path = v0f_dir / "class1971_main_sample.csv"
    members_path = v0f_dir / "multiblock_members.csv"
    if not main_path.exists() or not members_path.exists():
        raise FileNotFoundError("v0f outputs saknas. Kör RUN_VALUE_REGRESSION_CLASS1971_V0F.bat först.")

    outdir = build / "value_regression_v0g_soil_price_surprise"
    outdir.mkdir(parents=True, exist_ok=True)
    ferrari_ref_path = find_ferrari_reference(root, args.ferrari_reference)

    print("=" * 98)
    print("ÅkerSync · Value Regression v0g · modern soil surprise vs market price")
    print("=" * 98)
    print("v0f main sample:", main_path)
    print("Ferrari reference:", ferrari_ref_path)
    print("Output:", outdir)
    print()

    main = pd.read_csv(main_path, encoding="utf-8-sig")
    members = pd.read_csv(members_path, encoding="utf-8-sig")
    print(f"Locked v0f class-eligible sales: {len(main):,}")

    print("[1/5] Sampling DSMS2025 over the already locked reconstructed sale blocks...")
    enriched, block_soil = txsoil.add_transaction_soil_features(main, members, cfg, "tx_recon_match_20pct")
    if len(block_soil):
        block_soil.to_csv(outdir / "transaction_soil_block_features.csv", index=False, encoding="utf-8-sig")

    print("[2/5] Building spatially-held-out class-10 reference from agri v0c...")
    ref10 = prepare_class10_reference(ferrari_ref_path)
    print(f"Eligible class-10 reference skiften: {len(ref10):,}")

    print("[3/5] Scoring transaction soil against the frozen class-10 domain...")
    enriched = add_transaction_ferrari(enriched, ref10)
    enriched, soil_models = add_soil_surprises(v0a, enriched, outdir)
    enriched.to_csv(outdir / "soil_price_features.csv", index=False, encoding="utf-8-sig")

    print("[4/5] Testing whether modern soil adds price signal beyond simple market geography...")
    fits, price_comp, nested = run_price_models(v0a, enriched, outdir)
    enriched = attach_price_residual(enriched, fits.get("MARKET_YLL"), "market_yll")
    enriched = attach_price_residual(enriched, fits.get("MARKET_G1"), "market_g1")

    print("[5/5] Crossing soil surprise with price residual...")
    ranking, corr = candidate_ranking(enriched, outdir)
    enriched.to_csv(outdir / "soil_price_cross_all.csv", index=False, encoding="utf-8-sig")

    nscore = int(num(enriched[FERRARI]).notna().sum())
    rho = float(corr.iloc[0]["spearman_rho"]) if len(corr) else np.nan
    n_under = int((ranking.get("candidate_group", pd.Series(dtype=str)) == "high_soil_low_price").sum()) if len(ranking) else 0
    n_over = int((ranking.get("candidate_group", pd.Series(dtype=str)) == "low_soil_high_price").sum()) if len(ranking) else 0

    lines = [
        "ÅkerSync Value Regression v0g — modern soil surprise vs market price",
        "=" * 86,
        f"Locked v0f sales: {len(main)}",
        f"Sales with transaction FerrariScore: {nscore}/{len(enriched)}",
        f"Class-10 reference skiften: {len(ref10)}",
        "",
        "QUESTION",
        "Does modern class-10-like soil quality carry pricing information beyond the old class / simple market geography?",
        "",
        "SOIL SURPRISE",
    ]
    for _, r in soil_models.iterrows():
        lines.append(f"  {r['model']}: n={int(r['n'])}, LOO R2 for FerrariScore={r['loo_r2']:.4f}")
    lines += ["", "PRICE MODELS"]
    for _, r in price_comp.iterrows():
        lines.append(
            f"  {r['model']}: n={int(r['n'])}, LOO R2={r['loo_r2']:.4f}, "
            f"medianAPE={r['median_abs_pct_error_loo']:.1f}%"
        )
    if len(nested):
        lines += ["", "INCREMENTAL MODERN-SOIL TESTS — exact same rows"]
        for _, r in nested.iterrows():
            lines.append(
                f"  {r['baseline']} -> {r['augmented']}: n={int(r['n'])}, "
                f"LOO {r['baseline_loo_r2_same_n']:.4f} -> {r['augmented_loo_r2']:.4f}, "
                f"delta={r['delta_loo_r2']:+.4f}"
            )
    lines += [
        "",
        "SOIL x PRICE DIAGNOSTIC",
        f"  Spearman(soil surprise vs MARKET_YLL price residual): {rho:+.3f}" if np.isfinite(rho) else "  Spearman: unavailable",
        f"  High-soil / low-price quadrant (P75/P25 diagnostic): {n_under}",
        f"  Low-soil / high-price quadrant (P25/P75 diagnostic): {n_over}",
        "",
        "INTERPRETATION",
        "- Positive soil surprise means the modern soil score is better than expected from 1971 class in a leave-one-out diagnostic.",
        "- Price ratio <1 means the sale was cheaper than its leave-one-out simple geographic market model predicted.",
        "- If soil surprise predicts price residual positively, the market appears to recognize at least part of the modern soil information.",
        "- If incremental LOO is near zero/negative and high-soil/low-price cases exist, that is consistent with possible information inefficiency, not proof of arbitrage.",
        "",
        "GUARDRAILS",
        "- n is small; no model fishing or naive significance claims.",
        "- Sale geometry is a reconstructed-block proxy, not cadastral ground truth.",
        "- DSMS2025 is modeled soil information, not direct soil sampling at sale time.",
        "- FerrariScore is frozen from the prior soil-only class-10 experiment; topography/hydrology/climate are not used to define it.",
        "- Local buyer competition, drainage, climate, parcel rights and other omitted factors can rationally explain price residuals.",
    ]
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
