#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT B 100-field end-to-end pilot.

This pilot intentionally stays small and strict:
- deterministic 100-field sample from the full current Skåne population,
- local soil/TWI joined to real field geometry,
- SGU small-aquifer raster sampled at representative field points,
- SGU-HYPE area linkage + a few actual historical time-series downloads,
- SMHI SVAR2022 spatial linkage,
- current S-HYPE coupling table used to prove geometry -> AROID/SUBID mapping,
- one current S-HYPE 30-day NetCDF analysis file used to prove actual flow-series linkage.

No product score is frozen here.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import CRS
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_b.json"
DEFAULT_WORK = ROOT / "work" / "akervatten_mvp_v0a" / "b_pilot"
DEFAULT_RAW = ROOT / "data" / "raw" / "akervatten" / "b_pilot"

KEY = ["blockid", "skiftesbeteckning"]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class Downloader:
    def __init__(self, timeout: int, retries: int, backoff: float):
        self.timeout = timeout
        self.retries = max(1, retries)
        self.backoff = backoff
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "AkerVatten-MVP-v0a-B-pilot/1.0"})

    def get(self, url: str, *, params: dict[str, Any] | None = None,
            stream: bool = False, timeout: int | None = None) -> requests.Response:
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.s.get(
                    url, params=params, timeout=timeout or self.timeout,
                    allow_redirects=True, stream=stream
                )
                r.raise_for_status()
                return r
            except requests.RequestException as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * attempt)
        raise RuntimeError(f"GET failed after {self.retries} attempts: {url}: {last}")

    def download(self, url: str, path: Path, *, max_bytes: int | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 0:
            print(f"  cache: {path.name} ({path.stat().st_size/1024/1024:.1f} MB)")
            return path
        tmp = path.with_suffix(path.suffix + ".part")
        if tmp.exists():
            tmp.unlink()
        r = self.get(url, stream=True)
        total = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Download exceeds pilot limit {max_bytes/1024/1024:.0f} MB: {url}"
                    )
                f.write(chunk)
        tmp.replace(path)
        print(f"  downloaded: {path.name} ({path.stat().st_size/1024/1024:.1f} MB)")
        return path


def read_local_paths(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"local_paths.json not found: {path}")
    return load_json(path)


def stable_hash(blockid: str, skifte: str) -> int:
    key = f"{blockid}|{skifte}".encode("utf-8")
    # Keep the deterministic hash inside signed int64 so GDAL/GeoPackage
    # can serialize it safely if it ever leaks into an exported table.
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big", signed=False) & ((1 << 63) - 1)


def build_deterministic_sample(
    soil: pd.DataFrame,
    hydro: pd.DataFrame,
    status: pd.DataFrame,
    n_target: int,
    municipality_col: str,
) -> pd.DataFrame:
    x = soil.merge(
        hydro[KEY + ["twi_mean", "twi_p50", "twi_p90", "twi_n_cells"]],
        on=KEY, how="left", validate="one_to_one",
        suffixes=("", "_hydro"),
    )
    x = x.merge(
        status[KEY + ["a1b_data_status", "old_robust"]],
        on=KEY, how="left", validate="one_to_one",
    )
    if municipality_col not in x.columns:
        raise RuntimeError(f"Municipality column missing: {municipality_col}")

    for c in ("sand_mean", "clay_mean", "twi_mean"):
        x[c] = pd.to_numeric(x[c], errors="coerce")

    # Comparable 0..1 ranks over fields with data.
    x["sand_pct"] = x["sand_mean"].rank(method="average", pct=True)
    x["clay_pct"] = x["clay_mean"].rank(method="average", pct=True)
    x["twi_pct"] = x["twi_mean"].rank(method="average", pct=True)
    x["dry_axis"] = 0.5 * x["sand_pct"] + 0.5 * (1.0 - x["twi_pct"])
    x["wet_axis"] = 0.5 * x["clay_pct"] + 0.5 * x["twi_pct"]
    x["_hash"] = [
        stable_hash(str(a), str(b))
        for a, b in x[KEY].itertuples(index=False, name=None)
    ]

    picks = []
    used = set()

    municipalities = sorted(
        str(v) for v in x[municipality_col].dropna().unique()
        if str(v).strip()
    )
    for mun in municipalities:
        q = x[x[municipality_col].astype(str).eq(mun)].copy()
        if q.empty:
            continue

        # 1) dry archetype, 2) wet archetype, 3) non-old-robust quality-edge case.
        for mode in ("dry", "wet", "edge"):
            if mode == "dry":
                # Prefer a physically dry archetype with robust local inputs.
                base = q[q["old_robust"].fillna(False) & q["dry_axis"].notna()]
                if base.empty:
                    base = q[q["dry_axis"].notna()]
                z = base.sort_values(
                    ["dry_axis", "_hash"], ascending=[False, True]
                )
            elif mode == "wet":
                # Prefer a physically wet archetype with robust local inputs.
                base = q[q["old_robust"].fillna(False) & q["wet_axis"].notna()]
                if base.empty:
                    base = q[q["wet_axis"].notna()]
                z = base.sort_values(
                    ["wet_axis", "_hash"], ascending=[False, True]
                )
            else:
                z = q[~q["old_robust"].fillna(False)].sort_values("_hash")
                if z.empty:
                    z = q.sort_values("_hash")

            for idx in z.index:
                key = tuple(str(v) for v in x.loc[idx, KEY])
                if key not in used:
                    picks.append(idx)
                    used.add(key)
                    break

    # Intentionally include one DATA_MISSING field if available, to exercise flags.
    missing = x[x["a1b_data_status"].eq("DATA_MISSING")].sort_values("_hash")
    if len(picks) < n_target and not missing.empty:
        for idx in missing.index:
            key = tuple(str(v) for v in x.loc[idx, KEY])
            if key not in used:
                picks.append(idx)
                used.add(key)
                break

    # Deterministic fill/truncate to exact target.
    for idx in x.sort_values("_hash").index:
        if len(picks) >= n_target:
            break
        key = tuple(str(v) for v in x.loc[idx, KEY])
        if key not in used:
            picks.append(idx)
            used.add(key)

    out = x.loc[picks[:n_target]].copy().reset_index(drop=True)
    out["pilot_order"] = np.arange(1, len(out) + 1)
    if len(out) != n_target:
        raise RuntimeError(f"Could only select {len(out)} pilot fields, expected {n_target}")
    if out[KEY].duplicated().any():
        raise RuntimeError("Pilot sample contains duplicate field keys")
    return out


def load_pilot_geometries(sample: pd.DataFrame, skiften_path: Path) -> gpd.GeoDataFrame:
    print(f"  field geometry source: {skiften_path}")
    g = gpd.read_file(skiften_path)
    missing = [c for c in KEY if c not in g.columns]
    if missing:
        raise RuntimeError(f"Field geometry lacks key columns: {missing}")
    g["blockid"] = g["blockid"].astype(str)
    g["skiftesbeteckning"] = g["skiftesbeteckning"].astype(str)
    wanted = set(tuple(v) for v in sample[KEY].astype(str).itertuples(index=False, name=None))
    g["_k"] = list(zip(g["blockid"], g["skiftesbeteckning"]))
    g = g[g["_k"].isin(wanted)].drop(columns="_k").copy()
    if len(g) != len(sample):
        have = set(tuple(v) for v in g[KEY].astype(str).itertuples(index=False, name=None))
        miss = wanted - have
        raise RuntimeError(f"Only {len(g)}/{len(sample)} pilot field geometries found; missing={len(miss)}")
    if g.crs is None:
        raise RuntimeError("Field geometry has no CRS")

    # Preserve source polygons; representative point is guaranteed inside polygon.
    pts = g.to_crs(3006).copy()
    pts["geometry"] = pts.geometry.representative_point()
    pts = pts[KEY + ["geometry"]]
    # Internal sampling helpers are not product/output fields.
    sample_export = sample.drop(columns=["_hash"], errors="ignore")
    out = gpd.GeoDataFrame(sample_export.merge(pts, on=KEY, validate="one_to_one"), crs=pts.crs)
    w = out.to_crs(4326)
    out["lon"] = w.geometry.x.values
    out["lat"] = w.geometry.y.values
    out["x3006"] = out.geometry.x.values
    out["y3006"] = out.geometry.y.values
    return out


def extract_tifs(zip_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    found = sorted(out_dir.rglob("*.tif")) + sorted(out_dir.rglob("*.tiff"))
    if found:
        return found
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
        if not names:
            raise RuntimeError(f"No TIFF in {zip_path}")
        for name in names:
            z.extract(name, out_dir)
    return sorted(out_dir.rglob("*.tif")) + sorted(out_dir.rglob("*.tiff"))


def sample_smallmag(points3006: gpd.GeoDataFrame, tifs: list[Path]) -> pd.DataFrame:
    result = pd.DataFrame({
        "pilot_order": points3006["pilot_order"].values,
        "sgu_smallmag_value": np.nan,
        "sgu_smallmag_tif": None,
    })
    remaining = set(range(len(points3006)))

    for tif in tifs:
        if not remaining:
            break
        with rasterio.open(tif) as ds:
            if ds.crs is None:
                continue
            p = points3006.iloc[sorted(remaining)].to_crs(ds.crs)
            coords = [(geom.x, geom.y) for geom in p.geometry]
            vals = list(ds.sample(coords, indexes=1, masked=True))
            idxs = list(p.index)
            for source_idx, value in zip(idxs, vals):
                v = value[0]
                if np.ma.is_masked(v):
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if ds.nodata is not None and math.isclose(fv, float(ds.nodata), rel_tol=0, abs_tol=1e-12):
                    continue
                if not np.isfinite(fv):
                    continue
                row = points3006.index.get_loc(source_idx)
                result.loc[row, "sgu_smallmag_value"] = fv
                result.loc[row, "sgu_smallmag_tif"] = tif.name
                remaining.discard(source_idx)
    return result


def get_sgu_hype_areas(dl: Downloader, url: str, bbox_wgs84: tuple[float,float,float,float],
                       out_path: Path) -> gpd.GeoDataFrame:
    params = {
        "f": "application/geo+json",
        "bbox": ",".join(f"{v:.7f}" for v in bbox_wgs84),
        "limit": 10000,
    }
    r = dl.get(url, params=params)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    g = gpd.read_file(out_path)
    if g.empty:
        raise RuntimeError("SGU-HYPE bbox returned zero areas")
    return g


def spatial_join_points(points3006: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame,
                        prefix: str) -> gpd.GeoDataFrame:
    if polygons.crs is None:
        raise RuntimeError(f"{prefix} polygons lack CRS")
    p = points3006.to_crs(polygons.crs)
    j = gpd.sjoin(p, polygons, how="left", predicate="within")
    if len(j) != len(points3006):
        # For boundary hits, retry intersects and collapse only exact one-match cases.
        ji = gpd.sjoin(p, polygons, how="left", predicate="intersects")
        counts = ji.groupby("pilot_order").size()
        multi = counts[counts > 1]
        if len(multi):
            raise RuntimeError(f"{prefix}: {len(multi)} pilot points have multiple polygon matches")
        j = ji
    if len(j) != len(points3006):
        raise RuntimeError(f"{prefix}: join changed row count {len(points3006)} -> {len(j)}")
    return j.sort_values("pilot_order").reset_index(drop=True)


def fetch_sgu_history_samples(dl: Downloader, joined: pd.DataFrame, n_cells: int,
                              raw_dir: Path) -> list[dict[str, Any]]:
    if "omrade_id" not in joined.columns or "url_tidsserie" not in joined.columns:
        raise RuntimeError("SGU-HYPE join lacks omrade_id/url_tidsserie")
    unique = (
        joined[["omrade_id", "url_tidsserie"]]
        .dropna()
        .drop_duplicates()
        .sort_values("omrade_id", key=lambda s: s.astype(str))
        .head(n_cells)
    )
    rows = []
    for r in unique.itertuples(index=False):
        url = str(r.url_tidsserie)
        oid = str(r.omrade_id)
        print(f"  SGU-HYPE history area {oid}")
        resp = dl.get(url, timeout=180)
        ctype = (resp.headers.get("content-type") or "").lower()
        suffix = ".csv" if ("csv" in ctype or "text" in ctype) else ".dat"
        path = raw_dir / f"sgu_hype_{oid}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        text = resp.text
        lines = [x for x in text.splitlines() if x.strip()]
        if len(lines) < 2:
            raise RuntimeError(f"SGU-HYPE history area {oid}: response has <2 non-empty lines")
        rows.append({
            "omrade_id": oid,
            "url": url,
            "bytes": len(resp.content),
            "content_type": resp.headers.get("content-type"),
            "sha256": sha256(path),
            "header": lines[0],
            "first_data_line": lines[1],
        })
    if len(rows) < min(n_cells, joined["omrade_id"].dropna().nunique()):
        raise RuntimeError("Could not retrieve required SGU-HYPE history samples")
    return rows


def fetch_svar_wfs(dl: Downloader, base_url: str, typename: str,
                   bbox3006: tuple[float,float,float,float], out_path: Path) -> gpd.GeoDataFrame:
    # Add a modest margin so boundary polygons are safely included.
    minx,miny,maxx,maxy = bbox3006
    pad = 5000.0
    bbox_txt = f"{minx-pad:.3f},{miny-pad:.3f},{maxx+pad:.3f},{maxy+pad:.3f},urn:ogc:def:crs:EPSG::3006"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "application/json",
        "srsName": "EPSG:3006",
        "bbox": bbox_txt,
    }
    r = dl.get(base_url, params=params, timeout=180)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    g = gpd.read_file(out_path)
    if g.empty:
        raise RuntimeError("SMHI SVAR2022 WFS bbox returned zero polygons")
    return g


def read_coupling_table(path: Path) -> pd.DataFrame:
    # SMHI CSV may use semicolon and Swedish/UTF-8 variants.
    raw = path.read_bytes()
    best = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        for sep in (";", ",", "\t"):
            try:
                df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str)
            except Exception:
                continue
            if len(df.columns) >= 3:
                best = df
                break
        if best is not None:
            break
    if best is None:
        raise RuntimeError("Could not parse S-HYPE coupling table")
    best.columns = [str(c).strip() for c in best.columns]
    return best


def norm_id(s: pd.Series) -> pd.Series:
    return (
        s.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.upper()
    )


def discover_svar_mapping(joined: pd.DataFrame, coupling: pd.DataFrame,
                          min_fraction: float) -> dict[str, Any]:
    targets = [c for c in coupling.columns if c.upper() in {"SUBID", "AROID"}]
    if not targets:
        raise RuntimeError(f"Coupling table lacks SUBID/AROID columns: {list(coupling.columns)}")

    ignore = set(KEY + [
        "pilot_order","sand_mean","clay_mean","silt_mean","twi_mean","twi_p50","twi_p90",
        "twi_n_cells","lon","lat","x3006","y3006","geometry","index_right"
    ])
    polygon_cols = [c for c in joined.columns if c not in ignore]
    tests = []
    for pc in polygon_cols:
        vals = norm_id(joined[pc])
        denom = int(vals.notna().sum())
        if denom == 0:
            continue
        for tc in targets:
            valid = set(norm_id(coupling[tc]).dropna())
            matched = int(vals.isin(valid).sum())
            tests.append({
                "polygon_column": pc,
                "coupling_column": tc,
                "n_non_null": denom,
                "n_match": matched,
                "match_fraction": matched / denom if denom else 0.0,
            })
    tests = sorted(tests, key=lambda x: (-x["match_fraction"], -x["n_match"], x["polygon_column"]))
    if not tests:
        raise RuntimeError("No candidate SVAR->S-HYPE identifier mapping could be tested")
    best = tests[0]
    if best["match_fraction"] < min_fraction:
        raise RuntimeError(
            f"No SVAR->S-HYPE mapping reached {min_fraction:.0%}; best={best}"
        )
    return {"best": best, "all_candidates": tests[:20]}


def apply_svar_mapping(joined: pd.DataFrame, coupling: pd.DataFrame,
                       mapping: dict[str, Any]) -> pd.DataFrame:
    best = mapping["best"]
    pc = best["polygon_column"]
    tc = best["coupling_column"]
    c = coupling.copy()
    c["_joinid"] = norm_id(c[tc])
    keep = ["_joinid"] + [x for x in coupling.columns if x.upper() in {"SUBID","AROID","HARO"}]
    c = c[keep].drop_duplicates("_joinid")
    x = joined.copy()
    x["_joinid"] = norm_id(x[pc])
    x = x.merge(c, on="_joinid", how="left", validate="many_to_one", suffixes=("","_coupling"))
    return x


def latest_analysis_url(dl: Downloader, directory_url: str) -> tuple[str,str]:
    r = dl.get(directory_url)
    names = re.findall(r'href=["\']([^"\']*s-hype2022_analysis_\d{8}T\d+\.\d+\.nc)["\']', r.text)
    if not names:
        # Directory indexes can render href differently; also scan visible text.
        names = re.findall(r'(s-hype2022_analysis_\d{8}T\d+\.\d+\.nc)', r.text)
    if not names:
        raise RuntimeError("Could not locate current S-HYPE analysis NetCDF in official directory")
    name = sorted(set(Path(n).name for n in names))[-1]
    return directory_url.rstrip("/") + "/" + name, name


def extract_shype_flow(nc_path: Path, subids: list[str], out_path: Path) -> dict[str, Any]:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for S-HYPE NetCDF pilot") from exc

    ds = xr.open_dataset(nc_path)
    try:
        if "id" not in ds.variables:
            raise RuntimeError(f"S-HYPE NetCDF lacks id variable; variables={list(ds.variables)}")
        idvar = ds["id"]
        if len(idvar.dims) != 1:
            raise RuntimeError(f"Unexpected id dimensions: {idvar.dims}")
        id_dim = idvar.dims[0]
        ids = pd.Series(idvar.values).astype(str).str.replace(r"\.0$", "", regex=True).tolist()

        time_dim = None
        if "time" in ds.variables and len(ds["time"].dims) == 1:
            time_dim = ds["time"].dims[0]
        else:
            for d in ds.dims:
                if "time" in d.lower():
                    time_dim = d
                    break
        if time_dim is None:
            raise RuntimeError("Could not identify S-HYPE time dimension")

        candidates = []
        for name, da in ds.data_vars.items():
            if id_dim not in da.dims or time_dim not in da.dims:
                continue
            units = str(da.attrs.get("units",""))
            std = str(da.attrs.get("standard_name",""))
            long = str(da.attrs.get("long_name",""))
            score = 0
            txt = f"{name} {units} {std} {long}".lower()
            if "m3" in txt or "m^3" in txt or "m³" in txt:
                score += 3
            if "discharge" in txt or "flow" in txt or "vattenför" in txt:
                score += 3
            if name.lower().startswith("q"):
                score += 1
            candidates.append((score,name,units,std,long))
        candidates.sort(reverse=True)
        if not candidates or candidates[0][0] <= 0:
            raise RuntimeError(f"No plausible flow variable found; data_vars={list(ds.data_vars)}")
        flow_name = candidates[0][1]
        da = ds[flow_name]

        id_to_pos = {v:i for i,v in enumerate(ids)}
        chosen = [str(v).replace(".0","") for v in subids if str(v).replace(".0","") in id_to_pos]
        if not chosen:
            raise RuntimeError("None of selected SUBIDs exist in current S-HYPE NetCDF id variable")

        rows = []
        times = pd.to_datetime(ds["time"].values)
        for sid in chosen:
            pos = id_to_pos[sid]
            vals = da.isel({id_dim: pos}).values
            vals = np.asarray(vals).reshape(-1)
            for t, v in zip(times, vals):
                fv = float(v) if np.isfinite(v) else np.nan
                rows.append({"SUBID": sid, "time": t, "flow_value": fv})
        out = pd.DataFrame(rows)
        out.to_parquet(out_path, index=False)
        return {
            "flow_variable": flow_name,
            "flow_units": str(da.attrs.get("units","")),
            "candidate_variables": [
                {"score":s,"name":n,"units":u,"standard_name":st,"long_name":lo}
                for s,n,u,st,lo in candidates[:10]
            ],
            "requested_subids": subids,
            "matched_subids": chosen,
            "n_rows": int(len(out)),
            "time_start": str(out["time"].min()) if len(out) else None,
            "time_end": str(out["time"].max()) if len(out) else None,
        }
    finally:
        ds.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    work = Path(args.work)
    raw = Path(args.raw)
    work.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)

    net = cfg["network"]
    dl = Downloader(
        timeout=int(net["timeout_seconds"]),
        retries=int(net["retries"]),
        backoff=float(net["retry_backoff_seconds"]),
    )

    paths = cfg["paths"]
    soil = pd.read_csv(paths["soil"], dtype={"blockid":str,"skiftesbeteckning":str}, low_memory=False)
    hydro = pd.read_csv(paths["hydrology"], dtype={"blockid":str,"skiftesbeteckning":str}, low_memory=False)
    status_path = ROOT / paths["a1b_status"]
    status = pd.read_parquet(status_path)
    status["blockid"] = status["blockid"].astype(str)
    status["skiftesbeteckning"] = status["skiftesbeteckning"].astype(str)

    print("="*118)
    print("ÅkerVatten MVP v0a · STOPPUNKT B · 100-FIELD END-TO-END PILOT")
    print("="*118)

    print("\n[1/8] Deterministic pilot sample")
    sample = build_deterministic_sample(
        soil, hydro, status,
        int(cfg["pilot_fields"]),
        cfg["pilot_rules"]["municipality_column"],
    )
    print("  fields:", len(sample))
    print("  municipalities:", sample[cfg["pilot_rules"]["municipality_column"]].nunique())
    print("  status counts:")
    print(sample["a1b_data_status"].value_counts(dropna=False).to_string())

    local_paths = read_local_paths(Path(paths["local_paths_json"]))
    if "skiften" not in local_paths:
        raise RuntimeError(f"'skiften' missing in {paths['local_paths_json']}")
    points = load_pilot_geometries(sample, Path(local_paths["skiften"]))
    pilot_gpkg = work/"pilot_fields_100.gpkg"
    # A failed previous write may leave a partial GeoPackage. Recreate deterministically.
    pilot_gpkg.unlink(missing_ok=True)
    points.to_file(pilot_gpkg, layer="pilot_fields", driver="GPKG")

    print("\n[2/8] SGU small-magasin raster")
    zip_path = dl.download(
        cfg["sources"]["sgu_smallmag_zip"],
        raw/"sgu"/"grundvattentillgang-sma-magasin.zip",
        max_bytes=800*1024*1024,
    )
    tifs = extract_tifs(zip_path, raw/"sgu"/"smallmag_extracted")
    print("  TIFF files:", len(tifs))
    small = sample_smallmag(points, tifs)
    points = points.merge(small, on="pilot_order", validate="one_to_one")
    n_small = int(pd.to_numeric(points["sgu_smallmag_value"], errors="coerce").notna().sum())
    print(f"  matched raster values: {n_small}/{len(points)}")

    print("\n[3/8] SGU-HYPE spatial linkage")
    pwgs = points.to_crs(4326)
    minx,miny,maxx,maxy = pwgs.total_bounds
    hype_areas = get_sgu_hype_areas(
        dl, cfg["sources"]["sgu_hype_areas"],
        (float(minx),float(miny),float(maxx),float(maxy)),
        raw/"sgu"/"sgu_hype_areas_pilot.geojson",
    )
    hype_join = spatial_join_points(points, hype_areas, "SGU-HYPE")
    n_hype = int(hype_join["omrade_id"].notna().sum()) if "omrade_id" in hype_join else 0
    print(f"  area matches: {n_hype}/{len(points)}")
    print("  unique areas:", hype_join["omrade_id"].nunique(dropna=True))

    print("\n[4/8] SGU-HYPE actual historical samples")
    history_manifest = fetch_sgu_history_samples(
        dl, hype_join,
        int(cfg["pilot_rules"]["history_cells_to_fetch"]),
        raw/"sgu"/"history",
    )
    print("  history files:", len(history_manifest))

    print("\n[5/8] SMHI SVAR2022 spatial linkage")
    bbox3006 = tuple(float(v) for v in points.total_bounds)
    svar = fetch_svar_wfs(
        dl, cfg["sources"]["smhi_svar_wfs"], cfg["sources"]["smhi_svar_typename"],
        bbox3006,
        raw/"smhi"/"svar2022_pilot.geojson",
    )
    print("  polygons downloaded:", len(svar))
    print("  polygon columns:", ", ".join(str(c) for c in svar.columns))
    svar_join = spatial_join_points(points, svar, "SMHI SVAR2022")
    n_svar = int(svar_join["index_right"].notna().sum())
    print(f"  polygon matches: {n_svar}/{len(points)}")

    print("\n[6/8] Current S-HYPE coupling table and ID proof")
    coupling_path = dl.download(
        cfg["sources"]["smhi_shype_coupling"],
        raw/"smhi"/"s-hype2022_kopplingstabell.csv",
        max_bytes=20*1024*1024,
    )
    coupling = read_coupling_table(coupling_path)
    print("  coupling rows:", len(coupling))
    print("  coupling columns:", ", ".join(coupling.columns))
    mapping = discover_svar_mapping(
        svar_join, coupling,
        float(cfg["pilot_rules"]["mapping_min_match_fraction"]),
    )
    print("  best mapping:", mapping["best"])
    svar_mapped = apply_svar_mapping(svar_join, coupling, mapping)
    subid_col = next((c for c in svar_mapped.columns if c.upper()=="SUBID"), None)
    if subid_col is None:
        raise RuntimeError("No SUBID after SVAR/coupling mapping")
    n_subid = int(svar_mapped[subid_col].notna().sum())
    print(f"  SUBID mapped fields: {n_subid}/{len(svar_mapped)}")

    print("\n[7/8] Actual current S-HYPE flow series")
    analysis_url, analysis_name = latest_analysis_url(dl, cfg["sources"]["smhi_shype_dir"])
    nc_path = dl.download(
        analysis_url,
        raw/"smhi"/analysis_name,
        max_bytes=50*1024*1024,
    )
    subids = (
        svar_mapped[subid_col].dropna().astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .drop_duplicates().sort_values().head(int(cfg["pilot_rules"]["shype_ids_to_extract"])).tolist()
    )
    shype_manifest = extract_shype_flow(
        nc_path, subids,
        work/"shype_current_flow_samples.parquet",
    )
    print("  flow variable:", shype_manifest["flow_variable"], shype_manifest["flow_units"])
    print("  matched SUBIDs:", ", ".join(shype_manifest["matched_subids"]))
    print("  rows:", shype_manifest["n_rows"])
    print("  period:", shype_manifest["time_start"], "->", shype_manifest["time_end"])

    print("\n[8/8] QA and pilot output")
    # Compact field result. Keep geometry separately in GPKG.
    out = points.drop(columns="geometry").copy()
    hype_cols = [c for c in ["pilot_order","omrade_id","url_tidsserie"] if c in hype_join.columns]
    out = out.merge(hype_join[hype_cols], on="pilot_order", how="left", validate="one_to_one")
    svar_keep = ["pilot_order"]
    for c in svar_mapped.columns:
        if c.upper() in {"SUBID","AROID","HARO","VAROID","MS_CD","VERSION_SVAR"} and c not in svar_keep:
            svar_keep.append(c)
    out = out.merge(
        svar_mapped[svar_keep].drop_duplicates("pilot_order"),
        on="pilot_order", how="left", validate="one_to_one",
    )
    out.to_parquet(work/"pilot_fields_100_linked.parquet", index=False)

    coverage = {
        "fields_total": len(out),
        "municipalities": int(out[cfg["pilot_rules"]["municipality_column"]].nunique()),
        "smallmag_matched": n_small,
        "sgu_hype_matched": n_hype,
        "svar_matched": n_svar,
        "subid_matched": n_subid,
        "smallmag_pct": 100*n_small/len(out),
        "sgu_hype_pct": 100*n_hype/len(out),
        "svar_pct": 100*n_svar/len(out),
        "subid_pct": 100*n_subid/len(out),
    }

    problems = []
    if len(out) != int(cfg["pilot_fields"]):
        problems.append("field population changed")
    if n_small < 90:
        problems.append(f"SGU smallmag coverage only {n_small}/100")
    if n_hype < 95:
        problems.append(f"SGU-HYPE coverage only {n_hype}/100")
    if len(history_manifest) < 3:
        problems.append("fewer than 3 actual SGU-HYPE history series fetched")
    if n_svar < 95:
        problems.append(f"SVAR2022 coverage only {n_svar}/100")
    if n_subid < 95:
        problems.append(f"S-HYPE SUBID coverage only {n_subid}/100")
    if len(shype_manifest["matched_subids"]) < min(3, len(subids)):
        problems.append("fewer than 3 actual S-HYPE current flow series extracted")

    manifest = {
        "schema_version": "akervatten-mvp-v0a-b-pilot-result",
        "status": "PASS" if not problems else "FAIL",
        "coverage": coverage,
        "sample_rules": {
            "design": "per municipality: dry archetype + wet archetype + non-old-robust edge case, deterministic fill to 100",
            "n_fields": len(out),
        },
        "sgu_history_samples": history_manifest,
        "svar_to_shype_mapping": mapping,
        "shype_current_analysis": {
            "url": analysis_url,
            "file": analysis_name,
            "sha256": sha256(nc_path),
            **shype_manifest,
        },
        "guardrails": cfg["guardrails"],
        "problems": problems,
    }
    (work/"b_pilot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\nCOVERAGE")
    for k,v in coverage.items():
        print(f"  {k:24s}: {v}")

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -", p)

    print("\nOutputs:", work)
    print("="*118)
    print(f"AKERVATTEN STOPPUNKT B 100-FIELD PILOT: {manifest['status']}")
    print("="*118)
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
