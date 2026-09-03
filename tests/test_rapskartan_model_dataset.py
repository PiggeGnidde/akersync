from __future__ import annotations

import sys
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rapskartan_model_core import (  # noqa: E402
    SPECTRAL_NAMES, annual_geometry_path, build_development_stat_request,
    build_temporal_features, fetch_complete_statistics, load_model_contract, prior_from_overlap_records,
    select_development_year, target_period,
)


class RapskartanModelDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_model_contract(ROOT)

    def test_contract_is_preblind_and_resource_bounded(self):
        self.assertEqual(self.contract["development_years"], list(range(2018, 2025)))
        self.assertNotIn(2025, self.contract["development_years"])
        self.assertEqual(self.contract["resource_guards"]["expected_selected_field_years"], 1680)
        self.assertTrue(all(self.contract["forbidden_scope"].values()))

    def test_dataset_runner_imports_every_hash_helper_it_uses(self):
        namespace = runpy.run_path(str(SRC / "94_build_rapskartan_model_dataset.py"))
        self.assertTrue(callable(namespace["sha256_bytes"]))
        self.assertTrue(callable(namespace["sha256_file"]))

    def test_target_period_and_geometry_path_reject_blind_year(self):
        self.assertEqual(target_period(2024, self.contract), ("2024-03-01T00:00:00Z", "2024-06-11T00:00:00Z"))
        with self.assertRaisesRegex(RuntimeError, "BLIND_GUARD"):
            target_period(2025, self.contract)
        with self.assertRaisesRegex(RuntimeError, "BLIND_GUARD"):
            annual_geometry_path(Path("X:/raw"), 2025, "Lomma")

    def test_statistics_request_is_causal_and_has_no_blind_year(self):
        geometry = {"type": "Polygon", "coordinates": [[[400000, 6150000], [400100, 6150000], [400100, 6150100], [400000, 6150000]]]}
        request = build_development_stat_request(geometry, 2024, self.contract)
        self.assertEqual(request["aggregation"]["timeRange"]["to"], "2024-06-11T00:00:00Z")
        self.assertNotIn("2025", str(request))

    def test_year_sampler_is_deterministic_balanced_and_weighted(self):
        rows = []
        for group in self.contract["selection"]["groups"]:
            for index in range(80):
                rows.append({
                    "development_field_id": f"2018-{group}-{index}", "target_year": 2018,
                    "municipality_code": f"12{index % 8:02d}", "crop_group": group,
                    "area_ha": 0.5 + index, "stable_rank": f"{index:04d}",
                })
        candidates = pd.DataFrame(rows)
        first = select_development_year(candidates, 2018, self.contract)
        second = select_development_year(candidates.sample(frac=1, random_state=9), 2018, self.contract)
        self.assertEqual(len(first), 240)
        self.assertEqual(first.development_field_id.tolist(), second.development_field_id.tolist())
        self.assertEqual(set(first.groupby("crop_group").size()), {60})
        self.assertTrue(np.allclose(first["population_weight"], 80 / 60))

    def test_prior_uses_only_earlier_years(self):
        prior = prior_from_overlap_records(2024, [
            {"history_year": 2023, "official_crop_name": "Vete (höst)", "overlap_fraction": 0.9},
            {"history_year": 2022, "official_crop_name": "Raps (höst)", "overlap_fraction": 0.8},
            {"history_year": 2021, "official_crop_name": "Havre", "overlap_fraction": 0.7},
        ])
        self.assertEqual(prior["prior_raps_lag1"], 0)
        self.assertEqual(prior["prior_raps_lag2"], 1)
        self.assertEqual(prior["years_since_raps"], 2)
        self.assertAlmostEqual(prior["raps_frequency"], 1 / 3)
        with self.assertRaisesRegex(RuntimeError, "same-year or future"):
            prior_from_overlap_records(2024, [{"history_year": 2024, "official_crop_name": "Raps (höst)", "overlap_fraction": 1}])

    def test_temporal_features_never_use_observation_after_cutoff(self):
        dates = ["2024-03-10", "2024-03-14", "2024-03-20"]
        rows = []
        for index, acquisition in enumerate(dates):
            row = {
                "development_field_id": "f1", "target_year": 2024,
                "acquisition_date": acquisition, "data_quality_status": "VALID",
                "valid_pixel_fraction": 0.8,
            }
            for name in SPECTRAL_NAMES:
                row[f"{name}_p10"] = 0.1 + index
                row[f"{name}_p50"] = 0.2 + index
                row[f"{name}_p90"] = 0.3 + index
            rows.append(row)
        selection = pd.DataFrame([{
            "development_field_id": "f1", "target_year": 2024,
            "municipality_code": "1262", "geographic_fold": 0,
        }])
        features = build_temporal_features(pd.DataFrame(rows), selection, self.contract)
        march15 = features[features["cutoff_date"] == "2024-03-15"].iloc[0]
        self.assertEqual(march15["latest_used_acquisition"], "2024-03-14")
        self.assertEqual(march15["valid_obs_count"], 2)
        self.assertEqual(march15["NDVI_last"], 1.2)
        self.assertLessEqual(march15["latest_used_acquisition"], march15["cutoff_date"])

    def test_no_data_is_explicit_and_has_no_spectral_values(self):
        row = {
            "development_field_id": "f1", "target_year": 2024,
            "acquisition_date": "2024-03-10", "data_quality_status": "VALID",
            "valid_pixel_fraction": 0.8,
        }
        for name in SPECTRAL_NAMES:
            row[f"{name}_p10"] = 0.1
            row[f"{name}_p50"] = 0.2
            row[f"{name}_p90"] = 0.3
        selection = pd.DataFrame([{
            "development_field_id": "f1", "target_year": 2024,
            "municipality_code": "1262", "geographic_fold": 0,
        }])
        features = build_temporal_features(pd.DataFrame([row]), selection, self.contract)
        first = features.iloc[0]
        self.assertEqual(first["data_quality_status"], "NO_DATA")
        self.assertTrue(pd.isna(first["NDVI_last"]))

    def test_partial_statistics_response_is_evicted_and_retried(self):
        class FakeCache:
            offline = False

            def __init__(self, root):
                self.root = root
                self.calls = 0

            def _paths(self, key, suffix):
                endings = (".request.json", f".response{suffix}", ".meta.json")
                return tuple(self.root / f"{key}{ending}" for ending in endings)

            def fetch(self, endpoint, payload, *, response_suffix, accept):
                self.calls += 1
                status = "PARTIAL" if self.calls == 1 else "OK"
                body = (json.dumps({"status": status, "data": []}) + "\n").encode("utf-8")
                return SimpleNamespace(body=body)

        with tempfile.TemporaryDirectory() as temporary:
            cache = FakeCache(Path(temporary))
            result = fetch_complete_statistics(cache, {"test": True}, field_id="f1", retry_delay_seconds=0)
        self.assertEqual(json.loads(result.body)["status"], "OK")
        self.assertEqual(cache.calls, 2)


if __name__ == "__main__":
    unittest.main()
