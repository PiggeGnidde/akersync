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

# Two deliberately non-redundant-ish bases.
# Never include log_aspect and log_erl together because ERL is algebraically
# linked to area, rectangularity and aspect. compactness is dimensionless and
# replaces perimeter/ha, whose raw scale is strongly size-dependent.
FAMILIES = {
    "morphology": [
        "log_area", "rectangularity", "convexity", "compactness", "log_aspect", "has_holes"
    ],
    "runlength": [
        "log_area", "rectangularity", "convexity", "compactness", "log_erl", "has_holes"
    ],
    "minimal_shape": [
        "log_area", "rectangularity", "convexity", "compactness", "has_holes"
    ],
}

# Nonlinear terms are only considered when their parent terms exist.
EXTRA_PARENTS = {
    "area2": {"log_area"},
    "rect2": {"rectangularity"},
    "conv2": {"convexity"},
    "compact2": {"compactness"},
    "rect_x_area": {"rectangularity", "log_area"},
}

LEGACY_TERMS = [
    "log_area", "rectangularity", "convexity", "log_erl",
    "log_perimeter_per_ha", "log_aspect", "has_holes",
    "area2", "rect_x_area", "conv2",
]


def normalise_text(x):
    return str(x).strip().lower().replace("å", "a").replace("ä", "a").replace("ö", "o")


def infer_target(df: pd.DataFrame):
    for c in ["is_active_cultivation", "active_cultivation", "is_crop", "cultivated"]:
        if c in df.columns:
            s = pd.to_numeric(df[c], errors="coerce")
            if set(s.dropna().unique()).issubset({0, 1}):
                return s, c
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
    raise RuntimeError("Kunde inte hitta binärt mål i geometry_crop_ranked_1to5ha.csv")


def loglik(y, eta):
    return float(np.sum(y * -np.logaddexp(0.0, -eta) + (1.0 - y) * -np.logaddexp(0.0, eta)))


def fit_logit(X, y, max_iter=70, tol=1e-8):
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
                beta, ll = b2, ll2
                improved = True
                break
            scale *= 0.5
        if not improved:
            break
        if np.max(np.abs(scale * step)) < tol:
            converged = True
            break
        if np.max(np.abs(beta)) > 60:
            break
    return beta, ll, converged and np.max(np.abs(beta)) < 60


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


def make_raw_features(df):
    f = pd.DataFrame(index=df.index)
    f["log_area"] = np.log(pd.to_numeric(df["area_ha"], errors="coerce"))
    f["rectangularity"] = pd.to_numeric(df["rectangularity"], errors="coerce")
    f["convexity"] = pd.to_numeric(df["convexity"], errors="coerce")
    f["compactness"] = pd.to_numeric(df["compactness_4piA_P2"], errors="coerce")
    f["log_aspect"] = np.log(pd.to_numeric(df["mbr_aspect_ratio"], errors="coerce"))
    f["log_erl"] = np.log(pd.to_numeric(df["erl_proxy_m"], errors="coerce"))
    f["log_perimeter_per_ha"] = np.log(pd.to_numeric(df["perimeter_per_ha_m"], errors="coerce"))
    f["has_holes"] = (pd.to_numeric(df["hole_count"], errors="coerce").fillna(0) > 0).astype(float)
    return f


def fit_scaler(raw, cols):
    params = {}
    z = pd.DataFrame(index=raw.index)
    for c in cols:
        x = pd.to_numeric(raw[c], errors="coerce")
        mu = float(x.mean()); sd = float(x.std(ddof=0))
        if not np.isfinite(sd) or sd < 1e-12:
            sd = 1.0
        params[c] = (mu, sd)
        z[c] = (x - mu) / sd
    return z, params


def apply_scaler(raw, params):
    z = pd.DataFrame(index=raw.index)
    for c, (mu, sd) in params.items():
        z[c] = (pd.to_numeric(raw[c], errors="coerce") - mu) / sd
    return z


def add_extra_terms(z):
    x = z.copy()
    if "log_area" in x: x["area2"] = x["log_area"] ** 2
    if "rectangularity" in x: x["rect2"] = x["rectangularity"] ** 2
    if "convexity" in x: x["conv2"] = x["convexity"] ** 2
    if "compactness" in x: x["compact2"] = x["compactness"] ** 2
    if "log_area" in x and "rectangularity" in x:
        x["rect_x_area"] = x["rectangularity"] * x["log_area"]
    return x


def design(z, terms):
    return np.column_stack([np.ones(len(z))] + [z[t].to_numpy(float) for t in terms])


def fit_spec(z, y, terms, model_id, family):
    X = design(z, terms)
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
        "converged": bool(conv),
        "beta": beta,
    }


def vif_table(raw, family, cols):
    z, _ = fit_scaler(raw, cols)
    rows = []
    for c in cols:
        y = z[c].to_numpy(float)
        others = [o for o in cols if o != c]
        if not others:
            vif = 1.0; r2 = 0.0
        else:
            X = np.column_stack([np.ones(len(z))] + [z[o].to_numpy(float) for o in others])
            b, *_ = np.linalg.lstsq(X, y, rcond=None)
            pred = X @ b
            sse = float(np.sum((y - pred) ** 2))
            sst = float(np.sum((y - y.mean()) ** 2))
            r2 = 1 - sse / sst if sst > 0 else 0.0
            vif = 1.0 / max(1e-12, 1.0 - r2)
        rows.append({"family": family, "term": c, "r2_against_others": r2, "vif": vif})
    return rows


def holdout_eval(raw, y, terms, test):
    train = ~test
    main_terms = [t for t in terms if t not in EXTRA_PARENTS]
    ztr_main, params = fit_scaler(raw.loc[train], main_terms)
    zte_main = apply_scaler(raw.loc[test], params)
    ztr = add_extra_terms(ztr_main)
    zte = add_extra_terms(zte_main)

    # Standardize nonlinear terms using TRAIN only.
    for t in [t for t in terms if t in EXTRA_PARENTS]:
        mu = float(ztr[t].mean()); sd = float(ztr[t].std(ddof=0))
        if not np.isfinite(sd) or sd < 1e-12: sd = 1.0
        ztr[t] = (ztr[t] - mu) / sd
        zte[t] = (zte[t] - mu) / sd

    Xtr = design(ztr, terms); Xte = design(zte, terms)
    b, _, conv = fit_logit(Xtr, y[train])
    p = expit(np.clip(Xte @ b, -35, 35))
    return auc_score(y[test], p), logloss(y[test], p), conv


def main():
    if not GEOM.exists() or not TARGET.exists():
        raise FileNotFoundError("Kör först RUN_GEOMETRY_V1A.bat och RANK_GEOMETRY_CROPS.bat")
    OUT.mkdir(parents=True, exist_ok=True)

    g = pd.read_csv(GEOM, dtype={"blockid": str, "skiftesbeteckning": str})
    t = pd.read_csv(TARGET, dtype={"blockid": str, "skiftesbeteckning": str})
    y0, target_source = infer_target(t)
    t = t[["blockid", "skiftesbeteckning"]].copy().assign(active_cultivation=y0)
    d = g.merge(t, on=["blockid", "skiftesbeteckning"], how="inner")
    d = d[d["active_cultivation"].notna()].copy()
    d["active_cultivation"] = d["active_cultivation"].astype(int)
    area = pd.to_numeric(d["area_ha"], errors="coerce")
    d = d[(area >= 1.0) & (area <= 5.0)].copy().reset_index(drop=True)

    raw = make_raw_features(d)
    needed = sorted(set(sum(FAMILIES.values(), [])) | {"log_perimeter_per_ha"})
    mask = raw[needed].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    d = d.loc[mask].reset_index(drop=True)
    raw = raw.loc[mask].reset_index(drop=True)
    y = d["active_cultivation"].to_numpy(float)

    print("=" * 118)
    print("ÅkerSync · Geometry × markanvändning · orthogonal-ish model families")
    print("=" * 118)
    print(f"Population 1–5 ha: {len(y):,} | active odling: {100*y.mean():.1f}% | target: {target_source}")
    print("Mål: minska algebraisk redundans mellan area/rectangularity/aspect/ERL och ersätta perimeter/ha med dimensionlös compactness.")
    print("VIKTIGT: target är mänskligt markanvändningsbeslut 2025, inte maskinsimulerad effektivitet.")

    # Correlation and VIF diagnostics for each main basis.
    corr_rows = []
    vif_rows = []
    for fam, cols in FAMILIES.items():
        cmat = raw[cols].corr()
        for a in cols:
            for b in cols:
                corr_rows.append({"family": fam, "term_a": a, "term_b": b, "corr": float(cmat.loc[a, b])})
        vif_rows.extend(vif_table(raw, fam, cols))
    pd.DataFrame(corr_rows).to_csv(OUT / "geometry_orthogonal_correlations.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(vif_rows).to_csv(OUT / "geometry_orthogonal_vif.csv", index=False, encoding="utf-8-sig")

    rows = []
    specs_by_key = {}
    counter = 0
    family_best_main = {}

    # Stage 1: exhaustive subsets inside each interpretable main family.
    for fam, cols in FAMILIES.items():
        zmain, _ = fit_scaler(raw, cols)
        z = add_extra_terms(zmain)
        fam_rows = []
        for r in range(1, len(cols) + 1):
            for comb in itertools.combinations(cols, r):
                key = tuple(comb)
                if key in specs_by_key:
                    continue
                counter += 1
                rr = fit_spec(z, y, list(comb), f"O{counter:03d}", fam)
                specs_by_key[key] = rr
                rows.append(rr); fam_rows.append(rr)
        family_best_main[fam] = sorted([r for r in fam_rows if r["converged"]], key=lambda x: x["bic"])[:3]

    # Stage 2: nonlinear expansion only around the best three main models per family.
    for fam, bases in family_best_main.items():
        fam_cols = FAMILIES[fam]
        zmain, _ = fit_scaler(raw, fam_cols)
        z = add_extra_terms(zmain)
        for base in bases:
            base_terms = base["terms"].split("+")
            eligible = [e for e, parents in EXTRA_PARENTS.items() if parents.issubset(set(base_terms))]
            for rr_n in range(1, len(eligible) + 1):
                for ex in itertools.combinations(eligible, rr_n):
                    terms = base_terms + list(ex)
                    key = tuple(sorted(terms))
                    if key in specs_by_key:
                        continue
                    counter += 1
                    rr = fit_spec(z, y, terms, f"O{counter:03d}", fam + "_nonlinear")
                    specs_by_key[key] = rr
                    rows.append(rr)

    # Legacy M201-like benchmark: allowed to be redundant, for predictive/AIC/BIC comparison only.
    legacy_main = ["log_area", "rectangularity", "convexity", "log_erl", "log_perimeter_per_ha", "log_aspect", "has_holes"]
    zlegacy, _ = fit_scaler(raw, legacy_main)
    zlegacy = add_extra_terms(zlegacy)
    counter += 1
    legacy = fit_spec(zlegacy, y, LEGACY_TERMS, f"O{counter:03d}", "legacy_M201_benchmark")
    rows.append(legacy)

    # Null log-likelihood for McFadden R2.
    _, ll0, _ = fit_logit(np.ones((len(y), 1)), y)
    for r in rows:
        r["mcfadden_r2"] = 1 - r["loglik"] / ll0

    results = pd.DataFrame([{k: v for k, v in r.items() if k != "beta"} for r in rows])
    results = results.sort_values(["bic", "aic"]).reset_index(drop=True)

    # Deterministic holdout for best candidates plus legacy benchmark.
    h = pd.util.hash_pandas_object(d[["blockid", "skiftesbeteckning"]].astype(str), index=False).to_numpy(np.uint64)
    test = (h % 5 == 0)
    eval_ids = set(results[results.converged].nsmallest(25, "bic")["model_id"])
    eval_ids.add(legacy["model_id"])
    hold = []
    coef_rows = []
    row_map = {r["model_id"]: r for r in rows}
    for mid in eval_ids:
        r = row_map[mid]
        terms = r["terms"].split("+")
        auc, loss, conv = holdout_eval(raw, y, terms, test)
        hold.append({"model_id": mid, "holdout_auc": auc, "holdout_logloss": loss, "holdout_converged": conv})
        for name, val in zip(["intercept"] + terms, r["beta"]):
            coef_rows.append({"model_id": mid, "family": r["family"], "term": name, "beta_std": float(val), "odds_ratio_per_1sd": float(np.exp(np.clip(val, -20, 20)))})

    results = results.merge(pd.DataFrame(hold), on="model_id", how="left")
    results.to_csv(OUT / "geometry_orthogonal_model_selection.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(OUT / "geometry_orthogonal_coefficients.csv", index=False, encoding="utf-8-sig")

    best = results[results.converged].nsmallest(30, "bic").copy()
    best.to_csv(OUT / "geometry_orthogonal_best_models.csv", index=False, encoding="utf-8-sig")

    # One-line family summary: best BIC model in each family root + legacy benchmark.
    summary = []
    roots = list(FAMILIES) + ["legacy_M201_benchmark"]
    for root in roots:
        m = results[results["family"].astype(str).str.startswith(root)] if root != "legacy_M201_benchmark" else results[results["family"] == root]
        m = m[m.converged]
        if len(m):
            b = m.nsmallest(1, "bic").iloc[0]
            summary.append({k: b.get(k) for k in ["model_id", "family", "terms", "k", "aic", "bic", "mcfadden_r2", "holdout_auc", "holdout_logloss"]})
    s = pd.DataFrame(summary).sort_values("bic")
    s.to_csv(OUT / "geometry_orthogonal_family_summary.csv", index=False, encoding="utf-8-sig")

    print(f"Modeller testade: {len(results):,}")
    print("\nBästa modell per familj:")
    for _, r in s.iterrows():
        auc_txt = "–" if pd.isna(r["holdout_auc"]) else f"{r['holdout_auc']:.4f}"
        print(f"  {r['family']:<28} {r['model_id']}  BIC={r['bic']:.1f}  AIC={r['aic']:.1f}  R2={r['mcfadden_r2']:.4f}  AUC={auc_txt}")
        print(f"    {r['terms']}")

    best_nonlegacy = results[(results.converged) & (results.family != "legacy_M201_benchmark")].nsmallest(1, "bic").iloc[0]
    leg = results[results.family == "legacy_M201_benchmark"].iloc[0]
    print("\nOrthogonal-ish vinnare vs legacy M201-benchmark:")
    print(f"  BIC:  {best_nonlegacy['bic']:.1f} vs {leg['bic']:.1f}  (delta={best_nonlegacy['bic']-leg['bic']:+.1f})")
    if pd.notna(best_nonlegacy.get("holdout_auc")) and pd.notna(leg.get("holdout_auc")):
        print(f"  AUC:  {best_nonlegacy['holdout_auc']:.4f} vs {leg['holdout_auc']:.4f}  (delta={best_nonlegacy['holdout_auc']-leg['holdout_auc']:+.4f})")

    print("\nOutput:")
    for name in [
        "geometry_orthogonal_model_selection.csv",
        "geometry_orthogonal_best_models.csv",
        "geometry_orthogonal_coefficients.csv",
        "geometry_orthogonal_family_summary.csv",
        "geometry_orthogonal_correlations.csv",
        "geometry_orthogonal_vif.csv",
    ]:
        print(" ", OUT / name)
    print("\nOBS: detta validerar geometri mot mänskligt markanvändningsbeslut. Framtida maskinsimulering är en separat, oberoende validering.")


if __name__ == "__main__":
    main()
