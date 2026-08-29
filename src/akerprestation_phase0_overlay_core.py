#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import pandas as pd

SCHEMA_VERSION = "akerprestation-context-v0a"
CHECKPOINT_VERSION = "akerprestation-phase0-checkpoint-v0a"
NUMERIC_AREA_EPS = 1e-6
COVERAGE_TOL = 1e-6
VALID_SOIL_CLASSES = tuple(range(1, 11))

def text_id(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s

def field_id(blockid: Any, skiftesbeteckning: Any) -> str:
    return f"{text_id(blockid)}|{text_id(skiftesbeteckning)}"

def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()

def atomic_json(doc: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)

def atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.parquet")
    tmp.unlink(missing_ok=True)
    df.to_parquet(tmp, index=False)
    check = pd.read_parquet(tmp)
    if len(check) != len(df) or list(check.columns) != list(df.columns):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Parquet verification failed: {path}")
    os.replace(tmp, path)

def _make_valid(geom):
    if geom is None:
        return None, False, "EMPTY"
    try:
        if geom.is_empty:
            return geom, False, "EMPTY"
        if geom.is_valid:
            return geom, False, "OK"
    except Exception:
        return geom, False, "GEOMETRY_ERROR"
    try:
        from shapely import make_valid
        fixed = make_valid(geom)
    except Exception:
        try:
            fixed = geom.buffer(0)
        except Exception:
            return geom, False, "GEOMETRY_ERROR"
    if fixed is None or fixed.is_empty:
        return fixed, True, "GEOMETRY_ERROR"
    return fixed, True, "OK" if fixed.is_valid else "GEOMETRY_ERROR"

def prepare_geometries(gdf: gpd.GeoDataFrame, source_name: str) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    if gdf.crs is None:
        raise ValueError(f"{source_name}: missing CRS")
    work = gdf.to_crs(3006).copy().reset_index(drop=True)
    repaired = 0
    failed = 0
    empty = 0
    fixed = []
    flags = []
    for geom in work.geometry:
        g, was_repaired, status = _make_valid(geom)
        repaired += int(was_repaired and status == "OK")
        failed += int(status == "GEOMETRY_ERROR")
        empty += int(status == "EMPTY")
        fixed.append(g)
        flags.append("REPAIRED_REFERENCE_GEOMETRY" if was_repaired and status == "OK" else ("GEOMETRY_ERROR" if status == "GEOMETRY_ERROR" else ""))
    work.geometry = fixed
    work["_geometry_reason_flag"] = flags
    return work, {"source": source_name, "repaired": repaired, "failed": failed, "empty": empty, "rows": int(len(work))}

@dataclass(frozen=True)
class LayerSpec:
    layer_name: str
    code_field: str
    source_id_field: str
    valid_codes: tuple[str, ...] | None = None

SOIL_SPEC = LayerSpec("soil_class", "KLASS", "OBJECTID_12", tuple(str(x) for x in VALID_SOIL_CLASSES))
SKO_SPEC = LayerSpec("sko", "skordeomrade", "id", None)

def _stable_component_sort(df: pd.DataFrame, code_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values(
        ["current_field_id", "intersection_area_m2", code_col, "source_feature_id"],
        ascending=[True, False, True, True], kind="mergesort"
    ).reset_index(drop=True)

def overlay_fields(
    fields: gpd.GeoDataFrame,
    reference: gpd.GeoDataFrame,
    spec: LayerSpec,
    municipality: str,
    reference_year: int = 2025,
    progress_every: int = 5000,
    progress: Callable[[str], None] = print,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if fields.crs is None or reference.crs is None:
        raise ValueError("Both field and reference layers require CRS")
    f = fields.to_crs(3006).copy().reset_index(drop=True)
    r, ref_geom_qa = prepare_geometries(reference, spec.layer_name)
    for col in ("blockid", "skiftesbeteckning"):
        if col not in f.columns:
            raise ValueError(f"fields missing {col}")
    if spec.code_field not in r.columns:
        raise ValueError(f"{spec.layer_name} missing {spec.code_field}")
    if spec.source_id_field not in r.columns:
        raise ValueError(f"{spec.layer_name} missing {spec.source_id_field}")

    sindex = r.sindex
    summary_rows: list[dict[str, Any]] = []
    comp_rows: list[dict[str, Any]] = []
    field_repaired = field_failed = 0
    total = len(f)

    progress(f"[{municipality}][{spec.layer_name}] start: {total:,} fields, {len(r):,} reference polygons")
    for idx, row in f.iterrows():
        raw_geom = row.geometry
        geom, was_repaired, geom_status = _make_valid(raw_geom)
        if was_repaired and geom_status == "OK":
            field_repaired += 1
        if geom_status == "GEOMETRY_ERROR":
            field_failed += 1
        fid = field_id(row["blockid"], row["skiftesbeteckning"])
        block = text_id(row["blockid"])
        field_area = float(geom.area) if geom is not None and not geom.is_empty else 0.0

        comps: list[dict[str, Any]] = []
        union_parts = []
        unknown_codes: set[str] = set()
        reference_repair_used = False
        if field_area > 0 and geom_status != "GEOMETRY_ERROR":
            try:
                candidates = list(sindex.query(geom, predicate="intersects"))
            except Exception:
                candidates = list(sindex.query(geom))
            for j in candidates:
                refrow = r.iloc[int(j)]
                refgeom = refrow.geometry
                if refgeom is None or refgeom.is_empty:
                    continue
                try:
                    inter = geom.intersection(refgeom)
                except Exception:
                    continue
                if inter.is_empty:
                    continue
                area = float(inter.area)
                if area <= NUMERIC_AREA_EPS:
                    continue
                raw_code = text_id(refrow[spec.code_field])
                if spec.layer_name == "sko" and raw_code == "":
                    unknown_codes.add(raw_code)
                    normalized = None
                elif spec.valid_codes is not None and raw_code not in spec.valid_codes:
                    unknown_codes.add(raw_code)
                    normalized = None
                else:
                    normalized = int(raw_code) if spec.layer_name == "soil_class" else raw_code
                source_feature_id = text_id(refrow[spec.source_id_field])
                ref_reason = str(refrow.get("_geometry_reason_flag", "") or "")
                reference_repair_used = reference_repair_used or ref_reason == "REPAIRED_REFERENCE_GEOMETRY"
                reason_flags = []
                if normalized is None and spec.layer_name == "soil_class":
                    reason_flags.append("UNVERIFIED_CLASS_CODE")
                if normalized is None and spec.layer_name == "sko":
                    reason_flags.append("UNVERIFIED_SKO_ID")
                if ref_reason:
                    reason_flags.append(ref_reason)
                comps.append({
                    "schema_version": SCHEMA_VERSION,
                    "municipality": municipality,
                    "reference_year": int(reference_year),
                    "current_field_id": fid,
                    "current_block_id": block,
                    "soil_class_raw" if spec.layer_name == "soil_class" else "sko_id": raw_code,
                    "soil_class_normalized" if spec.layer_name == "soil_class" else "sko_id_normalized": normalized,
                    "intersection_area_m2": area,
                    "field_share_raw": area / field_area,
                    "source_feature_id": source_feature_id,
                    "reason_flags": ";".join(sorted(set(reason_flags))),
                    "_intersection_geometry": inter,
                })
                union_parts.append(inter)

        total_intersection = sum(c["intersection_area_m2"] for c in comps)
        coverage_raw = total_intersection / field_area if field_area > 0 else 0.0
        if union_parts and field_area > 0:
            try:
                from shapely.ops import unary_union
                unique_area = float(unary_union(union_parts).area)
            except Exception:
                unique_area = min(total_intersection, field_area)
        else:
            unique_area = 0.0
        coverage_unique = unique_area / field_area if field_area > 0 else 0.0
        uncovered_share = max(0.0, 1.0 - coverage_unique) if field_area > 0 else 1.0
        duplicate_overlap_area = max(0.0, total_intersection - unique_area)

        code_key = "soil_class_raw" if spec.layer_name == "soil_class" else "sko_id"
        by_code: dict[str, float] = {}
        for c in comps:
            by_code[c[code_key]] = by_code.get(c[code_key], 0.0) + c["intersection_area_m2"]
        ranked = sorted(by_code.items(), key=lambda x: (-x[1], x[0]))
        dominant_code = ranked[0][0] if ranked else None
        dominant_area = ranked[0][1] if ranked else 0.0
        dominant_share = dominant_area / field_area if field_area > 0 else 0.0
        component_count = len(ranked)
        crosses = component_count > 1

        reason_flags = []
        if was_repaired:
            reason_flags.append("REPAIRED_FIELD_GEOMETRY")
        if reference_repair_used:
            reason_flags.append("REPAIRED_REFERENCE_GEOMETRY")
        if geom_status == "GEOMETRY_ERROR" or field_area <= 0:
            reason_flags.append("GEOMETRY_ERROR")
        if unknown_codes:
            reason_flags.append("UNVERIFIED_CLASS_CODE" if spec.layer_name == "soil_class" else "UNVERIFIED_SKO_ID")
        if duplicate_overlap_area > max(NUMERIC_AREA_EPS, field_area * COVERAGE_TOL):
            reason_flags.append("DUPLICATE_CLASS_OVERLAP" if spec.layer_name == "soil_class" else "DUPLICATE_SKO_OVERLAP")
        if crosses:
            reason_flags.append("MULTIPLE_SOIL_CLASSES" if spec.layer_name == "soil_class" else "MULTIPLE_SKO")
        if coverage_unique <= COVERAGE_TOL:
            reason_flags.append("MISSING_SOIL_CLASS" if spec.layer_name == "soil_class" else "MISSING_SKO")
        elif coverage_unique < 1.0 - COVERAGE_TOL:
            reason_flags.append("LOW_SOIL_CLASS_COVERAGE" if spec.layer_name == "soil_class" else "LOW_SKO_COVERAGE")

        row_summary = {
            "schema_version": SCHEMA_VERSION,
            "municipality": municipality,
            "reference_year": int(reference_year),
            "current_field_id": fid,
            "current_block_id": block,
            "field_area_m2": field_area,
            f"{spec.layer_name}_coverage_raw": coverage_raw,
            f"{spec.layer_name}_coverage_unique": coverage_unique,
            f"{spec.layer_name}_uncovered_share": uncovered_share,
            f"{spec.layer_name}_duplicate_overlap_area_m2": duplicate_overlap_area,
            f"{spec.layer_name}_component_count": component_count,
            f"{spec.layer_name}_reason_flags": ";".join(sorted(set(reason_flags))),
            f"{spec.layer_name}_geometry_status": geom_status,
        }
        if spec.layer_name == "soil_class":
            row_summary.update({
                "dominant_soil_class": int(dominant_code) if dominant_code and dominant_code.isdigit() and dominant_code in SOIL_SPEC.valid_codes else None,
                "dominant_soil_class_raw": dominant_code,
                "dominant_soil_class_share": dominant_share,
                "soil_class_count": component_count,
                "unclassified_soil_share": uncovered_share,
                "mixed_soil_class": crosses,
                "unknown_soil_class_codes": ";".join(sorted(unknown_codes)),
            })
        else:
            row_summary.update({
                "dominant_sko_id": dominant_code,
                "dominant_sko_share": dominant_share,
                "sko_count": component_count,
                "crosses_sko_boundary": crosses,
                "unknown_sko_ids": ";".join(sorted(unknown_codes)),
            })
        summary_rows.append(row_summary)

        comps_sorted = sorted(comps, key=lambda c: (-c["intersection_area_m2"], c[code_key], c["source_feature_id"]))
        for rank, c in enumerate(comps_sorted, 1):
            c = dict(c)
            c["component_rank"] = rank
            c.pop("_intersection_geometry", None)
            comp_rows.append(c)

        n = idx + 1
        if progress_every > 0 and (n % progress_every == 0 or n == total):
            progress(f"[{municipality}][{spec.layer_name}] {n:,}/{total:,} fields ({100*n/total:.1f}%)")

    summary = pd.DataFrame(summary_rows).sort_values("current_field_id", kind="mergesort").reset_index(drop=True)
    components = pd.DataFrame(comp_rows)
    if not components.empty:
        components = _stable_component_sort(components, code_key)
        components["component_rank"] = components.groupby("current_field_id").cumcount() + 1

    qa = {
        "field_rows": int(len(f)),
        "field_repaired": int(field_repaired),
        "field_failed": int(field_failed),
        "reference_geometry": ref_geom_qa,
        "component_rows": int(len(components)),
        "coverage_raw_gt_1": int((summary[f"{spec.layer_name}_coverage_raw"] > 1.0 + COVERAGE_TOL).sum()),
        "partial_unique_coverage": int(((summary[f"{spec.layer_name}_coverage_unique"] > COVERAGE_TOL) & (summary[f"{spec.layer_name}_coverage_unique"] < 1.0 - COVERAGE_TOL)).sum()),
        "missing_coverage": int((summary[f"{spec.layer_name}_coverage_unique"] <= COVERAGE_TOL).sum()),
    }
    progress(f"[{municipality}][{spec.layer_name}] done: {len(summary):,} summaries, {len(components):,} components")
    return summary, components, qa

def combine_context(soil: pd.DataFrame, sko: pd.DataFrame, source_manifest_id: str) -> pd.DataFrame:
    keys = ["current_field_id", "current_block_id", "municipality", "reference_year", "field_area_m2"]
    if soil["current_field_id"].duplicated().any() or sko["current_field_id"].duplicated().any():
        raise RuntimeError("Summary layer contains duplicate current_field_id")
    merged = soil.merge(sko, on=["current_field_id", "current_block_id", "municipality", "reference_year"], suffixes=("_soil", "_sko"), validate="one_to_one")
    area_diff = (merged["field_area_m2_soil"] - merged["field_area_m2_sko"]).abs()
    if len(area_diff) and area_diff.max() > 1e-6:
        raise RuntimeError("Field area differs between soil and SKO overlays")
    merged["field_area_m2"] = merged.pop("field_area_m2_soil")
    merged.drop(columns=["field_area_m2_sko"], inplace=True)
    statuses = []
    all_flags = []
    for row in merged.itertuples(index=False):
        flags = set()
        for attr in ("soil_class_reason_flags", "sko_reason_flags"):
            val = getattr(row, attr, "")
            flags.update(x for x in str(val).split(";") if x)
        if "GEOMETRY_ERROR" in flags:
            status = "GEOMETRY_ERROR"
        elif "MISSING_SKO" in flags:
            status = "MISSING_SKO"
        elif "MISSING_SOIL_CLASS" in flags:
            status = "MISSING_SOIL_CLASS"
        elif "DUPLICATE_CLASS_OVERLAP" in flags or "DUPLICATE_SKO_OVERLAP" in flags:
            status = "OVERLAP_ANOMALY"
        elif "LOW_SKO_COVERAGE" in flags:
            status = "PARTIAL_SKO_COVERAGE"
        elif "LOW_SOIL_CLASS_COVERAGE" in flags:
            status = "PARTIAL_SOIL_CLASS_COVERAGE"
        elif bool(getattr(row, "crosses_sko_boundary", False)):
            status = "CROSSES_SKO_BOUNDARY"
        elif bool(getattr(row, "mixed_soil_class", False)):
            status = "COMPLETE_MIXED_SOIL_CLASS"
        else:
            status = "COMPLETE_SINGLE_CONTEXT"
        statuses.append(status)
        all_flags.append(";".join(sorted(flags)))
    merged["context_status"] = statuses
    merged["reason_flags"] = all_flags
    merged["schema_version"] = SCHEMA_VERSION
    merged["source_manifest_id"] = source_manifest_id
    ordered = [
        "current_field_id","current_block_id","municipality","reference_year","field_area_m2",
        "dominant_sko_id","dominant_sko_share","sko_count","sko_coverage_raw","sko_coverage_unique",
        "dominant_soil_class","dominant_soil_class_raw","dominant_soil_class_share","soil_class_count",
        "soil_class_coverage_raw","soil_class_coverage_unique","unclassified_soil_share",
        "mixed_soil_class","crosses_sko_boundary","context_status","reason_flags","schema_version","source_manifest_id",
    ]
    extras = [c for c in merged.columns if c not in ordered]
    return merged[ordered + extras].sort_values("current_field_id", kind="mergesort").reset_index(drop=True)

def checkpoint_valid(summary_path: Path, components_path: Path, manifest_path: Path, expected: dict[str, Any]) -> bool:
    try:
        if not summary_path.exists() or not components_path.exists() or not manifest_path.exists():
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for k, v in expected.items():
            if manifest.get(k) != v:
                return False
        summary = pd.read_parquet(summary_path)
        comps = pd.read_parquet(components_path)
        return (
            len(summary) == int(manifest["summary_rows"]) and
            len(comps) == int(manifest["component_rows"]) and
            summary["current_field_id"].is_unique
        )
    except Exception:
        return False

def find_akerminne_skane_roots(repo_root: Path) -> list[Path]:
    roots = []
    try:
        out = subprocess.check_output(["git", "worktree", "list", "--porcelain"], cwd=repo_root, text=True, encoding="utf-8", errors="replace")
        for line in out.splitlines():
            if line.startswith("worktree "):
                p = Path(line[len("worktree "):].strip()) / "data" / "derived" / "akerminne_v1a" / "skane"
                if p.exists():
                    roots.append(p)
    except Exception:
        pass
    direct = repo_root / "data" / "derived" / "akerminne_v1a" / "skane"
    if direct.exists() and direct not in roots:
        roots.append(direct)
    return roots

def find_frozen_akerminne_field_year_file(repo_root: Path, municipality_code: str, municipality: str) -> Path | None:
    tokens = {municipality_code.lower(), municipality.lower()}
    candidates = []
    for root in find_akerminne_skane_roots(repo_root):
        for path in root.rglob("*.parquet"):
            low = str(path).lower()
            if not any(t in low for t in tokens):
                continue
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
            cols = set(df.columns)
            if {"current_field_id", "history_year"}.issubset(cols):
                score = 0
                if len(df) % 11 == 0: score += 2
                if "status" in cols: score += 1
                if "reason_flags" in cols: score += 1
                candidates.append((score, len(df), path))
    candidates.sort(key=lambda x: (-x[0], -x[1], str(x[2])))
    return candidates[0][2] if candidates else None

def percentile_dict(series: pd.Series) -> dict[str, float | None]:
    if series.empty:
        return {k: None for k in ("p0","p1","p5","p10","p25","p50","p75","p90","p95","p99","p100")}
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {k: None for k in ("p0","p1","p5","p10","p25","p50","p75","p90","p95","p99","p100")}
    qs = [0,.01,.05,.10,.25,.50,.75,.90,.95,.99,1]
    vals = s.quantile(qs)
    return {f"p{int(q*100)}": float(vals.loc[q]) for q in qs}
