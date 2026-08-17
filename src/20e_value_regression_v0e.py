#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0e — soil texture + within-transaction variation.

This iteration deliberately pauses geometry as a price predictor and asks a
narrower question: does the balance and heterogeneity of sand/silt/clay carry
price information beyond geography?

Sand+silt+clay are compositional. We therefore test either two components
(clay+silt; sand implicit) or two log-ratios (clay/sand and silt/sand), never
all three raw percentages as independent linear regressors.

Transaction-level soil uses the v0c proximity/area multi-block reconstruction.
Only ±20% area-matched reconstructions are admitted to the main transaction
soil regressions. Organic matter stays categorical: DSMS class shares/mode and
heterogeneity are exported, but class codes are not treated as continuous %.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

import value_multiblock as mb
import value_transaction_soil as txsoil

G1 = ["year_centered", "log_area_20", "lat_centered", "lon_centered"]
G2 = G1 + ["lat2", "lon2", "lat_lon"]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
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


def numeric(s):
    return pd.to_numeric(s, errors="coerce")


def logratio(a: pd.Series, b: pd.Series) -> pd.Series:
    aa, bb = numeric(a), numeric(b)
    ok = aa.gt(0) & bb.gt(0)
    out = pd.Series(np.nan, index=aa.index, dtype=float)
    out.loc[ok] = np.log(aa.loc[ok] / bb.loc[ok])
    return out


def add_texture_terms(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    families = {
        "point": ("soil_clay_point", "soil_silt_point", "soil_sand_point"),
        "m100": ("soil_clay_100m_mean", "soil_silt_100m_mean", "soil_sand_100m_mean"),
        "tx": ("tx_soil_clay_mean_pct", "tx_soil_silt_mean_pct", "tx_soil_sand_mean_pct"),
    }
    for label, (c, s, sa) in families.items():
        if c not in out.columns:
            continue
        cc = numeric(out[c])
        out[f"{label}_clay_c25"] = cc - 25.0
        out[f"{label}_clay_c25_sq"] = (cc - 25.0) ** 2
        if s in out.columns:
            ss = numeric(out[s])
            out[f"{label}_silt_c35"] = ss - 35.0
            out[f"{label}_silt_c35_sq"] = (ss - 35.0) ** 2
            out[f"{label}_clay_silt_interaction"] = (cc - 25.0) * (ss - 35.0)
        if s in out.columns and sa in out.columns:
            out[f"{label}_log_clay_sand"] = logratio(out[c], out[sa])
            out[f"{label}_log_silt_sand"] = logratio(out[s], out[sa])
    return out


def complete(df: pd.DataFrame, terms: list[str]) -> pd.DataFrame:
    cols = ["log_kr_per_aker_ha"] + list(terms)
    mask = np.ones(len(df), dtype=bool)
    for c in cols:
        if c not in df.columns:
            return df.iloc[0:0].copy()
        mask &= numeric(df[c]).notna().to_numpy()
    return df.loc[mask].copy().reset_index(drop=True)


def design(df: pd.DataFrame, terms: list[str]):
    y = numeric(df["log_kr_per_aker_ha"]).to_numpy(float)
    X = np.column_stack([np.ones(len(df), float)] + [numeric(df[t]).to_numpy(float) for t in terms])
    return X, y, ["intercept"] + list(terms)


def eval_model(v0a, df: pd.DataFrame, baseline: list[str], extras: list[str]):
    x = complete(df, baseline + extras)
    min_n = max(12, len(baseline) + len(extras) + 5)
    if len(x) < min_n:
        return None
    X0, y, _ = design(x, baseline)
    X1, _, names = design(x, baseline + extras)
    if np.linalg.matrix_rank(X1) < X1.shape[1]:
        return None
    p0 = v0a.loo_predictions(X0, y)
    p1 = v0a.loo_predictions(X1, y)
    b, pred, r2, adj, rank, se, pv = v0a.fit_ols(X1, y)
    b0 = v0a.r2_score(y, p0)
    b1 = v0a.r2_score(y, p1)
    return {
        "n": len(x),
        "baseline_loo_r2_same_n": b0,
        "augmented_loo_r2": b1,
        "delta_loo_r2": b1 - b0,
        "train_r2_augmented": r2,
        "adj_r2_augmented": adj,
        "median_abs_pct_error_loo": 100.0 * float(np.median(v0a.pct_error_from_log(y, p1))),
        "names": names,
        "beta": b,
        "se": se,
        "p_value": pv,
        "data": x,
    }


def baseline_eval(v0a, df: pd.DataFrame, label: str, terms: list[str]):
    x = complete(df, terms)
    X, y, names = design(x, terms)
    b, pred, r2, adj, rank, se, pv = v0a.fit_ols(X, y)
    loo = v0a.loo_predictions(X, y)
    return {
        "baseline": label,
        "n": len(x),
        "train_r2": r2,
        "adj_r2": adj,
        "loo_r2": v0a.r2_score(y, loo),
        "median_abs_pct_error_loo": 100.0 * float(np.median(v0a.pct_error_from_log(y, loo))),
        "names": names,
        "beta": b,
        "se": se,
        "p_value": pv,
    }


def model_specs():
    return [
        ("point_clay_linear", ["soil_clay_point"], "point"),
        ("point_clay_quadratic", ["point_clay_c25", "point_clay_c25_sq"], "point"),
        ("mean100_clay_linear", ["soil_clay_100m_mean"], "100m"),
        ("mean100_clay_quadratic", ["m100_clay_c25", "m100_clay_c25_sq"], "100m"),
        ("point_texture_linear_clay_silt", ["soil_clay_point", "soil_silt_point"], "point"),
        ("mean100_texture_linear_clay_silt", ["soil_clay_100m_mean", "soil_silt_100m_mean"], "100m"),
        ("point_texture_logratio", ["point_log_clay_sand", "point_log_silt_sand"], "point"),
        ("mean100_texture_logratio", ["m100_log_clay_sand", "m100_log_silt_sand"], "100m"),
        ("mean100_texture_quadratic", ["m100_clay_c25", "m100_silt_c35", "m100_clay_c25_sq", "m100_silt_c35_sq", "m100_clay_silt_interaction"], "100m"),
        ("tx_clay_linear", ["tx_soil_clay_mean_pct"], "transaction"),
        ("tx_clay_quadratic", ["tx_clay_c25", "tx_clay_c25_sq"], "transaction"),
        ("tx_texture_linear_clay_silt", ["tx_soil_clay_mean_pct", "tx_soil_silt_mean_pct"], "transaction"),
        ("tx_texture_logratio", ["tx_log_clay_sand", "tx_log_silt_sand"], "transaction"),
        ("tx_texture_quadratic", ["tx_clay_c25", "tx_silt_c35", "tx_clay_c25_sq", "tx_silt_c35_sq", "tx_clay_silt_interaction"], "transaction"),
        ("tx_clay_p90_p10_variation", ["tx_soil_clay_p90_p10_pct"], "transaction_variation"),
        ("tx_texture_pixel_heterogeneity", ["tx_soil_texture_pixel_rms_sd_pct"], "transaction_variation"),
        ("tx_texture_between_blocks_diversity", ["tx_soil_texture_between_blocks_rms_pct"], "transaction_variation"),
        ("tx_organic_class_entropy_EXPLORATORY", ["tx_organic_entropy_bits"], "organic_categorical_variation"),
    ]


def turning_point(names, beta, model_name: str):
    if "clay_quadratic" not in model_name:
        return np.nan, ""
    lin = next((i for i, n in enumerate(names) if n.endswith("clay_c25")), None)
    sq = next((i for i, n in enumerate(names) if n.endswith("clay_c25_sq")), None)
    if lin is None or sq is None:
        return np.nan, ""
    b1, b2 = beta[lin], beta[sq]
    if not np.isfinite(b2) or abs(b2) < 1e-12:
        return np.nan, "flat"
    x = 25.0 - b1 / (2.0 * b2)
    kind = "maximum" if b2 < 0 else "minimum"
    return float(x), kind


def run_models(v0a, df: pd.DataFrame, outdir: Path):
    rows, coef_rows = [], []
    specs = [("G1_linear_geo", G1), ("G2_quadratic_geo", G2)]
    for blabel, bterms in specs:
        for mname, extras, family in model_specs():
            r = eval_model(v0a, df, bterms, extras)
            if r is None:
                continue
            tp, tptype = turning_point(r["names"], r["beta"], mname)
            rows.append({
                "baseline": blabel,
                "soil_model": mname,
                "family": family,
                "extra_terms": " + ".join(extras),
                "n": r["n"],
                "baseline_loo_r2_same_n": r["baseline_loo_r2_same_n"],
                "augmented_loo_r2": r["augmented_loo_r2"],
                "delta_loo_r2": r["delta_loo_r2"],
                "train_r2_augmented": r["train_r2_augmented"],
                "adj_r2_augmented": r["adj_r2_augmented"],
                "median_abs_pct_error_loo": r["median_abs_pct_error_loo"],
                "quadratic_turning_point_clay_pct": tp,
                "quadratic_turning_point_type": tptype,
            })
            for n, b, se, p in zip(r["names"], r["beta"], r["se"], r["p_value"]):
                coef_rows.append({
                    "baseline": blabel,
                    "soil_model": mname,
                    "term": n,
                    "coefficient": b,
                    "std_error": se,
                    "p_value": p,
                })
    z = pd.DataFrame(rows)
    if len(z):
        z = z.sort_values(["baseline", "delta_loo_r2"], ascending=[True, False])
    z.to_csv(outdir / "soil_model_comparison.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(outdir / "soil_model_coefficients.csv", index=False, encoding="utf-8-sig")
    return z


def robustness(v0a, df: pd.DataFrame, outdir: Path):
    chosen = {
        "point_clay_linear": ["soil_clay_point"],
        "mean100_clay_linear": ["soil_clay_100m_mean"],
        "tx_clay_linear": ["tx_soil_clay_mean_pct"],
        "tx_texture_logratio": ["tx_log_clay_sand", "tx_log_silt_sand"],
    }
    detail = []
    summary = []
    for blabel, bterms in [("G1_linear_geo", G1), ("G2_quadratic_geo", G2)]:
        for mname, extras in chosen.items():
            full = complete(df, bterms + extras)
            full_r = eval_model(v0a, full, bterms, extras)
            if full_r is None:
                continue
            deltas = []
            first_betas = []
            for k in range(len(full)):
                d = full.drop(index=k).reset_index(drop=True)
                r = eval_model(v0a, d, bterms, extras)
                if r is None:
                    continue
                deltas.append(r["delta_loo_r2"])
                j = r["names"].index(extras[0])
                first_betas.append(r["beta"][j])
                detail.append({
                    "baseline": blabel,
                    "soil_model": mname,
                    "deleted_sale_id": full.iloc[k].get("sale_id", ""),
                    "n_after_delete": r["n"],
                    "delta_loo_r2_after_delete": r["delta_loo_r2"],
                    "first_extra_coefficient": r["beta"][j],
                })
            jfull = full_r["names"].index(extras[0])
            fb = full_r["beta"][jfull]
            arrd = np.asarray(deltas, float)
            arrb = np.asarray(first_betas, float)
            sign = np.sign(fb) if np.isfinite(fb) and fb != 0 else 0
            summary.append({
                "baseline": blabel,
                "soil_model": mname,
                "n_full": full_r["n"],
                "full_delta_loo_r2": full_r["delta_loo_r2"],
                "full_first_extra_coefficient": fb,
                "delete1_runs": len(arrd),
                "delta_min": np.nanmin(arrd) if len(arrd) else np.nan,
                "delta_median": np.nanmedian(arrd) if len(arrd) else np.nan,
                "delta_max": np.nanmax(arrd) if len(arrd) else np.nan,
                "share_delta_positive_pct": 100.0 * float(np.mean(arrd > 0)) if len(arrd) else np.nan,
                "first_beta_min": np.nanmin(arrb) if len(arrb) else np.nan,
                "first_beta_median": np.nanmedian(arrb) if len(arrb) else np.nan,
                "first_beta_max": np.nanmax(arrb) if len(arrb) else np.nan,
                "share_first_beta_same_sign_pct": 100.0 * float(np.mean(np.sign(arrb) == sign)) if sign and len(arrb) else np.nan,
            })
    pd.DataFrame(detail).to_csv(outdir / "soil_delete1_robustness.csv", index=False, encoding="utf-8-sig")
    sm = pd.DataFrame(summary)
    sm.to_csv(outdir / "soil_robustness_summary.csv", index=False, encoding="utf-8-sig")
    return sm


def organic_summary(df: pd.DataFrame, outdir: Path):
    rows = []
    if "tx_organic_mode_code" in df.columns:
        x = df.loc[pd.to_numeric(df["tx_organic_mode_code"], errors="coerce").notna()].copy()
        for code in txsoil.ORG_CODES:
            n = int((pd.to_numeric(x["tx_organic_mode_code"], errors="coerce") == code).sum()) if len(x) else 0
            share_col = f"tx_organic_share_code_{code}_pct"
            rows.append({
                "organic_code": code,
                "label": txsoil.ORG_LABELS[code],
                "transactions_mode_is_code": n,
                "median_area_share_pct": pd.to_numeric(x.get(share_col), errors="coerce").median() if share_col in x else np.nan,
            })
    z = pd.DataFrame(rows)
    z.to_csv(outdir / "organic_class_summary.csv", index=False, encoding="utf-8-sig")
    return z


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--atl", help="ATL_AkerSync_*_v03.csv; om utelämnad öppnas filväljare")
    ap.add_argument("--radius-m", type=float, default=100.0)
    ap.add_argument("--since", default="2020-07-01")
    ap.add_argument("--recon-radius-m", type=float, default=3000.0)
    ap.add_argument("--max-link-gap-m", type=float, default=750.0)
    ap.add_argument("--max-blocks", type=int, default=15)
    ap.add_argument("--baseline-only", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    v0a = load_module(root / "src" / "20_value_regression_v0a.py", "value_v0a")
    cfg = v0a.load_config(root / args.config)
    atl = args.atl or v0a.choose_atl_csv()
    if not atl:
        print("Avbrutet: ingen ATL CSV vald.")
        return 2
    atl = Path(atl)
    since = pd.Timestamp(args.since)
    outdir = root / cfg.get("build_dir", "data/derived") / "value_regression_v0e"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 92)
    print("ÅkerSync · Value Regression v0e · soil texture")
    print("=" * 92)
    print("ATL:", atl)
    print("Output:", outdir)
    print("Sample start:", since.date())
    print("Texture rule: clay+silt (sand implicit) or log-ratios; never 3 raw parts independently.")
    print("Transaction soil requires v0c reconstruction area match ±20%.")
    print()

    audit, all_clean = v0a.load_and_select_clean(atl)
    clean = all_clean.loc[pd.to_datetime(all_clean["datum"], errors="coerce").ge(since)].copy().reset_index(drop=True)
    clean = add_geo_terms(clean)
    audit.to_csv(outdir / "selection_audit.csv", index=False, encoding="utf-8-sig")
    clean.to_csv(outdir / "clean_cases.csv", index=False, encoding="utf-8-sig")

    print(f"ATL-rader: {len(pd.read_csv(atl, sep=';', encoding='utf-8-sig')):,}")
    print(f"Unika transaktioner: {len(audit):,}")
    print(f"Rena före datumfilter: {len(all_clean):,}")
    print(f"Rena v0e-case: {len(clean):,}")
    print()

    enriched = clean.copy()
    members = pd.DataFrame()
    block_soil = pd.DataFrame()
    if not args.baseline_only:
        print("[1/3] Jord vid ATL-punkt + 100 m...")
        enriched = v0a.add_soil_features(enriched, cfg, args.radius_m)
        print("[2/3] Multi-block reconstruction (läge + area; ingen geometri i urvalet)...")
        enriched, members = mb.add_features(enriched, cfg, v0a, args.recon_radius_m, args.max_link_gap_m, args.max_blocks)
        print("[3/3] Jord över de rekonstruerade blocken...")
        enriched, block_soil = txsoil.add_transaction_soil_features(enriched, members, cfg, "tx_recon_match_20pct")
        enriched = add_geo_terms(add_texture_terms(enriched))

    enriched.to_csv(outdir / "soil_features_all.csv", index=False, encoding="utf-8-sig")
    if len(members):
        members.to_csv(outdir / "multiblock_members.csv", index=False, encoding="utf-8-sig")
    if len(block_soil):
        block_soil.to_csv(outdir / "transaction_soil_block_features.csv", index=False, encoding="utf-8-sig")

    baselines = [baseline_eval(v0a, enriched, "G1_linear_geo", G1), baseline_eval(v0a, enriched, "G2_quadratic_geo", G2)]
    pd.DataFrame([{k: v for k, v in r.items() if k not in {"names", "beta", "se", "p_value"}} for r in baselines]).to_csv(
        outdir / "geography_baseline_comparison.csv", index=False, encoding="utf-8-sig"
    )

    comp = pd.DataFrame()
    robust = pd.DataFrame()
    if not args.baseline_only:
        comp = run_models(v0a, enriched, outdir)
        robust = robustness(v0a, enriched, outdir)
        organic_summary(enriched, outdir)

    lines = [
        "ÅkerSync Value Regression v0e — soil texture",
        "=" * 76,
        f"ATL source: {atl}",
        f"Unique transactions after dedup: {len(audit)}",
        f"Clean cases before date window: {len(all_clean)}",
        f"Sample start: {since.date()}",
        f"Clean v0e cases: {len(clean)}",
    ]
    if "tx_recon_available" in enriched.columns:
        av = enriched["tx_recon_available"].fillna(False).astype(bool)
        lines += [
            f"Multi-block anchor available: {int(av.sum())}/{len(enriched)}",
            f"Multi-block area match ±20%: {int(enriched['tx_recon_match_20pct'].fillna(False).sum())}/{len(enriched)}",
        ]
        e = pd.to_numeric(enriched.loc[av, "tx_recon_area_abs_pct_diff"], errors="coerce")
        lines.append(f"Median reconstruction area error: {e.median():.1f}%")
    lines += ["", "GEOGRAPHY BASELINES"]
    for r in baselines:
        lines.append(
            f"  {r['baseline']}: n={r['n']}, train R2={r['train_r2']:.4f}, "
            f"LOO R2={r['loo_r2']:.4f}, medianAPE={r['median_abs_pct_error_loo']:.1f}%"
        )
    if len(comp):
        lines += ["", "SOIL MODELS — delta LOO versus SAME-row baseline"]
        for blabel in ["G1_linear_geo", "G2_quadratic_geo"]:
            x = comp.loc[comp.baseline == blabel].sort_values("delta_loo_r2", ascending=False)
            for _, r in x.iterrows():
                turn = ""
                if pd.notna(r.quadratic_turning_point_clay_pct):
                    turn = f", clay turn={r.quadratic_turning_point_clay_pct:.1f}% ({r.quadratic_turning_point_type})"
                lines.append(
                    f"  {r.baseline} + {r.soil_model}: n={int(r.n)}, LOO={r.augmented_loo_r2:.4f}, "
                    f"delta={r.delta_loo_r2:+.4f}, medianAPE={r.median_abs_pct_error_loo:.1f}%{turn}"
                )
    if len(robust):
        lines += ["", "DELETE-ONE ROBUSTNESS"]
        for _, r in robust.iterrows():
            lines.append(
                f"  {r.baseline} / {r.soil_model}: delta full={r.full_delta_loo_r2:+.4f}, "
                f"delete1 [{r.delta_min:+.4f}, {r.delta_max:+.4f}], positive={r.share_delta_positive_pct:.0f}%"
            )
    lines += [
        "",
        "ORGANIC / MULL HANDLING",
        "DSMS organic matter is categorical. v0e preserves mode + class shares + entropy.",
        "No organic class code is interpreted as a continuous mull percentage in the price model.",
        "",
        "Texture composition rule: sand+silt+clay are not entered as three independent raw regressors.",
        "Transaction-level soil is based on reconstructed 2025 agricultural blocks and is a proxy, not cadastral identification.",
        "Primary metric: delta LOO R2 versus baseline on the SAME rows.",
    ]
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
