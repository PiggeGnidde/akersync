#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0b.

Second land-value experiment, deliberately focused on QA rather than adding
more predictors.

Changes from v0a
----------------
1. Default analysis window starts 2020-07-01 (roughly six years in the current
   ATL capture). Older captures remain in selection_audit but are excluded from
   the v0b model sample.
2. Field-shape metrics are taken from the *Jordbruksverket block* containing
   the ATL point, not blindly from the crop skifte.
3. Geometry is admitted to regression only when block area is within ±20% of
   ATL sold arable area. 10% and 30% flags are saved for sensitivity checks.
4. Raw block/skifte area matches are exported so we can see whether the point
   plausibly identifies the land object that was sold.

The spatial probe still does NOT identify cadastral properties. A geometry
match therefore means "plausible single-block sale", not proven identity.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


def load_v0a(root: Path):
    p = root / "src" / "20_value_regression_v0a.py"
    spec = importlib.util.spec_from_file_location("akersync_value_v0a", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ratio_and_diff(area_geom, area_sale):
    try:
        a = float(area_geom)
        s = float(area_sale)
    except Exception:
        return np.nan, np.nan
    if not np.isfinite(a) or not np.isfinite(s) or a <= 0 or s <= 0:
        return np.nan, np.nan
    ratio = a / s
    return ratio, 100.0 * abs(ratio - 1.0)


def add_geometry_matches_v0b(clean: pd.DataFrame, cfg: dict, v0a, tolerance: float = 0.20) -> pd.DataFrame:
    """Match ATL point to block/skifte; validate block area before shape use."""
    out = clean.copy()
    out["point_inside_block_2025"] = False
    out["point_inside_skifte_2025"] = False
    out["geometry_source"] = ""

    qa_cols = [
        "block_geom_area_ha", "block_area_ratio_to_sale", "block_area_abs_pct_diff",
        "block_rectangularity_raw", "block_convexity_raw", "block_compactness_raw",
        "block_mbr_aspect_raw",
        "skifte_geom_area_ha", "skifte_area_ratio_to_sale", "skifte_area_abs_pct_diff",
    ]
    for c in qa_cols:
        out[c] = np.nan
    out["geom_area_match_10pct"] = False
    out["geom_area_match_20pct"] = False
    out["geom_area_match_30pct"] = False
    out["geom_area_match_main"] = False

    for c in [
        "geom_area_ha", "geom_rectangularity", "geom_convexity",
        "geom_compactness", "geom_mbr_aspect", "geom_mbr_long_m", "geom_mbr_short_m",
    ]:
        out[c] = np.nan

    blocks_path = Path(cfg.get("blocks", ""))
    skiften_path = Path(cfg.get("skiften", ""))
    if not blocks_path.exists():
        print("VARNING: blockfil saknas; hoppar över geometri:", blocks_path)
        return out

    blocks = gpd.read_file(blocks_path).to_crs(3006)
    skiften = gpd.read_file(skiften_path).to_crs(3006) if skiften_path.exists() else gpd.GeoDataFrame()
    points = gpd.GeoDataFrame(
        out[["sale_id"]].copy(),
        geometry=gpd.points_from_xy(out.lon_n, out.lat_n),
        crs=4326,
    ).to_crs(3006)

    for i, p in enumerate(points.geometry):
        b = v0a.containing_row(blocks, p)
        s = v0a.containing_row(skiften, p) if not skiften.empty else None
        sale_area = out.at[i, "akermark_ha_n"]

        if b is not None:
            out.at[i, "point_inside_block_2025"] = True
            b_area = float(b.geometry.area) / 10000.0
            b_ratio, b_diff = ratio_and_diff(b_area, sale_area)
            out.at[i, "block_geom_area_ha"] = b_area
            out.at[i, "block_area_ratio_to_sale"] = b_ratio
            out.at[i, "block_area_abs_pct_diff"] = b_diff
            raw_metrics = v0a.geometry_metrics(b.geometry)
            out.at[i, "block_rectangularity_raw"] = raw_metrics.get("geom_rectangularity", np.nan)
            out.at[i, "block_convexity_raw"] = raw_metrics.get("geom_convexity", np.nan)
            out.at[i, "block_compactness_raw"] = raw_metrics.get("geom_compactness", np.nan)
            out.at[i, "block_mbr_aspect_raw"] = raw_metrics.get("geom_mbr_aspect", np.nan)
            out.at[i, "geom_area_match_10pct"] = bool(np.isfinite(b_ratio) and abs(b_ratio - 1.0) <= 0.10)
            out.at[i, "geom_area_match_20pct"] = bool(np.isfinite(b_ratio) and abs(b_ratio - 1.0) <= 0.20)
            out.at[i, "geom_area_match_30pct"] = bool(np.isfinite(b_ratio) and abs(b_ratio - 1.0) <= 0.30)
            pass_main = bool(np.isfinite(b_ratio) and abs(b_ratio - 1.0) <= tolerance)
            out.at[i, "geom_area_match_main"] = pass_main
            if pass_main:
                out.at[i, "geometry_source"] = f"block_2025_area_match_{int(round(tolerance*100))}pct"
                for k, v in raw_metrics.items():
                    out.at[i, k] = v

        if s is not None:
            out.at[i, "point_inside_skifte_2025"] = True
            s_area = float(s.geometry.area) / 10000.0
            s_ratio, s_diff = ratio_and_diff(s_area, sale_area)
            out.at[i, "skifte_geom_area_ha"] = s_area
            out.at[i, "skifte_area_ratio_to_sale"] = s_ratio
            out.at[i, "skifte_area_abs_pct_diff"] = s_diff

    return out


def geometry_sensitivity(v0a, enriched: pd.DataFrame, outdir: Path) -> pd.DataFrame:
    """Rectangularity sensitivity for 10/20/30% block-area agreement."""
    rows = []
    for pct, flag in [(10, "geom_area_match_10pct"), (20, "geom_area_match_20pct"), (30, "geom_area_match_30pct")]:
        if flag not in enriched:
            continue
        x = enriched.loc[enriched[flag].fillna(False).astype(bool)].copy()
        x["geom_rect_sensitivity"] = pd.to_numeric(x.get("block_rectangularity_raw"), errors="coerce")
        model = v0a.complete_subset(x, ["geom_rect_sensitivity"])
        base_loo = aug_loo = delta = med_ape = np.nan
        if len(model) >= 12:
            X0, yy, _ = v0a.design(model)
            X1, _, _ = v0a.design(model, ["geom_rect_sensitivity"])
            if np.linalg.matrix_rank(X1) == X1.shape[1]:
                p0 = v0a.loo_predictions(X0, yy)
                p1 = v0a.loo_predictions(X1, yy)
                base_loo = v0a.r2_score(yy, p0)
                aug_loo = v0a.r2_score(yy, p1)
                delta = aug_loo - base_loo
                med_ape = 100.0 * float(np.median(v0a.pct_error_from_log(yy, p1)))
        rows.append({
            "area_tolerance_pct": pct,
            "n_block_area_matches": len(x),
            "n_rectangularity_model": len(model),
            "share_of_clean_pct": 100.0 * len(x) / max(1, len(enriched)),
            "median_block_area_abs_pct_diff": float(pd.to_numeric(x.block_area_abs_pct_diff, errors="coerce").median()) if len(x) else np.nan,
            "rect_loo_r2_baseline_same_n": base_loo,
            "rect_loo_r2_augmented": aug_loo,
            "rect_delta_loo_r2": delta,
            "rect_median_abs_pct_error_loo": med_ape,
        })
    s = pd.DataFrame(rows)
    s.to_csv(outdir / "geometry_area_match_sensitivity.csv", index=False, encoding="utf-8-sig")
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--atl", help="ATL_AkerSync_*_v03.csv; om utelämnad öppnas filväljare")
    ap.add_argument("--radius-m", type=float, default=100.0)
    ap.add_argument("--since", default="2020-07-01", help="Första försäljningsdatum i v0b-sample")
    ap.add_argument("--geom-area-tolerance", type=float, default=0.20,
                    help="Tillåten relativ skillnad blockarea vs såld åkerarea, default 0.20")
    ap.add_argument("--baseline-only", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    v0a = load_v0a(root)

    cfg_path = root / args.config
    if not cfg_path.exists():
        raise RuntimeError(f"Saknar {cfg_path}. Kopiera config/local_paths.json från din vanliga ÅkerSync-worktree.")
    cfg = v0a.load_config(cfg_path)

    atl = args.atl or v0a.choose_atl_csv()
    if not atl:
        print("Avbrutet: ingen ATL CSV vald.")
        return 2
    atl_csv = Path(atl)
    if not atl_csv.exists():
        raise FileNotFoundError(atl_csv)

    since = pd.Timestamp(args.since)
    tol = float(args.geom_area_tolerance)
    if not (0.0 < tol < 1.0):
        raise ValueError("--geom-area-tolerance måste ligga mellan 0 och 1")

    outdir = root / cfg.get("build_dir", "data/derived") / "value_regression_v0b"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print("ÅkerSync · Value Regression v0b")
    print("=" * 84)
    print("ATL:", atl_csv)
    print("Output:", outdir)
    print("Sample start:", since.date())
    print(f"Geometry block-area tolerance: ±{100*tol:.0f}%")
    print(f"Punkt-neighbourhood: {args.radius_m:g} m")
    print()

    audit, clean_all = v0a.load_and_select_clean(atl_csv)
    audit_dates = pd.to_datetime(audit["datum"], errors="coerce")
    audit["q_v0b_date_window"] = audit_dates.ge(since)
    audit["selected_clean_v0b"] = audit["selected_clean"].fillna(False).astype(bool) & audit["q_v0b_date_window"].fillna(False).astype(bool)
    audit["exclusion_reason_v0b"] = audit["exclusion_reason"].fillna("")
    older = ~audit["q_v0b_date_window"].fillna(False).astype(bool)
    audit.loc[older, "exclusion_reason_v0b"] = audit.loc[older, "exclusion_reason_v0b"].apply(
        lambda s: (str(s) + " | " if str(s) else "") + f"datum<{since.date()}"
    )
    clean = clean_all.loc[pd.to_datetime(clean_all["datum"], errors="coerce").ge(since)].copy().reset_index(drop=True)

    audit.to_csv(outdir / "selection_audit.csv", index=False, encoding="utf-8-sig")
    clean.to_csv(outdir / "clean_cases.csv", index=False, encoding="utf-8-sig")

    raw_n = len(pd.read_csv(atl_csv, sep=";", encoding="utf-8-sig"))
    print(f"ATL-rader:                 {raw_n:,}")
    print(f"Unika transaktioner:       {len(audit):,}")
    print(f"Rena case före datumfilter:{len(clean_all):8,d}")
    print(f"Rena v0b-case:             {len(clean):8,d}")
    print()

    enriched = clean.copy()
    if not args.baseline_only:
        print("[1/3] Matchar punkt mot 2025 block/skifte; QA mot såld åkerarea...")
        enriched = add_geometry_matches_v0b(enriched, cfg, v0a, tol)
        print("[2/3] Samplar jord 20 m vid punkt + 100 m...")
        enriched = v0a.add_soil_features(enriched, cfg, args.radius_m)
        print("[3/3] Samplar TWI/topografi vid punkt + 100 m...")
        enriched = v0a.add_hydro_topo_features(enriched, cfg, args.radius_m)

    enriched.to_csv(outdir / "point_features.csv", index=False, encoding="utf-8-sig")
    if "block_area_abs_pct_diff" in enriched.columns:
        enriched[[c for c in [
            "sale_id", "datum", "fastighetsbeteckning", "municipality_county",
            "akermark_ha_n", "point_inside_block_2025", "block_geom_area_ha",
            "block_area_ratio_to_sale", "block_area_abs_pct_diff",
            "block_rectangularity_raw", "block_convexity_raw", "block_compactness_raw", "block_mbr_aspect_raw",
            "geom_area_match_10pct", "geom_area_match_20pct", "geom_area_match_30pct",
            "point_inside_skifte_2025", "skifte_geom_area_ha", "skifte_area_ratio_to_sale",
            "skifte_area_abs_pct_diff", "geometry_source",
        ] if c in enriched.columns]].to_csv(
            outdir / "geometry_area_match.csv", index=False, encoding="utf-8-sig"
        )
        sens = geometry_sensitivity(v0a, enriched, outdir)
    else:
        sens = pd.DataFrame()

    result = v0a.run_models(enriched, outdir)

    lines = []
    lines.append("ÅkerSync Value Regression v0b")
    lines.append("=" * 72)
    lines.append(f"ATL source: {atl_csv}")
    lines.append(f"Unique transactions after dedup: {len(audit)}")
    lines.append(f"Clean cases before date window: {len(clean_all)}")
    lines.append(f"Sample start: {since.date()}")
    lines.append(f"Clean v0b cases: {len(clean)}")
    if "point_inside_block_2025" in enriched.columns:
        lines.append(f"Point inside 2025 block: {int(enriched.point_inside_block_2025.fillna(False).sum())}/{len(enriched)}")
    if "point_inside_skifte_2025" in enriched.columns:
        lines.append(f"Point inside 2025 skifte: {int(enriched.point_inside_skifte_2025.fillna(False).sum())}/{len(enriched)}")
    if "geom_area_match_main" in enriched.columns:
        lines.append(f"Block area match ±{100*tol:.0f}%: {int(enriched.geom_area_match_main.fillna(False).sum())}/{len(enriched)}")
        dif = pd.to_numeric(enriched.block_area_abs_pct_diff, errors="coerce")
        lines.append(f"Median |block area / sold arable area - 1|: {dif.median():.1f}%")
    if len(sens):
        lines.append("Geometry object-ID sensitivity:")
        for _, r in sens.iterrows():
            tail = ""
            if pd.notna(r.get("rect_delta_loo_r2")):
                tail = f", rectangularity ΔLOO={r.rect_delta_loo_r2:+.4f}"
            lines.append(f"  ±{int(r.area_tolerance_pct)}%: {int(r.n_block_area_matches)}/{len(enriched)} plausible single-block sales{tail}")
    lines.append("")
    lines.append("BASELINE")
    lines.append("log(kr/åker-ha) ~ year + log(area) + lat + lon")
    lines.append(f"n={result['n']}")
    lines.append(f"R2={result['r2']:.6f}")
    lines.append(f"Adjusted R2={result['adj_r2']:.6f}")
    lines.append(f"LOO R2={result['loo_r2']:.6f}")
    lines.append(f"LOO median absolute percentage error={result['median_abs_pct_error_loo']:.2f}%")
    lines.append("")
    lines.append("Coefficients:")
    for n, b in zip(result["names"], result["beta"]):
        lines.append(f"  {n:18s} {b: .8f}")
    comp = result["comparison"]
    if len(comp):
        lines.append("")
        lines.append("MODEL COMPARISON — sorted by Δ LOO R2")
        for _, r in comp.iterrows():
            lines.append(
                f"  {r['feature']}: n={int(r['n'])}, "
                f"LOO={r['loo_r2_augmented']:.4f}, Δ={r['delta_loo_r2']:+.4f}, "
                f"medianAPE={r['median_abs_pct_error_loo']:.1f}%"
            )
    lines.append("")
    lines.append("Geometry predictors are admitted only for block-area-matched cases.")
    lines.append("A match is QA evidence, not cadastral identification.")
    lines.append("Primary decision metric: Δ LOO R2 versus baseline on the SAME rows.")
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")

    print()
    print(report)
    print("Outputfiler:")
    for name in [
        "selection_audit.csv", "clean_cases.csv", "point_features.csv",
        "geometry_area_match.csv", "geometry_area_match_sensitivity.csv",
        "baseline_coefficients.csv", "baseline_loo_predictions.csv",
        "model_comparison.csv", "report.txt",
    ]:
        p = outdir / name
        if p.exists():
            print(" ", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
