#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transaction-level soil texture features for ÅkerSync value regression.

The transaction object is the proximity/area reconstruction from value_multiblock.
Soil is sampled from the DSMS2025 20 m rasters over the selected blocks.
Sand+silt+clay are treated as a composition. Organic matter remains categorical:
we preserve DSMS class codes/shares and do not pretend that the class code is a
continuous percent value.
"""
from __future__ import annotations

import math
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds

SOIL_MEMBERS = {
    "clay": "dsms2025_ler.tif",
    "sand": "dsms2025_sand.tif",
    "silt": "dsms2025_silt.tif",
    "organic": "dsms2025_organisk_klasser.tif",
}
ORG_CODES = [2, 3, 4, 5, 6, 9, 16, 30]
ORG_LABELS = {
    2: "<2,5 %",
    3: "2,5–3,5 %",
    4: "3,5–4,5 %",
    5: "4,5–5,5 %",
    6: "5,5–6,5 %",
    9: "6,5–12 %",
    16: "12–20 %",
    30: "≥20 %",
}


def crs_is_epsg3006(crs) -> bool:
    """Robust SWEREF99 TM check across Rasterio/GDAL/PROJ versions.

    On Bengt's current Python 3.14 stack ``to_epsg()`` can return None even
    though the WKT explicitly carries AUTHORITY["EPSG","3006"].  Accept the
    explicit authority/name as well; this mirrors the already proven check in
    src/02_soil.py.
    """
    if crs is None:
        return False
    try:
        if crs.to_epsg() == 3006:
            return True
    except Exception:
        pass
    text = str(crs)
    return (
        'AUTHORITY["EPSG","3006"]' in text
        or 'SWEREF99 TM' in text
        or 'SWEREF 99 TM' in text
    )


def extract_member(zf: zipfile.ZipFile, basename: str, td: str) -> Path:
    member = next((n for n in zf.namelist() if n == basename or n.endswith("/" + basename)), None)
    if member is None:
        raise RuntimeError(f"Soil ZIP saknar {basename}")
    zf.extract(member, td)
    return Path(td) / member


def geom_window(bounds, transform, width, height):
    w = from_bounds(*bounds, transform=transform)
    c0 = max(0, int(math.floor(w.col_off)))
    r0 = max(0, int(math.floor(w.row_off)))
    c1 = min(width, int(math.ceil(w.col_off + w.width)))
    r1 = min(height, int(math.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1 - c0, r1 - r0)


def vals_in_geom(ds, geom) -> np.ndarray:
    if geom is None or geom.is_empty or geom.area <= 0:
        return np.array([], dtype=float)
    w = geom_window(geom.bounds, ds.transform, ds.width, ds.height)
    if w is None:
        return np.array([], dtype=float)
    arr = ds.read(1, window=w, masked=False).astype(float)
    tr = ds.window_transform(w)
    mask = geometry_mask(
        [geom.__geo_interface__],
        out_shape=arr.shape,
        transform=tr,
        invert=True,
        all_touched=False,
    )
    ok = mask & np.isfinite(arr)
    if ds.nodata is not None:
        ok &= arr != ds.nodata
    return arr[ok].astype(float)


def continuous_summary(vals: np.ndarray) -> dict[str, float]:
    vals = np.asarray(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return {k: np.nan for k in ("mean", "sd", "p10", "p50", "p90", "n")}
    p10, p50, p90 = np.percentile(vals, [10, 50, 90])
    return {
        "mean": float(vals.mean()),
        "sd": float(vals.std()),
        "p10": float(p10),
        "p50": float(p50),
        "p90": float(p90),
        "n": int(vals.size),
    }


def entropy_bits_from_counts(counts: np.ndarray) -> float:
    counts = np.asarray(counts, dtype=float)
    counts = counts[counts > 0]
    if counts.size == 0:
        return np.nan
    p = counts / counts.sum()
    return float(-(p * np.log2(p)).sum())


def weighted_between_block_texture(block_rows: list[dict]) -> tuple[float, float, int]:
    good = []
    for r in block_rows:
        try:
            a = float(r["block_area_ha"])
            c = float(r["clay_mean"])
            s = float(r["silt_mean"])
            sa = float(r["sand_mean"])
        except Exception:
            continue
        if np.isfinite(a) and a > 0 and np.isfinite(c) and np.isfinite(s) and np.isfinite(sa):
            good.append((a, c, s, sa))
    if not good:
        return np.nan, np.nan, 0
    a = np.array([x[0] for x in good], float)
    x = np.array([[x[1], x[2], x[3]] for x in good], float)
    w = a / a.sum()
    mu = (w[:, None] * x).sum(axis=0)
    rms = float(np.sqrt((w * ((x - mu) ** 2).sum(axis=1)).sum()))
    clay_sd = float(np.sqrt((w * (x[:, 0] - mu[0]) ** 2).sum()))
    return rms, clay_sd, len(good)


def add_transaction_soil_features(
    clean_with_recon: pd.DataFrame,
    members: pd.DataFrame,
    cfg: dict,
    match_flag: str = "tx_recon_match_20pct",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add raw and QA-gated transaction-level soil features.

    Raw features are computed whenever reconstructed blocks are available.
    Main regression aliases are populated only when ``match_flag`` is true.
    """
    out = clean_with_recon.copy()
    if members is None or members.empty:
        return out, pd.DataFrame()

    blocks_path = Path(cfg.get("blocks", ""))
    soil_zip = Path(cfg.get("soil_zip", ""))
    if not blocks_path.exists():
        raise FileNotFoundError(f"Blockfil saknas: {blocks_path}")
    if not soil_zip.exists():
        raise FileNotFoundError(f"Soil ZIP saknas: {soil_zip}")

    blocks = gpd.read_file(blocks_path).to_crs(3006).copy()
    blocks["blockid"] = blocks["blockid"].astype(str)
    # Defensive dissolve in case a block id occurs in more than one geometry row.
    block_geom = blocks[["blockid", "geometry"]].dissolve(by="blockid").geometry.to_dict()

    mem = members.copy()
    mem["sale_id"] = mem["sale_id"].astype(str)
    mem["blockid"] = mem["blockid"].astype(str)
    mem = mem.drop_duplicates(["sale_id", "blockid"]).reset_index(drop=True)

    # Storage per sale/layer and per sale/block/layer.
    sale_vals: dict[tuple[str, str], list[np.ndarray]] = {}
    block_stats: dict[tuple[str, str], dict] = {}

    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(soil_zip) as zf:
        extracted = {kind: extract_member(zf, base, td) for kind, base in SOIL_MEMBERS.items()}
        for kind, path in extracted.items():
            print(f"  transaction soil layer: {kind}")
            with rasterio.open(path) as ds:
                if not crs_is_epsg3006(ds.crs):
                    raise RuntimeError(f"{path.name}: väntade SWEREF99 TM / EPSG:3006, fick {ds.crs}")
                for _, r in mem.iterrows():
                    sid = str(r["sale_id"])
                    bid = str(r["blockid"])
                    geom = block_geom.get(bid)
                    vals = vals_in_geom(ds, geom)
                    sale_vals.setdefault((sid, kind), []).append(vals)
                    bs = block_stats.setdefault((sid, bid), {
                        "sale_id": sid,
                        "blockid": bid,
                        "block_area_ha": pd.to_numeric(pd.Series([r.get("block_area_ha")]), errors="coerce").iloc[0],
                    })
                    if kind != "organic":
                        st = continuous_summary(vals)
                        bs[f"{kind}_mean"] = st["mean"]
                        bs[f"{kind}_sd"] = st["sd"]
                        bs[f"{kind}_n_pix"] = st["n"]
                    else:
                        vv = vals.astype(int) if vals.size else np.array([], dtype=int)
                        bs["organic_mode_code"] = (
                            max(ORG_CODES, key=lambda c: (int(np.sum(vv == c)), -ORG_CODES.index(c)))
                            if vv.size else np.nan
                        )

    sale_rows = []
    block_rows = list(block_stats.values())
    for sid, gm in mem.groupby("sale_id", sort=False):
        sid = str(sid)
        row = {"sale_id": sid}
        selected_area_ha = pd.to_numeric(gm.get("block_area_ha"), errors="coerce").sum(min_count=1)
        row["tx_soil_selected_block_area_ha_raw"] = selected_area_ha
        continuous = {}
        for kind in ("clay", "silt", "sand"):
            chunks = [v for v in sale_vals.get((sid, kind), []) if v.size]
            vals = np.concatenate(chunks) if chunks else np.array([], dtype=float)
            st = continuous_summary(vals)
            continuous[kind] = st
            for nm in ("mean", "sd", "p10", "p50", "p90", "n"):
                row[f"tx_soil_{kind}_{nm}_raw"] = st[nm]
            row[f"tx_soil_{kind}_coverage_pct_raw"] = (
                min(100.0, 100.0 * float(st["n"]) * 0.04 / float(selected_area_ha))
                if np.isfinite(selected_area_ha) and selected_area_ha > 0 and np.isfinite(st["n"]) else np.nan
            )
            row[f"tx_soil_{kind}_p90_p10_raw"] = (
                st["p90"] - st["p10"] if np.isfinite(st["p90"]) and np.isfinite(st["p10"]) else np.nan
            )

        c = continuous["clay"]["mean"]
        si = continuous["silt"]["mean"]
        sa = continuous["sand"]["mean"]
        row["tx_soil_texture_sum_mean_pct_raw"] = (
            c + si + sa if all(np.isfinite(x) for x in (c, si, sa)) else np.nan
        )
        row["tx_soil_texture_pixel_rms_sd_pct_raw"] = (
            float(np.sqrt(continuous["clay"]["sd"] ** 2 + continuous["silt"]["sd"] ** 2 + continuous["sand"]["sd"] ** 2))
            if all(np.isfinite(continuous[k]["sd"]) for k in ("clay", "silt", "sand")) else np.nan
        )

        br = [x for x in block_rows if str(x.get("sale_id")) == sid]
        between, clay_bsd, nb = weighted_between_block_texture(br)
        row["tx_soil_texture_between_blocks_rms_pct_raw"] = between
        row["tx_soil_clay_between_blocks_sd_pct_raw"] = clay_bsd
        row["tx_soil_blocks_with_complete_texture_raw"] = nb

        org_chunks = [v for v in sale_vals.get((sid, "organic"), []) if v.size]
        org = np.concatenate(org_chunks).astype(int) if org_chunks else np.array([], dtype=int)
        counts = np.array([int(np.sum(org == code)) for code in ORG_CODES], dtype=int)
        row["tx_organic_n_pix_raw"] = int(org.size)
        if org.size:
            mode = max(ORG_CODES, key=lambda c: (int(np.sum(org == c)), -ORG_CODES.index(c)))
            row["tx_organic_mode_code_raw"] = int(mode)
            row["tx_organic_mode_label_raw"] = ORG_LABELS[mode]
            row["tx_organic_entropy_bits_raw"] = entropy_bits_from_counts(counts)
            row["tx_organic_dominant_share_pct_raw"] = 100.0 * float(counts.max()) / float(org.size)
            for code, n in zip(ORG_CODES, counts):
                row[f"tx_organic_share_code_{code}_pct_raw"] = 100.0 * float(n) / float(org.size)
        else:
            row["tx_organic_mode_code_raw"] = np.nan
            row["tx_organic_mode_label_raw"] = ""
            row["tx_organic_entropy_bits_raw"] = np.nan
            row["tx_organic_dominant_share_pct_raw"] = np.nan
            for code in ORG_CODES:
                row[f"tx_organic_share_code_{code}_pct_raw"] = np.nan
        sale_rows.append(row)

    sf = pd.DataFrame(sale_rows)
    out = out.merge(sf, on="sale_id", how="left", validate="one_to_one")

    # QA-gated aliases used by the regression. Organic class shares are preserved,
    # but no class code is treated as a continuous percentage value.
    ok = out.get(match_flag, pd.Series(False, index=out.index)).fillna(False).astype(bool)
    raw_to_main = {
        "tx_soil_clay_mean_raw": "tx_soil_clay_mean_pct",
        "tx_soil_clay_sd_raw": "tx_soil_clay_sd_pct",
        "tx_soil_clay_p10_raw": "tx_soil_clay_p10_pct",
        "tx_soil_clay_p90_raw": "tx_soil_clay_p90_pct",
        "tx_soil_clay_p90_p10_raw": "tx_soil_clay_p90_p10_pct",
        "tx_soil_clay_coverage_pct_raw": "tx_soil_clay_coverage_pct",
        "tx_soil_silt_mean_raw": "tx_soil_silt_mean_pct",
        "tx_soil_sand_mean_raw": "tx_soil_sand_mean_pct",
        "tx_soil_texture_sum_mean_pct_raw": "tx_soil_texture_sum_mean_pct",
        "tx_soil_texture_pixel_rms_sd_pct_raw": "tx_soil_texture_pixel_rms_sd_pct",
        "tx_soil_texture_between_blocks_rms_pct_raw": "tx_soil_texture_between_blocks_rms_pct",
        "tx_soil_clay_between_blocks_sd_pct_raw": "tx_soil_clay_between_blocks_sd_pct",
        "tx_organic_entropy_bits_raw": "tx_organic_entropy_bits",
        "tx_organic_dominant_share_pct_raw": "tx_organic_dominant_share_pct",
    }
    for raw, main in raw_to_main.items():
        out[main] = np.where(ok, pd.to_numeric(out.get(raw), errors="coerce"), np.nan)

    # Keep organic mode as categorical diagnostic, not as a numeric regression term.
    out["tx_organic_mode_code"] = np.where(ok, out.get("tx_organic_mode_code_raw"), np.nan)
    out["tx_organic_mode_label"] = np.where(ok, out.get("tx_organic_mode_label_raw", ""), "")
    for code in ORG_CODES:
        raw = f"tx_organic_share_code_{code}_pct_raw"
        main = f"tx_organic_share_code_{code}_pct"
        out[main] = np.where(ok, pd.to_numeric(out.get(raw), errors="coerce"), np.nan)

    # Per-block diagnostics are useful for later map QA and diversity checks.
    block_df = pd.DataFrame(block_rows)
    return out, block_df
