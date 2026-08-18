#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync / ÅkerScore · soil 4-tuple prototype v0a.

Purpose
-------
Build a continuous soil-quality score from the joint topsoil signature
(clay, silt, sand, organic-matter proxy) observed in the historic Swedish
agricultural productivity classes.

The historic class is ONLY used as training/reference information.  A field or
pixel being scored does not get its historic class injected into the score.
That is important: a class-6 location with a class-10-like modern soil tuple is
allowed to score like class 10.

v0a deliberately starts with classes 5-10 because that is the already-QA'd
ÅkerSync experiment.  The scoring math is generic and can later be extended to
classes 1-10.

External check
--------------
After fitting the Swedish model, published soil-cluster means from Groß et al.
(Plant and Soil 493, 79-97, 2023; Triesdorf 2016) are scored without using the
German grain yields during fitting.  The German yields are therefore an
external ordering / sanity check, not training labels.

Guardrails
----------
* Sand+silt+clay are compositional; the model uses two ILR coordinates rather
  than three collinear raw percentages.
* DSMS2025 organic matter is categorical.  v0a converts its bins to a clearly
  labelled numeric proxy; this is NOT a laboratory SOM measurement.
* The 1970s class is a historic productivity class, not a soil class.
* This is an experimental soil component of ÅkerScore, not a crop-yield
  forecast and not a land valuation model.
"""
from __future__ import annotations

import argparse
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
from rasterio.windows import Window, from_bounds

from common import load_config


MODEL_VERSION = "akerscore_soil_v0a"
TARGET_CLASSES = tuple(range(5, 11))
REGULARIZATION = 0.20
MIN_CLASS_SAMPLE = 500
DEFAULT_MAX_PIXELS_PER_CLASS = 100_000
RANDOM_SEED = 310826

SOIL_MEMBERS = {
    "clay": "dsms2025_ler.tif",
    "sand": "dsms2025_sand.tif",
    "silt": "dsms2025_silt.tif",
    "organic": "dsms2025_organisk_klasser.tif",
}

# DSMS organic-class raster.  The values themselves are class codes.  For v0a
# we need a monotone numeric coordinate in the joint soil cloud, so use an
# explicit approximate bin midpoint/proxy.  The open-ended classes are capped
# to conservative representative values.  Keep both code and proxy in outputs.
ORG_PROXY_PCT = {
    2: 2.0,      # <2.5%
    3: 3.0,      # 2.5-3.5%
    4: 4.0,      # 3.5-4.5%
    5: 5.0,      # 4.5-5.5%
    6: 6.0,      # 5.5-6.5%
    9: 9.25,     # 6.5-12%
    16: 16.0,    # 12-20%
    30: 25.0,    # >=20%, capped proxy for model stability
}
ORG_LABELS = {
    2: "<2.5%",
    3: "2.5-3.5%",
    4: "3.5-4.5%",
    5: "4.5-5.5%",
    6: "5.5-6.5%",
    9: "6.5-12%",
    16: "12-20%",
    30: ">=20%",
}

# Groß et al. 2023, Table 5, Triesdorf 2016.  SOC is mg/g.  The conversion to
# approximate SOM uses the traditional factor SOM ~= 1.724 * organic carbon.
# These values are NEVER used to fit the Swedish model.
GERMAN_REFERENCES = [
    # 0-10 cm
    {"depth_cm": "0-10", "cluster": "LS",    "clay": 18.0, "silt": 34.3, "sand": 47.8, "soc_mg_g": 16.4, "yield_t_ha": 10.8},
    {"depth_cm": "0-10", "cluster": "HS-LC", "clay": 14.1, "silt": 27.9, "sand": 57.9, "soc_mg_g": 10.9, "yield_t_ha": 10.1},
    {"depth_cm": "0-10", "cluster": "HS-HC", "clay": 17.6, "silt": 28.7, "sand": 53.7, "soc_mg_g": 16.4, "yield_t_ha": 10.4},
    # 10-30 cm
    {"depth_cm": "10-30", "cluster": "LS",    "clay": 18.1, "silt": 34.9, "sand": 47.0, "soc_mg_g": 14.0, "yield_t_ha": 10.8},
    {"depth_cm": "10-30", "cluster": "HS-LC", "clay": 13.9, "silt": 27.3, "sand": 57.2, "soc_mg_g": 10.9, "yield_t_ha": 10.2},
    {"depth_cm": "10-30", "cluster": "HS-HC", "clay": 16.6, "silt": 29.5, "sand": 53.4, "soc_mg_g": 12.8, "yield_t_ha": 10.4},
    # 30-60 cm is retained as a z-profile diagnostic, not as a direct DSMS
    # topsoil calibration target.
    {"depth_cm": "30-60", "cluster": "LS",    "clay": 17.5, "silt": 36.7, "sand": 45.7, "soc_mg_g": 7.6, "yield_t_ha": 10.7},
    {"depth_cm": "30-60", "cluster": "HS-LC", "clay": 12.3, "silt": 28.6, "sand": 59.0, "soc_mg_g": 5.9, "yield_t_ha": 10.5},
    {"depth_cm": "30-60", "cluster": "HS-HC", "clay": 19.5, "silt": 28.0, "sand": 52.5, "soc_mg_g": 6.5, "yield_t_ha": 10.2},
]


def extract_member(zf: zipfile.ZipFile, basename: str, td: str) -> Path:
    member = next((n for n in zf.namelist() if n == basename or n.endswith("/" + basename)), None)
    if not member:
        raise RuntimeError("Soil ZIP saknar " + basename)
    zf.extract(member, td)
    return Path(td) / member


def crs_is_3006(crs) -> bool:
    if crs is None:
        return False
    try:
        if crs.to_epsg() == 3006:
            return True
    except Exception:
        pass
    t = str(crs)
    return ('AUTHORITY["EPSG","3006"]' in t) or ("SWEREF99 TM" in t)


def geom_window(ds, geom):
    if geom is None or geom.is_empty:
        return None
    w = from_bounds(*geom.bounds, transform=ds.transform)
    c0 = max(0, int(math.floor(w.col_off)))
    r0 = max(0, int(math.floor(w.row_off)))
    c1 = min(ds.width, int(math.ceil(w.col_off + w.width)))
    r1 = min(ds.height, int(math.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1 - c0, r1 - r0)


def valid_mask(arr, nodata):
    ok = np.isfinite(arr)
    if nodata is not None:
        ok &= arr != nodata
    return ok


def polygon_parts(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return [g for g in geom.geoms if not g.is_empty]
    try:
        return [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    except Exception:
        return []


def robust_center_scale(X: np.ndarray):
    med = np.nanmedian(X, axis=0)
    mad = 1.4826 * np.nanmedian(np.abs(X - med), axis=0)
    sd = np.nanstd(X, axis=0, ddof=0)
    scale = np.where(np.isfinite(mad) & (mad > 1e-9), mad, sd)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return med, scale


def ilr_texture(clay, silt, sand):
    """Two isometric log-ratio coordinates for the 3-part texture composition."""
    c = np.asarray(clay, float)
    si = np.asarray(silt, float)
    sa = np.asarray(sand, float)
    total = c + si + sa
    c = 100.0 * c / total
    si = 100.0 * si / total
    sa = 100.0 * sa / total
    eps = 1e-6
    c = np.maximum(c, eps)
    si = np.maximum(si, eps)
    sa = np.maximum(sa, eps)
    z1 = (1.0 / math.sqrt(2.0)) * np.log(c / si)
    z2 = math.sqrt(2.0 / 3.0) * np.log(np.sqrt(c * si) / sa)
    return z1, z2


def feature_matrix(df: pd.DataFrame, use_mull: bool) -> np.ndarray:
    z1, z2 = ilr_texture(df["clay_pct"], df["silt_pct"], df["sand_pct"])
    if not use_mull:
        return np.column_stack([z1, z2])
    # log1p makes the open-ended high-organic class less dominant while keeping
    # the ordering and the 2-6% mineral-soil range well resolved.
    m = np.log1p(df["mull_proxy_pct"].to_numpy(float))
    return np.column_stack([z1, z2, m])


def sample_joint_pixels(root: Path, cfg: dict, outdir: Path, max_per_class: int, seed: int):
    """Create a paired clay/silt/sand/organic sample for each historic class."""
    v0b = root / cfg.get("build_dir", "data/derived") / "agri_class5_10_v0b"
    class_gpkg = v0b / "source" / "jord_skogsklassificering_class5_10.gpkg"
    summary_csv = v0b / "class5_10_soil_summary.csv"
    if not class_gpkg.exists() or not summary_csv.exists():
        raise FileNotFoundError(
            "ÅkerScore v0a bygger på den QA:ade klass 5-10-körningen. "
            "Kör RUN_AGRI_CLASS5_10_V0B.bat först. Saknar: "
            f"{class_gpkg if not class_gpkg.exists() else summary_csv}"
        )

    classes = gpd.read_file(class_gpkg, layer="class5_10").to_crs(3006)
    classes["KLASS"] = pd.to_numeric(classes["KLASS"], errors="coerce").astype("Int64")
    classes = classes[classes["KLASS"].isin(TARGET_CLASSES)].copy()
    dissolved = classes[["KLASS", "geometry"]].dissolve(by="KLASS").reset_index()
    dissolved["KLASS"] = dissolved["KLASS"].astype(int)

    summary = pd.read_csv(summary_csv)
    current = summary[summary["population"].eq("current_2025_farmland")].copy()
    mask_pixels = {
        int(r.klass): max(1, int(r.mask_pixels)) for _, r in current.iterrows()
        if int(r.klass) in TARGET_CLASSES
    }
    missing = [k for k in TARGET_CLASSES if k not in mask_pixels]
    if missing:
        raise RuntimeError(f"v0b summary saknar klasser: {missing}")

    blocks_path = Path(cfg.get("blocks", ""))
    soil_zip = Path(cfg.get("soil_zip", ""))
    if not blocks_path.exists():
        raise FileNotFoundError(f"Blockfil saknas: {blocks_path}")
    if not soil_zip.exists():
        raise FileNotFoundError(f"soil_zip saknas: {soil_zip}")
    blocks = gpd.read_file(blocks_path).to_crs(3006)
    blocks = blocks[blocks.geometry.notna() & ~blocks.geometry.is_empty].reset_index(drop=True)
    sidx = blocks.sindex

    keep_prob = {k: min(1.0, max_per_class / mask_pixels[k]) for k in TARGET_CLASSES}
    rng = {k: np.random.default_rng(seed + 1009 * k) for k in TARGET_CLASSES}
    chunks = {k: [] for k in TARGET_CLASSES}

    print("Deterministic Bernoulli sampling probabilities:")
    for k in TARGET_CLASSES:
        print(f"  class {k}: mask_pixels={mask_pixels[k]:,}, p={keep_prob[k]:.6f}")

    with tempfile.TemporaryDirectory(prefix="akerscore_soil_") as td, zipfile.ZipFile(soil_zip) as zf:
        paths = {kind: extract_member(zf, base, td) for kind, base in SOIL_MEMBERS.items()}
        with rasterio.open(paths["clay"]) as clay, rasterio.open(paths["silt"]) as silt, rasterio.open(paths["sand"]) as sand, rasterio.open(paths["organic"]) as organic:
            dsmap = {"clay": clay, "silt": silt, "sand": sand, "organic": organic}
            ref = clay
            for kind, ds in dsmap.items():
                if not crs_is_3006(ds.crs):
                    raise RuntimeError(f"{paths[kind].name}: expected EPSG:3006, got {ds.crs}")
                if tuple(round(x, 6) for x in ds.res) != (20.0, 20.0):
                    raise RuntimeError(f"{paths[kind].name}: expected 20m pixels, got {ds.res}")
                if ds.width != ref.width or ds.height != ref.height or ds.transform != ref.transform:
                    raise RuntimeError(f"{paths[kind].name}: raster grids do not align")

            for _, rr in dissolved.sort_values("KLASS").iterrows():
                klass = int(rr.KLASS)
                parts = polygon_parts(rr.geometry)
                print(f"Class {klass}: scanning {len(parts)} polygon parts")
                for ip, part in enumerate(parts, 1):
                    w = geom_window(ref, part)
                    if w is None:
                        continue
                    tr = ref.window_transform(w)
                    shp = (int(w.height), int(w.width))
                    class_mask = geometry_mask([part.__geo_interface__], out_shape=shp, transform=tr, invert=True, all_touched=False)
                    if not class_mask.any():
                        continue
                    try:
                        idx = list(sidx.query(part, predicate="intersects"))
                    except Exception:
                        idx = list(sidx.query(part))
                    block_geoms = [g for g in blocks.iloc[idx].geometry if g is not None and not g.is_empty]
                    if not block_geoms:
                        continue
                    farm_mask = geometry_mask([g.__geo_interface__ for g in block_geoms], out_shape=shp, transform=tr, invert=True, all_touched=False)
                    pmask = class_mask & farm_mask
                    if not pmask.any():
                        continue

                    arr = {kind: ds.read(1, window=w, masked=False).astype(float) for kind, ds in dsmap.items()}
                    valid = pmask.copy()
                    for kind, ds in dsmap.items():
                        valid &= valid_mask(arr[kind], ds.nodata)
                    valid &= np.isin(arr["organic"].astype(int), list(ORG_PROXY_PCT))
                    valid &= arr["clay"] > 0
                    valid &= arr["silt"] > 0
                    valid &= arr["sand"] > 0
                    rr0, cc0 = np.where(valid)
                    if not len(rr0):
                        continue
                    take = rng[klass].random(len(rr0)) < keep_prob[klass]
                    rr1, cc1 = rr0[take], cc0[take]
                    if not len(rr1):
                        continue

                    org_code = arr["organic"][rr1, cc1].astype(int)
                    mull_proxy = np.array([ORG_PROXY_PCT[int(v)] for v in org_code], float)
                    xcoord = tr.c + (cc1 + 0.5) * tr.a + (rr1 + 0.5) * tr.b
                    ycoord = tr.f + (cc1 + 0.5) * tr.d + (rr1 + 0.5) * tr.e
                    chunks[klass].append(pd.DataFrame({
                        "historic_class": klass,
                        "clay_pct": arr["clay"][rr1, cc1],
                        "silt_pct": arr["silt"][rr1, cc1],
                        "sand_pct": arr["sand"][rr1, cc1],
                        "organic_code": org_code,
                        "mull_proxy_pct": mull_proxy,
                        "x_3006": xcoord,
                        "y_3006": ycoord,
                    }))
                    if ip % 100 == 0:
                        print(f"  processed {ip}/{len(parts)} parts", flush=True)

    frames = []
    for k in TARGET_CLASSES:
        if not chunks[k]:
            raise RuntimeError(f"No paired samples for class {k}")
        q = pd.concat(chunks[k], ignore_index=True)
        # Bernoulli sampling can overshoot.  Cap deterministically to keep every
        # class equally represented and the model lightweight/reproducible.
        if len(q) > max_per_class:
            q = q.sample(n=max_per_class, random_state=seed + k).reset_index(drop=True)
        if len(q) < MIN_CLASS_SAMPLE:
            raise RuntimeError(f"Too few samples for class {k}: {len(q)}")
        frames.append(q)
        print(f"  final class {k} sample: {len(q):,}")
    sample = pd.concat(frames, ignore_index=True)
    sample["spatial_cell_10km"] = (
        np.floor(sample["x_3006"] / 10_000).astype(int).astype(str) + "_" +
        np.floor(sample["y_3006"] / 10_000).astype(int).astype(str)
    )
    sample.to_csv(outdir / "training_sample.csv.gz", index=False, compression="gzip", encoding="utf-8")
    return sample


def fit_cloud_model(df: pd.DataFrame, use_mull: bool):
    classes = sorted(df["historic_class"].unique().astype(int).tolist())
    Xraw = feature_matrix(df, use_mull=use_mull)
    pooled_center, pooled_scale = robust_center_scale(Xraw)
    Z = (Xraw - pooled_center) / pooled_scale

    refs = {}
    for klass in classes:
        m = df["historic_class"].to_numpy(int) == klass
        Xk = Z[m]
        center = Xk.mean(axis=0)
        cov = np.cov(Xk, rowvar=False, ddof=1)
        if np.ndim(cov) == 0:
            cov = np.array([[float(cov)]])
        p = Xk.shape[1]
        if cov.shape != (p, p) or not np.all(np.isfinite(cov)):
            cov = np.eye(p)
        cov = (1.0 - REGULARIZATION) * cov + REGULARIZATION * np.eye(p)
        inv = np.linalg.pinv(cov)
        sign, logdet = np.linalg.slogdet(cov)
        if sign <= 0 or not np.isfinite(logdet):
            raise RuntimeError(f"Non-positive covariance determinant in class {klass}")
        delta = Xk - center
        d2 = np.einsum("ij,jk,ik->i", delta, inv, delta)
        d = np.sqrt(np.maximum(d2, 0.0))
        refs[klass] = {
            "center": center,
            "cov": cov,
            "inv": inv,
            "logdet": float(logdet),
            "dist_sorted": np.sort(d),
            "n": int(len(Xk)),
        }
    return {
        "use_mull": bool(use_mull),
        "features": ["ilr_clay_silt", "ilr_texture_vs_sand"] + (["log1p_mull_proxy"] if use_mull else []),
        "pooled_center": pooled_center,
        "pooled_scale": pooled_scale,
        "classes": refs,
    }


def empirical_centrality(sorted_dist: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Share of reference distances >= d; central point -> near 1."""
    a = np.asarray(sorted_dist, float)
    pos = np.searchsorted(a, d, side="right")
    return np.clip((len(a) - pos) / max(len(a), 1), 0.0, 1.0)


def score_df(df: pd.DataFrame, model: dict, prefix: str) -> pd.DataFrame:
    Xraw = feature_matrix(df, use_mull=model["use_mull"])
    Z = (Xraw - model["pooled_center"]) / model["pooled_scale"]
    classes = sorted(model["classes"])
    p = Z.shape[1]
    loglikes, band_scores, distances = [], [], []
    for klass in classes:
        ref = model["classes"][klass]
        delta = Z - ref["center"]
        d2 = np.einsum("ij,jk,ik->i", delta, ref["inv"], delta)
        d2 = np.maximum(d2, 0.0)
        d = np.sqrt(d2)
        ll = -0.5 * (d2 + ref["logdet"] + p * math.log(2.0 * math.pi))
        centrality = empirical_centrality(ref["dist_sorted"], d)
        # Class k occupies the nominal band [10*(k-1), 10*k].  A typical point
        # from its own class lands around the middle because its empirical
        # centrality is ~0.5; an unusually central class-10 tuple can approach 100.
        band = 10.0 * (klass - 1) + 10.0 * centrality
        loglikes.append(ll)
        band_scores.append(band)
        distances.append(d)

    L = np.column_stack(loglikes)
    L -= np.max(L, axis=1, keepdims=True)
    P = np.exp(L)
    P /= np.sum(P, axis=1, keepdims=True)
    B = np.column_stack(band_scores)
    D = np.column_stack(distances)
    score = np.sum(P * B, axis=1)
    expected_class = np.sum(P * np.asarray(classes, float), axis=1)
    winner = np.asarray(classes, int)[np.argmax(P, axis=1)]

    out = df.copy()
    out[f"{prefix}_score"] = score
    out[f"{prefix}_expected_class"] = expected_class
    out[f"{prefix}_modal_class"] = winner
    for j, klass in enumerate(classes):
        out[f"{prefix}_p_class{klass}"] = P[:, j]
        out[f"{prefix}_distance_class{klass}"] = D[:, j]
    return out


def model_jsonable(model: dict):
    qgrid = np.linspace(0, 1, 101)
    refs = {}
    for klass, r in model["classes"].items():
        refs[str(klass)] = {
            "n": r["n"],
            "center_standardized": r["center"].tolist(),
            "cov_regularized": r["cov"].tolist(),
            "distance_quantiles_q0_to_q100": np.quantile(r["dist_sorted"], qgrid).tolist(),
        }
    return {
        "use_mull": model["use_mull"],
        "features": model["features"],
        "pooled_robust_center": model["pooled_center"].tolist(),
        "pooled_robust_scale": model["pooled_scale"].tolist(),
        "equal_class_priors": True,
        "regularization": REGULARIZATION,
        "class_references": refs,
    }


def summarize_training(scored: pd.DataFrame, score_col: str):
    rows = []
    for klass, q in scored.groupby("historic_class"):
        x = q[score_col].to_numpy(float)
        rows.append({
            "historic_class": int(klass),
            "n": int(len(q)),
            "score_mean": float(np.mean(x)),
            "score_p10": float(np.percentile(x, 10)),
            "score_p50": float(np.percentile(x, 50)),
            "score_p90": float(np.percentile(x, 90)),
            "share_in_nominal_10pt_band_pct": float(100.0 * np.mean((x >= 10*(klass-1)) & (x <= 10*klass))),
        })
    return pd.DataFrame(rows)


def german_reference_frame():
    rows = []
    for r in GERMAN_REFERENCES:
        q = dict(r)
        # mg C / g soil -> percent C by dividing by 10; then traditional SOM
        # conversion.  Keep it explicitly named approximate.
        q["mull_proxy_pct"] = (q["soc_mg_g"] / 10.0) * 1.724
        q["historic_class"] = -1
        q["clay_pct"] = q.pop("clay")
        q["silt_pct"] = q.pop("silt")
        q["sand_pct"] = q.pop("sand")
        rows.append(q)
    return pd.DataFrame(rows)


def report_text(train_diag, german, n_sample):
    lines = [
        "ÅkerSync / ÅkerScore · Soil 4-tuple prototype v0a",
        "=" * 82,
        f"Training pixels: {n_sample:,} (balanced cap per historic class)",
        "Training target: historic Swedish productivity class 5-10, current-2025 farmland overlay.",
        "Predictors: ILR(sand/silt/clay) + DSMS organic-matter bin proxy.",
        "No historic class is injected when a new tuple is scored.",
        "Nominal class bands: class 5=40-50, 6=50-60, ..., 10=90-100.",
        "",
        "TRAINING-DISTRIBUTION DIAGNOSTIC (not an out-of-sample validation)",
    ]
    for _, r in train_diag.iterrows():
        lines.append(
            f"  Class {int(r.historic_class)}: score p10/p50/p90="
            f"{r.score_p10:.1f}/{r.score_p50:.1f}/{r.score_p90:.1f}; "
            f"in nominal band={r.share_in_nominal_10pt_band_pct:.1f}%"
        )
    lines += [
        "",
        "GERMAN EXTERNAL REFERENCE · Groß et al. 2023, Triesdorf 2016",
        "The Swedish model is frozen before these published German yields are inspected by the scoring algorithm.",
        "SOM/mull values below are approximate conversions from published SOC; texture-only score is therefore the cleaner check.",
    ]
    for depth in ["0-10", "10-30", "30-60"]:
        lines.append(f"  Depth {depth} cm:")
        q = german[german["depth_cm"].eq(depth)].sort_values("yield_t_ha")
        for _, r in q.iterrows():
            lines.append(
                f"    {r.cluster:5s}: yield={r.yield_t_ha:.1f} t/ha; "
                f"texture score={r.texture_score:.1f}; 4-tuple score={r.soil4_score:.1f}; "
                f"clay/silt/sand={r.clay_pct:.1f}/{r.silt_pct:.1f}/{r.sand_pct:.1f}; "
                f"approx mull={r.mull_proxy_pct:.2f}%"
            )
    lines += [
        "",
        "Interpretation guardrails:",
        "- A score is an intrinsic topsoil-signature proxy, not a predicted harvest in t/ha.",
        "- German yield is an external concept check; it is not used as a training target.",
        "- DSMS organic bins are modeled data and a coarse proxy, not a fresh laboratory soil test.",
        "- Classes 5-10 only imply empirical support mainly over score 40-100 in v0a.",
        "- If the Swedish 4-tuple cannot separate classes that history separated, that is a result, not a bug: other factors such as climate, drainage, profile depth and management may carry the missing signal.",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--max-pixels-per-class", type=int, default=DEFAULT_MAX_PIXELS_PER_CLASS)
    ap.add_argument("--seed", type=int, default=RANDOM_SEED)
    ap.add_argument("--reuse-sample", action="store_true", help="Reuse existing training_sample.csv.gz if present")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    outdir = root / cfg.get("build_dir", "data/derived") / MODEL_VERSION
    outdir.mkdir(parents=True, exist_ok=True)
    sample_path = outdir / "training_sample.csv.gz"

    print("=" * 92)
    print("ÅkerSync / ÅkerScore · soil 4-tuple prototype v0a")
    print("=" * 92)
    print("Output:", outdir)
    print()

    if args.reuse_sample and sample_path.exists():
        print("Using cached paired training sample:", sample_path)
        sample = pd.read_csv(sample_path)
    else:
        sample = sample_joint_pixels(root, cfg, outdir, args.max_pixels_per_class, args.seed)

    # Fit two models.  Texture-only is a diagnostic and the cleanest German
    # external comparison.  Texture+mull is the proposed ÅkerScore soil core.
    model_texture = fit_cloud_model(sample, use_mull=False)
    model_soil4 = fit_cloud_model(sample, use_mull=True)

    scored = score_df(sample, model_texture, "texture")
    scored = score_df(scored, model_soil4, "soil4")
    train_diag = summarize_training(scored, "soil4_score")
    train_diag.to_csv(outdir / "training_class_score_summary.csv", index=False, encoding="utf-8-sig")

    # Keep a compact per-class soil signature table for human inspection.
    sig_rows = []
    for klass, q in sample.groupby("historic_class"):
        sig_rows.append({
            "historic_class": int(klass),
            "n": int(len(q)),
            "clay_mean_pct": float(q.clay_pct.mean()),
            "clay_p50_pct": float(q.clay_pct.median()),
            "silt_mean_pct": float(q.silt_pct.mean()),
            "silt_p50_pct": float(q.silt_pct.median()),
            "sand_mean_pct": float(q.sand_pct.mean()),
            "sand_p50_pct": float(q.sand_pct.median()),
            "mull_proxy_mean_pct": float(q.mull_proxy_pct.mean()),
            "mull_proxy_p50_pct": float(q.mull_proxy_pct.median()),
            "share_mull_proxy_lt3_5_pct": float(100.0 * np.mean(q.mull_proxy_pct < 3.5)),
        })
    pd.DataFrame(sig_rows).to_csv(outdir / "class_soil4_signature.csv", index=False, encoding="utf-8-sig")

    german = german_reference_frame()
    german = score_df(german, model_texture, "texture")
    german = score_df(german, model_soil4, "soil4")
    keep_cols = [
        "depth_cm", "cluster", "clay_pct", "silt_pct", "sand_pct", "soc_mg_g",
        "mull_proxy_pct", "yield_t_ha", "texture_score", "soil4_score",
        "texture_expected_class", "soil4_expected_class", "texture_modal_class", "soil4_modal_class",
    ]
    german[keep_cols].to_csv(outdir / "german_triesdorf_reference_scores.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "model_version": MODEL_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "training_classes": list(TARGET_CLASSES),
        "score_band_definition": {str(k): [10*(k-1), 10*k] for k in TARGET_CLASSES},
        "score_definition": "posterior-weighted class-band score; within-class location from empirical Mahalanobis centrality",
        "texture_transform": "ILR: z1=1/sqrt(2)*ln(clay/silt); z2=sqrt(2/3)*ln(sqrt(clay*silt)/sand)",
        "organic_proxy_pct": ORG_PROXY_PCT,
        "organic_labels": ORG_LABELS,
        "class_priors": "equal",
        "regularization": REGULARIZATION,
        "random_seed": args.seed,
        "max_pixels_per_class": args.max_pixels_per_class,
        "german_reference": {
            "citation": "Groß et al. (2023), Plant and Soil 493:79-97, Table 5, Triesdorf 2016",
            "doi": "10.1007/s11104-023-06212-2",
            "yield_used_in_fit": False,
            "soc_to_mull_note": "approx SOM = (SOC mg/g / 10) * 1.724; diagnostic only",
        },
        "historic_productivity_reference": {
            "citation": "Hasund, Knut Per (1986), Jordbruksmarken i naturresursekonomiskt perspektiv, SLU, Institutionen for ekonomi och statistik, Rapport 269, Uppsala",
            "used_in_fit": False,
            "note": "Used as an independent productivity-scale reference; not the same classification as the 1971 map.",
        },
        "model_texture": model_jsonable(model_texture),
        "model_soil4": model_jsonable(model_soil4),
    }
    (outdir / "model_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    report = report_text(train_diag, german, len(sample))
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    print("Created:")
    for p in [
        sample_path,
        outdir / "class_soil4_signature.csv",
        outdir / "training_class_score_summary.csv",
        outdir / "german_triesdorf_reference_scores.csv",
        outdir / "model_metadata.json",
        outdir / "report.txt",
    ]:
        print(" ", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
