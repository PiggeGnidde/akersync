#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
GEOM = ROOT / "data/derived/geometry_v1a_skiften.csv"
TARGET = ROOT / "data/derived/geometry_crop_ranked_1to5ha.csv"
OUT = ROOT / "data/derived"

MAIN_FEATURES = [
    "log_area",
    "rectangularity",
    "convexity",
    "log_erl",
    "log_perimeter_per_ha",
    "log_aspect",
    "has_holes",
]
EXTRA_TERMS = ["rect2", "area2", "rect_x_area", "conv2"]


def normalise_text(x):
    return str(x).strip().lower().replace("å", "a").replace("ä", "a").replace("ö", "o")


def infer_target(df: pd.DataFrame):
    # Prefer an explicit binary column if the previous revealed-preference step wrote one.
    for c in ["is_active_cultivation", "active_cultivation", "is_crop", "cultivated"]:
        if c in df.columns:
            s = pd.to_numeric(df[c], errors="coerce")
            if set(s.dropna().unique()).issubset({0, 1}):
                return s, c

    # Otherwise use the semantic land-use group produced by RANK_GEOMETRY_CROPS.
    for c in ["landuse_group", "land_use_group", "crop_group", "group"]:
        if c not in df.columns:
            continue
        out = []
        for v in df[c]:
            t = normalise_text(v)
            if any(k in t for k in ["odling", "special", "crop", "active", "aker"]):
                out.append(1.0)
            elif any(k in t for k in ["bete", "pasture", "skydd", "trada", "miljo", "meadow", "noncrop", "non-crop"]):
                out.append(0.0)
            else:
                out.append(np.nan)
        s = pd.Series(out, index=df.index, dtype=float)
        if s.notna().sum() > 1000:
            return s, c

    # Conservative fallback from crop-name text if no group column exists.
    name_col = next((c for c in ["crop_name_reference_2026", "crop_name", "groda"] if c in df.columns), None)
    if name_col:
        inactive = ["skyddszon", "trada", "betesmark", "slatterang", "mosaikbetes", "grasfattig", "restaurering"]
        out = []
        for v in df[name_col]:
            t = normalise_text(v)
            if not t or t == "nan":
                out.append(np.nan)
            elif any(k in t for k in inactive) and "akermark" not in t:
                out.append(0.0)
            elif "skyddszon" in t or "trada" in t:
                out.append(0.0)
            else:
                out.append(1.0)
        return pd.Series(out, index=df.index, dtype=float), name_col

    raise RuntimeError("Kunde inte hitta binärt mål för odling kontra icke-odling i geometry_crop_ranked_1to5ha.csv")


def loglik(y, eta):
    # Stable Bernoulli log-likelihood.
    return float(np.sum(y * -np.logaddexp(0.0, -eta) + (1.0 - y) * -np.logaddexp(0.0, eta)))


def fit_logit(X, y, max_iter=60, tol=1e-8):
    beta = np.zeros(X.shape[1], dtype=float)
    ll = loglik(y, X @ beta)
    converged = False
    for _ in range(max_iter):
        eta = X @ beta
        p = expit(np.clip(eta, -35, 35))
        w = np.clip(p * (1.0 - p), 1e-9, None)
        grad = X.T @ (y - p)
        h = X.T @ (X * w[:, None])
        try:
            step = np.linalg.solve(h, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(h) @ grad

        scale = 1.0
        improved = False
        while scale >= 1 / 1024:
            b2 = beta + scale * step
            ll2 = loglik(y, X @ b2)
            if ll2 >= ll - 1e-10:
                improved = True
                beta, ll = b2, ll2
                break
            scale *= 0.5
        if not improved:
            break
        if np.max(np.abs(scale * step)) < tol:
            converged = True
            break
        if np.max(np.abs(beta)) > 50:
            break
    return beta, ll, converged and np.max(np.abs(beta)) < 50


def auc_score(y, p):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    n1 = int(y.sum()); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return np.nan
    r = rankdata(p)
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def logloss(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def make_features(df):
    f = pd.DataFrame(index=df.index)
    f["log_area"] = np.log(pd.to_numeric(df["area_ha"], errors="coerce"))
    f["rectangularity"] = pd.to_numeric(df["rectangularity"], errors="coerce")
    f["convexity"] = pd.to_numeric(df["convexity"], errors="coerce")
    f["log_erl"] = np.log(pd.to_numeric(df["erl_proxy_m"], errors="coerce"))
    f["log_perimeter_per_ha"] = np.log(pd.to_numeric(df["perimeter_per_ha_m"], errors="coerce"))
    f["log_aspect"] = np.log(pd.to_numeric(df["mbr_aspect_ratio"], errors="coerce"))
    f["has_holes"] = (pd.to_numeric(df["hole_count"], errors="coerce").fillna(0) > 0).astype(float)
    return f


def standardize_train_like(raw: pd.DataFrame):
    z = pd.DataFrame(index=raw.index)
    scales = []
    for c in raw.columns:
        x = pd.to_numeric(raw[c], errors="coerce")
        mu = float(x.mean()); sd = float(x.std(ddof=0))
        if not np.isfinite(sd) or sd < 1e-12:
            sd = 1.0
        z[c] = (x - mu) / sd
        scales.append({"term": c, "mean": mu, "sd": sd})
    # Hierarchical nonlinear terms built from standardized main effects.
    z["rect2"] = z["rectangularity"] ** 2
    z["area2"] = z["log_area"] ** 2
    z["rect_x_area"] = z["rectangularity"] * z["log_area"]
    z["conv2"] = z["convexity"] ** 2
    for c in EXTRA_TERMS:
        mu = float(z[c].mean()); sd = float(z[c].std(ddof=0))
        if sd < 1e-12: sd = 1.0
        z[c] = (z[c] - mu) / sd
        scales.append({"term": c, "mean": mu, "sd": sd})
    return z, pd.DataFrame(scales)


def fit_spec(z, y, terms, model_id, family):
    X = np.column_stack([np.ones(len(z))] + [z[t].to_numpy(float) for t in terms])
    beta, ll, conv = fit_logit(X, y)
    k = X.shape[1]; n = len(y)
    return {
        "model_id": model_id,
        "family": family,
        "terms": "+".join(terms),
        "n": n,
        "k": k,
        "loglik": ll,
        "aic": 2 * k - 2 * ll,
        "bic": math.log(n) * k - 2 * ll,
        "mcfadden_r2": np.nan,
        "converged": bool(conv),
        "beta": beta,
    }


def main():
    if not GEOM.exists() or not TARGET.exists():
        raise FileNotFoundError("Kör först RUN_GEOMETRY_V1A.bat och RANK_GEOMETRY_CROPS.bat")

    g = pd.read_csv(GEOM, dtype={"blockid": str, "skiftesbeteckning": str})
    t = pd.read_csv(TARGET, dtype={"blockid": str, "skiftesbeteckning": str})
    y0, target_source = infer_target(t)
    t = t[["blockid", "skiftesbeteckning"]].copy().assign(active_cultivation=y0)
    d = g.merge(t, on=["blockid", "skiftesbeteckning"], how="inner")
    d = d[d["active_cultivation"].notna()].copy()
    d["active_cultivation"] = d["active_cultivation"].astype(int)
    d = d[(pd.to_numeric(d["area_ha"], errors="coerce") >= 1.0) & (pd.to_numeric(d["area_ha"], errors="coerce") <= 5.0)].copy()

    raw = make_features(d)
    mask = raw.notna().all(axis=1)
    d = d.loc[mask].reset_index(drop=True)
    raw = raw.loc[mask].reset_index(drop=True)
    y = d["active_cultivation"].to_numpy(float)
    z, scales = standardize_train_like(raw)
    scales.to_csv(OUT / "geometry_logit_scaling.csv", index=False, encoding="utf-8-sig")

    # Null model for McFadden R2.
    X0 = np.ones((len(y), 1)); _, ll0, _ = fit_logit(X0, y)

    print("=" * 112)
    print("ÅkerSync · Geometry × markanvändning · exhaustive logistic model selection")
    print("=" * 112)
    print(f"Population 1–5 ha: {len(y):,} skiften | active odling: {100*y.mean():.1f}% | target source: {target_source}")
    print("Stage 1: alla 127 icke-tomma delmängder av 7 huvudmått.")

    rows = []
    counter = 0
    for r in range(1, len(MAIN_FEATURES) + 1):
        for comb in itertools.combinations(MAIN_FEATURES, r):
            counter += 1
            res = fit_spec(z, y, list(comb), f"M{counter:03d}", "main_subset")
            res["mcfadden_r2"] = 1 - res["loglik"] / ll0
            rows.append(res)
    main_df = pd.DataFrame([{k:v for k,v in r.items() if k != "beta"} for r in rows])
    top_main_ids = main_df[main_df.converged].nsmallest(5, "bic")["model_id"].tolist()
    top_main = [r for r in rows if r["model_id"] in top_main_ids]

    print("Stage 2: nonlinear expansion av de 5 bästa BIC-huvudmodellerna (alla delmängder av 4 hierarkiska extratermer).")
    seen = {tuple(sorted(r["terms"].split("+"))) for r in rows}
    for base in top_main:
        base_terms = base["terms"].split("+")
        for rr in range(1, len(EXTRA_TERMS) + 1):
            for ex in itertools.combinations(EXTRA_TERMS, rr):
                terms = base_terms + list(ex)
                key = tuple(sorted(terms))
                if key in seen: continue
                seen.add(key); counter += 1
                res = fit_spec(z, y, terms, f"M{counter:03d}", "nonlinear_expand")
                res["mcfadden_r2"] = 1 - res["loglik"] / ll0
                rows.append(res)

    results = pd.DataFrame([{k:v for k,v in r.items() if k != "beta"} for r in rows])
    results = results.sort_values(["bic", "aic"]).reset_index(drop=True)
    results.to_csv(OUT / "geometry_logit_model_selection.csv", index=False, encoding="utf-8-sig")

    best_aic = results[results.converged].nsmallest(20, "aic").assign(selection="top_AIC")
    best_bic = results[results.converged].nsmallest(20, "bic").assign(selection="top_BIC")
    best = pd.concat([best_aic, best_bic]).drop_duplicates("model_id").sort_values(["bic", "aic"])

    # Out-of-sample QA only on best candidates: deterministic 80/20 split.
    h = pd.util.hash_pandas_object(d[["blockid", "skiftesbeteckning"]].astype(str), index=False).to_numpy(np.uint64)
    test = (h % 5 == 0); train = ~test
    cv_rows = []
    coef_rows = []
    row_by_id = {r["model_id"]: r for r in rows}
    for mid in best["model_id"]:
        rr = row_by_id[mid]; terms = rr["terms"].split("+")
        Xtr = np.column_stack([np.ones(train.sum())] + [z.loc[train, t].to_numpy(float) for t in terms])
        Xte = np.column_stack([np.ones(test.sum())] + [z.loc[test, t].to_numpy(float) for t in terms])
        b, lltr, conv = fit_logit(Xtr, y[train])
        pte = expit(np.clip(Xte @ b, -35, 35))
        cv_rows.append({"model_id":mid,"terms":rr["terms"],"test_n":int(test.sum()),"test_auc":auc_score(y[test], pte),"test_logloss":logloss(y[test], pte),"train_converged":conv})
        # Full-data coefficients are standardized effects: OR per 1 SD.
        bfull = rr["beta"]
        for name, val in zip(["intercept"] + terms, bfull):
            coef_rows.append({"model_id":mid,"term":name,"beta_std":float(val),"odds_ratio_per_1sd":float(np.exp(np.clip(val,-20,20)))})

    cv = pd.DataFrame(cv_rows)
    best = best.merge(cv, on=["model_id","terms"], how="left")
    best.to_csv(OUT / "geometry_logit_best_models.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(OUT / "geometry_logit_coefficients.csv", index=False, encoding="utf-8-sig")

    # Sensitivity: refit the top 10 BIC specifications in 1–2 and 2–5 ha.
    sens_rows = []
    top10 = results[results.converged].nsmallest(10,"bic")
    for label, lo, hi in [("1-2ha",1.0,2.0),("2-5ha",2.0,5.0)]:
        m = (pd.to_numeric(d["area_ha"],errors="coerce") >= lo) & (pd.to_numeric(d["area_ha"],errors="coerce") < hi if hi < 5 else pd.to_numeric(d["area_ha"],errors="coerce") <= hi)
        for _, spec in top10.iterrows():
            terms = spec["terms"].split("+")
            X = np.column_stack([np.ones(m.sum())] + [z.loc[m,t].to_numpy(float) for t in terms])
            yy = y[m]
            b,ll,conv = fit_logit(X,yy)
            k=X.shape[1]; n=len(yy)
            sens_rows.append({"size_band":label,"model_id":spec.model_id,"terms":spec.terms,"n":n,"active_pct":100*yy.mean(),"aic":2*k-2*ll,"bic":math.log(n)*k-2*ll,"converged":conv})
    pd.DataFrame(sens_rows).to_csv(OUT / "geometry_logit_sizeband_sensitivity.csv", index=False, encoding="utf-8-sig")

    ba = results[results.converged].nsmallest(1,"aic").iloc[0]
    bb = results[results.converged].nsmallest(1,"bic").iloc[0]
    bbcv = best[best.model_id == bb.model_id].iloc[0] if (best.model_id == bb.model_id).any() else None
    print(f"Modeller testade: {len(results):,}")
    print(f"Bäst AIC: {ba.model_id}  AIC={ba.aic:.1f}  BIC={ba.bic:.1f}  R2_McF={ba.mcfadden_r2:.4f}")
    print(f"  {ba.terms}")
    print(f"Bäst BIC: {bb.model_id}  AIC={bb.aic:.1f}  BIC={bb.bic:.1f}  R2_McF={bb.mcfadden_r2:.4f}")
    print(f"  {bb.terms}")
    if bbcv is not None:
        print(f"  Holdout AUC={bbcv.test_auc:.4f}  logloss={bbcv.test_logloss:.4f}")
    print("\nOutput:")
    for fn in ["geometry_logit_model_selection.csv","geometry_logit_best_models.csv","geometry_logit_coefficients.csv","geometry_logit_scaling.csv","geometry_logit_sizeband_sensitivity.csv"]:
        print(" ", OUT / fn)
    print("\nOBS: detta är modellselektion för validering av geometri→markanvändning, inte en Geometry Score.")


if __name__ == "__main__":
    main()
