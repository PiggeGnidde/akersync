import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rapskartan_v1_discovery_core import (
    CUTOFF_MONTH_DAYS,
    EXPECTED_HISTORY_SHA256,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG_OBJECT,
    _process_payload,
    crop_code_contract,
    cutoff_contract,
    official_lookup,
    load_official_tables,
    satellite_code_inventory,
    storage_estimate,
    summarize_ground_truth_frame,
    write_inventory_csv,
)


class RapskartanDiscoveryTests(unittest.TestCase):
    def test_upstream_freeze_constants_are_exact(self):
        self.assertEqual(UPSTREAM_TAG_OBJECT, "c7f8022f13ef1fdc4560ce906e9a10c467f15c0f")
        self.assertEqual(UPSTREAM_COMMIT, "c859a69de51a104d10f87906d4d050a34222bbb4")
        self.assertEqual(EXPECTED_HISTORY_SHA256, "05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf")

    def test_official_annual_winter_rapeseed_paths_are_year_sensitive(self):
        tables, _ = load_official_tables(ROOT)
        self.assertEqual(official_lookup(tables, 2018, "20", None), ("Raps (höst)", None))
        self.assertEqual(official_lookup(tables, 2018, "80", "20"), ("Grönfoder", None))
        self.assertEqual(official_lookup(tables, 2019, "80", "20"), ("Raps (höst)", None))
        self.assertEqual(official_lookup(tables, 2025, "20", None), ("Raps (höst)", None))
        self.assertEqual(official_lookup(tables, 2025, "80", "20"), ("Raps (höst)", None))
        self.assertEqual(official_lookup(tables, 2025, "21", None), ("Raps (vår)", None))
        self.assertEqual(official_lookup(tables, 2025, "26", None), ("Högerukaraps", None))

    def test_crop_contract_excludes_spring_and_right_turnip_rape(self):
        contract = crop_code_contract(ROOT)
        self.assertEqual(contract["status"], "PASS")
        positive_names = {row["official_name"] for row in contract["positive_mappings"]}
        excluded_names = {row["official_name"] for row in contract["explicit_non_positive_rapeseed_mappings"]}
        self.assertEqual(positive_names, {"Raps (höst)"})
        self.assertTrue({"Raps (vår)", "Högerukaraps"}.issubset(excluded_names))

    def test_2025_inventory_is_aggregate_and_same_year_resolved(self):
        frame = pd.DataFrame([
            {"current_field_id": "a", "history_year": 2024, "current_area_m2": 10_000, "dominant_crop_code_raw": "20", "dominant_crop_subcategory_raw": None, "dominant_crop_name": "Raps (höst)", "status": "SINGLE_CROP"},
            {"current_field_id": "a", "history_year": 2025, "current_area_m2": 10_000, "dominant_crop_code_raw": "80", "dominant_crop_subcategory_raw": "20", "dominant_crop_name": "Raps (höst)", "status": "SINGLE_CROP"},
            {"current_field_id": "b", "history_year": 2025, "current_area_m2": 20_000, "dominant_crop_code_raw": "21", "dominant_crop_subcategory_raw": None, "dominant_crop_name": "Raps (vår)", "status": "SINGLE_CROP"},
            {"current_field_id": "c", "history_year": 2025, "current_area_m2": 30_000, "dominant_crop_code_raw": "20", "dominant_crop_subcategory_raw": None, "dominant_crop_name": "Raps (höst)", "status": "MIXED_CROPS"},
        ])
        out = summarize_ground_truth_frame(ROOT, frame, enforce_frozen_dimensions=False)
        row = out[out.target_year == 2025].iloc[0]
        self.assertEqual(row.winter_rapeseed_fields, 1)
        self.assertEqual(row.winter_rapeseed_area_ha, 1.0)
        self.assertEqual(row.positive_raw_code_pairs, "80/20")
        self.assertNotIn("current_field_id", out.columns)

    def test_inventory_writer_rejects_row_level_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                write_inventory_csv(Path(tmp) / "bad.csv", pd.DataFrame([{"current_field_id": "secret"}]))

    def test_cutoffs_are_ordered_and_causal_contract_is_explicit(self):
        contract = cutoff_contract()
        self.assertEqual([(x["month"], x["day"]) for x in contract["cutoff_month_days"]], CUTOFF_MONTH_DAYS)
        self.assertEqual(contract["blind_year_dates"][0], "2025-03-15")
        self.assertEqual(contract["blind_year_dates"][-1], "2025-06-10")
        self.assertIn("acquisition_time <=", contract["causal_rule"])

    def test_process_smoke_is_small_preblind_and_label_independent(self):
        payload = _process_payload()
        encoded = json.dumps(payload)
        self.assertEqual(payload["output"]["width"], 32)
        self.assertEqual(payload["output"]["height"], 32)
        self.assertIn("sentinel-2-l2a", encoded)
        self.assertIn("2024-04", encoded)
        self.assertNotIn("2025", encoded)
        self.assertNotIn("crop", encoded.lower())

    def test_storage_estimate_is_bounded_and_marks_uncertainty(self):
        estimate = storage_estimate()
        self.assertEqual(estimate["status"], "PLANNING_ESTIMATE_NOT_ALLOCATION")
        self.assertEqual(estimate["recommended_source_cache_envelope_gib"], [200, 800])
        self.assertLessEqual(estimate["pilot_budget"]["source_cache_gib"][1], 10)

    def test_no_preexisting_satellite_pipeline_is_found(self):
        self.assertEqual(satellite_code_inventory(ROOT), [])


if __name__ == "__main__":
    unittest.main()
