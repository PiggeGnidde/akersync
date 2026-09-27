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
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
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
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  cache: {out_path.name}")
        g = gpd.read_file(out_path)
        if not g.empty:
            return g

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
    raw_dir.mkdir(parents=True, exist_ok=True)
    for r in unique.itertuples(index=False):
        url = str(r.url_tidsserie)
        oid = str(r.omrade_id)

        cached = sorted(raw_dir.glob(f"sgu_hype_{oid}.*"))
        if cached:
            path = cached[0]
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
            print(f"  SGU-HYPE history area {oid} (cache)")
            ctype = "cached"
        else:
            print(f"  SGU-HYPE history area {oid}")
            resp = dl.get(url, timeout=180)
            ctype = resp.headers.get("content-type")
            suffix = ".csv" if ("csv" in (ctype or "").lower() or "text" in (ctype or "").lower()) else ".dat"
            path = raw_dir / f"sgu_hype_{oid}{suffix}"
            path.write_bytes(resp.content)
            raw = resp.content
            text = resp.text

        lines = [x for x in text.splitlines() if x.strip()]
        if len(lines) < 2:
            raise RuntimeError(f"SGU-HYPE history area {oid}: response has <2 non-empty lines")
        rows.append({
            "omrade_id": oid,
            "url": url,
            "bytes": len(raw),
            "content_type": ctype,
            "sha256": sha256(path),
            "header": lines[0],
            "first_data_line": lines[1],
        })
    if len(rows) < min(n_cells, joined["omrade_id"].dropna().nunique()):
        raise RuntimeError("Could not retrieve required SGU-HYPE history samples")
    return rows

def extract_svar_bulk(zip_path: Path, extract_dir: Path) -> list[Path]:
    extract_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(extract_dir.rglob("*.gpkg")) + sorted(extract_dir.rglob("*.shp"))
    if existing:
        return existing

    with zipfile.ZipFile(zip_path) as z:
        wanted = []
        for name in z.namelist():
            lower = name.lower()
            if lower.endswith((".gpkg", ".shp", ".dbf", ".shx", ".prj", ".cpg")):
                wanted.append(name)
        if not wanted:
            raise RuntimeError(f"No GeoPackage/Shapefile content found in {zip_path}")
        for name in wanted:
            z.extract(name, extract_dir)

    return sorted(extract_dir.rglob("*.gpkg")) + sorted(extract_dir.rglob("*.shp"))


def read_svar_bulk_for_pilot(zip_path: Path, bbox3006: tuple[float,float,float,float],
                             extract_dir: Path) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    candidates = extract_svar_bulk(zip_path, extract_dir)
    if not candidates:
        raise RuntimeError("SVAR2022 bulk extraction produced no vector candidates")

    minx,miny,maxx,maxy = bbox3006
    pad = 5000.0
    clip = box(minx-pad, miny-pad, maxx+pad, maxy+pad)

    attempts = []
    for path in candidates:
        try:
            if path.suffix.lower() == ".gpkg":
                try:
                    layers = gpd.list_layers(path)
                    layer_names = layers["name"].astype(str).tolist()
                except Exception:
                    layer_names = [None]
            else:
                layer_names = [None]

            for layer in layer_names:
                try:
                    kwargs = {"layer": layer} if layer else {}
                    g = gpd.read_file(path, **kwargs)
                    if g.empty or g.crs is None:
                        attempts.append({
                            "path": str(path),
                            "layer": layer,
                            "status": "empty_or_no_crs",
                        })
                        continue
                    g3006 = g.to_crs(3006)
                    keep = g3006.geometry.intersects(clip)
                    sub = g3006.loc[keep].copy()
                    attempts.append({
                        "path": str(path),
                        "layer": layer,
                        "status": "ok",
                        "rows_total": int(len(g)),
                        "rows_pilot_bbox": int(len(sub)),
                        "crs": str(g.crs),
                    })
                    if len(sub):
                        return sub, {
                            "mode": "OFFICIAL_BULK_ZIP",
                            "source_file": str(path),
                            "layer": layer,
                            "source_crs": str(g.crs),
                            "rows_total": int(len(g)),
                            "rows_pilot_bbox": int(len(sub)),
                            "attempts": attempts,
                        }
                except Exception as exc:
                    attempts.append({
                        "path": str(path),
                        "layer": layer,
                        "status": "error",
                        "error": repr(exc),
                    })
        except Exception as exc:
            attempts.append({
                "path": str(path),
                "layer": None,
                "status": "error",
                "error": repr(exc),
            })

    raise RuntimeError(
        "Could not read any SVAR2022 bulk vector layer intersecting the pilot bbox. "
        f"Attempts={attempts}"
    )

def download_vattenwebb_excel(dl: Downloader, url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        print(f"  cache: {path.name} ({path.stat().st_size/1024/1024:.1f} MB)")
        return path
    r = dl.get(url, stream=True, timeout=300)
    tmp = path.with_suffix(path.suffix + ".part")
    total = 0
    with tmp.open("wb") as fh:
        for chunk in r.iter_content(1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > 100 * 1024 * 1024:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise RuntimeError("Vattenwebb flowstatistics workbook unexpectedly exceeds 100 MB")
            fh.write(chunk)
    tmp.replace(path)
    print(f"  downloaded: {path.name} ({path.stat().st_size/1024/1024:.1f} MB)")
    return path


def _xlsx_col_index(cell_ref: str) -> int:
    letters = re.match(r"([A-Z]+)", cell_ref.upper())
    if not letters:
        return 0
    n = 0
    for ch in letters.group(1):
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _xlsx_shared_strings(z: zipfile.ZipFile) -> list[str]:
    name = "xl/sharedStrings.xml"
    if name not in z.namelist():
        return []
    root = ET.fromstring(z.read(name))
    out = []
    for si in root:
        if si.tag.endswith("}si") or si.tag == "si":
            parts = []
            for el in si.iter():
                if el.tag.endswith("}t") or el.tag == "t":
                    parts.append(el.text or "")
            out.append("".join(parts))
    return out


def _xlsx_sheet_paths(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))

    relmap = {}
    for rel in rels:
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            relmap[rid] = target

    out = []
    for el in workbook.iter():
        if not (el.tag.endswith("}sheet") or el.tag == "sheet"):
            continue
        name = el.attrib.get("name", "")
        rid = None
        for k, v in el.attrib.items():
            if k.endswith("}id") or k == "r:id":
                rid = v
                break
        if not rid or rid not in relmap:
            continue
        target = relmap[rid].replace("\\\\", "/")
        if target.startswith("/"):
            path = target.lstrip("/")
        elif target.startswith("xl/"):
            path = target
        else:
            path = str(PurePosixPath("xl") / target)
        out.append((name, path))
    return out


def _xlsx_rows(z: zipfile.ZipFile, sheet_path: str, shared: list[str]) -> list[list[Any]]:
    root = ET.fromstring(z.read(sheet_path))
    rows: list[list[Any]] = []

    for row_el in root.iter():
        if not (row_el.tag.endswith("}row") or row_el.tag == "row"):
            continue
        vals: dict[int, Any] = {}
        for cell in row_el:
            if not (cell.tag.endswith("}c") or cell.tag == "c"):
                continue
            ref = cell.attrib.get("r", "A1")
            idx = _xlsx_col_index(ref)
            ctype = cell.attrib.get("t")
            value = None

            if ctype == "inlineStr":
                parts = []
                for el in cell.iter():
                    if el.tag.endswith("}t") or el.tag == "t":
                        parts.append(el.text or "")
                value = "".join(parts)
            else:
                v_el = None
                for el in cell:
                    if el.tag.endswith("}v") or el.tag == "v":
                        v_el = el
                        break
                if v_el is not None:
                    raw = v_el.text or ""
                    if ctype == "s":
                        try:
                            value = shared[int(raw)]
                        except Exception:
                            value = raw
                    elif ctype == "b":
                        value = raw == "1"
                    else:
                        value = raw

            vals[idx] = value

        if vals:
            width = max(vals) + 1
            row = [None] * width
            for idx, value in vals.items():
                row[idx] = value
            rows.append(row)
        else:
            rows.append([])
    return rows


def read_vattenwebb_flowstatistics(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read SMHI's XLSX without requiring openpyxl.

    XLSX is a ZIP of XML files, so the pilot uses only Python stdlib here.
    """
    with zipfile.ZipFile(path) as z:
        shared = _xlsx_shared_strings(z)
        sheets = _xlsx_sheet_paths(z)
        if not sheets:
            raise RuntimeError("Vattenwebb workbook contains no readable worksheets")

        candidates = []
        parsed: dict[str, list[list[Any]]] = {}

        for sheet_name, sheet_path in sheets:
            rows = _xlsx_rows(z, sheet_path, shared)
            parsed[sheet_name] = rows
            for row_idx, row in enumerate(rows[:100]):
                vals = [
                    str(v).strip().upper()
                    for v in row
                    if v is not None and str(v).strip()
                ]
                score = 0
                if "SUBID" in vals:
                    score += 5
                if "AROID" in vals:
                    score += 5
                if any("SUBID" in v for v in vals):
                    score += 2
                if any("AROID" in v for v in vals):
                    score += 2
                if any("MEDEL" in v or v in {"MQ","MLQ","MHQ"} for v in vals):
                    score += 1
                if score:
                    candidates.append((score, sheet_name, row_idx))

        if not candidates:
            raise RuntimeError(
                "Could not locate SUBID/AROID header in Vattenwebb workbook. "
                f"sheets={[name for name,_ in sheets]}"
            )

        candidates.sort(reverse=True)
        _, sheet_name, header_row = candidates[0]
        rows = parsed[sheet_name]
        header = rows[header_row]

        columns = []
        seen = {}
        for i, value in enumerate(header):
            base = str(value).strip() if value is not None and str(value).strip() else f"unnamed_{i}"
            n = seen.get(base, 0)
            seen[base] = n + 1
            columns.append(base if n == 0 else f"{base}_{n+1}")

        data_rows = []
        for row in rows[header_row + 1:]:
            if not row or not any(v is not None and str(v).strip() for v in row):
                continue
            padded = list(row) + [None] * max(0, len(columns) - len(row))
            data_rows.append(padded[:len(columns)])

        df = pd.DataFrame(data_rows, columns=columns)
        df = df.dropna(how="all").copy()

        info = {
            "sheet": sheet_name,
            "header_row_zero_based": int(header_row),
            "rows": int(len(df)),
            "columns": list(df.columns),
            "sheets": [name for name,_ in sheets],
            "xlsx_reader": "stdlib_zipfile_xml",
        }
        return df, info

def choose_model_id_column(df: pd.DataFrame) -> str | None:
    for wanted in ("SUBID", "AROID"):
        for c in df.columns:
            if c.upper() == wanted:
                return c
    return None


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
    targets = [
        c for c in coupling.columns
        if c.upper() in {"SUBID", "AROID", "VAROID", "MS_CD", "ARO_UUID"}
    ]
    if not targets:
        raise RuntimeError(f"Model table lacks recognized identifier columns: {list(coupling.columns)}")

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
    keep = ["_joinid"] + [x for x in coupling.columns if x != "_joinid"]
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

    # Use SMHI's official bulk package as the strict B data path. A2 already
    # proved WFS capabilities, but GetFeature can return server-side HTTP 500
    # for a large Skåne bbox. Bulk + local clipping is more reproducible.
    svar_zip = dl.download(
        cfg["sources"]["smhi_svar_zip"],
        raw/"smhi"/"SVAR2022_Vattenforekomstavrinningsomraden.zip",
        max_bytes=800*1024*1024,
    )
    svar, svar_source = read_svar_bulk_for_pilot(
        svar_zip, bbox3006,
        raw/"smhi"/"svar2022_extracted",
    )
    print("  source mode:", svar_source["mode"])
    print("  source file:", svar_source["source_file"])
    print("  source layer:", svar_source["layer"])
    print("  source CRS:", svar_source["source_crs"])
    print("  polygons in pilot bbox:", len(svar))
    print("  polygon columns:", ", ".join(str(c) for c in svar.columns))
    svar_join = spatial_join_points(points, svar, "SMHI SVAR2022")
    n_svar = int(svar_join["index_right"].notna().sum())
    print(f"  polygon matches: {n_svar}/{len(points)}")

    print("\n[6/8] Open Vattenwebb flow statistics and ID proof")
    flowstats_path = download_vattenwebb_excel(
        dl,
        cfg["sources"]["smhi_vattenwebb_flowstatistics"],
        raw/"smhi"/"vattenwebb_flowstatistics.xlsx",
    )
    flowstats, flowstats_info = read_vattenwebb_flowstatistics(flowstats_path)
    print("  workbook sheet:", flowstats_info["sheet"])
    print("  rows:", len(flowstats))
    print("  columns:", ", ".join(flowstats.columns))

    mapping = discover_svar_mapping(
        svar_join, flowstats,
        float(cfg["pilot_rules"]["mapping_min_match_fraction"]),
    )
    print("  best mapping:", mapping["best"])
    svar_mapped = apply_svar_mapping(svar_join, flowstats, mapping)

    model_id_col = choose_model_id_column(svar_mapped)
    if model_id_col is None:
        raise RuntimeError(
            "SVAR/Vattenwebb mapping succeeded but no SUBID/AROID column is present afterwards"
        )
    n_model_id = int(svar_mapped[model_id_col].notna().sum())
    print(f"  {model_id_col} mapped fields: {n_model_id}/{len(svar_mapped)}")

    print("\n[7/8] Documented NADIA daily-series handoff")
    nadia_ids = (
        svar_mapped[model_id_col].dropna().astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .drop_duplicates().sort_values()
        .head(int(cfg["pilot_rules"]["shype_ids_to_extract"])).tolist()
    )
    if len(nadia_ids) < 3:
        raise RuntimeError("Fewer than 3 mapped Vattenwebb basin IDs available for NADIA test")

    nadia_handoff = work/"nadia_ids_for_manual_check.txt"
    nadia_handoff.write_text(
        "NADIA URL: " + cfg["sources"]["smhi_nadia"] + "\n"
        + "IDs (" + model_id_col + "): " + ",".join(nadia_ids) + "\n"
        + "Requested validation: daily model data for a short period, e.g. 2025.\n"
        + "This manual handoff is deliberate: no undocumented NADIA backend endpoint is reverse-engineered.\n",
        encoding="utf-8",
    )
    print("  NADIA URL:", cfg["sources"]["smhi_nadia"])
    print("  sample IDs:", ",".join(nadia_ids))
    print("  NOTE: daily-series retrieval remains a manual/documented-UI validation before STOPPUNKT B is fully frozen.")

    print("\n[8/8] QA and pilot output")
    # Compact field result. Keep geometry separately in GPKG.
    out = points.drop(columns="geometry").copy()
    hype_cols = [c for c in ["pilot_order","omrade_id","url_tidsserie"] if c in hype_join.columns]
    out = out.merge(hype_join[hype_cols], on="pilot_order", how="left", validate="one_to_one")
    svar_keep = ["pilot_order"]
    for c in svar_mapped.columns:
        if c.upper() in {"SUBID","AROID","HARO","VAROID","MS_CD","VERSION_SVAR","ARO_UUID"} and c not in svar_keep:
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
        "shype_model_id_column": model_id_col,
        "shype_model_id_matched": n_model_id,
        "smallmag_pct": 100*n_small/len(out),
        "sgu_hype_pct": 100*n_hype/len(out),
        "svar_pct": 100*n_svar/len(out),
        "shype_model_id_pct": 100*n_model_id/len(out),
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
    if n_model_id < 95:
        problems.append(f"S-HYPE/Vattenwebb model-ID coverage only {n_model_id}/100")

    manifest = {
        "schema_version": "akervatten-mvp-v0a-b-pilot-result",
        "status": "PASS_WITH_WARNING" if not problems else "FAIL",
        "coverage": coverage,
        "sample_rules": {
            "design": "per municipality: dry archetype + wet archetype + non-old-robust edge case, deterministic fill to 100",
            "n_fields": len(out),
        },
        "sgu_history_samples": history_manifest,
        "svar_source": svar_source,
        "svar_to_shype_mapping": mapping,
        "vattenwebb_flowstatistics": {
            "url": cfg["sources"]["smhi_vattenwebb_flowstatistics"],
            "file": str(flowstats_path),
            "sha256": sha256(flowstats_path),
            **flowstats_info,
        },
        "nadia_daily_series": {
            "url": cfg["sources"]["smhi_nadia"],
            "id_column": model_id_col,
            "sample_ids": nadia_ids,
            "status": "MANUAL_DOCUMENTED_UI_VALIDATION_REQUIRED",
            "handoff_file": str(nadia_handoff),
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
    if not problems:
        print("Daily S-HYPE/NADIA series still require documented-UI validation before B can be frozen as full PASS.")
    print("="*118)
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
