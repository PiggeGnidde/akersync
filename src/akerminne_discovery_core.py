#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

from common import sha256_file

ALLOWED_EXAMPLE_COLUMNS = (
    "arslager", "blockid", "skiftesbeteckning", "grdkod_mar", "grdkod_und", "region_kod"
)

def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if pd.isna(value) else value
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    return str(value)


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    s = str(value)
    return s[:-2] if s.endswith(".0") else s


def _layer_names(path: Path) -> list[str]:
    return [str(row[0]) for row in pyogrio.list_layers(path)]


def choose_layer(path: Path, kind: str) -> str:
    layers = _layer_names(path)
    if not layers:
        raise RuntimeError(f"Inga lager i {path}")
    hints = ("skifte",) if kind == "skiften" else ("block",)
    ranked = sorted(layers, key=lambda name: (0 if any(h in name.lower() for h in hints) else 1, name.lower()))
    return ranked[0]


def candidate_score(path: Path, kind: str, year: int) -> tuple[int, str]:
    name = path.name.lower()
    stem = path.stem.lower()
    kind_hints = ("skifte", "field") if kind == "skiften" else ("block",)
    score = 0
    if str(year) in name:
        score += 10
    if any(h in name for h in kind_hints):
        score += 8
    if "arslager" in name:
        score += 4
    if path.suffix.lower() == ".gpkg":
        score += 3
    if re.search(rf"(^|[_-]){year}([_.-]|$)", stem):
        score += 2
    return score, str(path).lower()


def find_candidates(raw_root: Path, kind: str, year: int) -> list[Path]:
    if not raw_root.exists():
        return []
    hits: list[Path] = []
    for p in raw_root.rglob("*.gpkg"):
        low = p.name.lower()
        full_low = str(p).lower()
        if str(year) not in full_low:
            continue
        if kind == "skiften" and not ("skifte" in low or "field" in low):
            continue
        if kind == "blocks" and "block" not in low:
            continue
        hits.append(p)
    return sorted(hits, key=lambda p: candidate_score(p, kind, year), reverse=True)


def resolve_source(local_cfg: dict[str, Any], project_cfg: dict[str, Any], year: int, kind: str) -> dict[str, Any]:
    override = ((local_cfg.get("year_sources") or {}).get(str(year)) or {}).get(kind)
    if override:
        return {"path": str(Path(override)), "resolution": "akerminne_local_override", "candidates": [str(Path(override))]}
    if year == 2025:
        key = "skiften" if kind == "skiften" else "blocks"
        configured = project_cfg.get(key)
        if configured:
            return {"path": str(Path(configured)), "resolution": "project_local_paths_2025", "candidates": [str(Path(configured))]}
    raw_root = Path(local_cfg.get("raw_root") or "")
    candidates = find_candidates(raw_root, kind, year)
    if not candidates:
        return {"path": None, "resolution": "not_found", "candidates": []}
    best_score = candidate_score(candidates[0], kind, year)[0]
    top = [p for p in candidates if candidate_score(p, kind, year)[0] == best_score]
    if len(top) > 1:
        return {"path": None, "resolution": "ambiguous", "candidates": [str(p) for p in top[:20]]}
    return {"path": str(candidates[0]), "resolution": "auto_discovered", "candidates": [str(p) for p in candidates[:20]]}


def inspect_dataset(path: Path, kind: str, year: int, do_hash: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists(), "kind": kind, "year": year}
    if not path.exists():
        result["error"] = "FILE_NOT_FOUND"
        return result
    try:
        layer = choose_layer(path, kind)
        info = pyogrio.read_info(path, layer=layer)
        fields = [str(x) for x in info.get("fields", [])]
        dtypes = [str(x) for x in info.get("dtypes", [])]
        result.update({
            "layer": layer,
            "layers": _layer_names(path),
            "crs": info.get("crs"),
            "geometry_type": info.get("geometry_type"),
            "feature_count": int(info.get("features", -1)),
            "fields": fields,
            "dtypes": dict(zip(fields, dtypes)),
            "size_bytes": path.stat().st_size,
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
        if do_hash:
            result["sha256"] = sha256_file(path)
        sample = gpd.read_file(path, layer=layer, rows=50)
        result["sample_rows"] = int(len(sample))
        if len(sample):
            valid = sample.geometry.notna() & ~sample.geometry.is_empty & sample.geometry.is_valid
            result["sample_valid_geometry"] = int(valid.sum())
            result["sample_invalid_or_empty_geometry"] = int(len(sample) - valid.sum())
        examples: dict[str, list[Any]] = {}
        for c in ALLOWED_EXAMPLE_COLUMNS:
            if c in sample.columns:
                vals = []
                for v in sample[c].drop_duplicates().head(5).tolist():
                    vals.append(_jsonable(v))
                examples[c] = vals
        result["examples"] = examples
        year_col = "arslager" if "arslager" in sample.columns else None
        if year_col and len(sample):
            result["sample_year_values"] = sorted({_text(v) for v in sample[year_col].dropna().tolist()})[:20]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _read_skurup_blocks(path: Path, layer: str, region_col: str, code: str) -> gpd.GeoDataFrame:
    try:
        blocks = gpd.read_file(path, layer=layer, where=f"CAST({region_col} AS TEXT) LIKE '{code}%'")
        if len(blocks):
            return blocks
    except Exception:
        pass
    blocks = gpd.read_file(path, layer=layer)
    if region_col not in blocks.columns:
        return blocks.iloc[0:0].copy()
    mask = blocks[region_col].astype(str).str.startswith(code)
    return blocks.loc[mask].copy()


def inspect_skurup_subset(
    skifte_meta: dict[str, Any], block_meta: dict[str, Any], contract: dict[str, Any], municipality_code: str
) -> dict[str, Any]:
    out: dict[str, Any] = {"available": False}
    if not skifte_meta.get("exists") or not block_meta.get("exists"):
        out["reason"] = "SKIFTE_OR_BLOCK_SOURCE_MISSING"
        return out
    spath = Path(skifte_meta.get("path") or "")
    bpath = Path(block_meta.get("path") or "")
    if not spath.exists() or not bpath.exists() or skifte_meta.get("error") or block_meta.get("error"):
        out["reason"] = "SKIFTE_OR_BLOCK_SOURCE_MISSING"
        return out
    region_col = contract["region_column"]
    blockid_col = contract["current_block_column"]
    try:
        blocks = _read_skurup_blocks(bpath, block_meta["layer"], region_col, municipality_code)
        if blocks.empty:
            out["reason"] = "NO_SKURUP_BLOCKS_OR_REGION_COLUMN"
            return out
        allowed = set(blocks[blockid_col].astype(str)) if blockid_col in blocks.columns else set()
        if not allowed:
            out["reason"] = "BLOCKID_COLUMN_MISSING_IN_BLOCK_SOURCE"
            return out
        bbox = tuple(float(v) for v in blocks.total_bounds)
        fields = set(skifte_meta.get("fields") or [])
        if region_col in fields:
            try:
                skiften = gpd.read_file(spath, layer=skifte_meta["layer"], where=f"CAST({region_col} AS TEXT) LIKE '{municipality_code}%'")
                method = "direct_region_filter"
            except Exception:
                skiften = gpd.read_file(spath, layer=skifte_meta["layer"], bbox=bbox)
                skiften = skiften[skiften[blockid_col].astype(str).isin(allowed)].copy()
                method = "block_bbox_plus_blockid"
        else:
            skiften = gpd.read_file(spath, layer=skifte_meta["layer"], bbox=bbox)
            if blockid_col not in skiften.columns:
                out["reason"] = "BLOCKID_COLUMN_MISSING_IN_SKIFTE_SOURCE"
                return out
            skiften = skiften[skiften[blockid_col].astype(str).isin(allowed)].copy()
            method = "block_bbox_plus_blockid"
        id_col = contract["current_field_column"]
        crop_col = contract["crop_code_column"]
        sub_col = contract["crop_subcategory_column"]
        valid = skiften.geometry.notna() & ~skiften.geometry.is_empty & skiften.geometry.is_valid
        duplicate_key_count = None
        if blockid_col in skiften.columns and id_col in skiften.columns:
            duplicate_key_count = int(skiften.duplicated([blockid_col, id_col], keep=False).sum())
        out.update({
            "available": True,
            "method": method,
            "block_rows": int(len(blocks)),
            "skifte_rows": int(len(skiften)),
            "bbox": [round(float(v), 3) for v in bbox],
            "valid_geometry_rows": int(valid.sum()),
            "invalid_or_empty_geometry_rows": int(len(skiften) - valid.sum()),
            "duplicate_field_key_rows": duplicate_key_count,
            "field_key_columns_available": blockid_col in skiften.columns and id_col in skiften.columns,
            "crop_code_available": crop_col in skiften.columns,
            "crop_subcategory_available": sub_col in skiften.columns,
            "unique_crop_codes": int(skiften[crop_col].nunique(dropna=True)) if crop_col in skiften.columns else None,
        })
        examples = []
        cols = [c for c in (blockid_col, id_col, crop_col, sub_col) if c in skiften.columns]
        for _, row in skiften[cols].head(5).iterrows():
            examples.append({c: _jsonable(row[c]) for c in cols})
        out["examples"] = examples
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"
    return out


def network_probe(source: dict[str, Any], years: list[int], max_features: int, timeout: int = 30) -> dict[str, Any]:
    base = source["wfs"]
    typename = source["skifte_typename"]
    out: dict[str, Any] = {"wfs": base, "years": {}, "status": "OK"}
    for year in years:
        params = {
            "SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetFeature",
            "TYPENAME": typename, "CQL_FILTER": f"arslager={year}",
            "MAXFEATURES": str(max_features), "OUTPUTFORMAT": "application/json", "SRSNAME": "EPSG:3006",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AkerSync-AkerMinne/1a"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
            doc = json.loads(raw.decode("utf-8"))
            features = doc.get("features") or []
            props = (features[0].get("properties") if features else {}) or {}
            out["years"][str(year)] = {
                "ok": bool(features), "sample_features": len(features),
                "property_names": sorted(props.keys()),
                "example": {k: _jsonable(props.get(k)) for k in ALLOWED_EXAMPLE_COLUMNS if k in props},
            }
        except Exception as exc:
            out["status"] = "PARTIAL"
            out["years"][str(year)] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return out

