from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rapskartan_map_product_core import (
    aggregate_local_scene_timeseries, load_map_contract, local_asset_path,
)
from rapskartan_parity_diagnostic_core import (
    compare_tables, ensure_separate_output, local_path, offline_audit,
    read_day_checkpoint, read_table, save_day_checkpoint, save_table,
    validate_scenes, verify_day_assets,
)


class DiagnosticTests(unittest.TestCase):
    def test_main_packages_reports_with_hash_manifest_not_scene_cache(self):
        spec = importlib.util.spec_from_file_location("diagnostic_packaging", ROOT / "src/102_diagnose_rapskartan_2025_parity.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "output"
            args = ["diagnostic", "--output-dir", str(base)]
            for option in ("stop-c-dir", "stop-d-dir", "product-dir", "scene-archive"):
                args.extend([f"--{option}", str(Path(temporary) / option)])
            def completed(_args, output):
                out = output / "run_test"
                (out / "checkpoints").mkdir(parents=True)
                (out / "diagnostic_summary.json").write_text('{"status":"DIAGNOSTICS_COMPLETE"}')
                (out / "checkpoints/date.parquet").write_bytes(b"not part of ZIP")
                return out
            with patch.object(sys, "argv", args), patch.object(sys, "addaudithook"), patch.object(runner, "run", side_effect=completed):
                self.assertEqual(runner.main(), 0)
            archives = list(base.glob("*.zip"))
            self.assertEqual(len(archives), 1)
            with zipfile.ZipFile(archives[0]) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()), {"diagnostic_summary.json", "diagnostic_console.log", "diagnostic_manifest.json"})
                manifest = json.loads(archive.read("diagnostic_manifest.json"))
                for row in manifest["artifacts"]:
                    self.assertEqual(hashlib.sha256(archive.read(row["path"])).hexdigest(), row["sha256"])

    def test_complete_report_and_restart_even_when_parity_fails(self):
        from shapely.geometry import box
        spec = importlib.util.spec_from_file_location("diagnostic_runner", ROOT / "src/102_diagnose_rapskartan_2025_parity.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        contract = load_map_contract(ROOT)
        field_id, day = "2025-1262-a-1", "2025-04-20"
        selection = pd.DataFrame({"development_field_id": [field_id], "municipality_code": ["1262"]})
        features = pd.DataFrame({"development_field_id": [field_id], "cutoff_date": [day], "x": [.1]})
        predictions = pd.DataFrame({"development_field_id": [field_id], "cutoff_date": [day],
                                    "model_arm": ["SATELLITE_ONLY"], "data_quality_status": ["USABLE"],
                                    "raw_probability": [.1], "calibrated_probability": [.1],
                                    "predicted_at_frozen_p95": [False]})
        ts = pd.DataFrame({"development_field_id": [field_id], "acquisition_date": [day],
                           "data_quality_status": ["VALID"], "sample_pixels": [4], "valid_pixels": [4],
                           "valid_pixel_fraction": [1.], **{f"{name}_p{p}": [.1] for name in runner.SPECTRAL_NAMES for p in (10, 50, 90)}})
        local_predictions = predictions.copy()
        local_predictions["raw_probability"] = .9
        local_predictions["calibrated_probability"] = .9
        local_predictions["predicted_at_frozen_p95"] = True
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stop_c, stop_d, product, archive, base = [root / name for name in ("c", "d", "product", "archive", "output")]
            for folder in (stop_c, stop_d, product / "source", product / "qa", archive, base):
                folder.mkdir(parents=True, exist_ok=True)
            for name, frame in {"blind_field_selection.csv": selection, "blind_predictions_locked.csv": predictions,
                                "blind_prior_features.csv": selection, "blind_s2_timeseries.csv": ts,
                                "blind_temporal_features.csv": features,
                                "blind_selection_geometry_wkb.csv": pd.DataFrame({"development_field_id": [field_id], "geometry_wkb_hex": [box(0, 0, 20, 20).wkb_hex]})}.items():
                save_table(stop_d / name, frame)
            (stop_c / "model_artifacts_manifest.json").write_text("{}")
            (stop_d / "prediction_lock_manifest.json").write_text("{}")
            (product / "source/scene_inventory.json").write_text("{}")
            previous, _ = runner.compare_parity_predictions(local_predictions, predictions, contract)
            save_table(product / "qa/local_engine_parity_rows.csv", previous)
            args = Namespace(stop_c_dir=stop_c, stop_d_dir=stop_d, product_dir=product, scene_archive=archive)
            snapshot = {"branch": runner.FEATURE_BRANCH, "working_tree_clean": True, "head_tree": "tree", "head": "head"}
            frozen = {"model_version": "test", "frozen_feature_contract_version": "test",
                      "frozen_model_contract_id": "test", "frozen_feature_contract": {}}
            with contextlib.ExitStack() as stack:
                for name, value in {"repository_snapshot": snapshot, "verify_stop_c": None, "verify_stop_d": None,
                                    "frozen_runtime_contract": frozen, "select_parity_field_ids": [field_id],
                                    "runtime_versions": {"test": True}, "validate_scenes": [{"acquisition_date": day}],
                                    "verify_day_assets": [], "temporal_feature_columns": ["x"],
                                    "build_blind_temporal_features": features}.items():
                    stack.enter_context(patch.object(runner, name, return_value=value))
                aggregate = stack.enter_context(patch.object(runner, "aggregate_local_scene_timeseries", return_value=ts))
                predict = stack.enter_context(patch.object(runner, "make_predictions", side_effect=[predictions, predictions, local_predictions] * 2))
                out = runner.run(args, base)
                result = json.loads((out / "diagnostic_summary.json").read_text())
                self.assertEqual(result["status"], "DIAGNOSTICS_COMPLETE")
                self.assertEqual(result["local_engine_vs_locked"]["status"], "FAIL")
                self.assertEqual(result["reference_feature_replay_vs_locked"]["status"], "PASS")
                self.assertEqual(result["local_engine_vs_previous_local_run"]["status"], "PASS")
                self.assertEqual(len(read_table(out / "decision_mismatches.csv")), 1)
                second = runner.run(args, base)
                self.assertEqual(second, out)
                self.assertEqual(aggregate.call_count, 1)
                self.assertEqual(predict.call_count, 6)
                self.assertEqual(read_table(out / "date_progress.csv").iloc[0]["mode"], "checkpoint")

    def test_network_operations_are_blocked_before_connection(self):
        for event in ("socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"):
            with self.assertRaisesRegex(RuntimeError, "OFFLINE_ONLY"):
                offline_audit(event, ())
        offline_audit("open", ())
        code = """
import sys, socket
from rapskartan_parity_diagnostic_core import offline_audit
sys.addaudithook(offline_audit)
try:
    socket.socket().connect(('127.0.0.1', 9))
except RuntimeError as exc:
    assert 'OFFLINE_ONLY' in str(exc)
else:
    raise AssertionError('network guard did not run')
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "src", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_paths_and_nonoverlapping_output(self):
        for value in (r"\\server\share", "/vsicurl/file", "s3://bucket/file", "https://example.com/file"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "OFFLINE_ONLY"):
                    local_path(Path(value))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertEqual(local_path(root), root)
            ensure_separate_output(root / "output", [root / "input"])
            for output, source in ((root, root), (root, root / "input"), (root / "out", root)):
                with self.assertRaisesRegex(RuntimeError, "overlaps"):
                    ensure_separate_output(output, [source])

    def test_windows_normalized_remote_paths_are_rejected_on_every_platform(self):
        # PureWindowsPath reproduces Windows separator conversion on Linux too.
        for value in ("/vsicurl/file", r"\vsicurl\file", "/VSICURL/file",
                      r"\\server\share", "//server/share", "s3://bucket/file",
                      "https://example.com/file", r"\\?\UNC\server\share"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "OFFLINE_ONLY"):
                    local_path(PureWindowsPath(value))

    def test_resolved_windows_network_path_is_also_rejected(self):
        from unittest.mock import Mock
        candidate = Mock(spec=Path)
        candidate.__str__ = Mock(return_value="local-link")
        candidate.resolve.return_value = PureWindowsPath(r"\\server\share")
        with self.assertRaisesRegex(RuntimeError, "OFFLINE_ONLY"):
            local_path(candidate)

    def test_comparison_preserves_signed_deltas_and_missing_rows(self):
        a = pd.DataFrame({"id": ["a", "b", "c"], "x": [2., np.nan, 4.]})
        b = pd.DataFrame({"id": ["a", "b", "d"], "x": [1., 2., 5.]})
        joined, summary = compare_tables(a, b, ["id"], ["x"])
        self.assertEqual(len(joined), 4)
        row = summary.iloc[0]
        self.assertEqual(row.finite_pairs, 1)
        self.assertEqual(row.unmatched_rows, 2)
        self.assertEqual(row.missing_mismatch, 3)
        self.assertEqual(row.mean_signed_delta, 1.)
        self.assertEqual(row.p95_abs_delta, 1.)
        with self.assertRaises(pd.errors.MergeError):
            compare_tables(pd.concat([a, a]), b, ["id"], ["x"])

    def test_comparison_handles_matching_missing_and_nonfinite(self):
        frame = pd.DataFrame({"id": [1, 2], "x": [np.nan, np.inf]})
        _, summary = compare_tables(frame, frame, ["id"], ["x"])
        self.assertEqual(summary.iloc[0].missing_mismatch, 0)
        self.assertEqual(summary.iloc[0].nonfinite_nonmissing_pairs, 1)
        self.assertIsNone(summary.iloc[0].p95_abs_delta)

    def test_saved_tables_keep_precision_and_reject_truth(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "table.csv"
            value = 0.12345678901234567
            save_table(path, pd.DataFrame({"development_field_id": ["0001"], "x": [value]}))
            self.assertIn("0.12345678901234566", path.read_text())
            self.assertEqual(read_table(path).iloc[0].development_field_id, "0001")
            from rapskartan_map_product_core import FORBIDDEN_PRODUCT_COLUMNS
            save_table(path, pd.DataFrame({next(iter(FORBIDDEN_PRODUCT_COLUMNS)): [1]}))
            with self.assertRaisesRegex(RuntimeError, "Ground-truth"):
                read_table(path)

    def test_checkpoint_restart_precision_and_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            day = "2025-04-20"
            frame = pd.DataFrame({"acquisition_date": [day], "value": [0.12345678901234567]})
            self.assertIsNone(read_day_checkpoint(folder, day, "identity"))
            save_day_checkpoint(folder, day, "identity", frame)
            pd.testing.assert_frame_equal(read_day_checkpoint(folder, day, "identity"), frame)
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                read_day_checkpoint(folder, day, "changed")
            data = folder / f"{day}.parquet"
            data.write_bytes(data.read_bytes() + b"corrupt")
            original = data.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                read_day_checkpoint(folder, day, "identity")
            self.assertEqual(data.read_bytes(), original)

    def test_checkpoint_incomplete_or_wrong_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            day = "2025-04-20"
            (folder / f"{day}.parquet").write_bytes(b"interrupted")
            self.assertIsNone(read_day_checkpoint(folder, day, "identity"))
            save_day_checkpoint(folder, day, "identity", pd.DataFrame({"acquisition_date": ["2025-04-21"]}))
            with self.assertRaisesRegex(RuntimeError, "row/date mismatch"):
                read_day_checkpoint(folder, day, "identity")

    def test_asset_verification_is_read_only_and_never_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary).resolve()
            payload = b"synthetic asset"
            scene = {"item_id": "scene", "assets": {"B02": {
                "s3_uri": "s3://eodata/test/file.jp2", "bytes": len(payload),
                "checksum": "1220" + hashlib.sha256(payload).hexdigest(),
            }}}
            path = local_asset_path(archive, scene, "B02")
            with self.assertRaisesRegex(RuntimeError, "no download attempted"):
                verify_day_assets([scene], archive)
            self.assertFalse(path.exists())
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
            self.assertEqual(len(verify_day_assets([scene], archive)), 1)
            bad = b"x" * len(payload)
            path.write_bytes(bad)
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                verify_day_assets([scene], archive)
            self.assertEqual(path.read_bytes(), bad)

    def test_inventory_rejects_unsafe_and_changed_scope(self):
        contract = load_map_contract(ROOT)
        assets = {band: {"s3_uri": "s3://eodata/file.jp2", "bytes": 1, "checksum": "abc"}
                  for band in [*contract["scene_archive"]["reflectance_assets"], "SCL"]}
        scene = {"item_id": "scene", "datetime": "2025-04-20T10:00:00Z",
                 "acquisition_date": "2025-04-20", "assets": assets}
        self.assertEqual(validate_scenes({"items": [scene]}, contract), [scene])
        for key, value in (("item_id", "../../outside"), ("datetime", "2026-04-20T10:00:00Z"),
                           ("acquisition_date", "2025-04-21"), ("assets", {})):
            altered = {**scene, key: value}
            with self.assertRaises(RuntimeError):
                validate_scenes({"items": [altered]}, contract)
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            validate_scenes({"items": [scene, scene]}, contract)

    def test_daily_processing_equals_original_engine_without_radiometric_change(self):
        import geopandas as gpd
        import rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import box
        contract = copy.deepcopy(load_map_contract(ROOT))
        contract["scene_archive"].update(minimum_valid_pixels=1, minimum_valid_pixel_fraction=.1)
        fields = gpd.GeoDataFrame([{"development_field_id": "2025-1262-a-1",
                                   "municipality_code": "1262", "area_ha": .04,
                                   "geometry": box(0, 0, 20, 20)}], crs=32633)
        scenes = []
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)
            for index, day in enumerate(("2025-04-20", "2025-04-25")):
                assets = {band: {"s3_uri": f"s3://eodata/{band}.jp2", "scale": .0001 if band != "SCL" else 1.,
                                 "offset": -.1 if band != "SCL" else 0., "nodata": 0}
                          for band in [*contract["scene_archive"]["reflectance_assets"], "SCL"]}
                scene = {"item_id": f"synthetic-{index}", "acquisition_date": day, "cloud_cover": 0., "assets": assets}
                scenes.append(scene)
                for band in assets:
                    path = local_asset_path(archive, scene, band)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    values = np.full((4, 4), 4 if band == "SCL" else 500 + index * 2000, dtype=np.uint16)
                    with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1, dtype=values.dtype,
                                       crs="EPSG:32633", transform=from_origin(0, 40, 10, 10), nodata=0) as dest:
                        dest.write(values, 1)
            original = aggregate_local_scene_timeseries(fields, scenes, archive, contract)
            daily = pd.concat([aggregate_local_scene_timeseries(fields, [scene], archive, contract)
                               for scene in scenes], ignore_index=True)
            pd.testing.assert_frame_equal(original.reset_index(drop=True), daily.reset_index(drop=True))
            self.assertLess(float(daily.iloc[0].B02_p50), 0.)

    def test_runner_avoids_powershell_and_preserves_parity_failure_reporting(self):
        bat = (ROOT / "RUN_RAPSKARTAN_PARITY_DIAGNOSTIC.bat").read_text()
        self.assertNotIn("powershell", bat.lower())
        source = (ROOT / "src/102_diagnose_rapskartan_2025_parity.py").read_text()
        self.assertNotIn("download_scene_archive", source)
        self.assertNotIn("fetch_scene", source)
        self.assertIn('"status": "DIAGNOSTICS_COMPLETE"', source)
        self.assertIn('"local_engine_vs_locked": local_gate', source)


if __name__ == "__main__":
    unittest.main()
