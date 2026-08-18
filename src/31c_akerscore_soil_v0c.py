#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerScore Soil v0c · tail-aware display scale + skifte-level spatial variation.

v0c keeps the scientifically useful raw v0a/v0b soil signal unchanged and
changes only the human-facing 0-100 display mapping.  It then applies the
frozen model to every current skifte pixel-by-pixel so a field receives both a
central ÅkerScore and its within-field P10-P90 variation.

Important distinction
---------------------
P10-P90 here is SPATIAL VARIATION across mapped 20 m soil pixels inside the
field.  It is not a statistical confidence interval.  ÅkerVärde may have a
separate model-uncertainty interval; the two must not be labelled the same.

Training / validation
---------------------
* Training signal: historic Swedish productivity classes 5-10 over current
  farmland, as in v0a.
* Raw model: ILR(texture) + DSMS organic-matter proxy cloud model, unchanged.
* 0-100 display scale: class medians -> 45,55,...,95 plus explicit class-10
  upper-tail anchors so elite fields do not all saturate at 100.
* German Groß et al. Triesdorf references are scored after the Swedish model
  and calibration are frozen.  Rank checks use RAW score first, display score
  second; display clipping must never decide scientific ordering.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask


VERSION = "akerscore_soil_v0c"
TAIL_TARGETS = {
    "class10_p90": 98.0,
    "class10_p99": 99.5,
    "class10_p999": 100.0,
}
MIN_VALID_PIXELS = 3


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fit_tail_calibration(scored_training: pd.DataFrame):
    """Build transparent monotone raw->display knots.

    Core anchors preserve the requested 10-point class-centre convention.
    Upper-tail anchors reserve 100 for roughly the most extreme 0.1% of the
    class-10 reference distribution instead of clipping every elite tuple.
    """
    rows = []
    for klass, target in zip(range(5, 11), [45., 55., 65., 75., 85., 95.]):
        q = scored_training.loc[
            scored_training["historic_class"].eq(klass), "raw_score"
        ].dropna().to_numpy(float)
        if len(q) == 0:
            raise RuntimeError(f"No raw training scores for class {klass}")
        rows.append({
            "anchor": f"class{klass}_median",
            "raw": float(np.median(q)),
            "display": target,
        })

    q10 = scored_training.loc[
        scored_training["historic_class"].eq(10), "raw_score"
    ].dropna().to_numpy(float)
    for label, quantile, target in [
        ("class10_p90", 0.90, TAIL_TARGETS["class10_p90"]),
        ("class10_p99", 0.99, TAIL_TARGETS["class10_p99"]),
        ("class10_p999", 0.999, TAIL_TARGETS["class10_p999"]),
    ]:
        rows.append({
            "anchor": label,
            "raw": float(np.quantile(q10, quantile)),
            "display": float(target),
        })

    rows = sorted(rows, key=lambda r: r["raw"])
    cleaned = []
    last_raw = -np.inf
    last_display = -np.inf
    for r in rows:
        raw = max(float(r["raw"]), last_raw + 1e-6)
        display = max(float(r["display"]), last_display + 1e-6)
        cleaned.append({"anchor": r["anchor"], "raw": raw, "display": display})
        last_raw, last_display = raw, display
    x = np.array([r["raw"] for r in cleaned], float)
    y = np.array([r["display"] for r in cleaned], float)
    return x, y, pd.DataFrame(cleaned)


def apply_tail_calibration(values, x, y):
    """Piecewise-linear display mapping with linear lower extrapolation.

    Above the final P99.9 class-10 anchor the display remains 100 by design.
    """
    v = np.asarray(values, float)
    out = np.interp(v, x, y)
    lo = v < x[0]
    if len(x) >= 2 and np.any(lo):
        slope = (y[1] - y[0]) / (x[1] - x[0])
        out[lo] = y[0] + slope * (v[lo] - x[0])
    return np.clip(out, 0.0, 100.0)


def rank_check(german: pd.DataFrame, score_col: str, label: str):
    rows = []
    for depth, q in german.groupby("depth_cm", sort=False):
        y_order = q.sort_values(["yield_t_ha", "cluster"])["cluster"].tolist()
        s_order = q.sort_values([score_col, "cluster"])["cluster"].tolist()
        rows.append({
            "score_type": label,
            "depth_cm": depth,
            "yield_order": " < ".join(y_order),
            "score_order": " < ".join(s_order),
            "exact_order": bool(y_order == s_order),
            "winner_correct": bool(
                q.loc[q["yield_t_ha"].idxmax(), "cluster"] ==
                q.loc[q[score_col].idxmax(), "cluster"]
            ),
        })
    return pd.DataFrame(rows)


def assign_historic_class_qa(skiften: gpd.GeoDataFrame, class_gpkg: Path):
    """Representative-point class label for QA summaries only; never used to score."""
    out = skiften.copy()
    out["historic_class_qa"] = np.nan
    if not class_gpkg.exists():
        return out
    classes = gpd.read_file(class_gpkg, layer="class5_10").to_crs(3006)
    classes["KLASS"] = pd.to_numeric(classes["KLASS"], errors="coerce")
    classes = classes[classes["KLASS"].between(5, 10)].copy()
    dissolved = classes[["KLASS", "geometry"]].dissolve(by="KLASS").reset_index()
    pts = out[["geometry"]].copy()
    pts["geometry"] = pts.representative_point()
    joined = gpd.sjoin(pts, dissolved[["KLASS", "geometry"]], how="left", predicate="within")
    if joined.index.duplicated().any():
        joined = joined[~joined.index.duplicated(keep="first")]
    out["historic_class_qa"] = pd.to_numeric(joined["KLASS"].reindex(out.index), errors="coerce")
    return out


def summarize_field_scores(field_gdf: gpd.GeoDataFrame):
    q = field_gdf[field_gdf["historic_class_qa"].between(5, 10)].copy()
    if q.empty:
        return pd.DataFrame()
    rows = []
    for klass, g in q.groupby("historic_class_qa"):
        s = g["akerscore_soil_p50"].dropna().to_numpy(float)
        if not len(s):
            continue
        rows.append({
            "historic_class_qa": int(klass),
            "n_skiften": int(len(s)),
            "field_score_mean": float(np.mean(s)),
            "field_score_p10": float(np.percentile(s, 10)),
            "field_score_p50": float(np.percentile(s, 50)),
            "field_score_p90": float(np.percentile(s, 90)),
            "median_within_field_p90_minus_p10": float(
                np.nanmedian(g["akerscore_soil_spread_p90_p10"].to_numpy(float))
            ),
        })
    return pd.DataFrame(rows)


def score_skiften(v0a, cfg: dict, model: dict, cal_x, cal_y, outdir: Path, max_skiften: int | None):
    skiften_path = Path(cfg.get("skiften", ""))
    soil_zip = Path(cfg.get("soil_zip", ""))
    if not skiften_path.exists():
        raise FileNotFoundError(f"Skiftefil saknas: {skiften_path}")
    if not soil_zip.exists():
        raise FileNotFoundError(f"soil_zip saknas: {soil_zip}")

    skiften = gpd.read_file(skiften_path).to_crs(3006)
    skiften = skiften[skiften.geometry.notna() & ~skiften.geometry.is_empty].copy().reset_index(drop=True)
    if max_skiften is not None:
        skiften = skiften.iloc[:max_skiften].copy()

    root = Path(__file__).resolve().parents[1]
    class_gpkg = root / cfg.get("build_dir", "data/derived") / "agri_class5_10_v0b" / "source" / "jord_skogsklassificering_class5_10.gpkg"
    skiften = assign_historic_class_qa(skiften, class_gpkg)

    records = []
    with tempfile.TemporaryDirectory(prefix="akerscore_v0c_") as td, zipfile.ZipFile(soil_zip) as zf:
        paths = {kind: v0a.extract_member(zf, base, td) for kind, base in v0a.SOIL_MEMBERS.items()}
        with rasterio.open(paths["clay"]) as clay, rasterio.open(paths["silt"]) as silt, rasterio.open(paths["sand"]) as sand, rasterio.open(paths["organic"]) as organic:
            dsmap = {"clay": clay, "silt": silt, "sand": sand, "organic": organic}
            ref = clay
            for kind, ds in dsmap.items():
                if not v0a.crs_is_3006(ds.crs):
                    raise RuntimeError(f"{paths[kind].name}: expected EPSG:3006, got {ds.crs}")
                if tuple(round(x, 6) for x in ds.res) != (20.0, 20.0):
                    raise RuntimeError(f"{paths[kind].name}: expected 20m pixels, got {ds.res}")
                if ds.width != ref.width or ds.height != ref.height or ds.transform != ref.transform:
                    raise RuntimeError(f"{paths[kind].name}: raster grids do not align")

            total = len(skiften)
            for n, (_, r) in enumerate(skiften.iterrows(), 1):
                geom = r.geometry
                rec = {
                    "row_index": n - 1,
                    "blockid": str(r.get("blockid", "")),
                    "skiftesbeteckning": str(r.get("skiftesbeteckning", "")),
                    "crop_code": r.get("grdkod_mar", np.nan),
                    "area_ha": float(geom.area / 10000.0),
                    "historic_class_qa": r.get("historic_class_qa", np.nan),
                    "soil_pixels_total": 0,
                    "soil_pixels_valid": 0,
                    "soil_coverage_pct": 0.0,
                    "akerscore_soil_p10": np.nan,
                    "akerscore_soil_p50": np.nan,
                    "akerscore_soil_p90": np.nan,
                    "akerscore_soil_mean": np.nan,
                    "akerscore_soil_sd": np.nan,
                    "akerscore_soil_spread_p90_p10": np.nan,
                    "raw_score_p50": np.nan,
                }
                w = v0a.geom_window(ref, geom)
                if w is not None:
                    tr = ref.window_transform(w)
                    shape2 = (int(w.height), int(w.width))
                    pmask = geometry_mask([geom.__geo_interface__], out_shape=shape2, transform=tr, invert=True, all_touched=False)
                    rec["soil_pixels_total"] = int(pmask.sum())
                    arr = {kind: ds.read(1, window=w, masked=False).astype(float) for kind, ds in dsmap.items()}
                    valid = pmask.copy()
                    for kind, ds in dsmap.items():
                        valid &= v0a.valid_mask(arr[kind], ds.nodata)
                    valid &= np.isin(arr["organic"].astype(int), list(v0a.ORG_PROXY_PCT))
                    valid &= arr["clay"] > 0
                    valid &= arr["silt"] > 0
                    valid &= arr["sand"] > 0
                    nv = int(valid.sum())
                    rec["soil_pixels_valid"] = nv
                    rec["soil_coverage_pct"] = 100.0 * nv / rec["soil_pixels_total"] if rec["soil_pixels_total"] else 0.0
                    if nv >= MIN_VALID_PIXELS:
                        org_code = arr["organic"][valid].astype(int)
                        pix = pd.DataFrame({
                            "historic_class": -1,
                            "clay_pct": arr["clay"][valid],
                            "silt_pct": arr["silt"][valid],
                            "sand_pct": arr["sand"][valid],
                            "mull_proxy_pct": np.array([v0a.ORG_PROXY_PCT[int(c)] for c in org_code], float),
                        })
                        pix_sc = v0a.score_df(pix, model, "raw")
                        raw = pix_sc["raw_score"].to_numpy(float)
                        disp = apply_tail_calibration(raw, cal_x, cal_y)
                        rec["raw_score_p50"] = float(np.median(raw))
                        rec["akerscore_soil_p10"] = float(np.percentile(disp, 10))
                        rec["akerscore_soil_p50"] = float(np.percentile(disp, 50))
                        rec["akerscore_soil_p90"] = float(np.percentile(disp, 90))
                        rec["akerscore_soil_mean"] = float(np.mean(disp))
                        rec["akerscore_soil_sd"] = float(np.std(disp, ddof=0))
                        rec["akerscore_soil_spread_p90_p10"] = rec["akerscore_soil_p90"] - rec["akerscore_soil_p10"]
                records.append(rec)
                if n % 500 == 0 or n == total:
                    print(f"  scored {n:,}/{total:,} skiften", flush=True)

    attrs = pd.DataFrame(records)
    out = skiften.reset_index(drop=True).copy()
    for col in attrs.columns:
        if col == "row_index":
            continue
        out[col] = attrs[col].to_numpy()

    csv_cols = [c for c in attrs.columns if c != "row_index"]
    attrs[csv_cols].to_csv(outdir / "akerscore_soil_skiften.csv", index=False, encoding="utf-8-sig")
    gpkg = outdir / "akerscore_soil_skiften.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    out.to_file(gpkg, layer="akerscore_soil_v0c", driver="GPKG")
    summary = summarize_field_scores(out)
    summary.to_csv(outdir / "skifte_class_score_summary.csv", index=False, encoding="utf-8-sig")
    return out, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--max-skiften", type=int, default=None, help="QA/debug cap; omit for all skiften")
    ap.add_argument("--rescore-fields", action="store_true", help="Force full pixel-by-pixel rescoring even if completed v0c field outputs already exist")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    v0a = load_module(root / "src" / "31_akerscore_soil_v0a.py", "akerscore_soil_v0a")
    cfg = v0a.load_config(root / args.config)
    base = root / cfg.get("build_dir", "data/derived")
    indir = base / "akerscore_soil_v0a"
    outdir = base / VERSION
    outdir.mkdir(parents=True, exist_ok=True)

    sample_path = indir / "training_sample.csv.gz"
    if not sample_path.exists():
        raise FileNotFoundError(f"Missing {sample_path}. Run RUN_AKERSCORE_SOIL_V0A.bat first.")

    print("=" * 92)
    print("ÅkerScore Soil v0c · tail-aware scale + skifte P10/P50/P90")
    print("=" * 92)
    print("Loading training sample:", sample_path)
    sample = pd.read_csv(sample_path)

    model = v0a.fit_cloud_model(sample, use_mull=True)
    train_sc = v0a.score_df(sample, model, "raw")
    cal_x, cal_y, knots = fit_tail_calibration(train_sc)
    knots.to_csv(outdir / "tail_calibration_knots.csv", index=False, encoding="utf-8-sig")

    german = v0a.german_reference_frame()
    german = v0a.score_df(german, model, "raw")
    german["akerscore_soil_v0c"] = apply_tail_calibration(german["raw_score"].to_numpy(float), cal_x, cal_y)
    german.to_csv(outdir / "german_triesdorf_reference_scores_v0c.csv", index=False, encoding="utf-8-sig")
    rank_raw = rank_check(german, "raw_score", "raw")
    rank_display = rank_check(german, "akerscore_soil_v0c", "display")
    ranks = pd.concat([rank_raw, rank_display], ignore_index=True)
    ranks.to_csv(outdir / "german_rank_check_v0c.csv", index=False, encoding="utf-8-sig")

    cached_gpkg = outdir / "akerscore_soil_skiften.gpkg"
    cached_summary = outdir / "skifte_class_score_summary.csv"
    can_reuse = (
        args.max_skiften is None
        and not args.rescore_fields
        and cached_gpkg.exists()
        and cached_summary.exists()
    )
    if can_reuse:
        print("\nCompleted field outputs already exist; reusing them (no 128k-skifte rescan).")
        field_gdf = gpd.read_file(cached_gpkg, layer="akerscore_soil_v0c")
        field_summary = pd.read_csv(cached_summary)
    else:
        print("\nScoring current skiften pixel-by-pixel...")
        field_gdf, field_summary = score_skiften(v0a, cfg, model, cal_x, cal_y, outdir, args.max_skiften)

    # IMPORTANT: valid_fields must be a GeoDataFrame/DataFrame, not the Boolean
    # Series returned by .notna().  The original v0c bug happened here, after
    # all 128,636 fields had already been scored and saved.
    valid_fields = field_gdf[field_gdf["akerscore_soil_p50"].notna()].copy()
    lines = [
        "ÅkerScore Soil v0c · tail-aware display scale + skifte spatial variation",
        "=" * 84,
        f"Training pixels: {len(sample):,}",
        f"Skiften scored: {len(field_gdf):,}; valid score: {len(valid_fields):,}",
        "Raw model: unchanged Swedish ILR(texture)+mull-proxy cloud model.",
        "Display centres: historic class medians -> 45/55/65/75/85/95.",
        "Upper tail: class-10 P90->98, P99->99.5, P99.9->100.",
        "Field output: median pixel score (P50) plus spatial P10/P90 and P90-P10 spread.",
        "P10-P90 is within-field mapped spatial variation, NOT a confidence interval.",
        "",
        "TAIL CALIBRATION KNOTS",
    ]
    for _, r in knots.iterrows():
        lines.append(f"  {r.anchor}: raw={r.raw:.3f} -> display={r.display:.2f}")

    lines += ["", "GERMAN EXTERNAL RANK CHECK (RAW SCORE IS PRIMARY)"]
    for _, r in ranks.iterrows():
        lines.append(
            f"  {r.score_type:7s} {r.depth_cm} cm: yield {r.yield_order}; "
            f"score {r.score_order}; exact={r.exact_order}; winner_correct={r.winner_correct}"
        )

    if len(valid_fields):
        q50 = valid_fields["akerscore_soil_p50"].to_numpy(float)
        spread = valid_fields["akerscore_soil_spread_p90_p10"].to_numpy(float)
        lines += [
            "",
            "ALL SCORED SKIFTEN",
            f"  field P50 score p10/p50/p90={np.percentile(q50,10):.1f}/{np.percentile(q50,50):.1f}/{np.percentile(q50,90):.1f}",
            f"  within-field P90-P10 spread median={np.nanmedian(spread):.1f} points",
        ]

    if not field_summary.empty:
        lines += ["", "SKIFTE-LEVEL QA BY HISTORIC CLASS (class used only after scoring)"]
        for _, r in field_summary.iterrows():
            lines.append(
                f"  class {int(r.historic_class_qa)}: n={int(r.n_skiften):,}; "
                f"field-score p10/p50/p90={r.field_score_p10:.1f}/{r.field_score_p50:.1f}/{r.field_score_p90:.1f}; "
                f"median within-field spread={r.median_within_field_p90_minus_p10:.1f}"
            )

    lines += [
        "",
        "Interpretation guardrails:",
        "- The display calibration only sets a readable 0-100 scale; raw score contains the model signal.",
        "- 100 is intentionally reserved for approximately the extreme class-10 upper tail.",
        "- P10/P90 over a field describes mapped soil heterogeneity and is not statistical uncertainty.",
        "- Historic class QA labels are appended after scoring and are never inputs to the score.",
        "- DSMS2025 organic matter is a modeled categorical proxy, not a fresh laboratory SOM test.",
    ]
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")

    metadata = {
        "version": VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "training_source": str(sample_path),
        "score_model": "v0a ILR(texture)+mull-proxy class-cloud model, unchanged",
        "display_calibration": knots.to_dict(orient="records"),
        "field_central_score": "P50 of calibrated 20m pixel scores within skifte",
        "field_variation": "P10/P90 of calibrated 20m pixel scores; spatial variation, not confidence interval",
        "german_rank_primary": "raw_score",
        "historic_class_used_when_scoring_fields": False,
        "field_outputs_reused": bool(can_reuse),
    }
    (outdir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + report)
    print("Output:", outdir)
    print("Send report.txt, tail_calibration_knots.csv, german_triesdorf_reference_scores_v0c.csv,")
    print("     skifte_class_score_summary.csv and a sample/whole akerscore_soil_skiften.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
