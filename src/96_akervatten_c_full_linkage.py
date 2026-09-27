#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT C full-Skåne spatial/ID linkage.

Design goals:
- scale the B-proven linkage to the full current Skåne field population,
- never do one network call per field,
- cache public source data,
- process fields in deterministic chunks (default 1,000),
- atomically checkpoint every completed chunk,
- resume safely after Ctrl-C, reboot, network loss, etc.,
- print progress/rate/ETA for every field chunk.

No historical drought features or product scores are computed here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_c.json"
KEY = ["blockid", "skiftesbeteckning"]

# Reuse the B-frozen source readers and WFS negotiation helpers.
_spec = importlib.util.spec_from_file_location(
    "akervatten_b", ROOT / "src" / "94_akervatten_b_pilot.py"
)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Could not load STOPPUNKT B helper module")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt_duration(seconds: float | None) -> str:
    if seconds is None or not np.isfinite(seconds) or seconds < 0:
        return "--:--:--"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def norm_id_series(s: pd.Series) -> pd.Series:
    return (
        s.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.upper()
    )


def chunk_ranges(n: int, size: int) -> list[tuple[int, int, int]]:
    if n <= 0 or size <= 0:
        raise ValueError((n, size))
    out = []
    chunk_no = 1
    for start in range(0, n, size):
        end = min(n, start + size)
        out.append((chunk_no, start, end))
        chunk_no += 1
    return out


def checkpoint_path(checkpoint_dir: Path, start: int, end: int) -> Path:
    # Human-readable 1-based inclusive range.
    return checkpoint_dir / f"fields_{start+1:06d}_{end:06d}.parquet"


def checkpoint_valid(path: Path, expected_keys: pd.DataFrame) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        q = pd.read_parquet(path, columns=KEY)
    except Exception:
        return False
    if len(q) != len(expected_keys):
        return False
    a = q[KEY].astype(str).reset_index(drop=True)
    b = expected_keys[KEY].astype(str).reset_index(drop=True)
    return a.equals(b)


def load_canonical_population(cfg: dict[str, Any]) -> pd.DataFrame:
    soil = pd.read_csv(
        cfg["paths"]["soil"],
        dtype={"blockid": str, "skiftesbeteckning": str},
        low_memory=False,
    )
    if soil[KEY].duplicated().any():
        raise RuntimeError("Soil/current population has duplicate field keys")

    expected = int(cfg["expected_fields"])
    if len(soil) != expected:
        raise RuntimeError(f"Current population changed: {len(soil)} != expected {expected}")

    cols = KEY.copy()
    for candidate in ("kommun", "area_ha", "crop_code"):
        if candidate in soil.columns and candidate not in cols:
            cols.append(candidate)
    base = soil[cols].copy()

    status_path = ROOT / cfg["paths"]["a1b_status"]
    status = pd.read_parquet(status_path)
    for k in KEY:
        status[k] = status[k].astype(str)
    status_cols = KEY + [
        c for c in ("a1b_data_status", "old_robust")
        if c in status.columns
    ]
    base = base.merge(
        status[status_cols],
        on=KEY, how="left", validate="one_to_one"
    )

    # Stable deterministic order independent of source file order.
    base["_block_sort"] = base["blockid"].astype(str)
    base["_skifte_sort"] = base["skiftesbeteckning"].astype(str)
    base = (
        base.sort_values(["_block_sort", "_skifte_sort"], kind="mergesort")
        .drop(columns=["_block_sort", "_skifte_sort"])
        .reset_index(drop=True)
    )
    base["field_seq"] = np.arange(1, len(base) + 1, dtype=np.int64)
    return base


def build_or_load_points(
    base: pd.DataFrame,
    skiften_path: Path,
    cache_path: Path,
) -> pd.DataFrame:
    if cache_path.exists() and cache_path.stat().st_size > 0:
        p = pd.read_parquet(cache_path)
        if (
            len(p) == len(base)
            and p[KEY].astype(str).reset_index(drop=True).equals(
                base[KEY].astype(str).reset_index(drop=True)
            )
        ):
            print(f"  field-point cache: {cache_path} ({len(p):,} fields)")
            return p
        print("  field-point cache does not match current population; rebuilding")

    print(f"  reading field geometries: {skiften_path}")
    g = gpd.read_file(skiften_path)
    missing = [k for k in KEY if k not in g.columns]
    if missing:
        raise RuntimeError(f"Field geometry missing keys: {missing}")
    for k in KEY:
        g[k] = g[k].astype(str)

    g = g[KEY + ["geometry"]].copy()
    if g[KEY].duplicated().any():
        raise RuntimeError("Field geometry source has duplicate field keys")
    if g.crs is None:
        raise RuntimeError("Field geometry source has no CRS")

    wanted = set(map(tuple, base[KEY].itertuples(index=False, name=None)))
    g["_k"] = list(map(tuple, g[KEY].itertuples(index=False, name=None)))
    g = g[g["_k"].isin(wanted)].drop(columns="_k")
    if len(g) != len(base):
        have = set(map(tuple, g[KEY].itertuples(index=False, name=None)))
        miss = wanted - have
        raise RuntimeError(
            f"Field geometry coverage {len(g)}/{len(base)}; missing={len(miss)}"
        )

    g3006 = g.to_crs(3006)
    reps = g3006.geometry.representative_point()
    coords = g3006[KEY].copy()
    coords["x3006"] = reps.x.to_numpy()
    coords["y3006"] = reps.y.to_numpy()

    p = base.merge(coords, on=KEY, how="left", validate="one_to_one")
    if p[["x3006", "y3006"]].isna().any().any():
        raise RuntimeError("Missing representative-point coordinates")
    atomic_parquet(p, cache_path)
    print(f"  field-point cache saved: {cache_path} ({len(p):,} fields)")
    return p


def fetch_all_sgu_hype(
    dl: Any,
    url: str,
    points: pd.DataFrame,
    path: Path,
) -> gpd.GeoDataFrame:
    if path.exists() and path.stat().st_size > 0:
        g = gpd.read_file(path)
        if not g.empty and "omrade_id" in g.columns:
            print(f"  SGU-HYPE cache: {path.name} ({len(g):,} areas)")
            return g

    pts = gpd.GeoDataFrame(
        points[["field_seq"]].copy(),
        geometry=gpd.points_from_xy(points["x3006"], points["y3006"]),
        crs=3006,
    ).to_crs(4326)
    minx, miny, maxx, maxy = pts.total_bounds
    params = {
        "f": "application/geo+json",
        "bbox": f"{minx:.7f},{miny:.7f},{maxx:.7f},{maxy:.7f}",
        "limit": 10000,
    }
    print("  downloading SGU-HYPE areas for full Skåne bbox...")
    r = dl.get(url, params=params, timeout=180)
    doc = r.json()
    feats = doc.get("features") or []
    number_matched = doc.get("numberMatched")
    if number_matched not in (None, "unknown"):
        try:
            if int(number_matched) > len(feats):
                raise RuntimeError(
                    f"SGU-HYPE response truncated: returned={len(feats)}, matched={number_matched}"
                )
        except ValueError:
            pass
    if not feats:
        raise RuntimeError("SGU-HYPE full-Skåne bbox returned zero features")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    g = gpd.read_file(path)
    print(f"  SGU-HYPE cache saved: {path.name} ({len(g):,} areas)")
    return g


def tile_plan(bounds: tuple[float, float, float, float], size: float) -> list[dict[str, Any]]:
    minx, miny, maxx, maxy = bounds
    x0 = math.floor(minx / size) * size
    y0 = math.floor(miny / size) * size
    x1 = math.ceil(maxx / size) * size
    y1 = math.ceil(maxy / size) * size
    out = []
    i = 0
    y = y0
    while y < y1:
        x = x0
        while x < x1:
            i += 1
            out.append({
                "tile_no": i,
                "minx": x, "miny": y,
                "maxx": x + size, "maxy": y + size,
            })
            x += size
        y += size
    return out


def tile_params(mode: str, typename: str, bbox_txt: str, count: int) -> dict[str, Any]:
    p = B._wfs_params(mode, typename, bbox_txt)
    p.pop("count", None)
    p.pop("maxFeatures", None)
    if str(p.get("version", "")).startswith("2"):
        p["count"] = int(count)
    else:
        p["maxFeatures"] = int(count)
    return p


def fetch_svar_tiles(
    dl: Any,
    points: pd.DataFrame,
    bcfg: dict[str, Any],
    ccfg: dict[str, Any],
    tile_dir: Path,
    state_path: Path,
) -> gpd.GeoDataFrame:
    tile_dir.mkdir(parents=True, exist_ok=True)
    tile_size = float(ccfg["svar"]["tile_size_m"])
    pad = float(ccfg["svar"]["tile_pad_m"])
    count = int(ccfg["svar"]["count_per_tile"])

    pgeo = gpd.GeoDataFrame(
        points[["field_seq"]].copy(),
        geometry=gpd.points_from_xy(points["x3006"], points["y3006"]),
        crs=3006,
    )
    plan = tile_plan(tuple(float(v) for v in pgeo.total_bounds), tile_size)

    urls = bcfg["sources"].get(
        "smhi_svar_subcatch_wfs_candidates",
        [bcfg["sources"]["smhi_svar_subcatch_wfs"]],
    )
    hint = ccfg["svar"]["typename_hint"]

    print(f"  negotiating SVAR WFS once for {len(plan)} tiles...")
    working = []
    probes = []
    for url in urls:
        probe = B._probe_wfs_service(dl, url, hint, pgeo, 250.0)
        probes.append(probe)
        if probe and probe.get("status") == "WORKING":
            working.append(probe)
            print(f"    WORKING: {url} · {probe['mode']} · {probe['typename']}")
    if not working:
        raise RuntimeError(f"No working SVAR WFS service. probes={probes}")

    pieces = []
    total = len(plan)
    for idx, tile in enumerate(plan, start=1):
        stem = (
            f"tile_{int(tile['minx']):07d}_{int(tile['miny']):07d}"
        )
        geo_path = tile_dir / f"{stem}.geojson"
        empty_path = tile_dir / f"{stem}.empty.json"

        if geo_path.exists() and geo_path.stat().st_size > 0:
            g = gpd.read_file(geo_path)
            if not g.empty:
                pieces.append(g)
            print(f"  [SVAR tiles] {idx:03d}/{total:03d} · cache · {stem}")
            continue
        if empty_path.exists():
            print(f"  [SVAR tiles] {idx:03d}/{total:03d} · cache-empty · {stem}")
            continue

        bbox_txt = (
            f"{tile['minx']-pad:.3f},{tile['miny']-pad:.3f},"
            f"{tile['maxx']+pad:.3f},{tile['maxy']+pad:.3f},EPSG:3006"
        )
        got_piece = None
        successful_empty = False
        errors = []

        for svc in working:
            params = tile_params(svc["mode"], svc["typename"], bbox_txt, count)
            try:
                r = dl.get(svc["base_url"], params=params, timeout=240)
                g = B._read_wfs_response(r.content, r.headers.get("content-type"))
                if g.empty:
                    successful_empty = True
                    continue
                aro = next(
                    (c for c in g.columns if str(c).upper() == "ARO_UUID"),
                    None,
                )
                if aro is None:
                    errors.append(
                        f"{svc['base_url']} returned columns without ARO_UUID: {list(g.columns)}"
                    )
                    continue
                got_piece = g
                break
            except Exception as exc:
                errors.append(f"{svc['base_url']} {svc['mode']}: {exc!r}")

        if got_piece is not None:
            geo_path.unlink(missing_ok=True)
            got_piece.to_file(geo_path, driver="GeoJSON")
            pieces.append(got_piece)
            status = f"saved {len(got_piece)} features"
        elif successful_empty:
            atomic_json(empty_path, {"bbox": bbox_txt, "status": "EMPTY"})
            status = "saved empty marker"
        else:
            raise RuntimeError(f"SVAR tile {stem} failed: {errors}")

        atomic_json(state_path, {
            "phase": "SVAR_TILES",
            "tiles_total": total,
            "tiles_completed_through": idx,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        })
        print(f"  [SVAR tiles] {idx:03d}/{total:03d} · {status} · checkpoint saved")

    # Re-read all cached non-empty tiles to make resume independent of this run.
    pieces = []
    for path in sorted(tile_dir.glob("tile_*.geojson")):
        g = gpd.read_file(path)
        if not g.empty:
            pieces.append(g)
    if not pieces:
        raise RuntimeError("SVAR tile cache contains no polygons")

    svar = gpd.GeoDataFrame(pd.concat(pieces, ignore_index=True), crs=pieces[0].crs)
    aro = next((c for c in svar.columns if str(c).upper() == "ARO_UUID"), None)
    if aro is None:
        raise RuntimeError(f"SVAR tiles lack ARO_UUID: {list(svar.columns)}")
    before = len(svar)
    svar = svar.drop_duplicates(subset=[aro]).reset_index(drop=True)
    print(f"  SVAR unique polygons: {len(svar):,} (from {before:,} tiled records)")
    return svar


def prepare_flow_map(
    dl: Any,
    bcfg: dict[str, Any],
    cfg: dict[str, Any],
    raw_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any], Path]:
    bcache = ROOT / cfg["paths"]["b_flowstats_cache"]
    if bcache.exists() and bcache.stat().st_size > 0:
        path = bcache
        print(f"  Vattenwebb cache reused from B: {path}")
    else:
        path = B.download_vattenwebb_excel(
            dl,
            bcfg["sources"]["smhi_vattenwebb_flowstatistics"],
            raw_dir / "smhi" / "vattenwebb_flowstatistics.xls",
        )
    df, info = B.read_vattenwebb_flowstatistics(path)
    aroid = next((c for c in df.columns if str(c).upper() == "AROID"), None)
    subid = next((c for c in df.columns if str(c).upper() == "SUBID"), None)
    if aroid is None or subid is None:
        raise RuntimeError(f"Flow table lacks Aroid/Subid: {list(df.columns)}")

    m = df[[aroid, subid]].copy()
    m["_joinid"] = norm_id_series(m[aroid])
    m["_subid_norm"] = norm_id_series(m[subid])

    conflicts = (
        m.dropna(subset=["_joinid"])
        .groupby("_joinid")["_subid_norm"]
        .nunique(dropna=True)
    )
    conflicts = conflicts[conflicts > 1]
    if len(conflicts):
        raise RuntimeError(f"Aroid->Subid conflicts: {len(conflicts)}")

    m = m.drop_duplicates("_joinid")
    m = m.rename(columns={aroid: "Vattenwebb_Aroid", subid: "Subid"})
    return m[["_joinid", "Vattenwebb_Aroid", "Subid"]], info, path


def spatial_join_one(
    pts: gpd.GeoDataFrame,
    polys: gpd.GeoDataFrame,
    keep_cols: list[str],
    prefix: str,
) -> pd.DataFrame:
    source_cols = [c for c in keep_cols if c in polys.columns]
    q = polys[source_cols + ["geometry"]].copy()
    if q.crs is None:
        raise RuntimeError(f"{prefix} polygons have no CRS")
    p = pts.to_crs(q.crs)

    j = gpd.sjoin(p[["field_seq", "geometry"]], q, how="left", predicate="within")
    dup = j["field_seq"].duplicated(keep=False)
    if dup.any():
        bad = j.loc[dup, "field_seq"].nunique()
        raise RuntimeError(f"{prefix}: {bad} point(s) matched multiple polygons")

    out = j[["field_seq"] + source_cols].copy()
    return out


def process_field_chunk(
    chunk: pd.DataFrame,
    small_tifs: list[Path],
    hype: gpd.GeoDataFrame,
    svar: gpd.GeoDataFrame,
    flow_map: pd.DataFrame,
) -> pd.DataFrame:
    pts = gpd.GeoDataFrame(
        chunk[["field_seq"]].copy(),
        geometry=gpd.points_from_xy(chunk["x3006"], chunk["y3006"]),
        crs=3006,
    )

    raster_pts = pts.copy()
    raster_pts["pilot_order"] = raster_pts["field_seq"]
    small = B.sample_smallmag(raster_pts, small_tifs).rename(
        columns={"pilot_order": "field_seq"}
    )

    hype_join = spatial_join_one(
        pts, hype,
        ["omrade_id", "url_tidsserie"],
        "SGU-HYPE",
    )

    svar_keep = [
        c for c in (
            "ARO_UUID", "HARO", "MAINDOWN", "BARONR", "COUNTRY",
            "VERSION_SVAR", "AREA", "AREA_UPSTREAM"
        )
        if c in svar.columns
    ]
    svar_join = spatial_join_one(
        pts, svar, svar_keep, "SVAR2022 Delavrinningsområden"
    )
    aro_col = next((c for c in svar_join.columns if str(c).upper() == "ARO_UUID"), None)
    if aro_col is None:
        raise RuntimeError("Chunk SVAR join lacks ARO_UUID")

    svar_join["_joinid"] = norm_id_series(svar_join[aro_col])
    svar_join = svar_join.merge(
        flow_map,
        on="_joinid", how="left", validate="many_to_one"
    ).drop(columns="_joinid")

    out = chunk.copy()
    out = out.merge(small, on="field_seq", how="left", validate="one_to_one")
    out = out.merge(hype_join, on="field_seq", how="left", validate="one_to_one")
    out = out.merge(svar_join, on="field_seq", how="left", validate="one_to_one")
    return out


def distribution_stats(series: pd.Series) -> dict[str, Any]:
    counts = series.dropna().astype(str).value_counts()
    if counts.empty:
        return {"unique": 0, "fields_per_unit_median": None, "p90": None, "max": None}
    return {
        "unique": int(len(counts)),
        "fields_per_unit_median": float(counts.median()),
        "fields_per_unit_p90": float(counts.quantile(0.90)),
        "fields_per_unit_max": int(counts.max()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    bcfg = read_json(ROOT / cfg["paths"]["b_config"])
    raw_dir = ROOT / cfg["output"]["raw_dir"]
    work_dir = ROOT / cfg["output"]["work_dir"]
    checkpoint_dir = work_dir / "checkpoints"
    tile_dir = raw_dir / "smhi" / "svar_tiles"
    state_path = work_dir / "c_state.json"
    raw_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Remove only abandoned atomic temp files; completed checkpoints remain.
    for tmp in checkpoint_dir.glob("*.tmp"):
        tmp.unlink(missing_ok=True)
    for tmp in checkpoint_dir.glob("*.tmp.parquet"):
        tmp.unlink(missing_ok=True)

    dl = B.Downloader(
        timeout=int(cfg["network"]["timeout_seconds"]),
        retries=int(cfg["network"]["retries"]),
        backoff=float(cfg["network"]["retry_backoff_seconds"]),
    )

    print("=" * 120)
    print("ÅkerVatten MVP v0a · STOPPUNKT C · FULL SKÅNE SPATIAL/ID LINKAGE")
    print("=" * 120)
    print("Resumable design: source tiles + atomic field checkpoints.")
    print(f"Field checkpoint interval: {int(cfg['chunk_size_fields']):,}")

    print("\n[1/6] Canonical field population + representative-point cache")
    base = load_canonical_population(cfg)
    local_paths = read_json(Path(cfg["paths"]["local_paths_json"]))
    if "skiften" not in local_paths:
        raise RuntimeError("local_paths.json lacks 'skiften'")
    points = build_or_load_points(
        base,
        Path(local_paths["skiften"]),
        work_dir / "field_points_3006.parquet",
    )
    print(f"  population: {len(points):,}")

    print("\n[2/6] Public source caches")
    b_small = ROOT / cfg["paths"]["b_smallmag_cache"]
    if b_small.exists() and b_small.stat().st_size > 0:
        small_zip = b_small
        print(f"  SGU small-magasin cache reused from B: {small_zip}")
    else:
        small_zip = dl.download(
            bcfg["sources"]["sgu_smallmag_zip"],
            raw_dir / "sgu" / "grundvattentillgang-sma-magasin.zip",
            max_bytes=800 * 1024 * 1024,
        )
    small_tifs = B.extract_tifs(
        small_zip,
        raw_dir / "sgu" / "smallmag_extracted",
    )
    print(f"  SGU small-magasin TIFFs: {len(small_tifs)}")

    hype = fetch_all_sgu_hype(
        dl,
        bcfg["sources"]["sgu_hype_areas"],
        points,
        raw_dir / "sgu" / "sgu_hype_areas_skane.geojson",
    )

    flow_map, flow_info, flow_path = prepare_flow_map(dl, bcfg, cfg, raw_dir)
    print(f"  Vattenwebb mapping rows: {len(flow_map):,}")
    print(f"  Vattenwebb workbook sheet: {flow_info['sheet']}")

    print("\n[3/6] SVAR2022 Delavrinningsområden tile cache")
    svar = fetch_svar_tiles(
        dl, points, bcfg, cfg, tile_dir,
        work_dir / "c_source_state.json",
    )

    print("\n[4/6] Resume scan")
    ranges = chunk_ranges(len(points), int(cfg["chunk_size_fields"]))
    valid_done = 0
    valid_chunks = 0
    for _, start, end in ranges:
        path = checkpoint_path(checkpoint_dir, start, end)
        if checkpoint_valid(path, points.iloc[start:end][KEY]):
            valid_done += end - start
            valid_chunks += 1
    print(
        f"  valid checkpoints: {valid_chunks}/{len(ranges)} · "
        f"{valid_done:,}/{len(points):,} fields already safe on disk"
    )

    print("\n[5/6] Full field linkage")
    run_start = time.monotonic()
    new_fields = 0
    for chunk_no, start, end in ranges:
        path = checkpoint_path(checkpoint_dir, start, end)
        expected_keys = points.iloc[start:end][KEY]

        if checkpoint_valid(path, expected_keys):
            pct = 100.0 * end / len(points)
            print(
                f"  [FIELDS] {end:6d}/{len(points):6d} · {pct:5.1f}% · "
                f"chunk {chunk_no:3d}/{len(ranges):3d} · RESUME checkpoint already complete"
            )
            continue

        if path.exists():
            print(f"  invalid checkpoint will be replaced: {path.name}")

        q = points.iloc[start:end].copy()
        result = process_field_chunk(q, small_tifs, hype, svar, flow_map)
        if len(result) != len(q):
            raise RuntimeError(
                f"Chunk row count changed: {len(q)} -> {len(result)}"
            )
        if result[KEY].duplicated().any():
            raise RuntimeError(f"Duplicate field keys in chunk {chunk_no}")

        atomic_parquet(result, path)
        if not checkpoint_valid(path, expected_keys):
            raise RuntimeError(f"Checkpoint verification failed after write: {path}")

        new_fields += len(q)
        elapsed = time.monotonic() - run_start
        rate = new_fields / elapsed if elapsed > 0 else float("nan")
        remaining = len(points) - end
        eta = remaining / rate if rate > 0 else None
        pct = 100.0 * end / len(points)

        atomic_json(state_path, {
            "phase": "FIELD_CHUNKS",
            "status": "RUNNING",
            "population": int(len(points)),
            "chunk_size": int(cfg["chunk_size_fields"]),
            "last_completed_field_seq": int(end),
            "last_completed_chunk": int(chunk_no),
            "new_fields_this_run": int(new_fields),
            "rate_fields_per_second": float(rate) if np.isfinite(rate) else None,
            "eta_seconds": float(eta) if eta is not None else None,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        })

        print(
            f"  [FIELDS] {end:6d}/{len(points):6d} · {pct:5.1f}% · "
            f"chunk {chunk_no:3d}/{len(ranges):3d} · "
            f"{rate:8.1f} fields/s · ETA {fmt_duration(eta)} · checkpoint saved"
        )

    print("\n[6/6] Final assembly + QA")
    parts = []
    for _, start, end in ranges:
        path = checkpoint_path(checkpoint_dir, start, end)
        if not checkpoint_valid(path, points.iloc[start:end][KEY]):
            raise RuntimeError(f"Missing/invalid final checkpoint: {path}")
        parts.append(pd.read_parquet(path))
    final = pd.concat(parts, ignore_index=True)

    if len(final) != int(cfg["expected_fields"]):
        raise RuntimeError(f"Final population {len(final)} != {cfg['expected_fields']}")
    if final[KEY].duplicated().any():
        raise RuntimeError("Final output has duplicate field keys")
    if not final[KEY].astype(str).reset_index(drop=True).equals(
        points[KEY].astype(str).reset_index(drop=True)
    ):
        raise RuntimeError("Final output field order/identity differs from canonical population")

    aro_col = next((c for c in final.columns if str(c).upper() == "ARO_UUID"), None)
    subid_col = next((c for c in final.columns if str(c).upper() == "SUBID"), None)
    if aro_col is None or subid_col is None:
        raise RuntimeError("Final output lacks ARO_UUID/Subid")

    coverage = {
        "fields_total": int(len(final)),
        "smallmag_matched": int(final["sgu_smallmag_value"].notna().sum()),
        "sgu_hype_matched": int(final["omrade_id"].notna().sum()),
        "svar_aro_uuid_matched": int(final[aro_col].notna().sum()),
        "subid_matched": int(final[subid_col].notna().sum()),
    }
    for key in list(coverage):
        if key != "fields_total":
            coverage[key + "_pct"] = 100.0 * coverage[key] / len(final)

    units = {
        "sgu_hype": distribution_stats(final["omrade_id"]),
        "svar_aro_uuid": distribution_stats(final[aro_col]),
        "shype_subid": distribution_stats(final[subid_col]),
    }

    by_municipality = []
    if "kommun" in final.columns:
        for mun, q in final.groupby("kommun", dropna=False):
            by_municipality.append({
                "kommun": None if pd.isna(mun) else str(mun),
                "fields": int(len(q)),
                "smallmag_pct": 100.0 * q["sgu_smallmag_value"].notna().mean(),
                "sgu_hype_pct": 100.0 * q["omrade_id"].notna().mean(),
                "svar_pct": 100.0 * q[aro_col].notna().mean(),
                "subid_pct": 100.0 * q[subid_col].notna().mean(),
            })

    final_path = work_dir / "akervatten_c_spatial_links_skane.parquet"
    atomic_parquet(final, final_path)

    acc = cfg["acceptance"]
    problems = []
    checks = [
        ("smallmag", coverage["smallmag_matched"] / len(final), float(acc["min_smallmag_fraction"])),
        ("sgu_hype", coverage["sgu_hype_matched"] / len(final), float(acc["min_sgu_hype_fraction"])),
        ("svar", coverage["svar_aro_uuid_matched"] / len(final), float(acc["min_svar_fraction"])),
        ("subid", coverage["subid_matched"] / len(final), float(acc["min_subid_fraction"])),
    ]
    for name, actual, minimum in checks:
        if actual < minimum:
            problems.append(
                f"{name} coverage {actual:.3%} below acceptance {minimum:.3%}"
            )

    summary = {
        "schema_version": "akervatten-mvp-v0a-c-full-linkage-result",
        "status": "PASS" if not problems else "FAIL",
        "coverage": coverage,
        "hydrological_units": units,
        "municipality_coverage": by_municipality,
        "source_provenance": {
            "smallmag_file": str(small_zip),
            "smallmag_sha256": sha256(small_zip),
            "sgu_hype_file": str(raw_dir / "sgu" / "sgu_hype_areas_skane.geojson"),
            "vattenwebb_flowstats_file": str(flow_path),
            "vattenwebb_flowstats_sha256": sha256(flow_path),
            "svar_tile_dir": str(tile_dir),
        },
        "resume": {
            "chunk_size_fields": int(cfg["chunk_size_fields"]),
            "chunks_total": int(len(ranges)),
            "checkpoint_dir": str(checkpoint_dir),
        },
        "guardrails": cfg["guardrails"],
        "problems": problems,
    }
    atomic_json(work_dir / "c_summary.json", summary)
    atomic_json(state_path, {
        "phase": "COMPLETE",
        "status": summary["status"],
        "population": int(len(final)),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "final_output": str(final_path),
    })

    print("\nCOVERAGE")
    print(f"  fields total       : {len(final):,}")
    print(
        f"  smallmag           : {coverage['smallmag_matched']:,} "
        f"({coverage['smallmag_matched_pct']:.2f}%)"
    )
    print(
        f"  SGU-HYPE           : {coverage['sgu_hype_matched']:,} "
        f"({coverage['sgu_hype_matched_pct']:.2f}%)"
    )
    print(
        f"  SVAR ARO_UUID      : {coverage['svar_aro_uuid_matched']:,} "
        f"({coverage['svar_aro_uuid_matched_pct']:.2f}%)"
    )
    print(
        f"  S-HYPE Subid       : {coverage['subid_matched']:,} "
        f"({coverage['subid_matched_pct']:.2f}%)"
    )

    print("\nHYDROLOGICAL REUSE")
    for name, stat in units.items():
        print(
            f"  {name:14s}: unique={stat['unique']:,} · "
            f"fields/unit median={stat['fields_per_unit_median']} · "
            f"P90={stat['fields_per_unit_p90']} · max={stat['fields_per_unit_max']}"
        )

    if problems:
        print("\nPROBLEMS")
        for problem in problems:
            print("  -", problem)

    print("\nFinal output:", final_path)
    print("Summary     :", work_dir / "c_summary.json")
    print("=" * 120)
    print(f"AKERVATTEN STOPPUNKT C FULL LINKAGE: {summary['status']}")
    print("=" * 120)
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
