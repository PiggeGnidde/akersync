from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("pixel_cases", ROOT / "src/103_export_rapskartan_pixel_cases.py")
pixel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pixel)


def fixture(archive):
    contract = copy.deepcopy(pixel.load_map_contract(ROOT))
    contract["scene_archive"].update(minimum_valid_pixels=1, minimum_valid_pixel_fraction=.1)
    field = gpd.GeoDataFrame([{"development_field_id": "test-field", "municipality_code": "1262",
                               "area_ha": .12, "geometry": box(221.3, 211.2, 250.7, 250.4)}], crs=32633)
    scenes = []
    for index, day in enumerate(("2025-04-20", "2025-04-25")):
        scene = {"item_id": f"test-{index}", "acquisition_date": day, "cloud_cover": 0., "assets": {}}
        for band in [*contract["scene_archive"]["reflectance_assets"], "SCL"]:
            scene["assets"][band] = {"s3_uri": f"s3://eodata/test/{band}.jp2", "scale": 1. if band == "SCL" else .0001,
                                      "offset": 0. if band == "SCL" else -.1, "nodata": 0}
            path = pixel.local_asset_path(archive, scene, band)
            path.parent.mkdir(parents=True, exist_ok=True)
            values = np.full((64, 64), 4, dtype="uint16") if band == "SCL" else (np.arange(4096).reshape(64, 64)+500+index*100).astype("uint16")
            resolution = 10 if band in ("B02", "B03", "B04", "B08") else 20
            with rasterio.open(path, "w", driver="GTiff", width=64, height=64, count=1, dtype="uint16",
                               crs="EPSG:32633", transform=from_origin(0, 64*resolution, resolution, resolution), nodata=0) as target:
                target.write(values, 1)
            scene["assets"][band].update(bytes=path.stat().st_size, checksum="1220"+pixel.sha256_file(path))
        scenes.append(scene)
    return contract, field, scenes


class PixelCaseTests(unittest.TestCase):
    def test_main_creates_recursive_zip_with_verified_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            argv = ["pixel", "--output-dir", str(root / "output")]
            for name in ("diagnostic-dir", "stop-d-dir", "product-dir", "scene-archive"):
                argv.extend([f"--{name}", str(root / name)])
            def completed(args, out):
                (out / "case_01").mkdir()
                (out / "case_01/native.tif").write_bytes(b"test-crop")
                pixel.write_json(out / "pixel_export_summary.json", {"status": "PIXEL_EXPORT_COMPLETE"})
            with patch.object(sys, "argv", argv), patch.object(sys, "addaudithook"), patch.object(pixel, "run", side_effect=completed):
                self.assertEqual(pixel.main(), 0)
            packages = list((root / "output").glob("*.zip"))
            self.assertEqual(len(packages), 1)
            with zipfile.ZipFile(packages[0]) as package:
                self.assertIsNone(package.testzip())
                manifest = json.loads(package.read("pixel_export_manifest.json"))
                self.assertIn("case_01/native.tif", package.namelist())
                for item in manifest["artifacts"]:
                    self.assertEqual(hashlib.sha256(package.read(item["path"])).hexdigest(), item["sha256"])

    def test_selection_is_bounded_deterministic_and_label_free(self):
        fields = pd.DataFrame({"development_field_id": [f"f{i}" for i in range(7)], "area_ha": range(1, 8)})
        rows = []
        for i in range(7):
            for day in ("2025-04-20", "2025-04-25"):
                rows.append({"development_field_id": f"f{i}", "acquisition_date": day,
                             "valid_pixels_local": 50, "valid_pixels_reference": 60,
                             "B08_p50_delta": .01*i, "valid_pixel_fraction_delta": .01*(6-i)})
        obs = pd.DataFrame(rows)
        a = pixel.select_cases(obs, fields)
        b = pixel.select_cases(obs.sample(frac=1, random_state=22), fields.sample(frac=1, random_state=9))
        pd.testing.assert_frame_equal(a, b)
        self.assertLessEqual(len(a), 5)
        self.assertEqual(a.iloc[0].development_field_id, "f0")
        self.assertEqual(a.iloc[1].development_field_id, "f3")
        self.assertEqual(a.iloc[2].development_field_id, "f6")
        self.assertFalse(a.duplicated(["development_field_id", "acquisition_date"]).any())
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            pixel.select_cases(pd.concat([obs, obs]), fields)

    def test_native_export_preserves_pixels_grid_dtype_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _, field, scenes = fixture(root / "source")
            source = pixel.local_asset_path(root / "source", scenes[0], "B02")
            before = pixel.sha256_file(source)
            destination = root / "output/crop.tif"
            info = pixel.export_band(source, destination, field.geometry.iloc[0].bounds, field.crs, [0])
            col, row, width, height = info["window"]
            with rasterio.open(source) as original, rasterio.open(destination) as crop:
                expected = original.read(1)[row:row+height, col:col+width]
                np.testing.assert_array_equal(crop.read(1), expected)
                self.assertEqual(crop.transform, original.window_transform(rasterio.windows.Window(col, row, width, height)))
                self.assertEqual(crop.dtypes, original.dtypes)
                self.assertEqual(crop.nodata, original.nodata)
                self.assertEqual(info["native_array_sha256"], hashlib.sha256(expected.tobytes()).hexdigest())
            self.assertEqual(pixel.sha256_file(source), before)
            with self.assertRaisesRegex(RuntimeError, "never overwrites"):
                pixel.export_band(source, destination, field.geometry.iloc[0].bounds, field.crs, [0])

    def test_crop_guards_prevent_large_allocation_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _, field, scenes = fixture(root / "source")
            source = pixel.local_asset_path(root / "source", scenes[0], "B02")
            with patch.object(pixel, "MAX_PIXELS_PER_BAND", 1):
                with rasterio.open(source) as dataset:
                    with self.assertRaisesRegex(RuntimeError, "bounded export guard"):
                        pixel.native_window(dataset, field.geometry.iloc[0].bounds, field.crs)
            destination = root / "crop.tif"
            with self.assertRaisesRegex(RuntimeError, "256 MiB"):
                pixel.export_band(source, destination, field.geometry.iloc[0].bounds, field.crs, [pixel.MAX_RAW_BYTES])
            self.assertFalse(destination.exists())
            with rasterio.open(source) as dataset:
                with self.assertRaisesRegex(RuntimeError, "no intersection"):
                    pixel.native_window(dataset, (10000, 10000, 11000, 11000), field.crs)

    def test_offline_export_replays_native_crops_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            archive, out = root / "source", root / "output"
            out.mkdir()
            contract, field, scenes = fixture(archive)
            original = pixel.aggregate_local_scene_timeseries(field, scenes, archive, contract)
            cases = pd.DataFrame({"case_id": ["case_01", "case_02"], "development_field_id": ["test-field"]*2,
                                  "acquisition_date": ["2025-04-20", "2025-04-25"]})
            source_hashes = {str(p): pixel.sha256_file(p) for p in archive.rglob("*.jp2")}
            summary = pixel.export_cases(out, cases, field, scenes, archive, contract, original, original)
            self.assertEqual(summary["status"], "PIXEL_EXPORT_COMPLETE")
            self.assertEqual(summary["exported_bands"], 22)
            self.assertTrue(summary["crop_replay_counts_exact"])
            self.assertTrue(summary["crop_replay_quality_agrees"])
            self.assertTrue(summary["crop_replay_matches_local_within_1e_6"])
            for path, before in source_hashes.items():
                self.assertEqual(pixel.sha256_file(Path(path)), before)
            metadata = json.loads((out / "native_asset_provenance.json").read_text())
            for asset in metadata["assets"]:
                self.assertEqual(pixel.sha256_file(out / asset["path"]), asset["sha256"])
                self.assertIn("source_asset", asset)
            with rasterio.open(out / "case_01/geometry_masks.tif") as masks:
                self.assertEqual(masks.count, 2)
                self.assertGreaterEqual(int(masks.read(2).sum()), int(masks.read(1).sum()))

    def test_bad_source_is_not_repaired_or_downloaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary).resolve()
            _, _, scenes = fixture(archive)
            path = pixel.local_asset_path(archive, scenes[0], "B02")
            path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "size mismatch"):
                pixel.source_path(archive, scenes[0], "B02")
            self.assertEqual(path.read_bytes(), b"corrupt")
            missing = copy.deepcopy(scenes[0]); missing["item_id"] = "absent"
            with self.assertRaisesRegex(RuntimeError, "no download"):
                pixel.source_path(archive, missing, "SCL")

    def test_diagnostic_manifest_requires_complete_verified_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            names = ["diagnostic_summary.json", "diagnostic_inputs.json", "selected_fields.csv",
                     "observation_comparison.csv", "local_timeseries.csv", "reference_timeseries.csv"]
            for name in names:
                (root / name).write_text('{"status":"DIAGNOSTICS_COMPLETE"}')
            manifest = {"status": "DIAGNOSTICS_COMPLETE", "artifacts": pixel.artifact_records(root, names)}
            pixel.write_json(root / "diagnostic_manifest.json", manifest)
            self.assertEqual(pixel.verify_diagnostic(root)["status"], "DIAGNOSTICS_COMPLETE")
            (root / names[-1]).write_text("changed")
            with self.assertRaisesRegex(RuntimeError, "artifact mismatch"):
                pixel.verify_diagnostic(root)

    def test_bat_has_no_powershell_or_full_map_call(self):
        text = (ROOT / "RUN_RAPSKARTAN_PIXEL_CASES.bat").read_text()
        self.assertNotIn("powershell", text.lower())
        self.assertNotIn("100_generate", text)
        self.assertIn("103_export_rapskartan_pixel_cases.py", text)


if __name__ == "__main__":
    unittest.main()
