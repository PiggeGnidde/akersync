#!/usr/bin/env python3
"""Export bounded native-resolution pixel cases from existing local scenes only."""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import platform
import shutil
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from shapely import wkb

from rapskartan_map_product_core import (
    aggregate_local_scene_timeseries, field_grid, load_map_contract,
    local_asset_path, sha256_file, verify_stop_d,
)
from rapskartan_model_core import SPECTRAL_NAMES
from rapskartan_parity_diagnostic_core import (
    Tee, compare_tables, ensure_separate_output, heartbeat, local_path,
    offline_audit, read_table, save_table, validate_scenes, verify_day_assets,
)
from rapskartan_s2_pilot_core import artifact_records, write_json
from rapskartan_v1_discovery_core import repository_snapshot

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feature/rapskartan-skane-v1a"
MAX_CASES = 5
MAX_SCENES = 20
MAX_PIXELS_PER_BAND = 4_000_000
MAX_RAW_BYTES = 256 * 2**20
PADDING_PIXELS = 16


def verify_diagnostic(folder: Path) -> dict:
    manifest = json.loads((folder / "diagnostic_manifest.json").read_text(encoding="utf-8"))
    required = {"diagnostic_summary.json", "diagnostic_inputs.json", "selected_fields.csv",
                "observation_comparison.csv", "local_timeseries.csv", "reference_timeseries.csv"}
    records = manifest.get("artifacts", [])
    names = [record["path"] for record in records]
    if manifest.get("status") != "DIAGNOSTICS_COMPLETE" or not required <= set(names) or len(names) != len(set(names)):
        raise RuntimeError("Incomplete/duplicate diagnostic manifest")
    for record in records:
        path = local_path(folder / record["path"])
        if path.parent != folder or not path.is_file():
            raise RuntimeError("Diagnostic manifest must contain existing local root files")
        if path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Diagnostic artifact mismatch: {path.name}")
    summary = json.loads((folder / "diagnostic_summary.json").read_text(encoding="utf-8"))
    if summary.get("status") != "DIAGNOSTICS_COMPLETE":
        raise RuntimeError("Diagnostic is not complete")
    return json.loads((folder / "diagnostic_inputs.json").read_text(encoding="utf-8"))


def select_cases(observations: pd.DataFrame, fields: pd.DataFrame) -> pd.DataFrame:
    """Fixed diagnostic recipe; no crop labels, scores or model optimization."""
    keys = ["development_field_id", "acquisition_date"]
    if observations.duplicated(keys).any():
        raise RuntimeError("Duplicate diagnostic observations")
    obs = observations.merge(fields[["development_field_id", "area_ha"]], on="development_field_id", validate="many_to_one")
    maxima = obs.groupby("development_field_id")[["valid_pixels_local", "valid_pixels_reference"]].transform("max")
    clear = obs[obs.valid_pixels_local.eq(maxima.valid_pixels_local)
                & obs.valid_pixels_reference.eq(maxima.valid_pixels_reference)
                & obs.valid_pixels_local.gt(0)]
    clear = clear.sort_values(keys).drop_duplicates("development_field_id").sort_values(["area_ha", *keys])
    if clear.empty:
        raise RuntimeError("No jointly maximum-coverage observations for pixel cases")
    rows = []
    for index, reason in ((0, "small_field_max_coverage"), (len(clear)//2, "median_field_max_coverage"),
                          (len(clear)-1, "large_field_max_coverage")):
        row = clear.iloc[index].copy(); row["reason"] = reason; rows.append(row)
    spectral = obs[np.isfinite(obs.B08_p50_delta)].copy()
    spectral["magnitude"] = spectral.B08_p50_delta.abs()
    if not spectral.empty:
        row = spectral.sort_values(["magnitude", *keys], ascending=[False, True, True]).iloc[0].copy()
        row["reason"] = "largest_nir_median_difference"; rows.append(row)
    row = obs.sort_values(["valid_pixel_fraction_delta", *keys], ascending=[False, True, True]).iloc[0].copy()
    row["reason"] = "largest_positive_coverage_difference"; rows.append(row)
    selected = pd.DataFrame(rows).drop_duplicates(keys).reset_index(drop=True)
    selected.insert(0, "case_id", [f"case_{i+1:02d}" for i in range(len(selected))])
    return selected[["case_id", *keys, "reason", "area_ha", "valid_pixels_local", "valid_pixels_reference"]]


def source_path(archive: Path, scene: dict, band: str) -> Path:
    path = local_path(local_asset_path(archive, scene, band))
    if archive not in path.parents or not path.is_file():
        raise RuntimeError(f"Missing/nonlocal source; no download attempted: {path}")
    if path.stat().st_size != int(scene["assets"][band]["bytes"]):
        raise RuntimeError(f"Source size mismatch: {path}")
    return path


def native_window(source, field_bounds, field_crs) -> Window:
    if source.count != 1 or source.crs is None or source.transform.b or source.transform.d:
        raise RuntimeError("Expected a single-band georeferenced north-up source")
    bounds = transform_bounds(field_crs, source.crs, *field_bounds, densify_pts=21)
    raw = from_bounds(*bounds, transform=source.transform)
    left = max(0, math.floor(raw.col_off)-PADDING_PIXELS)
    top = max(0, math.floor(raw.row_off)-PADDING_PIXELS)
    right = min(source.width, math.ceil(raw.col_off+raw.width)+PADDING_PIXELS)
    bottom = min(source.height, math.ceil(raw.row_off+raw.height)+PADDING_PIXELS)
    if right <= left or bottom <= top:
        raise RuntimeError("Selected band has no intersection with the field window")
    if (right-left)*(bottom-top) > MAX_PIXELS_PER_BAND:
        raise RuntimeError("Pixel window exceeds the bounded export guard")
    return Window(left, top, right-left, bottom-top)


def export_band(source_file: Path, destination: Path, bounds, crs, budget: list[int]) -> dict:
    if destination.exists():
        raise RuntimeError("Pixel export never overwrites an existing file")
    with rasterio.open(source_file) as source:
        window = native_window(source, bounds, crs)
        size = int(window.width*window.height*np.dtype(source.dtypes[0]).itemsize)
        if budget[0]+size > MAX_RAW_BYTES:
            raise RuntimeError("Pixel package exceeds 256 MiB uncompressed pixel guard")
        values = source.read(1, window=window)  # Native pixels: no resampling/out_shape.
        transform = source.window_transform(window)
        destination.parent.mkdir(parents=True, exist_ok=True)
        profile = dict(driver="GTiff", width=values.shape[1], height=values.shape[0], count=1,
                       dtype=values.dtype, crs=source.crs, transform=transform, nodata=source.nodata,
                       compress="deflate")
        with rasterio.open(destination, "w", **profile) as target:
            target.write(values, 1)
        with rasterio.open(destination) as check:
            if not np.array_equal(check.read(1), values, equal_nan=True) or check.transform != transform or check.crs != source.crs:
                raise RuntimeError("Exported native pixels/georeferencing failed round-trip verification")
            if check.dtypes[0] != source.dtypes[0] or check.nodata != source.nodata:
                raise RuntimeError("Exported datatype/nodata changed")
        budget[0] += size
        return {"window": [int(window.col_off), int(window.row_off), int(window.width), int(window.height)],
                "source_shape": [source.height, source.width], "source_transform": list(source.transform)[:6],
                "crop_transform": list(transform)[:6], "crs": source.crs.to_string(),
                "dtype": source.dtypes[0], "nodata": source.nodata,
                "native_array_sha256": hashlib.sha256(values.tobytes(order="C")).hexdigest(),
                "pixel_bytes": size, "sha256": sha256_file(destination), "bytes": destination.stat().st_size}


def export_cases(out: Path, cases: pd.DataFrame, geometries, scenes: list[dict], archive: Path, contract: dict,
                 local: pd.DataFrame, reference: pd.DataFrame) -> dict:
    if not 1 <= len(cases) <= MAX_CASES:
        raise RuntimeError("Pixel export requires 1 to 5 cases")
    verified, assets, replay_parts = {}, [], []
    budget = [0]
    columns = ["sample_pixels", "valid_pixels", "valid_pixel_fraction"] + [f"{b}_p{p}" for b in SPECTRAL_NAMES for p in (10, 50, 90)]
    keys = ["development_field_id", "acquisition_date"]
    for case in cases.itertuples(index=False):
        print(f"[PIXEL] {case.case_id}/{len(cases)}: {case.development_field_id}, {case.acquisition_date}", flush=True)
        field = geometries[geometries.development_field_id.eq(case.development_field_id)].to_crs(32633)
        if len(field) != 1 or not field.geometry.is_valid.all():
            raise RuntimeError("Pixel case geometry missing/invalid")
        geom = field.geometry.iloc[0]
        folder = out / case.case_id
        folder.mkdir()
        save_table(folder / "field.csv", field.drop(columns="geometry"))
        write_json(folder / "geometry.json", {"crs": "EPSG:32633", "geometry": geom.__geo_interface__})
        crop_scenes = []
        for scene in scenes:
            if scene["acquisition_date"] != case.acquisition_date:
                continue
            scl_path = source_path(archive, scene, "SCL")
            with rasterio.open(scl_path) as scl:
                left, bottom, right, top = transform_bounds(scl.crs, field.crs, *scl.bounds, densify_pts=21)
            a, b, c, d = geom.bounds
            if right <= a or c <= left or top <= b or d <= bottom:
                continue
            if scene["item_id"] not in verified:
                if len(verified) >= MAX_SCENES:
                    raise RuntimeError("Pixel cases exceed the 20-source-scene guard")
                print(f"[PIXEL] Checking existing scene {scene['item_id']} (no download)...", flush=True)
                with heartbeat("selected source checksums"):
                    verified[scene["item_id"]] = verify_day_assets([scene], archive)
            cropped = copy.deepcopy(scene)
            for band, asset in scene["assets"].items():
                cropped["assets"][band]["s3_uri"] = f"s3://eodata/pixel-export/{band}.tif"
                destination = local_asset_path(folder / "archive", cropped, band)
                with heartbeat(f"{case.case_id} {band} native pixel export"):
                    info = export_band(source_path(archive, scene, band), destination, geom.bounds, field.crs, budget)
                cropped["assets"][band].update(bytes=info["bytes"], checksum="1220"+info["sha256"])
                assets.append({"case_id": case.case_id, "item_id": scene["item_id"], "band": band,
                               "path": destination.relative_to(out).as_posix(), "source_asset": asset, **info})
            crop_scenes.append(cropped)
        if not crop_scenes:
            raise RuntimeError("No cached scene intersects a selected case")
        write_json(folder / "scene_inventory.json", {"items": crop_scenes})
        transform, width, height = field_grid(geom.bounds, 10)
        masks = np.stack([rasterize([(geom, 1)], out_shape=(height, width), transform=transform,
                                   all_touched=touched, dtype="uint8") for touched in (False, True)])
        with rasterio.open(folder / "geometry_masks.tif", "w", driver="GTiff", width=width, height=height,
                           count=2, dtype="uint8", crs=field.crs, transform=transform, compress="deflate") as target:
            target.write(masks)
            target.set_band_description(1, "current_center_mask")
            target.set_band_description(2, "diagnostic_all_touched_mask_not_a_fix")
        with heartbeat(f"{case.case_id} crop replay"):
            replay = aggregate_local_scene_timeseries(field, crop_scenes, folder / "archive", contract, progress_prefix="PIXEL")
        replay_parts.append(replay)
        save_table(folder / "crop_replay.csv", replay)
    replay = pd.concat(replay_parts, ignore_index=True)
    chosen = cases[keys]
    local = chosen.merge(local, on=keys, validate="one_to_one")
    reference = chosen.merge(reference, on=keys, validate="one_to_one")
    if len(local) != len(cases) or len(reference) != len(cases):
        raise RuntimeError("Selected observation coverage incomplete")
    save_table(out / "local_observations.csv", local)
    save_table(out / "reference_observations.csv", reference)
    joined, summary = compare_tables(replay, local, keys, columns)
    save_table(out / "crop_replay_comparison.csv", joined)
    save_table(out / "crop_replay_variable_summary.csv", summary)
    exact_counts = all(joined[f"{column}_delta"].eq(0).all() for column in ("sample_pixels", "valid_pixels"))
    quality_agrees = replay.set_index(keys).data_quality_status.sort_index().equals(local.set_index(keys).data_quality_status.sort_index())
    numerical_match = bool(summary.missing_mismatch.eq(0).all() and summary.unmatched_rows.eq(0).all()
                           and summary.max_abs_delta.fillna(0).le(1e-6).all())
    write_json(out / "native_asset_provenance.json", {"assets": assets})
    save_table(out / "verified_source_assets.csv", pd.DataFrame([record for records in verified.values() for record in records]))
    return {"status": "PIXEL_EXPORT_COMPLETE", "cases": len(cases), "source_scenes": len(verified),
            "native_pixel_bytes": budget[0], "exported_bands": len(assets),
            "crop_replay_counts_exact": bool(exact_counts), "crop_replay_quality_agrees": bool(quality_agrees),
            "crop_replay_matches_local_within_1e_6": numerical_match,
            "interpretation": "Crop replay checks export fidelity, NOT production parity approval.",
            "model_changed": False, "thresholds_changed": False, "downloads": 0}


def run(args, out: Path) -> None:
    snapshot = repository_snapshot(ROOT)
    if snapshot["branch"] != BRANCH or not snapshot["working_tree_clean"]:
        raise RuntimeError(f"Pixel export requires clean branch {BRANCH}")
    diagnostic = args.diagnostic_dir
    if diagnostic is None:
        candidates = sorted((ROOT / "data/derived/rapskartan_v1/2025_parity_diagnostic_v1").glob("run_*/diagnostic_manifest.json"))
        if len(candidates) != 1:
            raise RuntimeError("Expected one completed diagnostic; specify --diagnostic-dir with the desired run folder")
        diagnostic = local_path(candidates[0].parent)
    ensure_separate_output(out.parent, [diagnostic, args.stop_d_dir, args.product_dir, args.scene_archive])
    print(f"[PIXEL] Reading completed diagnostic: {diagnostic}", flush=True)
    with heartbeat("verifying existing diagnostic and frozen reference"):
        inputs = verify_diagnostic(diagnostic)
        contract = load_map_contract(ROOT)
        verify_stop_d(ROOT, args.stop_d_dir, contract)
    inventory = args.product_dir / "source/scene_inventory.json"
    if sha256_file(inventory) != inputs["scene_inventory_sha256"] or sha256_file(args.stop_d_dir / "prediction_lock_manifest.json") != inputs["prediction_lock_sha256"]:
        raise RuntimeError("Source inventory/reference lock differs from the completed diagnostic")
    scenes = validate_scenes(json.loads(inventory.read_text(encoding="utf-8")), contract)
    selected = read_table(diagnostic / "selected_fields.csv")
    observations = read_table(diagnostic / "observation_comparison.csv")
    cases = select_cases(observations, selected)
    save_table(out / "selected_cases.csv", cases)
    locked_geometry = read_table(args.stop_d_dir / "blind_selection_geometry_wkb.csv")
    geometry = selected.merge(locked_geometry[["development_field_id", "geometry_wkb_hex"]], on="development_field_id", validate="one_to_one")
    geometry = geometry[geometry.development_field_id.isin(cases.development_field_id)].copy()
    fields = gpd.GeoDataFrame(geometry.drop(columns="geometry_wkb_hex"), geometry=[wkb.loads(v, hex=True) for v in geometry.geometry_wkb_hex], crs=3006)
    write_json(out / "export_inputs.json", {"repository_head": snapshot["head"], "repository_tree": snapshot["head_tree"],
               "diagnostic_manifest_sha256": sha256_file(diagnostic / "diagnostic_manifest.json"),
               "source_diagnostic": inputs, "selection_recipe": "three_area_ranks_at_joint_max_coverage_plus_two_pixel_outliers_v1",
               "padding_native_pixels": PADDING_PIXELS, "python": platform.python_version(),
               "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__, "proj": rasterio.__proj_version__})
    write_json(out / "map_contract.json", contract)
    result = export_cases(out, cases, fields, scenes, args.scene_archive, contract,
                          read_table(diagnostic / "local_timeseries.csv"), read_table(diagnostic / "reference_timeseries.csv"))
    end = repository_snapshot(ROOT)
    if end["head"] != snapshot["head"] or not end["working_tree_clean"]:
        raise RuntimeError("Repository changed during export")
    write_json(out / "pixel_export_summary.json", result)
    print(f"[PIXEL] Complete: {result['cases']} cases, {result['exported_bands']} native crops; crop replay matches: {result['crop_replay_matches_local_within_1e_6']}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-dir", type=Path)
    parser.add_argument("--stop-d-dir", type=Path, default=Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"))
    parser.add_argument("--product-dir", type=Path, default=ROOT / "data/derived/rapskartan_v1/2025")
    parser.add_argument("--scene-archive", type=Path, default=Path(r"C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\map_product_2025_scene_archive_v1"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/derived/rapskartan_v1/2025_pixel_cases_v1")
    args = parser.parse_args()
    sys.addaudithook(offline_audit)
    for name, value in vars(args).items():
        if value is not None:
            setattr(args, name, local_path(value))
    ensure_separate_output(args.output_dir, [args.stop_d_dir, args.product_dir, args.scene_archive] + ([args.diagnostic_dir] if args.diagnostic_dir else [ROOT / "data/derived/rapskartan_v1/2025_parity_diagnostic_v1"]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.output_dir).free < 2*2**30:
        raise RuntimeError("Pixel export requires 2 GiB free output space")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = args.output_dir / f"run_{stamp}"
    out.mkdir()
    with (out / "pixel_export_console.log").open("w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
            try:
                run(args, out)
            except Exception:
                traceback.print_exc()
                print(f"PIXEL EXPORT BLOCKED. Sources unchanged. Return log: {out / 'pixel_export_console.log'}")
                return 1
    files = sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())
    write_json(out / "pixel_export_manifest.json", {"status": "PIXEL_EXPORT_COMPLETE", "artifacts": artifact_records(out, files)})
    package = args.output_dir / f"rapskartan_pixel_cases_{stamp}.zip"
    with zipfile.ZipFile(package, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in [*files, "pixel_export_manifest.json"]:
            archive.write(out / name, name)
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Pixel ZIP integrity failure")
    print(f"RETURN THIS ZIP: {package}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
