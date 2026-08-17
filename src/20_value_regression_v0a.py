#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0a.

First deliberately-naive land-value experiment.

Input
-----
- ATL Fastigheter CSV exported by the local Tampermonkey capture script v0.3.
- Existing ÅkerSync local_paths.json.
- Existing Jordbruksverket block/skifte GeoPackages.
- Existing soil ZIP and (when available) hydrology work rasters.

The script deliberately does NOT try to identify cadastral properties. ATL's
lat/lon point is used as a spatial probe. If the point happens to lie inside a
2025 Jordbruksverket block/skifte, transparent geometry descriptors are added.
Raster features are sampled at the point and in a 100 m circle.

Baseline model
--------------
    log(kr / åker-ha)
      ~ (year - 2024)
      + log(åker-ha / 20)
      + (lat - 55.5)
      + (lon - 13.0)

Evaluation is primarily leave-one-out (LOO) R². Every single-feature model is
compared with the baseline on exactly the same complete-case subset.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds, Window
from scipy import stats
from shapely.geometry import Polygon, MultiPolygon

from common import load_config

BASE_TERMS = ["year_centered", "log_area_20", "lat_centered", "lon_centered"]
SOIL_MEMBERS = {
    "clay": "dsms2025_ler.tif",
    "sand": "dsms2025_sand.tif",
    "silt": "dsms2025_silt.tif",
    "organic": "dsms2025_organisk_klasser.tif",
}


def choose_atl_csv() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    p = filedialog.askopenfilename(
        title="Välj ATL_AkerSync_*_v03.csv",
        filetypes=[("CSV", "*.csv"), ("Alla filer", "*.*")],
    )
    root.destroy()
    return p or None


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype("string")
        .str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )


def normalized_properties(v) -> str:
    if pd.isna(v):
        return ""
    parts = [x.strip() for x in str(v).split("|") if x.strip()]
    return " | ".join(sorted(set(parts)))


def load_and_select_clean(atl_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(atl_csv, sep=";", encoding="utf-8-sig", dtype=str)
    required = {
        "datum", "kopeskilling_kr", "kt_tal", "objekttyp",
        "total_areal_ha", "akermark_ha", "skogsmark_ha", "akerandel_pct",
        "lat", "lon", "fastighetsbeteckningar",
    }
    missing = sorted(required - set(raw.columns))
    if missing:
        raise RuntimeError("ATL CSV saknar kolumner: " + ", ".join(missing))

    d = raw.copy()
    numeric_cols = [
        "kopeskilling_kr", "kt_tal", "total_areal_ha", "jordbruksmark_ha",
        "akermark_ha", "betesmark_ha", "skogsmark_ha", "skogsimpediment_ha",
        "akerandel_pct", "ekonomibyggnad_kvm_total", "smahus_kvm_total",
        "lat", "lon",
    ]
    for c in numeric_cols:
        if c in d.columns:
            d[c + "_n"] = num(d[c])

    d["year"] = pd.to_datetime(d["datum"], errors="coerce").dt.year
    d["props_norm"] = d["fastighetsbeteckningar"].apply(normalized_properties)
    fallback = (
        d.get("fastighetsbeteckning", pd.Series("", index=d.index)).fillna("")
        .astype(str).str.strip()
    )
    d.loc[d.props_norm.eq(""), "props_norm"] = fallback[d.props_norm.eq("")]
    d["transaction_key"] = (
        d.props_norm.fillna("") + "|" + d.datum.fillna("") + "|" +
        d.kopeskilling_kr.fillna("")
    )
    d["sale_id"] = d.transaction_key.map(
        lambda x: hashlib.sha1(str(x).encode("utf-8")).hexdigest()[:12]
    )

    # Same transaction can appear in more than one ATL result card/URL.
    d["duplicate_transaction"] = d.duplicated("transaction_key", keep="first")
    u = d.loc[~d.duplicate_transaction].copy()

    obj = u.objekttyp.fillna("").str.casefold()
    u["q_price_positive"] = u.kopeskilling_kr_n.gt(0)
    u["q_zero_forest"] = u.skogsmark_ha_n.fillna(0).eq(0)
    u["q_unbuilt"] = obj.str.contains("obebyggd", regex=False)
    u["q_arable_share_80"] = u.akerandel_pct_n.ge(80)
    u["q_positive_area"] = u.akermark_ha_n.gt(0) & u.total_areal_ha_n.gt(0)
    # Deliberately strict QA: no relativistic hectares in the training set.
    u["q_area_consistent"] = u.akermark_ha_n.le(u.total_areal_ha_n)
    u["q_kt"] = u.kt_tal_n.isna() | u.kt_tal_n.between(0.5, 6.0, inclusive="both")
    u["q_coords"] = u.lat_n.notna() & u.lon_n.notna()
    u["q_year"] = u.year.notna()

    clean_flags = [
        "q_price_positive", "q_zero_forest", "q_unbuilt", "q_arable_share_80",
        "q_positive_area", "q_area_consistent", "q_kt", "q_coords", "q_year",
    ]
    # Nullable boolean dtypes can otherwise make bool(pd.NA) ambiguous.
    for c in clean_flags:
        u[c] = u[c].fillna(False).astype(bool)
    u["selected_clean"] = u[clean_flags].all(axis=1)

    labels = {
        "q_price_positive": "pris<=0",
        "q_zero_forest": "skog>0",
        "q_unbuilt": "ej_obebyggd",
        "q_arable_share_80": "åkerandel<80",
        "q_positive_area": "area<=0",
        "q_area_consistent": "åker>total",
        "q_kt": "K/T_utanför_0.5-6",
        "q_coords": "latlon_saknas",
        "q_year": "år_saknas",
    }
    reasons = []
    for _, r in u.iterrows():
        reasons.append(" | ".join(labels[c] for c in clean_flags if not bool(r[c])))
    u["exclusion_reason"] = reasons

    clean = u.loc[u.selected_clean].copy().reset_index(drop=True)
    clean["kr_per_aker_ha"] = clean.kopeskilling_kr_n / clean.akermark_ha_n
    clean["log_kr_per_aker_ha"] = np.log(clean.kr_per_aker_ha)
    clean["year_centered"] = clean.year.astype(float) - 2024.0
    clean["log_area_20"] = np.log(clean.akermark_ha_n / 20.0)
    clean["lat_centered"] = clean.lat_n - 55.5
    clean["lon_centered"] = clean.lon_n - 13.0
    return u, clean


def polygon_parts(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if g is not None and not g.is_empty]
    try:
        return [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
    except Exception:
        return []


def geometry_metrics(geom) -> dict[str, float]:
    parts = polygon_parts(geom)
    if not parts:
        return {}
    area = float(geom.area)
    if not np.isfinite(area) or area <= 0:
        return {}
    perimeter = float(sum(p.exterior.length for p in parts) +
                      sum(r.length for p in parts for r in p.interiors))
    hull = geom.convex_hull
    hull_area = float(hull.area) if hull is not None and not hull.is_empty else np.nan
    mrr = geom.minimum_rotated_rectangle
    mrr_area = float(mrr.area) if mrr is not None and not mrr.is_empty else np.nan
    lengths = []
    if mrr is not None and not mrr.is_empty:
        coords = list(mrr.exterior.coords)
        for a, b in zip(coords[:-1], coords[1:]):
            lengths.append(math.hypot(float(b[0]-a[0]), float(b[1]-a[1])))
    lengths = sorted([x for x in lengths if x > 0], reverse=True)
    long_m = lengths[0] if lengths else np.nan
    short_m = lengths[-1] if lengths else np.nan
    return {
        "geom_area_ha": area / 10000.0,
        "geom_rectangularity": area / mrr_area if np.isfinite(mrr_area) and mrr_area > 0 else np.nan,
        "geom_convexity": area / hull_area if np.isfinite(hull_area) and hull_area > 0 else np.nan,
        "geom_compactness": 4.0 * math.pi * area / (perimeter * perimeter) if perimeter > 0 else np.nan,
        "geom_mbr_aspect": long_m / short_m if np.isfinite(short_m) and short_m > 0 else np.nan,
        "geom_mbr_long_m": long_m,
        "geom_mbr_short_m": short_m,
    }


def containing_row(gdf: gpd.GeoDataFrame, point):
    if gdf.empty:
        return None
    try:
        cand = list(gdf.sindex.query(point, predicate="intersects"))
    except Exception:
        cand = list(gdf.sindex.query(point))
    hits = []
    for i in cand:
        row = gdf.iloc[int(i)]
        geom = row.geometry
        if geom is not None and not geom.is_empty and geom.covers(point):
            hits.append(row)
    if not hits:
        return None
    return min(hits, key=lambda r: float(r.geometry.area))


def add_geometry_matches(clean: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = clean.copy()
    out["point_inside_block_2025"] = False
    out["point_inside_skifte_2025"] = False
    out["geometry_source"] = ""
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
        b = containing_row(blocks, p)
        s = containing_row(skiften, p) if not skiften.empty else None
        if b is not None:
            out.at[i, "point_inside_block_2025"] = True
        if s is not None:
            out.at[i, "point_inside_skifte_2025"] = True
            chosen = s.geometry
            out.at[i, "geometry_source"] = "skifte_2025"
        elif b is not None:
            chosen = b.geometry
            out.at[i, "geometry_source"] = "block_2025"
        else:
            continue
        for k, v in geometry_metrics(chosen).items():
            out.at[i, k] = v
    return out


def clipped_window(ds, x, y, radius_m):
    w = from_bounds(x-radius_m, y-radius_m, x+radius_m, y+radius_m, transform=ds.transform)
    c0 = max(0, int(math.floor(w.col_off)))
    r0 = max(0, int(math.floor(w.row_off)))
    c1 = min(ds.width, int(math.ceil(w.col_off + w.width)))
    r1 = min(ds.height, int(math.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1-c0, r1-r0)


def sample_circle(ds, x3006, y3006, radius_m=100.0) -> dict[str, float]:
    if ds.crs is None:
        return {}
    if ds.crs.to_epsg() == 3006:
        x, y = x3006, y3006
    else:
        tf = Transformer.from_crs(3006, ds.crs, always_xy=True)
        x, y = tf.transform(x3006, y3006)

    point = np.nan
    try:
        z = next(ds.sample([(x, y)]))[0]
        if np.isfinite(z) and (ds.nodata is None or z != ds.nodata):
            point = float(z)
    except Exception:
        pass

    w = clipped_window(ds, x, y, radius_m)
    if w is None:
        return {"point": point}
    a = ds.read(1, window=w, masked=False).astype(float)
    tr = ds.window_transform(w)
    rr, cc = np.indices(a.shape)
    xs = tr.c + (cc + 0.5) * tr.a + (rr + 0.5) * tr.b
    ys = tr.f + (cc + 0.5) * tr.d + (rr + 0.5) * tr.e
    circle = (xs-x)**2 + (ys-y)**2 <= radius_m**2
    valid = circle & np.isfinite(a)
    if ds.nodata is not None:
        valid &= a != ds.nodata
    vals = a[valid]
    if vals.size == 0:
        return {"point": point, "n": 0}
    p05, p50, p90, p95 = np.percentile(vals, [5, 50, 90, 95])
    return {
        "point": point,
        "mean": float(np.mean(vals)),
        "sd": float(np.std(vals)),
        "p05": float(p05),
        "p50": float(p50),
        "p90": float(p90),
        "p95": float(p95),
        "n": int(vals.size),
    }


def sample_categorical_mode(ds, x3006, y3006, radius_m=100.0) -> float:
    if ds.crs is None:
        return np.nan
    if ds.crs.to_epsg() == 3006:
        x, y = x3006, y3006
    else:
        tf = Transformer.from_crs(3006, ds.crs, always_xy=True)
        x, y = tf.transform(x3006, y3006)
    w = clipped_window(ds, x, y, radius_m)
    if w is None:
        return np.nan
    a = ds.read(1, window=w, masked=False)
    tr = ds.window_transform(w)
    rr, cc = np.indices(a.shape)
    xs = tr.c + (cc + 0.5) * tr.a + (rr + 0.5) * tr.b
    ys = tr.f + (cc + 0.5) * tr.d + (rr + 0.5) * tr.e
    circle = (xs-x)**2 + (ys-y)**2 <= radius_m**2
    valid = circle & np.isfinite(a)
    if ds.nodata is not None:
        valid &= a != ds.nodata
    vals = a[valid]
    if vals.size == 0:
        return np.nan
    vals = vals.astype(int)
    uq, counts = np.unique(vals, return_counts=True)
    return float(uq[np.argmax(counts)])


def extract_zip_member(z: zipfile.ZipFile, basename: str, td: Path) -> Path:
    member = next((n for n in z.namelist() if n == basename or n.endswith("/" + basename)), None)
    if not member:
        raise RuntimeError("Jord-ZIP saknar " + basename)
    z.extract(member, td)
    return td / member


def add_soil_features(df: pd.DataFrame, cfg: dict, radius_m: float) -> pd.DataFrame:
    out = df.copy()
    soil_zip = Path(cfg.get("soil_zip", ""))
    if not soil_zip.exists():
        print("VARNING: soil_zip saknas; hoppar över jordprofil:", soil_zip)
        return out

    tf = Transformer.from_crs(4326, 3006, always_xy=True)
    xy = [tf.transform(float(lon), float(lat)) for lon, lat in zip(out.lon_n, out.lat_n)]
    with tempfile.TemporaryDirectory(prefix="akersync_value_soil_") as td0:
        td = Path(td0)
        with zipfile.ZipFile(soil_zip) as z, ExitStack() as stack:
            layers = {}
            for kind, basename in SOIL_MEMBERS.items():
                p = extract_zip_member(z, basename, td)
                layers[kind] = stack.enter_context(rasterio.open(p))

            for kind in ("clay", "sand", "silt"):
                for suffix in ("point", "100m_mean", "100m_p90"):
                    out[f"soil_{kind}_{suffix}"] = np.nan
            out["soil_organic_point_code"] = np.nan
            out["soil_organic_100m_mode_code"] = np.nan

            for i, (x, y) in enumerate(xy):
                for kind in ("clay", "sand", "silt"):
                    st = sample_circle(layers[kind], x, y, radius_m)
                    out.at[i, f"soil_{kind}_point"] = st.get("point", np.nan)
                    out.at[i, f"soil_{kind}_100m_mean"] = st.get("mean", np.nan)
                    out.at[i, f"soil_{kind}_100m_p90"] = st.get("p90", np.nan)
                org = sample_circle(layers["organic"], x, y, radius_m)
                out.at[i, "soil_organic_point_code"] = org.get("point", np.nan)
                out.at[i, "soil_organic_100m_mode_code"] = sample_categorical_mode(
                    layers["organic"], x, y, radius_m
                )
    return out


def find_work_raster(work_dir: Path, stem: str) -> Path | None:
    exact = work_dir / stem
    if exact.exists():
        return exact
    hits = sorted(work_dir.glob(stem.replace("10m", "*m")))
    if not hits:
        return None
    hits.sort(key=lambda p: ("10m" not in p.name, p.name))
    return hits[0]


def add_hydro_topo_features(df: pd.DataFrame, cfg: dict, radius_m: float) -> pd.DataFrame:
    out = df.copy()
    work = Path(cfg.get("whitebox_work_dir", ""))
    if not work.exists():
        print("VARNING: whitebox_work_dir saknas; hoppar över TWI/topografi:", work)
        return out

    candidates = {
        "twi": find_work_raster(work, "twi_10m.tif"),
        "slope": find_work_raster(work, "slope_10m_deg.tif"),
        "dem": find_work_raster(work, "dem_10m.tif"),
        "sca": find_work_raster(work, "dinf_sca_10m.tif"),
    }
    existing = {k: p for k, p in candidates.items() if p is not None and p.exists()}
    if not existing:
        print("VARNING: inga hydrologiraster hittades i", work)
        return out
    print("Punktraster:")
    for k, p in existing.items():
        print(f"  {k:6s} {p}")

    tf = Transformer.from_crs(4326, 3006, always_xy=True)
    xy = [tf.transform(float(lon), float(lat)) for lon, lat in zip(out.lon_n, out.lat_n)]

    with ExitStack() as stack:
        ds = {k: stack.enter_context(rasterio.open(p)) for k, p in existing.items()}
        for i, (x, y) in enumerate(xy):
            if "twi" in ds:
                st = sample_circle(ds["twi"], x, y, radius_m)
                out.at[i, "twi_point"] = st.get("point", np.nan)
                out.at[i, "twi_100m_mean"] = st.get("mean", np.nan)
                out.at[i, "twi_100m_p90"] = st.get("p90", np.nan)
                out.at[i, "twi_100m_p95"] = st.get("p95", np.nan)
            if "slope" in ds:
                st = sample_circle(ds["slope"], x, y, radius_m)
                out.at[i, "slope_point_deg"] = st.get("point", np.nan)
                out.at[i, "slope_100m_mean_deg"] = st.get("mean", np.nan)
                out.at[i, "slope_100m_p90_deg"] = st.get("p90", np.nan)
            if "dem" in ds:
                st = sample_circle(ds["dem"], x, y, radius_m)
                out.at[i, "elev_point_m"] = st.get("point", np.nan)
                out.at[i, "elev_100m_mean_m"] = st.get("mean", np.nan)
                if np.isfinite(st.get("p95", np.nan)) and np.isfinite(st.get("p05", np.nan)):
                    out.at[i, "relief_100m_p95_p05_m"] = st["p95"] - st["p05"]
            if "sca" in ds:
                st = sample_circle(ds["sca"], x, y, radius_m)
                out.at[i, "sca_point_m"] = st.get("point", np.nan)
                out.at[i, "sca_100m_mean_m"] = st.get("mean", np.nan)
                p90 = st.get("p90", np.nan)
                out.at[i, "ln_sca_100m_p90"] = math.log(max(p90, 1e-9)) if np.isfinite(p90) else np.nan
    return out


def design(df: pd.DataFrame, extra: list[str] | None = None) -> tuple[np.ndarray, np.ndarray, list[str]]:
    cols = BASE_TERMS + list(extra or [])
    X = np.column_stack([
        np.ones(len(df))
    ] + [pd.to_numeric(df[c], errors="coerce").to_numpy(float) for c in cols])
    y = pd.to_numeric(df.log_kr_per_aker_ha, errors="coerce").to_numpy(float)
    return X, y, ["intercept"] + cols


def fit_ols(X: np.ndarray, y: np.ndarray):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    resid = y - pred
    sse = float(resid @ resid)
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - sse/sst if sst > 0 else np.nan
    n, p = X.shape
    adj = 1.0 - (1.0-r2)*(n-1)/(n-p) if n > p and np.isfinite(r2) else np.nan
    rank = int(np.linalg.matrix_rank(X))
    se = np.full(p, np.nan)
    pval = np.full(p, np.nan)
    if n > p and rank == p:
        sigma2 = sse / (n-p)
        cov = sigma2 * np.linalg.pinv(X.T @ X)
        se = np.sqrt(np.clip(np.diag(cov), 0, np.inf))
        with np.errstate(divide="ignore", invalid="ignore"):
            t = beta / se
        pval = 2.0 * stats.t.sf(np.abs(t), df=n-p)
    return beta, pred, r2, adj, rank, se, pval


def loo_predictions(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    n = len(y)
    pred = np.full(n, np.nan)
    for i in range(n):
        keep = np.ones(n, dtype=bool)
        keep[i] = False
        b, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
        pred[i] = float(X[i] @ b)
    return pred


def r2_score(y, pred):
    y = np.asarray(y, float)
    pred = np.asarray(pred, float)
    sst = float(((y-y.mean())**2).sum())
    return 1.0 - float(((y-pred)**2).sum())/sst if sst > 0 else np.nan


def pct_error_from_log(y, pred):
    return np.abs(np.exp(pred-y) - 1.0)


def complete_subset(df, extras):
    cols = ["log_kr_per_aker_ha"] + BASE_TERMS + list(extras)
    mask = np.ones(len(df), dtype=bool)
    for c in cols:
        if c not in df.columns:
            return df.iloc[0:0].copy()
        mask &= pd.to_numeric(df[c], errors="coerce").notna().to_numpy()
    return df.loc[mask].copy().reset_index(drop=True)


def run_models(df: pd.DataFrame, outdir: Path):
    base = complete_subset(df, [])
    if len(base) < 10:
        raise RuntimeError(f"För få kompletta baseline-case: {len(base)}")
    X, y, names = design(base)
    beta, pred, r2, adj, rank, se, pval = fit_ols(X, y)
    loo = loo_predictions(X, y)
    loo_r2 = r2_score(y, loo)
    med_ape = float(np.median(pct_error_from_log(y, loo)))

    pd.DataFrame({
        "term": names, "coefficient": beta, "std_error": se, "p_value": pval,
    }).to_csv(outdir / "baseline_coefficients.csv", index=False, encoding="utf-8-sig")
    bp = base[["sale_id", "datum", "akermark_ha_n", "kr_per_aker_ha", "lat_n", "lon_n"]].copy()
    bp["observed_log_kr_per_ha"] = y
    bp["loo_pred_log_kr_per_ha"] = loo
    bp["observed_kr_per_ha"] = np.exp(y)
    bp["loo_pred_kr_per_ha"] = np.exp(loo)
    bp["abs_pct_error"] = 100.0 * pct_error_from_log(y, loo)
    bp.to_csv(outdir / "baseline_loo_predictions.csv", index=False, encoding="utf-8-sig")

    candidates = [
        "soil_clay_point", "soil_clay_100m_mean",
        "soil_sand_100m_mean", "soil_silt_100m_mean",
        "twi_point", "twi_100m_mean", "twi_100m_p90", "twi_100m_p95",
        "slope_point_deg", "slope_100m_mean_deg", "slope_100m_p90_deg",
        "elev_point_m", "elev_100m_mean_m", "relief_100m_p95_p05_m",
        "ln_sca_100m_p90",
        "geom_rectangularity", "geom_convexity", "geom_compactness", "geom_mbr_aspect",
    ]
    rows = []
    for feature in candidates:
        if feature not in df.columns:
            continue
        x = complete_subset(df, [feature])
        if len(x) < 12:
            continue
        X0, yy, _ = design(x)
        X1, _, nm = design(x, [feature])
        if np.linalg.matrix_rank(X1) < X1.shape[1]:
            continue
        loo0 = loo_predictions(X0, yy)
        loo1 = loo_predictions(X1, yy)
        b1, _, r21, adj1, _, se1, pv1 = fit_ols(X1, yy)
        base_loo = r2_score(yy, loo0)
        aug_loo = r2_score(yy, loo1)
        rows.append({
            "model": "baseline + " + feature,
            "feature": feature,
            "n": len(x),
            "loo_r2_baseline_same_n": base_loo,
            "loo_r2_augmented": aug_loo,
            "delta_loo_r2": aug_loo - base_loo,
            "train_r2_augmented": r21,
            "adj_r2_augmented": adj1,
            "feature_coefficient": b1[-1],
            "feature_std_error": se1[-1],
            "feature_p_value": pv1[-1],
            "median_abs_pct_error_loo": 100.0 * float(np.median(pct_error_from_log(yy, loo1))),
        })

    # One pre-declared small multivariable model; no fishing after seeing results.
    small = ["soil_clay_100m_mean", "slope_100m_mean_deg", "twi_100m_mean", "geom_rectangularity"]
    sx = complete_subset(df, small)
    if len(sx) >= 16:
        X0, yy, _ = design(sx)
        X1, _, _ = design(sx, small)
        if np.linalg.matrix_rank(X1) == X1.shape[1]:
            loo0 = loo_predictions(X0, yy)
            loo1 = loo_predictions(X1, yy)
            _, _, r21, adj1, _, _, _ = fit_ols(X1, yy)
            base_loo = r2_score(yy, loo0)
            aug_loo = r2_score(yy, loo1)
            rows.append({
                "model": "baseline + clay + slope + TWI + rectangularity",
                "feature": "PREDECLARED_SMALL_MODEL",
                "n": len(sx),
                "loo_r2_baseline_same_n": base_loo,
                "loo_r2_augmented": aug_loo,
                "delta_loo_r2": aug_loo - base_loo,
                "train_r2_augmented": r21,
                "adj_r2_augmented": adj1,
                "feature_coefficient": np.nan,
                "feature_std_error": np.nan,
                "feature_p_value": np.nan,
                "median_abs_pct_error_loo": 100.0 * float(np.median(pct_error_from_log(yy, loo1))),
            })

    comp = pd.DataFrame(rows)
    if len(comp):
        comp = comp.sort_values("delta_loo_r2", ascending=False)
    comp.to_csv(outdir / "model_comparison.csv", index=False, encoding="utf-8-sig")
    return {
        "n": len(base), "beta": beta, "names": names,
        "r2": r2, "adj_r2": adj, "loo_r2": loo_r2,
        "median_abs_pct_error_loo": 100.0 * med_ape,
        "comparison": comp,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--atl", help="ATL_AkerSync_*_v03.csv; om utelämnad öppnas filväljare")
    ap.add_argument("--radius-m", type=float, default=100.0)
    ap.add_argument("--baseline-only", action="store_true", help="Kör urval + baseline utan GIS-enrichment")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg_path = root / args.config
    if not cfg_path.exists():
        raise RuntimeError(f"Saknar {cfg_path}. Kopiera config/local_paths.json från din vanliga ÅkerSync-worktree.")
    cfg = load_config(cfg_path)

    atl = args.atl or choose_atl_csv()
    if not atl:
        print("Avbrutet: ingen ATL CSV vald.")
        return 2
    atl_csv = Path(atl)
    if not atl_csv.exists():
        raise FileNotFoundError(atl_csv)

    outdir = root / cfg.get("build_dir", "data/derived") / "value_regression_v0a"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print("ÅkerSync · Value Regression v0a")
    print("=" * 84)
    print("ATL:", atl_csv)
    print("Output:", outdir)
    print(f"Punkt-neighbourhood: {args.radius_m:g} m")
    print()

    audit, clean = load_and_select_clean(atl_csv)
    audit.to_csv(outdir / "selection_audit.csv", index=False, encoding="utf-8-sig")
    clean.to_csv(outdir / "clean_cases.csv", index=False, encoding="utf-8-sig")

    print(f"ATL-rader:                 {len(pd.read_csv(atl_csv, sep=';', encoding='utf-8-sig')):,}")
    print(f"Unika transaktioner:       {len(audit):,}")
    print(f"Rena regressionscase:      {len(clean):,}")
    if len(clean) == 32:
        print("Reference check:            32 case — matchar 315-posters baseline ✅")
    print()

    enriched = clean.copy()
    if not args.baseline_only:
        print("[1/3] Matchar punkt mot 2025 block/skifte + geometri...")
        enriched = add_geometry_matches(enriched, cfg)
        print("[2/3] Samplar jord 20 m vid punkt + 100 m...")
        enriched = add_soil_features(enriched, cfg, args.radius_m)
        print("[3/3] Samplar TWI/topografi vid punkt + 100 m...")
        enriched = add_hydro_topo_features(enriched, cfg, args.radius_m)

    enriched.to_csv(outdir / "point_features.csv", index=False, encoding="utf-8-sig")
    result = run_models(enriched, outdir)

    lines = []
    lines.append("ÅkerSync Value Regression v0a")
    lines.append("=" * 72)
    lines.append(f"ATL source: {atl_csv}")
    lines.append(f"Unique transactions after dedup: {len(audit)}")
    lines.append(f"Clean cases: {len(clean)}")
    if "point_inside_block_2025" in enriched.columns:
        lines.append(f"Point inside 2025 block: {int(enriched.point_inside_block_2025.fillna(False).sum())}/{len(enriched)}")
    if "point_inside_skifte_2025" in enriched.columns:
        lines.append(f"Point inside 2025 skifte: {int(enriched.point_inside_skifte_2025.fillna(False).sum())}/{len(enriched)}")
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
    lines.append("Primary decision metric: Δ LOO R2 versus baseline on the SAME rows.")
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print()
    print(report)
    print("Outputfiler:")
    for name in [
        "selection_audit.csv", "clean_cases.csv", "point_features.csv",
        "baseline_coefficients.csv", "baseline_loo_predictions.csv",
        "model_comparison.csv", "report.txt",
    ]:
        print(" ", outdir / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
