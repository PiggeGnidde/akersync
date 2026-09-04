#!/usr/bin/env python3
"""Five bounded reference cases, ten persistent data requests, separate OAuth login."""
from __future__ import annotations

import argparse
import contextlib
import json
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
from shapely import wkb
from shapely.geometry import shape

from rapskartan_blind_prediction_core import frozen_runtime_contract, load_blind_contract, verify_stop_c
from rapskartan_map_product_core import load_map_contract, sha256_file, verify_stop_d
from rapskartan_parity_diagnostic_core import Tee, ensure_separate_output, heartbeat, local_path, read_table, save_table
from rapskartan_pixel_reference_core import BudgetCache, Transport, atomic_json, build_plan, run_lock, unpack_response
from rapskartan_s2_pilot_core import artifact_records
from rapskartan_v1_discovery_core import repository_snapshot

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feature/rapskartan-skane-v1a"


def verify_pixel_package(folder):
    manifest = json.loads((folder / "pixel_export_manifest.json").read_text(encoding="utf-8"))
    records = manifest.get("artifacts", [])
    required = {"selected_cases.csv", "reference_observations.csv", "local_observations.csv", "export_inputs.json", "pixel_export_summary.json"}
    names = [r["path"] for r in records]
    if manifest.get("status") != "PIXEL_EXPORT_COMPLETE" or not required <= set(names) or len(names) != len(set(names)):
        raise RuntimeError("Incomplete pixel manifest")
    for record in records:
        path = local_path(folder / record["path"])
        if folder not in path.parents or not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError("Pixel package artifact/hash mismatch")
    cases = read_table(folder / "selected_cases.csv").to_dict("records")
    for case in cases:
        if case["case_id"] not in {f"case_{i:02d}" for i in range(1,6)} or f"{case['case_id']}/geometry.json" not in names:
            raise RuntimeError("Case geometry is absent from verified manifest")
    return cases


def analyze_simple(folder, record, reference):
    with rasterio.open(folder / "default.tif") as image:
        values = image.read()
        valid = values[record["bands"].index("valid_mask")] > 0
        input_mask = values[record["bands"].index("input_dataMask")] > 0
        scl = values[record["bands"].index("SCL")]
        result = {"case_id": record["case_id"], "new_reference_valid_pixels": int(valid.sum()),
                  "old_reference_valid_pixels": int(reference.valid_pixels), "input_data_pixels": int(input_mask.sum()),
                  "valid_count_matches_old_reference": int(valid.sum()) == int(reference.valid_pixels),
                  "scl_values_inside_data": [float(v) for v in np.unique(scl[input_mask])],
                  "note": "New reference pixels do not replace locked historical observations; percentile algorithm remains under investigation."}
        rows = []
        for i, band in enumerate(record["bands"][:18]):
            pixels = values[i][valid]
            for method in ("linear", "nearest", "higher", "lower"):
                percentiles = np.percentile(pixels, [10,50,90], method=method) if pixels.size else [np.nan]*3
                for p, value in zip((10,50,90), percentiles):
                    old = reference.get(f"{band}_p{p}", np.nan)
                    rows.append({"band": band, "percentile": p, "method": method, "new_pixel_statistic": value,
                                 "old_locked_statistic": old, "delta": value-old})
        save_table(folder / "percentile_diagnostics.csv", pd.DataFrame(rows))
        atomic_json(folder / "reference_comparison.json", result)
        return result


def run(args, out):
    snap = repository_snapshot(ROOT)
    if snap["branch"] != BRANCH or not snap["working_tree_clean"]:
        raise RuntimeError(f"Reference runner requires clean branch {BRANCH}")
    source = args.pixel_dir
    if source is None:
        matches = sorted((ROOT / "data/derived/rapskartan_v1/2025_pixel_cases_v1").glob("run_*/pixel_export_manifest.json"))
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one pixel package; specify --pixel-dir with its run directory")
        source = local_path(matches[0].parent)
    ensure_separate_output(out, [source, args.stop_c_dir, args.stop_d_dir])
    print(f"[REFERENCE] Verifying input package: {source}", flush=True)
    with heartbeat("reference preflight"):
        cases = verify_pixel_package(source)
        verify_stop_c(ROOT, args.stop_c_dir)
        verify_stop_d(ROOT, args.stop_d_dir, load_map_contract(ROOT))
    runtime = frozen_runtime_contract(args.stop_c_dir, load_blind_contract(ROOT))
    frozen = runtime["frozen_feature_contract"]
    geometries = {case["case_id"]: json.loads((source/case["case_id"]/"geometry.json").read_text(encoding="utf-8")) for case in cases}
    locked = read_table(args.stop_d_dir / "blind_selection_geometry_wkb.csv").set_index("development_field_id")
    for case in cases:
        geom = wkb.loads(locked.loc[case["development_field_id"], "geometry_wkb_hex"], hex=True)
        expected = gpd.GeoSeries([geom], crs=3006).to_crs(32633).iloc[0]
        if not shape(geometries[case["case_id"]]["geometry"]).equals_exact(expected, tolerance=1e-6):
            raise RuntimeError("Pixel-case geometry differs from locked field geometry")
    plan = build_plan(cases, geometries, frozen)
    cache = BudgetCache(out / "cache", plan)
    pending = cache.pending()  # Check budget/corruption before any login request.
    print(f"[REFERENCE] {len(plan)} planned data requests; {len(pending)} uncached; {len(cache.state['attempts'])}/10 attempts already reserved.", flush=True)
    print("[REFERENCE] No automatic retries. OAuth login is separate from the ten data requests.", flush=True)
    atomic_json(out / "request_plan.json", plan)
    atomic_json(out / "reference_inputs.json", {"repository_head": snap["head"], "pixel_manifest_sha256": sha256_file(source / "pixel_export_manifest.json"),
                                               "model_manifest_sha256": sha256_file(args.stop_c_dir / "model_artifacts_manifest.json"),
                                               "primary_mode": "unchanged SIMPLE", "scene_diagnostic_mode": "TILE, never substituted for SIMPLE"})
    for name in ("selected_cases.csv", "reference_observations.csv", "local_observations.csv", "export_inputs.json"):
        shutil.copyfile(source / name, out / name)
    transport = Transport()
    if pending:
        print("[REFERENCE] Logging in using locally configured CDSE credentials...", flush=True)
        with heartbeat("Copernicus login"):
            transport.authenticate()
    old = read_table(source / "reference_observations.csv").set_index(["development_field_id", "acquisition_date"])
    case_lookup = {case["case_id"]: case for case in cases}
    comparisons = []
    for i, record in enumerate(plan, 1):
        print(f"[REFERENCE] {i}/{len(plan)}: {record['id']}", flush=True)
        with heartbeat(record["id"]):
            body, meta = cache.fetch(record, transport)
        folder = out / "responses" / record["id"]
        image = unpack_response(body, folder, record)
        if record["mode"] == "simple":
            case = case_lookup[record["case_id"]]
            comparison = analyze_simple(folder, record, old.loc[(case["development_field_id"], case["acquisition_date"])])
            comparisons.append({**comparison, "grid_matches_local": image["grid_matches_local"]})
    end = repository_snapshot(ROOT)
    if snap["head"] != end["head"] or not end["working_tree_clean"]:
        raise RuntimeError("Repository changed during reference run")
    atomic_json(out / "reference_summary.json", {"status": "REFERENCE_PIXELS_COMPLETE", "comparisons": comparisons,
                 "data_attempts_total": len(cache.state["attempts"]), "cache_hits_this_run": cache.hits,
                 "oauth_login_this_run": bool(pending), "source_files_modified": False, "models_changed": False,
                 "production_parity_approved": False, "thresholds_changed": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pixel-dir", type=Path)
    parser.add_argument("--stop-c-dir", type=Path, default=Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"))
    parser.add_argument("--stop-d-dir", type=Path, default=Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/derived/rapskartan_v1/2025_pixel_reference_v1")
    args = parser.parse_args()
    for name,value in vars(args).items():
        if value is not None:
            setattr(args, name, local_path(value))
    out = args.output_dir
    ensure_separate_output(out, [args.stop_c_dir,args.stop_d_dir,args.pixel_dir or ROOT / "data/derived/rapskartan_v1/2025_pixel_cases_v1"])
    out.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out).free < 2*2**30:
        raise RuntimeError("Reference output requires 2 GiB free disk space")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = out / f"reference_console_{stamp}.log"
    with run_lock(out), log_path.open("w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(Tee(sys.stdout,log)), contextlib.redirect_stderr(Tee(sys.stderr,log)):
            try:
                run(args,out)
            except Exception:
                traceback.print_exc()
                print(f"REFERENCE BLOCKED. Keep cache and request_budget.json. Return this log: {log_path}")
                return 1
        # The closed redirect's log handle is flushed on every write.
        files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
                       and p.suffix not in (".zip", ".tmp", ".lock") and p.name != "reference_manifest.json")
        atomic_json(out / "reference_manifest.json", {"status": "REFERENCE_PIXELS_COMPLETE", "artifacts": artifact_records(out,files)})
        package = out / f"rapskartan_reference_pixels_{stamp}.zip"
        with zipfile.ZipFile(package,"x",compression=zipfile.ZIP_DEFLATED) as archive:
            for name in [*files,"reference_manifest.json"]:
                archive.write(out/name,name)
        with zipfile.ZipFile(package) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Reference ZIP integrity failure")
        print(f"RETURN THIS ZIP: {package}",flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
