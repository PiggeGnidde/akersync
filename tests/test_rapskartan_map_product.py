from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rapskartan_map_product_core import (  # noqa: E402
    add_outside_scope_rows, aggregate_local_scene_timeseries, apply_product_memory_rule,
    compare_parity_predictions, field_grid, load_map_contract, local_asset_path,
    select_parity_field_ids, validate_map_contract,
)


def prediction_row(field: str, cutoff: str, probability: float | None, detected: bool, *, municipality: str = "1262") -> dict:
    usable = probability is not None
    return {
        "development_field_id": f"2025-{municipality}-{field}",
        "field_id": field,
        "current_field_id": field,
        "municipality_code": municipality,
        "target_year": 2025,
        "area_ha": 2.0,
        "cutoff_date": cutoff,
        "latest_used_acquisition": cutoff if usable else None,
        "data_quality_status": "USABLE" if usable else "NO_DATA",
        "valid_obs_count": 3 if usable else np.nan,
        "days_since_last_obs": 0 if usable else np.nan,
        "valid_pixel_fraction": 0.8 if usable else np.nan,
        "calibrated_probability": probability,
        "frozen_p95_threshold": 0.9,
        "predicted_at_frozen_p95": detected,
        "model_arm": "SATELLITE_ONLY",
        "model_version": "frozen",
        "feature_contract_version": "frozen",
        "source_manifest_id": "frozen",
    }


class RapskartanMapProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_map_contract(ROOT)

    def test_contract_authorizes_only_full_historical_product(self):
        self.assertTrue(self.contract["scope"]["full_historical_2025_map_product"])
        self.assertFalse(self.contract["scope"]["ground_truth_in_product"])
        for key in ["post_blind_model_retuning", "threshold_retuning", "sentinel1", "web", "deployment", "tag", "merge"]:
            self.assertFalse(self.contract["scope"][key])
        self.assertEqual(self.contract["product_rule"]["rule_class"], "POST_BLIND_PRODUCT_RULE")
        self.assertTrue(self.contract["product_rule"]["blind_benchmark_is_immutable"])

    def test_map_product_runner_passes_redirection_to_powershell_unescaped(self):
        runner = (ROOT / "RUN_RAPSKARTAN_2025_MAP_PRODUCT.bat").read_text(encoding="utf-8")
        self.assertIn(" 2>&1 | Tee-Object ", runner)
        self.assertNotIn("2^>^&1 ^|", runner)

    def test_contract_rejects_changed_scl_or_threshold_scope(self):
        changed = copy.deepcopy(self.contract)
        changed["scene_archive"]["valid_scl_codes"] = [4, 5]
        with self.assertRaisesRegex(RuntimeError, "SCL"):
            validate_map_contract(changed)
        changed = copy.deepcopy(self.contract)
        changed["scope"]["threshold_retuning"] = True
        with self.assertRaisesRegex(RuntimeError, "forbidden scope"):
            validate_map_contract(changed)

    def test_memory_rule_never_forgets_an_earlier_secure_detection(self):
        rows = [
            prediction_row("a", "2025-04-20", 0.91, True),
            prediction_row("a", "2025-04-30", 0.40, False),
            prediction_row("a", "2025-05-10", None, False),
            prediction_row("b", "2025-04-20", 0.60, False),
            prediction_row("b", "2025-04-30", 0.20, False),
            prediction_row("b", "2025-05-10", None, False),
        ]
        result = apply_product_memory_rule(pd.DataFrame(rows), self.contract)
        a = result[result["field_id"] == "a"].sort_values("cutoff_date")
        self.assertEqual(a["confidence_status"].tolist(), ["HIGH_CONFIDENCE"] * 3)
        self.assertEqual(a["remembered_high_confidence"].tolist(), [True, True, True])
        self.assertEqual(set(a["first_high_confidence_date"]), {"2025-04-20"})
        b = result[result["field_id"] == "b"].sort_values("cutoff_date")
        self.assertEqual(b["confidence_status"].tolist(), ["POSSIBLE", "LOW", "NO_DATA"])
        self.assertNotIn("is_winter_rapeseed", result.columns)
        self.assertFalse(result["ground_truth_present"].any())

    def test_memory_rule_ignores_non_primary_arms(self):
        rows = [prediction_row("a", "2025-04-20", 0.91, True)]
        other = dict(rows[0]); other["model_arm"] = "PRIOR_PLUS_SATELLITE"
        result = apply_product_memory_rule(pd.DataFrame([*rows, other]), self.contract)
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result["model_arm"]), {"SATELLITE_ONLY"})

    def test_full_product_keeps_outside_area_fields_as_explicit_no_data(self):
        rows = [
            prediction_row("a", "2025-04-20", 0.91, True),
            prediction_row("a", "2025-04-30", 0.40, False),
        ]
        product = apply_product_memory_rule(pd.DataFrame(rows), self.contract)
        fields = pd.DataFrame([
            {"current_field_id": "a", "municipality_code": "1262", "area_ha": 2.0, "model_scope_status": "MODEL_ELIGIBLE"},
            {"current_field_id": "tiny", "municipality_code": "1262", "area_ha": 0.1, "model_scope_status": "OUTSIDE_AREA_SCOPE"},
        ])
        contract = dict(self.contract)
        contract.update({
            "model_version": "frozen", "frozen_feature_contract_version": "frozen",
            "frozen_model_contract_id": "frozen",
        })
        result = add_outside_scope_rows(product, fields, contract)
        self.assertEqual(len(result), 4)
        tiny = result[result["field_id"] == "tiny"]
        self.assertEqual(set(tiny["confidence_status"]), {"NO_DATA"})
        self.assertEqual(set(tiny["data_quality_status"]), {"OUTSIDE_MODEL_SCOPE"})
        self.assertTrue(tiny["p_raps"].isna().all())
        self.assertFalse(tiny["ground_truth_present"].any())

    def test_parity_gate_requires_every_frozen_p95_decision(self):
        locked = pd.DataFrame([
            prediction_row("a", "2025-04-20", 0.91, True),
            prediction_row("b", "2025-04-20", 0.20, False),
        ])
        local = locked.copy()
        local["calibrated_probability"] += 0.001
        _, summary = compare_parity_predictions(local, locked, self.contract)
        self.assertEqual(summary["status"], "PASS")
        local.loc[0, "predicted_at_frozen_p95"] = False
        _, summary = compare_parity_predictions(local, locked, self.contract)
        self.assertEqual(summary["status"], "FAIL")
        self.assertLess(summary["decision_agreement"], 1.0)

    def test_parity_selection_is_deterministic_and_bounded(self):
        municipalities = [f"{1200 + index}" for index in range(33)]
        selection_rows, prediction_rows = [], []
        for code in municipalities:
            for number in range(10):
                field = f"{code}|{number}"
                row = prediction_row(field, "2025-04-30", 0.88 + number / 1000, number == 9, municipality=code)
                selection_rows.append({
                    "development_field_id": row["development_field_id"],
                    "current_field_id": field,
                    "municipality_code": code,
                })
                prediction_rows.append(row)
        selection = pd.DataFrame(selection_rows)
        predictions = pd.DataFrame(prediction_rows)
        first = select_parity_field_ids(selection, predictions, self.contract)
        second = select_parity_field_ids(selection.sample(frac=1, random_state=4), predictions.sample(frac=1, random_state=5), self.contract)
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), self.contract["parity_gate"]["minimum_fields"])
        self.assertLessEqual(len(first), self.contract["parity_gate"]["maximum_fields"])

    def test_field_grid_matches_locked_statistics_api_sample_counts(self):
        # Exact projected bounds/sampleCount pairs observed in the immutable
        # blind return.  The Statistics API rounds each bounds dimension.
        examples = [
            ((0.0, 0.0, 537.3, 573.89), 54, 57, 3078),
            ((0.0, 0.0, 220.33, 644.66), 22, 64, 1408),
            ((0.0, 0.0, 657.87, 639.05), 66, 64, 4224),
            ((0.0, 0.0, 130.49, 159.93), 13, 16, 208),
        ]
        for bounds, expected_width, expected_height, expected_count in examples:
            transform, width, height = field_grid(bounds, 10)
            self.assertEqual((width, height, width * height), (expected_width, expected_height, expected_count))
            self.assertAlmostEqual(transform.a * width, bounds[2] - bounds[0])
            self.assertAlmostEqual(-transform.e * height, bounds[3] - bounds[1])

    def test_local_scene_aggregation_counts_full_bounds_and_masks_polygon(self):
        import geopandas as gpd
        import rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import Polygon

        contract = copy.deepcopy(self.contract)
        contract["scene_archive"]["minimum_valid_pixels"] = 1
        contract["scene_archive"]["minimum_valid_pixel_fraction"] = 0.1
        assets = {
            band: {
                "s3_uri": f"s3://eodata/test/{band}.jp2", "bytes": 0,
                "checksum": None, "scale": 0.0001 if band != "SCL" else 1.0,
                "offset": -0.1 if band != "SCL" else 0.0, "nodata": 0,
            }
            for band in [*contract["scene_archive"]["reflectance_assets"], "SCL"]
        }
        scene = {
            "item_id": "synthetic", "acquisition_date": "2025-04-20",
            "cloud_cover": 0.0, "assets": assets,
        }
        field = gpd.GeoDataFrame([{
            "development_field_id": "2025-1262-a-1", "municipality_code": "1262",
            "area_ha": 0.02,
            "geometry": Polygon([(0, 0), (20, 0), (0, 20)]),
        }], crs=32633)
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)
            for band in assets:
                path = local_asset_path(archive, scene, band)
                path.parent.mkdir(parents=True, exist_ok=True)
                values = np.full((4, 4), 4 if band == "SCL" else 5000, dtype=np.uint16)
                with rasterio.open(
                    path, "w", driver="GTiff", width=4, height=4, count=1,
                    dtype=values.dtype, crs="EPSG:32633", transform=from_origin(0, 40, 10, 10),
                    nodata=0,
                ) as destination:
                    destination.write(values, 1)
            result = aggregate_local_scene_timeseries(field, [scene], archive, contract)
        self.assertEqual(len(result), 1)
        self.assertEqual(int(result.iloc[0]["sample_pixels"]), 4)
        self.assertGreater(int(result.iloc[0]["valid_pixels"]), 0)
        self.assertLess(int(result.iloc[0]["valid_pixels"]), 4)
        self.assertEqual(result.iloc[0]["data_quality_status"], "VALID")


if __name__ == "__main__":
    unittest.main()
