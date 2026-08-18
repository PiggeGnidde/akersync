#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0f — 1971 agricultural productivity class.

Question
--------
How much of modern observed farmland price/ha is explained by the historic
Swedish agricultural productivity class (1–10), and how much geographic price
structure remains after the class is included?

Primary class feature
---------------------
For each ATL sale, reconstruct the sold agricultural area using the already
established v0c multi-block algorithm (location + sold hectares only). Intersect
those selected 2025 agricultural blocks with the historic class polygons and
calculate an area-weighted class. Main regressions require:
  * reconstruction area match within ±20%; and
  * at least 80% of reconstructed block area covered by the historic class map.

The historic class is kept OUT of the reconstruction algorithm, so class cannot
circularly influence which blocks are selected.

Important interpretation
------------------------
The 1971 class is an old production-potential classification, not a modern soil
measurement. A strong price association can reflect productivity reputation,
location, climate, market geography, or correlated omitted variables. This
script tests predictive/pricing structure; it does not prove causal value.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape

import value_multiblock as mb

LAYER_URL = "https://kartportal.ystad.se/arcgis/rest/services/SAM/SAM_OP_Hansyn/MapServer/32"
QUERY_URL = LAYER_URL + "/query"
CLASS_MIN = 1
CLASS_MAX = 10
DEFAULT_CLASS_COVERAGE_PCT = 80.0

TA = ["year_centered", "log_area_20"]
G1 = TA + ["lat_centered", "lon_centered"]
G2 = G1 + ["lat2", "lon2", "lat_lon"]
CLASS = "class1971_tx_mean_aw"
CLASS_SQ = "class1971_tx_mean_aw_sq"
POINT_CLASS = "class1971_point"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def numeric(s):
    return pd.to_numeric(s, errors="coerce")


def add_geo_terms(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["lat2"] = numeric(out["lat_centered"]) ** 2
    out["lon2"] = numeric(out["lon_centered"]) ** 2
    out["lat_lon"] = numeric(out["lat_centered"]) * numeric(out["lon_centered"])
    return out


def arcgis_get(params, timeout=120):
    url = QUERY_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AkerSync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download_class_polygons(class_min=CLASS_MIN, class_max=CLASS_MAX):
    features = []
    offset = 0
    page_size = 1000
    where = f"KLASS >= {class_min} AND KLASS <= {class_max}"
    while True:
        data = arcgis_get({
            "where": where,
            "outFields": "OBJECTID_12,KLASS",
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": "OBJECTID_12",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "geojson",
        })
        if "error" in data:
            raise RuntimeError("ArcGIS query failed: " + json.dumps(data["error"], ensure_ascii=False))
        batch = data.get("features", [])
        features.extend(batch)
        print(f"\rDownloaded class polygons: {len(features):,}", end="", flush=True)
        if len(batch) < page_size:
            break
        offset += len(batch)
    print()
    if not features:
        raise RuntimeError("No 1971 agricultural class polygons returned.")
    rows, geoms = [], []
    for f in features:
        p = f.get("properties", {})
        rows.append({"OBJECTID_12": p.get("OBJECTID_12"), "KLASS": p.get("KLASS")})
        geoms.append(shape(f.get("geometry")))
    g = gpd.GeoDataFrame(rows, geometry=geoms, crs=4326)
    g["KLASS"] = numeric(g["KLASS"]).astype("Int64")
    g = g[g["KLASS"].between(class_min, class_max) & g.geometry.notna() & ~g.geometry.is_empty].copy()
    return g.to_crs(3006)


def load_classes(outdir: Path, refresh: bool):
    cache = outdir / "source" / "jord_skogsklassificering_class1_10.gpkg"
    if cache.exists() and not refresh:
        print("Using cached 1971 class polygons:", cache)
        return gpd.read_file(cache, layer="class1_10").to_crs(3006)
    print("Downloading historic agricultural classes 1–10...")
    g = download_class_polygons()
    cache.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(cache, layer="class1_10", driver="GPKG")
    print("Cached:", cache)
    return g


def dissolve_classes(classes: gpd.GeoDataFrame):
    d = classes[["KLASS", "geometry"]].dissolve(by="KLASS").reset_index()
    d["KLASS"] = numeric(d["KLASS"]).astype(int)
    return d.sort_values("KLASS").reset_index(drop=True)


def point_classes(clean: pd.DataFrame, dissolved: gpd.GeoDataFrame):
    pts = gpd.GeoDataFrame(
        clean[["sale_id"]].copy(),
        geometry=gpd.points_from_xy(clean["lon_n"], clean["lat_n"]),
        crs=4326,
    ).to_crs(3006)
    out = []
    sidx = dissolved.sindex
    for sid, p in zip(pts["sale_id"], pts.geometry):
        try:
            cand = list(sidx.query(p, predicate="intersects"))
        except Exception:
            cand = list(sidx.query(p))
        hits = []
        for j in cand:
            r = dissolved.iloc[int(j)]
            if r.geometry.covers(p):
                hits.append(int(r.KLASS))
        out.append({"sale_id": sid, POINT_CLASS: hits[0] if len(hits) == 1 else (min(hits) if hits else np.nan),
                    "class1971_point_multiple_hits": len(hits) > 1})
    return pd.DataFrame(out)


def block_class_areas(block_geom, dissolved: gpd.GeoDataFrame):
    if block_geom is None or block_geom.is_empty or block_geom.area <= 0:
        return {}, 0.0
    areas = {}
    try:
        cand = list(dissolved.sindex.query(block_geom, predicate="intersects"))
    except Exception:
        cand = list(dissolved.sindex.query(block_geom))
    for j in cand:
        r = dissolved.iloc[int(j)]
        inter = block_geom.intersection(r.geometry)
        if inter is None or inter.is_empty:
            continue
        a = float(inter.area)
        if a > 0:
            k = int(r.KLASS)
            areas[k] = areas.get(k, 0.0) + a
    return areas, float(block_geom.area)


def add_transaction_classes(enriched: pd.DataFrame, members: pd.DataFrame, cfg: dict,
                            dissolved: gpd.GeoDataFrame, min_coverage_pct: float):
    blocks_path = Path(cfg.get("blocks", ""))
    if not blocks_path.exists():
        raise FileNotFoundError(f"Blockfil saknas: {blocks_path}")
    blocks = gpd.read_file(blocks_path).to_crs(3006).copy()
    blocks["blockid"] = blocks["blockid"].astype(str)
    block_map = dict(zip(blocks["blockid"], blocks.geometry))

    cache = {}
    relevant = sorted(set(members.get("blockid", pd.Series(dtype=str)).astype(str)))
    print(f"Intersecting {len(relevant):,} reconstructed blocks with 1971 classes...")
    for n, bid in enumerate(relevant, 1):
        geom = block_map.get(bid)
        cache[bid] = block_class_areas(geom, dissolved)
        if n % 100 == 0 or n == len(relevant):
            print(f"\r  class overlay {n:,}/{len(relevant):,}", end="", flush=True)
    print()

    rows = []
    for sid, m in members.groupby("sale_id", sort=False):
        by_class = {k: 0.0 for k in range(CLASS_MIN, CLASS_MAX + 1)}
        total_area_m2 = 0.0
        classified_m2 = 0.0
        for bid in m["blockid"].astype(str):
            areas, block_area = cache.get(bid, ({}, 0.0))
            total_area_m2 += block_area
            for k, a in areas.items():
                by_class[k] += a
                classified_m2 += a
        coverage = 100.0 * classified_m2 / total_area_m2 if total_area_m2 > 0 else np.nan
        if classified_m2 > 0:
            mean = sum(k * a for k, a in by_class.items()) / classified_m2
            var = sum(a * (k - mean) ** 2 for k, a in by_class.items()) / classified_m2
            mode = max(by_class, key=lambda k: by_class[k])
            nonzero = [k for k, a in by_class.items() if a > 0]
            row = {
                "sale_id": sid,
                "class1971_tx_mean_aw": float(mean),
                "class1971_tx_sd_aw": float(math.sqrt(max(var, 0.0))),
                "class1971_tx_mode": int(mode),
                "class1971_tx_mode_share_pct": 100.0 * by_class[mode] / classified_m2,
                "class1971_tx_min": min(nonzero),
                "class1971_tx_max": max(nonzero),
                "class1971_tx_coverage_pct": coverage,
                "class1971_tx_classified_area_ha": classified_m2 / 10000.0,
            }
            for k in range(CLASS_MIN, CLASS_MAX + 1):
                row[f"class1971_tx_share_{k}_pct"] = 100.0 * by_class[k] / classified_m2
        else:
            row = {"sale_id": sid, "class1971_tx_coverage_pct": coverage}
        rows.append(row)

    tx = pd.DataFrame(rows)
    out = enriched.merge(tx, on="sale_id", how="left", validate="one_to_one")
    out[CLASS_SQ] = numeric(out.get(CLASS)) ** 2
    out["class1971_main_eligible"] = (
        out["tx_recon_match_20pct"].fillna(False).astype(bool)
        & numeric(out["class1971_tx_coverage_pct"]).ge(min_coverage_pct)
        & numeric(out[CLASS]).notna()
    )
    return out


def complete(df: pd.DataFrame, terms: list[str]):
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


def eval_model(v0a, df: pd.DataFrame, label: str, terms: list[str]):
    x = complete(df, terms)
    if len(x) < max(12, len(terms) + 5):
        return None
    X, y, names = design(x, terms)
    if np.linalg.matrix_rank(X) < X.shape[1]:
        return None
    beta, pred, r2, adj, rank, se, pv = v0a.fit_ols(X, y)
    loo = v0a.loo_predictions(X, y)
    return {
        "model": label,
        "terms": terms,
        "n": len(x),
        "train_r2": r2,
        "adj_r2": adj,
        "loo_r2": v0a.r2_score(y, loo),
        "median_abs_pct_error_loo": 100.0 * float(np.median(v0a.pct_error_from_log(y, loo))),
        "names": names,
        "beta": beta,
        "se": se,
        "p_value": pv,
        "data": x,
        "y": y,
        "loo": loo,
    }


def run_ladder(v0a, main: pd.DataFrame, outdir: Path):
    specs = [
        ("K_ONLY_class1971", [CLASS]),
        ("K_ONLY_class1971_quadratic", [CLASS, CLASS_SQ]),
        ("YEAR_CLASS", ["year_centered", CLASS]),
        ("TA_year_area", TA),
        ("TA_CLASS", TA + [CLASS]),
        ("TA_CLASS_QUAD", TA + [CLASS, CLASS_SQ]),
        ("YEAR_LAT_LON", ["year_centered", "lat_centered", "lon_centered"]),
        ("G1_year_area_lat_lon", G1),
        ("G1_CLASS", G1 + [CLASS]),
        ("G2_quadratic_geo", G2),
        ("G2_CLASS", G2 + [CLASS]),
        ("G2_CLASS_QUAD", G2 + [CLASS, CLASS_SQ]),
    ]
    rows, coef_rows, pred_rows = [], [], []
    fits = {}
    for label, terms in specs:
        r = eval_model(v0a, main, label, terms)
        if r is None:
            continue
        fits[label] = r
        rows.append({
            "model": label,
            "terms": " + ".join(terms),
            "n": r["n"],
            "train_r2": r["train_r2"],
            "adj_r2": r["adj_r2"],
            "loo_r2": r["loo_r2"],
            "median_abs_pct_error_loo": r["median_abs_pct_error_loo"],
        })
        for nm, b, se, p in zip(r["names"], r["beta"], r["se"], r["p_value"]):
            coef_rows.append({"model": label, "term": nm, "coefficient": b, "std_error": se, "p_value": p})
        d = r["data"]
        for i in range(len(d)):
            pred_rows.append({
                "model": label,
                "sale_id": d.iloc[i].get("sale_id", ""),
                "datum": d.iloc[i].get("datum", ""),
                "class1971_tx_mean_aw": d.iloc[i].get(CLASS, np.nan),
                "observed_kr_per_ha": float(np.exp(r["y"][i])),
                "loo_pred_kr_per_ha": float(np.exp(r["loo"][i])),
                "loo_log_residual": float(r["y"][i] - r["loo"][i]),
                "observed_to_pred_ratio": float(np.exp(r["y"][i] - r["loo"][i])),
                "abs_pct_error": 100.0 * float(v0a.pct_error_from_log([r["y"][i]], [r["loo"][i]])[0]),
            })
    comp = pd.DataFrame(rows).sort_values("loo_r2", ascending=False)
    comp.to_csv(outdir / "class1971_model_comparison.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(outdir / "class1971_model_coefficients.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(pred_rows).to_csv(outdir / "class1971_model_loo_predictions.csv", index=False, encoding="utf-8-sig")

    nested = []
    for base, aug in [("TA_year_area", "TA_CLASS"), ("G1_year_area_lat_lon", "G1_CLASS"), ("G2_quadratic_geo", "G2_CLASS")]:
        if base in fits and aug in fits and fits[base]["n"] == fits[aug]["n"]:
            nested.append({
                "baseline": base,
                "augmented": aug,
                "n": fits[base]["n"],
                "baseline_loo_r2": fits[base]["loo_r2"],
                "augmented_loo_r2": fits[aug]["loo_r2"],
                "delta_loo_r2": fits[aug]["loo_r2"] - fits[base]["loo_r2"],
                "baseline_median_ape": fits[base]["median_abs_pct_error_loo"],
                "augmented_median_ape": fits[aug]["median_abs_pct_error_loo"],
            })
    nested_df = pd.DataFrame(nested)
    nested_df.to_csv(outdir / "class1971_incremental_tests.csv", index=False, encoding="utf-8-sig")
    return comp, nested_df, fits


def run_point_sensitivity(v0a, df: pd.DataFrame, outdir: Path):
    z = df[numeric(df[POINT_CLASS]).notna()].copy()
    z["class1971_point_sq"] = numeric(z[POINT_CLASS]) ** 2
    specs = [
        ("POINT_K_ONLY", [POINT_CLASS]),
        ("POINT_TA_CLASS", TA + [POINT_CLASS]),
        ("POINT_G1_CLASS", G1 + [POINT_CLASS]),
        ("POINT_G2_CLASS", G2 + [POINT_CLASS]),
    ]
    rows = []
    for label, terms in specs:
        r = eval_model(v0a, z, label, terms)
        if r is not None:
            rows.append({"model": label, "n": r["n"], "loo_r2": r["loo_r2"],
                         "median_abs_pct_error_loo": r["median_abs_pct_error_loo"]})
    pd.DataFrame(rows).to_csv(outdir / "point_class1971_sensitivity.csv", index=False, encoding="utf-8-sig")


def class_price_summary(main: pd.DataFrame, outdir: Path):
    z = main.copy()
    z["class_mode"] = numeric(z["class1971_tx_mode"])
    rows = []
    for k, q in z.dropna(subset=["class_mode"]).groupby("class_mode"):
        p = numeric(q["kr_per_aker_ha"]).dropna()
        rows.append({
            "class1971_tx_mode": int(k),
            "n_sales": len(q),
            "median_kr_per_ha": float(p.median()) if len(p) else np.nan,
            "mean_kr_per_ha": float(p.mean()) if len(p) else np.nan,
            "p25_kr_per_ha": float(p.quantile(0.25)) if len(p) else np.nan,
            "p75_kr_per_ha": float(p.quantile(0.75)) if len(p) else np.nan,
            "median_area_ha": float(numeric(q["akermark_ha_n"]).median()),
            "median_year": float(numeric(q["year"]).median()),
        })
    pd.DataFrame(rows).sort_values("class1971_tx_mode").to_csv(outdir / "observed_price_by_class1971.csv", index=False, encoding="utf-8-sig")


def pricing_residual_candidates(fits: dict, main: pd.DataFrame, outdir: Path):
    preferred = "TA_CLASS" if "TA_CLASS" in fits else "K_ONLY_class1971"
    if preferred not in fits:
        return pd.DataFrame()
    r = fits[preferred]
    d = r["data"].copy()
    d["pricing_model"] = preferred
    d["loo_pred_kr_per_ha_class_model"] = np.exp(r["loo"])
    d["observed_to_class_model_ratio"] = np.exp(r["y"] - r["loo"])
    d["class_model_log_residual"] = r["y"] - r["loo"]
    keep = [
        "sale_id", "datum", "fastighetsbeteckningar", "akermark_ha_n", "kr_per_aker_ha",
        "class1971_tx_mean_aw", "class1971_tx_sd_aw", "class1971_tx_mode",
        "class1971_tx_mode_share_pct", "class1971_tx_coverage_pct", "tx_recon_area_abs_pct_diff",
        "lat_n", "lon_n", "pricing_model", "loo_pred_kr_per_ha_class_model",
        "observed_to_class_model_ratio", "class_model_log_residual",
    ]
    z = d[[c for c in keep if c in d.columns]].copy()
    z = z.sort_values("class_model_log_residual")
    z.to_csv(outdir / "class1971_pricing_residual_candidates.csv", index=False, encoding="utf-8-sig")
    return z


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--atl", help="ATL_AkerSync_*_v03.csv; om utelämnad öppnas filväljare")
    ap.add_argument("--since", default="2020-07-01")
    ap.add_argument("--recon-radius-m", type=float, default=3000.0)
    ap.add_argument("--max-link-gap-m", type=float, default=750.0)
    ap.add_argument("--max-blocks", type=int, default=15)
    ap.add_argument("--class-coverage-pct", type=float, default=DEFAULT_CLASS_COVERAGE_PCT)
    ap.add_argument("--refresh-class-map", action="store_true")
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
    outdir = root / cfg.get("build_dir", "data/derived") / "value_regression_v0f_class1971"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 94)
    print("ÅkerSync · Value Regression v0f · 1971 agricultural class")
    print("=" * 94)
    print("ATL:", atl)
    print("Output:", outdir)
    print("Sample start:", since.date())
    print(f"Main class coverage gate: >= {args.class_coverage_pct:.0f}%")
    print("Main class feature: area-weighted class across reconstructed sold blocks.")
    print()

    audit, all_clean = v0a.load_and_select_clean(atl)
    clean = all_clean.loc[pd.to_datetime(all_clean["datum"], errors="coerce").ge(since)].copy().reset_index(drop=True)
    clean = add_geo_terms(clean)
    audit.to_csv(outdir / "selection_audit.csv", index=False, encoding="utf-8-sig")

    print(f"Clean cases after date window: {len(clean):,}")
    classes = load_classes(outdir, args.refresh_class_map)
    dissolved = dissolve_classes(classes)
    print("Historic classes found:", sorted(dissolved["KLASS"].unique().tolist()))

    pc = point_classes(clean, dissolved)
    enriched = clean.merge(pc, on="sale_id", how="left", validate="one_to_one")

    print("Reconstructing sold block sets (location + area only)...")
    enriched, members = mb.add_features(
        enriched, cfg, v0a, args.recon_radius_m, args.max_link_gap_m, args.max_blocks
    )
    enriched = add_transaction_classes(enriched, members, cfg, dissolved, args.class_coverage_pct)
    enriched = add_geo_terms(enriched)
    enriched.to_csv(outdir / "class1971_features_all.csv", index=False, encoding="utf-8-sig")
    members.to_csv(outdir / "multiblock_members.csv", index=False, encoding="utf-8-sig")

    main = enriched[enriched["class1971_main_eligible"].fillna(False).astype(bool)].copy().reset_index(drop=True)
    main.to_csv(outdir / "class1971_main_sample.csv", index=False, encoding="utf-8-sig")
    class_price_summary(main, outdir)
    comp, nested, fits = run_ladder(v0a, main, outdir)
    run_point_sensitivity(v0a, enriched, outdir)
    residuals = pricing_residual_candidates(fits, main, outdir)

    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "historic_class_layer": LAYER_URL,
        "class_range": [CLASS_MIN, CLASS_MAX],
        "sample_start": str(since.date()),
        "reconstruction_match_gate_pct": 20,
        "class_coverage_gate_pct": args.class_coverage_pct,
        "primary_class_feature": CLASS,
    }
    (outdir / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "ÅkerSync Value Regression v0f — 1971 agricultural productivity class",
        "=" * 82,
        f"ATL source: {atl}",
        f"Clean cases after {since.date()}: {len(clean)}",
        f"Point class available: {int(numeric(enriched[POINT_CLASS]).notna().sum())}/{len(enriched)}",
        f"Reconstruction ±20%: {int(enriched['tx_recon_match_20pct'].fillna(False).sum())}/{len(enriched)}",
        f"Main class sample (±20% recon + >= {args.class_coverage_pct:.0f}% class coverage): {len(main)}/{len(enriched)}",
        "",
        "PRIMARY QUESTION",
        "Does the old productivity class explain modern log(price/ha), and does it replace or add to lat/lon geography?",
        "",
        "MODEL LADDER — all main models use the same class-eligible transaction sample",
    ]
    for _, r in comp.sort_values("loo_r2", ascending=False).iterrows():
        lines.append(
            f"  {r['model']}: n={int(r['n'])}, LOO R2={r['loo_r2']:.4f}, "
            f"train R2={r['train_r2']:.4f}, medianAPE={r['median_abs_pct_error_loo']:.1f}%"
        )
    if len(nested):
        lines += ["", "INCREMENTAL CLASS TESTS — same rows"]
        for _, r in nested.iterrows():
            lines.append(
                f"  {r['baseline']} -> {r['augmented']}: LOO {r['baseline_loo_r2']:.4f} -> "
                f"{r['augmented_loo_r2']:.4f}, delta={r['delta_loo_r2']:+.4f}"
            )
    if len(residuals):
        lines += ["", "PRICING RESIDUAL OUTPUT",
                  "class1971_pricing_residual_candidates.csv ranks sales relative to the LOO year+area+class model.",
                  "ratio <1 = cheaper than class-model prediction; ratio >1 = dearer than prediction."]
    lines += [
        "",
        "GUARDRAILS",
        "- 1971 class is a historic production-potential class, not a direct modern soil measurement.",
        "- Transaction class is a proxy based on reconstructed 2025 blocks, not cadastral sale geometry.",
        "- A strong class-price relation can still be geographic/confounded; G1/G2 + class tests address this descriptively.",
        "- Point-class models are sensitivity only because ATL coordinates can be an address/farm-centre proxy.",
        "- Pricing residuals are candidate mispricing diagnostics, not proof of arbitrage or intrinsic value.",
    ]
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
