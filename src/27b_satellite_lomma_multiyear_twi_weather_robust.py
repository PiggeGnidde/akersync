#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small robustness wrapper for step 27.

Fixes the categorical-window baseline in the descriptive weather regression.
When step 27 fits W2-W4 only, W1 is absent; the original helper still coded all
three remaining windows as dummies together with an intercept. NumPy can solve
that rank-deficient system, but individual coefficients are not identifiable.
This wrapper makes the first window present in each fit the explicit baseline.
The satellite selection, SCL QA and TWI analysis in step 27 are unchanged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_base():
    path = ROOT / "src" / "27_satellite_lomma_multiyear_twi_weather.py"
    spec = importlib.util.spec_from_file_location("akersync_multiyear27", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fixed_fit(df: pd.DataFrame, model_name: str, late_only: bool = False):
    x = df.copy()
    if late_only:
        x = x[x.window != "W1_early_april"].copy()
    needed = ["q5_minus_q1", "precip_30d_mm", "tmean_30d_c", "window", "year"]
    x = x.dropna(subset=needed).copy()
    if len(x) < 10:
        return pd.DataFrame(), {"model": model_name, "n": len(x), "r2": np.nan, "loyo_rmse": np.nan, "loyo_mae": np.nan}

    p_mean, p_sd = x.precip_30d_mm.mean(), x.precip_30d_mm.std(ddof=0)
    t_mean, t_sd = x.tmean_30d_c.mean(), x.tmean_30d_c.std(ddof=0)
    if p_sd <= 1e-12 or t_sd <= 1e-12:
        return pd.DataFrame(), {"model": model_name, "n": len(x), "r2": np.nan, "loyo_rmse": np.nan, "loyo_mae": np.nan}

    levels = sorted(x.window.astype(str).unique())
    baseline = levels[0]
    dummy_windows = levels[1:]

    def design(frame: pd.DataFrame, pm=p_mean, ps=p_sd, tm=t_mean, ts=t_sd):
        cols = [
            np.ones(len(frame)),
            (frame.precip_30d_mm.to_numpy(float) - pm) / ps,
            (frame.tmean_30d_c.to_numpy(float) - tm) / ts,
        ]
        names = ["intercept", "precip30_z", "tmean30_z"]
        arrw = frame.window.astype(str).to_numpy()
        for w in dummy_windows:
            cols.append((arrw == w).astype(float))
            names.append(f"window_{w}")
        return np.column_stack(cols), names

    X, names = design(x)
    y = x.q5_minus_q1.to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    sse = float(np.sum((y - pred) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else np.nan

    errs = []
    for yr in sorted(x.year.unique()):
        train = x[x.year != yr].copy()
        test = x[x.year == yr].copy()
        if len(train) < 8 or test.empty:
            continue
        pm, ps = train.precip_30d_mm.mean(), train.precip_30d_mm.std(ddof=0)
        tm, ts = train.tmean_30d_c.mean(), train.tmean_30d_c.std(ddof=0)
        if ps <= 1e-12 or ts <= 1e-12:
            continue
        Xtr, _ = design(train, pm, ps, tm, ts)
        Xte, _ = design(test, pm, ps, tm, ts)
        b, *_ = np.linalg.lstsq(Xtr, train.q5_minus_q1.to_numpy(float), rcond=None)
        errs.extend((test.q5_minus_q1.to_numpy(float) - Xte @ b).tolist())

    errs = np.asarray(errs, dtype=float)
    loyo_rmse = float(np.sqrt(np.mean(errs ** 2))) if errs.size else np.nan
    loyo_mae = float(np.mean(np.abs(errs))) if errs.size else np.nan

    coef = pd.DataFrame({
        "model": model_name,
        "baseline_window": baseline,
        "term": names,
        "coefficient": beta,
        "n_observations": len(x),
        "r2_in_sample": r2,
        "loyo_rmse": loyo_rmse,
        "loyo_mae": loyo_mae,
        "precip30_mean_mm": p_mean,
        "precip30_sd_mm": p_sd,
        "tmean30_mean_c": t_mean,
        "tmean30_sd_c": t_sd,
    })
    return coef, {"model": model_name, "n": len(x), "r2": r2, "loyo_rmse": loyo_rmse, "loyo_mae": loyo_mae}


def main() -> int:
    base = load_base()
    base.fit_fixed_effect_model = fixed_fit
    return base.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
