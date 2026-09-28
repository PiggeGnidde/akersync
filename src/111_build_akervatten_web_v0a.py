#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build ÅkerVatten web v0a on top of the frozen ÅkerFrö web dist.

Owns only:
  - data/akervatten/*
  - assets/akervatten_v0a.{css,js}
  - patched index.html

No ÅkerVatten model is recalculated here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIELDS = 128_636
EXPECTED_MUNICIPALITIES = 33
SCHEMA = "akervatten-web-field-v0a"
INDEX_SCHEMA = "akervatten-web-index-v0a"
MANIFEST_SCHEMA = "akervatten-web-manifest-v0a"
OWNED_PREFIX = Path("data/akervatten")
OWNED_FILES = {Path("assets/akervatten_v0a.css"), Path("assets/akervatten_v0a.js")}
KEY = ["blockid", "skiftesbeteckning"]

SCORE_COLUMNS = {
    "mark_torka": "mark_torka_score_0_100",
    "mark_vata": "mark_vata_score_0_100",
    "small_gw": "groundwater_small_availability_score_0_100",
    "gw_drought": "groundwater_drought_history_score_0_100",
    "sw_drought": "surfacewater_drought_history_score_0_100",
}
EXPECTED_COVERAGE = {
    "mark_torka": 124_380,
    "mark_vata": 124_380,
    "small_gw": 128_632,
    "gw_drought": 128_636,
    "sw_drought": 128_636,
}
ROW_COLUMNS = [
    "mark_torka", "mark_vata", "small_gw", "gw_drought", "sw_drought",
    "large_relation", "large_magazine_count", "large_magazine_names",
    "large_capacity_class", "large_capacity_lower_lps", "large_capacity_upper_lps",
    "large_position", "large_aquifer", "large_rock", "legal_status",
]
DICT_COLUMNS = {
    "large_relation", "large_magazine_names", "large_capacity_class",
    "large_position", "large_aquifer", "large_rock", "legal_status",
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def repository_head() -> str:
    supplied = os.environ.get("AKERVATTEN_WEB_REPOSITORY_HEAD", "").strip()
    if supplied:
        return supplied
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def stable_json(obj: Any, compact: bool = False) -> str:
    kw = {"ensure_ascii": False, "allow_nan": False}
    if compact:
        return json.dumps(obj, separators=(",", ":"), **kw) + "\n"
    return json.dumps(obj, indent=2, sort_keys=True, **kw) + "\n"


def atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def is_owned(rel: Path) -> bool:
    return rel == OWNED_PREFIX or OWNED_PREFIX in rel.parents or rel in OWNED_FILES


def inventory(root: Path, *, exclude_owned: bool = False, exclude_index: bool = False) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if exclude_owned and is_owned(rel):
            continue
        if exclude_index and rel.as_posix() == "index.html":
            continue
        rows.append({"path": rel.as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def verify_base_target(base: Path, target: Path) -> list[dict[str, Any]]:
    b = inventory(base, exclude_owned=True, exclude_index=True)
    t = inventory(target, exclude_owned=True, exclude_index=True)
    if b != t:
        bm = {r["path"]: r for r in b}
        tm = {r["path"]: r for r in t}
        changed = sorted(x for x in set(bm) | set(tm) if bm.get(x) != tm.get(x))
        raise RuntimeError("Target differs from ÅkerFrö base outside ÅkerVatten-owned paths: " + ", ".join(changed[:40]))
    return b


def clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def number(value: Any, digits: int | None = None) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x if digits is None else round(x, digits)


def int_or_none(value: Any) -> int | None:
    x = number(value)
    return None if x is None else int(round(x))


def norm_id(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.upper()


def make_field_id(frame: pd.DataFrame) -> pd.Series:
    return frame["blockid"].astype(str) + "|" + frame["skiftesbeteckning"].astype(str)


def validate_h2(frame: pd.DataFrame) -> None:
    required = set(KEY + ["kommun", "water_legal_status", "water_overall_verdict"] + list(SCORE_COLUMNS.values()) + [
        "large_gw_relation", "large_gw_magazine_count", "large_gw_magazine_names",
        "large_gw_highest_mapped_capacity_class", "large_gw_highest_mapped_capacity_lower_lps",
        "large_gw_highest_mapped_capacity_upper_lps", "large_gw_highest_mapped_capacity_position",
        "large_gw_highest_mapped_capacity_aquifer", "large_gw_highest_mapped_capacity_rock",
    ])
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError("H2 product missing columns: " + ", ".join(missing))
    if len(frame) != EXPECTED_FIELDS:
        raise RuntimeError(f"Expected {EXPECTED_FIELDS:,} fields, got {len(frame):,}")
    if frame[KEY].astype(str).duplicated().any():
        raise RuntimeError("H2 product has duplicate field keys")
    if frame["kommun"].nunique(dropna=True) != EXPECTED_MUNICIPALITIES:
        raise RuntimeError("H2 product municipality count mismatch")
    for name, col in SCORE_COLUMNS.items():
        n = int(frame[col].notna().sum())
        if n != EXPECTED_COVERAGE[name]:
            raise RuntimeError(f"{name} coverage changed: {n:,} != {EXPECTED_COVERAGE[name]:,}")
        valid = pd.to_numeric(frame[col], errors="coerce").dropna()
        if len(valid) and ((valid < 0).any() or (valid > 100).any()):
            raise RuntimeError(f"{name} outside 0..100")
    if set(frame["water_legal_status"].dropna().astype(str)) != {"NOT_ASSESSED"}:
        raise RuntimeError("H2 legal status is not uniformly NOT_ASSESSED")
    if set(frame["water_overall_verdict"].dropna().astype(str)) != {"NOT_CREATED"}:
        raise RuntimeError("H2 overall verdict changed")


def make_dictionaries(group: pd.DataFrame) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    source = {
        "large_relation": "large_gw_relation",
        "large_magazine_names": "large_gw_magazine_names",
        "large_capacity_class": "large_gw_highest_mapped_capacity_class",
        "large_position": "large_gw_highest_mapped_capacity_position",
        "large_aquifer": "large_gw_highest_mapped_capacity_aquifer",
        "large_rock": "large_gw_highest_mapped_capacity_rock",
        "legal_status": "water_legal_status",
    }
    dictionaries, indexes = {}, {}
    for target, col in source.items():
        vals = sorted({clean(v) for v in group[col]})
        dictionaries[target] = vals
        indexes[target] = {v: i for i, v in enumerate(vals)}
    return dictionaries, indexes


def pack_row(row: pd.Series, idx: dict[str, dict[str, int]]) -> list[Any]:
    return [
        number(row[SCORE_COLUMNS["mark_torka"]], 2),
        number(row[SCORE_COLUMNS["mark_vata"]], 2),
        number(row[SCORE_COLUMNS["small_gw"]], 2),
        number(row[SCORE_COLUMNS["gw_drought"]], 2),
        number(row[SCORE_COLUMNS["sw_drought"]], 2),
        idx["large_relation"][clean(row["large_gw_relation"])],
        int_or_none(row["large_gw_magazine_count"]),
        idx["large_magazine_names"][clean(row["large_gw_magazine_names"])],
        idx["large_capacity_class"][clean(row["large_gw_highest_mapped_capacity_class"])],
        number(row["large_gw_highest_mapped_capacity_lower_lps"], 4),
        number(row["large_gw_highest_mapped_capacity_upper_lps"], 4),
        idx["large_position"][clean(row["large_gw_highest_mapped_capacity_position"])],
        idx["large_aquifer"][clean(row["large_gw_highest_mapped_capacity_aquifer"])],
        idx["large_rock"][clean(row["large_gw_highest_mapped_capacity_rock"])],
        idx["legal_status"][clean(row["water_legal_status"])],
    ]


def build_field_payload(group: pd.DataFrame) -> dict[str, Any]:
    municipality = str(group["kommun"].iloc[0])
    dictionaries, indexes = make_dictionaries(group)
    fields: dict[str, list[Any]] = {}
    q = group.copy()
    q["_id"] = make_field_id(q)
    for _, row in q.sort_values("_id", kind="mergesort").iterrows():
        fields[str(row["_id"])] = pack_row(row, indexes)
    return {
        "schema_version": SCHEMA,
        "municipality": municipality,
        "field_count": int(len(q)),
        "columns": ROW_COLUMNS,
        "dictionaries": dictionaries,
        "fields": fields,
    }


def slug(text: str) -> str:
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return "_".join(part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in plain).split())


def build_field_sidecars(frame: pd.DataFrame, destination: Path) -> dict[str, Any]:
    temp = destination.with_name(destination.name + ".tmp")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    entries, total = [], 0
    for municipality, group in frame.groupby("kommun", sort=True):
        payload = build_field_payload(group)
        filename = f"{slug(municipality)}.json"
        path = temp / filename
        atomic_text(stable_json(payload, compact=True), path)
        entries.append({
            "municipality": str(municipality),
            "file": f"data/akervatten/{filename}",
            "fields": int(len(group)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
        total += len(group)
    if len(entries) != EXPECTED_MUNICIPALITIES or total != EXPECTED_FIELDS:
        raise RuntimeError("ÅkerVatten municipality partition mismatch")
    return {"temp": temp, "entries": entries}


def compact_geojson(gdf: gpd.GeoDataFrame, path: Path) -> dict[str, Any]:
    if gdf.crs is None:
        raise RuntimeError(f"GeoJSON source has no CRS: {path.name}")
    q = gdf.to_crs(3006).copy()
    q["geometry"] = q.geometry.simplify(35.0, preserve_topology=True)
    q = q.to_crs(4326)
    doc = json.loads(q.to_json(drop_id=True))
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    atomic_text(text, path)
    return {"file": f"data/akervatten/{path.name}", "features": int(len(q)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def build_groundwater_history(water_root: Path, h2: pd.DataFrame, destination: Path) -> dict[str, Any]:
    links = pd.read_parquet(water_root / "work/akervatten_mvp_v0a/c_full_linkage/akervatten_c_spatial_links_skane.parquet")
    links[KEY] = links[KEY].astype(str)
    q = links[KEY + ["omrade_id"]].merge(
        h2[KEY + [SCORE_COLUMNS["gw_drought"]]], on=KEY, how="left", validate="one_to_one"
    ).dropna(subset=["omrade_id", SCORE_COLUMNS["gw_drought"]])
    q["_unit"] = q["omrade_id"].map(norm_id)
    check = q.groupby("_unit")[SCORE_COLUMNS["gw_drought"]].nunique(dropna=True)
    if (check > 1).any() or len(check) != 786:
        raise RuntimeError("Groundwater drought unit invariant failed in web build")
    unit = q.groupby("_unit", as_index=False)[SCORE_COLUMNS["gw_drought"]].first().rename(columns={SCORE_COLUMNS["gw_drought"]:"score"})
    geo = gpd.read_file(water_root / "data/raw/akervatten/c_full_linkage/sgu/sgu_hype_areas_skane.geojson")
    if "omrade_id" not in geo.columns:
        raise RuntimeError("SGU-HYPE geometry lacks omrade_id")
    geo["_unit"] = geo["omrade_id"].map(norm_id)
    out = geo.merge(unit, on="_unit", how="inner", validate="one_to_one")
    if len(out) != 786:
        raise RuntimeError(f"Expected 786 SGU-HYPE polygons, got {len(out)}")
    out = out[["omrade_id", "score", "geometry"]]
    return compact_geojson(out, destination / "groundwater_history.geojson")


def build_surfacewater_history(water_root: Path, h2: pd.DataFrame, destination: Path) -> dict[str, Any]:
    links = pd.read_parquet(water_root / "work/akervatten_mvp_v0a/c_full_linkage/akervatten_c_spatial_links_skane.parquet")
    links[KEY] = links[KEY].astype(str)
    aro_col = next((c for c in links.columns if str(c).upper() == "ARO_UUID"), None)
    sub_col = next((c for c in links.columns if str(c).upper() == "SUBID"), None)
    if aro_col is None or sub_col is None:
        raise RuntimeError("C links lack ARO_UUID/Subid")
    q = links[KEY + [aro_col, sub_col]].merge(
        h2[KEY + [SCORE_COLUMNS["sw_drought"]]], on=KEY, how="left", validate="one_to_one"
    ).dropna(subset=[aro_col, sub_col, SCORE_COLUMNS["sw_drought"]])
    q["_aro"] = q[aro_col].map(norm_id)
    q["_sub"] = q[sub_col].map(norm_id)
    score_check = q.groupby("_sub")[SCORE_COLUMNS["sw_drought"]].nunique(dropna=True)
    if (score_check > 1).any() or len(score_check) != 502:
        raise RuntimeError("Surface-water drought unit invariant failed in web build")
    aro_sub = q.groupby("_aro").agg(subid=("_sub","first"), nsub=("_sub","nunique")).reset_index()
    if (aro_sub["nsub"] > 1).any():
        raise RuntimeError("ARO_UUID -> Subid conflict")
    score = q.groupby("_sub", as_index=False)[SCORE_COLUMNS["sw_drought"]].first().rename(columns={SCORE_COLUMNS["sw_drought"]:"score"})
    aro_sub = aro_sub.merge(score, left_on="subid", right_on="_sub", how="left").drop(columns=["_sub"])
    tile_dir = water_root / "data/raw/akervatten/c_full_linkage/smhi/svar_tiles"
    paths = sorted(tile_dir.glob("tile_*.geojson"))
    if not paths:
        raise RuntimeError("SVAR tile cache missing")
    pieces = [gpd.read_file(p) for p in paths]
    svar = gpd.GeoDataFrame(pd.concat(pieces, ignore_index=True), crs=pieces[0].crs)
    aro_src = next((c for c in svar.columns if str(c).upper() == "ARO_UUID"), None)
    if aro_src is None:
        raise RuntimeError("SVAR geometry lacks ARO_UUID")
    svar["_aro"] = svar[aro_src].map(norm_id)
    svar = svar.drop_duplicates("_aro")
    out = svar.merge(aro_sub[["_aro","subid","score"]], on="_aro", how="inner", validate="one_to_one")
    if out["subid"].nunique() != 502:
        raise RuntimeError(f"Expected 502 Subid in surface web polygons, got {out['subid'].nunique()}")
    keep = [aro_src, "subid", "score", "geometry"]
    return compact_geojson(out[keep], destination / "surfacewater_history.geojson")


def build_large_groundwater(water_root: Path, destination: Path) -> dict[str, Any]:
    layers = pd.read_parquet(
        water_root / "work/akervatten_mvp_v0a/h2_product_dimensions/akervatten_h2_large_groundwater_layers.parquet"
    )
    id_col = "unik_delomradesidentitet"
    if id_col not in layers.columns:
        raise RuntimeError("H2 large-groundwater layer table lacks unique subarea id")
    meta_cols = [c for c in [
        id_col, "unik_magasinsidentitet", "magasinsnamn", "magasinsposition",
        "akvifertyp", "bergart", "withdrawal_label_norm",
        "withdrawal_lower_lps", "withdrawal_upper_lps",
    ] if c in layers.columns]
    meta = layers[meta_cols].drop_duplicates(id_col)
    if meta[id_col].duplicated().any():
        raise RuntimeError("Large-groundwater subarea metadata inconsistent")
    gpkg = water_root / "raw/akervatten_h0_large_groundwater/extracted/grundvattenmagasin.gpkg"
    geo = gpd.read_file(gpkg, layer="magasinsdelomraden")
    if id_col not in geo.columns:
        raise RuntimeError("SGU subarea geometry lacks unique id")
    wanted = set(meta[id_col].dropna().astype(str))
    geo = geo[geo[id_col].astype(str).isin(wanted)].copy()
    geo[id_col] = geo[id_col].astype(str)
    meta[id_col] = meta[id_col].astype(str)
    out = geo[[id_col, "geometry"]].merge(meta, on=id_col, how="inner", validate="one_to_one")
    if out.empty:
        raise RuntimeError("No SGU large-groundwater subareas selected")
    return compact_geojson(out, destination / "large_groundwater.geojson")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dist", required=True, type=Path)
    ap.add_argument("--water-root", required=True, type=Path)
    ap.add_argument("--dist", default=str(ROOT / "dist"), type=Path)
    ap.add_argument("--work", default=str(ROOT / "work/akervatten_web_v0a"), type=Path)
    args = ap.parse_args()

    base = args.base_dist.resolve()
    water_root = args.water_root.resolve()
    dist = args.dist.resolve()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)

    if base == dist:
        raise RuntimeError("ÅkerFrö base dist and ÅkerVatten target dist must differ")
    if not (base / "index.html").exists():
        raise RuntimeError("ÅkerFrö base index missing")
    base_html = (base / "index.html").read_text(encoding="utf-8")
    for marker in ("AKERNORM_WEB_UI_V1", "AKERFRO_ERTOR_WEB_UI_V0A"):
        if marker not in base_html:
            raise RuntimeError(f"ÅkerFrö base marker missing: {marker}")
    if not (base / "data/akerfro/skane_index.json").exists():
        raise RuntimeError("Base dist lacks ÅkerFrö sidecars")

    h2_path = water_root / "work/akervatten_mvp_v0a/h2_product_dimensions/akervatten_h2_field_water_dimensions_skane.parquet"
    summary_path = water_root / "work/akervatten_mvp_v0a/h2_product_dimensions/h2_summary.json"
    if not h2_path.exists() or not summary_path.exists():
        raise RuntimeError("Frozen H2 product outputs missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "PASS_WITH_REVIEW" or summary.get("overall_score_created") is not False:
        raise RuntimeError("H2 source summary is not the reviewed no-composite product")
    h2 = pd.read_parquet(h2_path)
    h2[KEY] = h2[KEY].astype(str)
    validate_h2(h2)

    if not dist.exists():
        shutil.copytree(base, dist)
    verify_base_target(base, dist)

    data_dest = dist / OWNED_PREFIX
    if data_dest.exists():
        shutil.rmtree(data_dest)
    side = build_field_sidecars(h2, data_dest)
    temp = side["temp"]

    regional = {
        "groundwater_history": build_groundwater_history(water_root, h2, temp),
        "surfacewater_history": build_surfacewater_history(water_root, h2, temp),
        "large_groundwater": build_large_groundwater(water_root, temp),
    }

    index = {
        "schema_version": INDEX_SCHEMA,
        "status": "PASS",
        "field_count": EXPECTED_FIELDS,
        "municipality_count": EXPECTED_MUNICIPALITIES,
        "coverage": EXPECTED_COVERAGE,
        "overall_score": "NOT_CREATED",
        "legal_status": "NOT_ASSESSED",
        "municipalities": side["entries"],
        "regional": regional,
    }
    atomic_text(stable_json(index), temp / "skane_index.json")
    os.replace(temp, data_dest)

    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in ("akervatten_v0a.css", "akervatten_v0a.js"):
        src = ROOT / "web" / name
        if not src.exists():
            raise RuntimeError(f"Missing web asset: {src}")
        shutil.copy2(src, assets / name)

    spec = importlib.util.spec_from_file_location(
        "akervatten_web_patch", ROOT / "src/112_patch_akervatten_web_v0a_ui.py"
    )
    assert spec and spec.loader
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    mapping = {str(r["municipality"]): str(r["file"]) for r in index["municipalities"]}
    patched = patcher.patch_html(base_html, mapping, {k:v["file"] for k,v in regional.items()})
    atomic_text(patched, dist / "index.html")
    protected = verify_base_target(base, dist)

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "status": "PASS",
        "repository_head": repository_head(),
        "base_dist": str(base),
        "target_dist": str(dist),
        "water_root": str(water_root),
        "h2_product": str(h2_path),
        "h2_product_sha256": sha256_file(h2_path),
        "base_index_sha256": sha256_file(base / "index.html"),
        "patched_index_sha256": sha256_file(dist / "index.html"),
        "protected_base_files": len(protected),
        "scope": {
            "akervatten_model_recalculated": False,
            "akerfro_base_changed": False,
            "deployment": False,
            "overall_water_score_created": False,
        },
        "regional": regional,
    }
    atomic_text(stable_json(manifest), work / "akervatten_web_manifest.json")

    print("=" * 100)
    print("ÅkerVatten WEB BUILD")
    print("=" * 100)
    print(f"Fields: {len(h2):,} · municipalities: {h2['kommun'].nunique():,}")
    print("Coverage:", EXPECTED_COVERAGE)
    print(f"SGU-HYPE polygons: {regional['groundwater_history']['features']:,}")
    print(f"S-HYPE/SVAR polygons: {regional['surfacewater_history']['features']:,}")
    print(f"Large-GW subareas: {regional['large_groundwater']['features']:,}")
    print("Overall water score: NOT CREATED")
    print("Legal status: NOT ASSESSED")
    print(f"Output: {dist / 'index.html'}")
    print("=" * 100)
    print("BUILD_AKERVATTEN_WEB_V0A: PASS")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
