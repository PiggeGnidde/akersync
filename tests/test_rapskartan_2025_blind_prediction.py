from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rapskartan_blind_prediction_core import (  # noqa: E402
    SAFE_GEOMETRY_COLUMNS, blind_prior_from_overlap_records, build_blind_stat_request,
    build_blind_temporal_features, load_blind_contract, make_predictions,
    select_blind_fields, validate_safe_projection_columns,
)
from rapskartan_model_core import (  # noqa: E402
    SPECTRAL_NAMES, build_development_stat_request, build_temporal_features,
    load_model_contract, temporal_feature_columns,
)


def runtime_contract() -> dict:
    blind = load_blind_contract(ROOT)
    development = load_model_contract(ROOT)
    blind["frozen_feature_contract"] = {
        "temporal": development["temporal"], "sentinel2": development["sentinel2"],
        "cloud_mask": development["cloud_mask"], "statistics": development["statistics"],
        "prior_features": development["prior"]["features"],
        "satellite_features": temporal_feature_columns(development),
        "model_arms": development["model"]["arms"],
    }
    blind["frozen_feature_contract_version"] = "rapskartan-feature-contract-v1"
    blind["frozen_model_contract_id"] = "test-model-contract-sha256"
    return blind


def observation(field_id: str, year: int, acquisition: str, value: float) -> dict:
    row = {"development_field_id": field_id, "target_year": year, "acquisition_date": acquisition, "data_quality_status": "VALID", "valid_pixel_fraction": 0.8}
    for name in SPECTRAL_NAMES:
        row[f"{name}_p10"] = value - 0.1
        row[f"{name}_p50"] = value
        row[f"{name}_p90"] = value + 0.1
    return row


class FakeEstimator:
    def predict_proba(self, frame):
        p = np.full(len(frame), 0.6, dtype=float)
        return np.column_stack([1 - p, p])


class FakeCalibrator:
    def predict(self, probability):
        return np.asarray(probability, dtype=float)


class RapskartanBlindPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = runtime_contract()
        cls.development = load_model_contract(ROOT)

    def test_contract_is_bounded_and_preserves_later_phase_guards(self):
        self.assertEqual(self.contract["target_year"], 2025)
        self.assertEqual(self.contract["selection"]["maximum_selected_fields"], 3300)
        self.assertEqual(self.contract["resource_guards"]["maximum_authenticated_api_requests"], 3400)
        self.assertTrue(self.contract["scope"]["prediction_before_label_join"])
        self.assertFalse(self.contract["scope"]["full_skane_prediction"])
        self.assertFalse(self.contract["scope"]["web"])

    def test_safe_geometry_projection_rejects_any_extra_attribute(self):
        with self.assertRaisesRegex(RuntimeError, "BLIND_LABEL_GATE"):
            validate_safe_projection_columns([*SAFE_GEOMETRY_COLUMNS, "geometry", "unsafe_crop"])
        self.assertEqual(SAFE_GEOMETRY_COLUMNS, ("arslager", "blockid", "skiftesbeteckning", "region_kod"))

    def test_blind_selection_is_deterministic_stratified_and_weighted(self):
        municipalities = json.loads((ROOT / "config/akerminne_skane_municipalities.json").read_text(encoding="utf-8"))["municipalities"]
        rows = []
        for municipality in municipalities:
            for index in range(120):
                rows.append({
                    "development_field_id": f"2025-{municipality['code']}-{index}",
                    "current_field_id": f"{municipality['code']}|{index}", "target_year": 2025,
                    "municipality_code": municipality["code"], "area_ha": 0.5 + index,
                    "geographic_fold": index % 5,
                })
        candidates = pd.DataFrame(rows)
        first = select_blind_fields(candidates, self.contract)
        second = select_blind_fields(candidates.sample(frac=1, random_state=8), self.contract)
        self.assertEqual(len(first), 3300)
        self.assertEqual(first.development_field_id.tolist(), second.development_field_id.tolist())
        self.assertEqual(set(first.groupby("municipality_code").size()), {100})
        self.assertEqual(set(first.groupby(["municipality_code", "area_stratum"]).size()), {25})
        self.assertTrue(np.allclose(first["population_weight"], 30 / 25))

    def test_blind_request_is_frozen_request_with_only_year_changed(self):
        geometry = {"type": "Polygon", "coordinates": [[[400000, 6150000], [400100, 6150000], [400100, 6150100], [400000, 6150000]]]}
        development = build_development_stat_request(geometry, 2024, self.development)
        blind = build_blind_stat_request(geometry, self.contract)
        self.assertEqual(json.dumps(blind, sort_keys=True), json.dumps(development, sort_keys=True).replace("2024", "2025"))

    def test_blind_prior_uses_only_2021_through_2024(self):
        result = blind_prior_from_overlap_records([
            {"history_year": 2024, "official_crop_name": "Vete (höst)", "overlap_fraction": 0.9},
            {"history_year": 2023, "official_crop_name": "Raps (höst)", "overlap_fraction": 0.8},
            {"history_year": 2020, "official_crop_name": "Raps (höst)", "overlap_fraction": 1.0},
        ])
        self.assertEqual(result["prior_raps_lag1"], 0)
        self.assertEqual(result["prior_raps_lag2"], 1)
        self.assertEqual(result["years_since_raps"], 2)
        with self.assertRaisesRegex(RuntimeError, "same-year or future"):
            blind_prior_from_overlap_records([{"history_year": 2025, "official_crop_name": "Raps (höst)", "overlap_fraction": 1}])

    def test_blind_temporal_features_equal_frozen_development_algorithm(self):
        old_ts = pd.DataFrame([observation("f", 2024, "2024-03-10", 0.2), observation("f", 2024, "2024-03-14", 0.4), observation("f", 2024, "2024-04-02", 0.8)])
        new_ts = old_ts.copy()
        new_ts["target_year"] = 2025
        new_ts["acquisition_date"] = new_ts["acquisition_date"].str.replace("2024", "2025")
        old_sel = pd.DataFrame([{"development_field_id": "f", "target_year": 2024, "municipality_code": "1262", "geographic_fold": 1}])
        new_sel = old_sel.copy(); new_sel["target_year"] = 2025
        old = build_temporal_features(old_ts, old_sel, self.development)
        new = build_blind_temporal_features(new_ts, new_sel, self.contract)
        columns = [column for column in temporal_feature_columns(self.development) if not column.endswith("_max_doy")] + ["data_quality_status", "source_observation_rows"]
        pd.testing.assert_frame_equal(old[columns], new[columns], check_dtype=False)
        self.assertEqual(new.loc[new["cutoff_date"] == "2025-03-15", "NDVI_max_doy"].iloc[0], 73)
        self.assertTrue((pd.to_datetime(new.latest_used_acquisition.dropna()) <= pd.to_datetime(new.loc[new.latest_used_acquisition.notna(), "cutoff_date"])).all())

    def test_prediction_output_has_locked_thresholds_and_no_label(self):
        prior_columns = self.contract["frozen_feature_contract"]["prior_features"]
        satellite_columns = self.contract["frozen_feature_contract"]["satellite_features"]
        selection = pd.DataFrame([{"development_field_id": "f", "current_field_id": "b|s", "target_year": 2025, "municipality_code": "1262", "area_ha": 2.0, "area_stratum": 1, "population_weight": 10.0, "geographic_fold": 0}])
        prior = selection[["development_field_id", "current_field_id", "target_year", "municipality_code"]].copy()
        for column in prior_columns:
            prior[column] = 0.0
        temporal_rows = []
        for cutoff in self.contract["frozen_feature_contract"]["temporal"]["cutoff_month_days"]:
            row = {"development_field_id": "f", "target_year": 2025, "municipality_code": "1262", "geographic_fold": 0, "cutoff_date": f"2025-{cutoff}", "latest_used_acquisition": f"2025-{cutoff}", "data_quality_status": "USABLE", "valid_obs_count": 2, "days_since_last_obs": 0, "mean_valid_pixel_fraction": 0.8}
            for column in satellite_columns:
                row.setdefault(column, 0.1)
            temporal_rows.append(row)
        temporal = pd.DataFrame(temporal_rows)
        records = []
        for cutoff in self.contract["frozen_feature_contract"]["temporal"]["cutoff_month_days"]:
            for arm in self.contract["frozen_feature_contract"]["model_arms"]:
                records.append({"model_arm": arm, "cutoff_month_day": cutoff, "precision_95": {"available": True, "threshold": 0.55}, "precision_90": {"available": True, "threshold": 0.45}})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "threshold_contract_v1.json").write_text(json.dumps({"records": records}), encoding="utf-8")
            def load_bundle(path):
                name = Path(path).stem
                arm = next(value for value in self.contract["frozen_feature_contract"]["model_arms"] if name.startswith(value.lower()))
                cutoff = name.rsplit("_", 1)[1]
                cutoff = cutoff[:2] + "-" + cutoff[2:]
                features = prior_columns if arm == "PRIOR_ONLY" else satellite_columns if arm == "SATELLITE_ONLY" else prior_columns + satellite_columns
                return {"model_arm": arm, "cutoff_month_day": cutoff, "feature_columns": features, "training_years": list(range(2018, 2025)), "model_family": "TEST", "calibration_method": "TEST", "estimator": FakeEstimator(), "calibrator": FakeCalibrator()}
            with patch("rapskartan_blind_prediction_core.joblib.load", side_effect=load_bundle):
                result = make_predictions(selection, prior, temporal, root, self.contract)
        self.assertEqual(len(result), 27)
        self.assertTrue(result["predicted_at_frozen_p95"].all())
        self.assertFalse({"is_winter_rapeseed", "official_crop_name", "crop_code_raw"} & set(result.columns))
        self.assertTrue({
            "field_id", "valid_pixel_fraction", "prior_raps_probability", "satellite_score",
            "p_raps", "confidence_status", "model_version", "feature_contract_version",
            "source_manifest_id",
        }.issubset(result.columns))
        self.assertTrue((result["field_id"] == result["current_field_id"]).all())
        self.assertTrue(np.allclose(result["p_raps"], result["calibrated_probability"]))
        self.assertEqual(set(result["confidence_status"]), {"MEDIUM"})

    def test_prediction_module_has_no_ground_truth_csv_reader(self):
        source = (SRC / "rapskartan_blind_prediction_core.py").read_text(encoding="utf-8")
        runner = (SRC / "97_generate_rapskartan_2025_blind_predictions.py").read_text(encoding="utf-8")
        self.assertNotIn("pd.read_csv", source)
        self.assertNotIn("--ground-truth", runner.lower())


if __name__ == "__main__":
    unittest.main()
