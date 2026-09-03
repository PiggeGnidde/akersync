from __future__ import annotations

import json
import importlib.util
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

from rapskartan_blind_evaluation_core import (  # noqa: E402
    LABEL_COLUMNS, data_quality_breakdown, evaluate_predictions, join_sample_ground_truth,
    load_ground_truth, open_prediction_lock,
)
from rapskartan_s2_pilot_core import sha256_file  # noqa: E402

VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_rapskartan_2025_blind", SRC / "99_verify_rapskartan_2025_blind.py"
)
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


def selection() -> pd.DataFrame:
    return pd.DataFrame([
        {"development_field_id": f"d{i}", "current_field_id": f"f{i}", "target_year": 2025, "municipality_code": "1262", "area_ha": float(i + 1), "area_stratum": i, "eligible_stratum_fields": 1, "selected_stratum_fields": 1, "population_weight": 1.0, "geographic_fold": 0, "geometry_source": "safe.gpkg"}
        for i in range(4)
    ])


def truth() -> pd.DataFrame:
    return pd.DataFrame([
        {"current_field_id": "f0", "current_area_m2": 10000, "dominant_crop_code_raw": 20, "dominant_crop_subcategory_raw": np.nan, "dominant_crop_name": "Raps (höst)", "status": "SINGLE_CROP", "is_winter_rapeseed": 1},
        {"current_field_id": "f1", "current_area_m2": 20000, "dominant_crop_code_raw": 20, "dominant_crop_subcategory_raw": np.nan, "dominant_crop_name": "Raps (höst)", "status": "SINGLE_CROP", "is_winter_rapeseed": 1},
        {"current_field_id": "f2", "current_area_m2": 30000, "dominant_crop_code_raw": 4, "dominant_crop_subcategory_raw": np.nan, "dominant_crop_name": "Vete (höst)", "status": "SINGLE_CROP", "is_winter_rapeseed": 0},
        {"current_field_id": "f3", "current_area_m2": 40000, "dominant_crop_code_raw": 3, "dominant_crop_subcategory_raw": np.nan, "dominant_crop_name": "Korn (vår)", "status": "SINGLE_CROP", "is_winter_rapeseed": 0},
    ])


def predictions() -> pd.DataFrame:
    probabilities = [0.9, np.nan, 0.8, 0.1]
    rows = []
    for i, probability in enumerate(probabilities):
        rows.append({
            "development_field_id": f"d{i}", "current_field_id": f"f{i}", "target_year": 2025,
            "municipality_code": "1262", "area_ha": float(i + 1), "area_stratum": i,
            "population_weight": 1.0, "cutoff_date": "2025-06-10", "latest_used_acquisition": "2025-06-08" if np.isfinite(probability) else np.nan,
            "data_quality_status": "USABLE" if np.isfinite(probability) else "NO_DATA",
            "valid_obs_count": 5 if np.isfinite(probability) else np.nan, "days_since_last_obs": 2 if np.isfinite(probability) else np.nan,
            "mean_valid_pixel_fraction": 0.8 if np.isfinite(probability) else np.nan,
            "model_arm": "SATELLITE_ONLY", "model_family": "TEST", "calibration": "TEST",
            "raw_probability": probability, "calibrated_probability": probability,
            "frozen_p95_available": True, "frozen_p95_threshold": 0.85,
            "predicted_at_frozen_p95": i == 0, "frozen_p90_available": True,
            "frozen_p90_threshold": 0.75, "predicted_at_frozen_p90": i in (0, 2),
            "predicted_at_0_5": i in (0, 2), "predicted_at_0_8": i in (0, 2),
            "predicted_at_0_9": i == 0, "predicted_at_0_95": False,
        })
    return pd.DataFrame(rows)


class RapskartanBlindEvaluationTests(unittest.TestCase):
    def test_probability_recomputation_allows_only_decimal_roundtrip_noise(self):
        locked = pd.DataFrame({
            "raw_probability": [0.123456789, np.nan],
            "calibrated_probability": [0.987654321, np.nan],
        })
        recomputed = locked.copy()
        recomputed.loc[0, "raw_probability"] += 5e-7
        self.assertAlmostEqual(VERIFY.verify_probability_recomputation(recomputed, locked), 5e-7)
        recomputed.loc[0, "raw_probability"] += 2e-6
        with self.assertRaisesRegex(RuntimeError, "max_abs_delta"):
            VERIFY.verify_probability_recomputation(recomputed, locked)
        changed_missingness = locked.copy()
        changed_missingness.loc[1, "raw_probability"] = 0.1
        with self.assertRaisesRegex(RuntimeError, "missingness"):
            VERIFY.verify_probability_recomputation(changed_missingness, locked)

    def test_ground_truth_gate_requires_complete_untampered_prediction_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "GROUND_TRUTH_GATE"):
                open_prediction_lock(out, ROOT)
            (out / "blind_predictions_locked.csv").write_text("current_field_id,calibrated_probability\nf,0.5\n", encoding="utf-8")
            artifacts = []
            for name in ["blind_field_selection.csv", "blind_prior_features.csv", "blind_temporal_features.csv"]:
                (out / name).write_text("current_field_id\nf\n", encoding="utf-8")
                artifacts.append({"path": name, "bytes": (out / name).stat().st_size, "sha256": sha256_file(out / name)})
            p = out / "blind_predictions_locked.csv"
            artifacts.append({"path": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)})
            lock = {"status": "PREDICTIONS_HASH_LOCKED", "labels_opened": False, "critical_prediction_sha256": sha256_file(p), "code_hashes": [], "artifacts": artifacts}
            (out / "prediction_lock_manifest.json").write_text(json.dumps(lock), encoding="utf-8")
            self.assertEqual(open_prediction_lock(out, ROOT)["status"], "PREDICTIONS_HASH_LOCKED")
            p.write_text(p.read_text(encoding="utf-8") + "tamper", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                open_prediction_lock(out, ROOT)

    def test_prelock_label_columns_are_explicitly_forbidden(self):
        self.assertIn("is_winter_rapeseed", LABEL_COLUMNS)
        self.assertIn("dominant_crop_name", LABEL_COLUMNS)
        self.assertIn("grdkod_mar", LABEL_COLUMNS)

    def test_ground_truth_is_opened_and_verified_only_post_lock(self):
        frame = truth().copy(); frame["history_year"] = 2025
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truth.csv"
            frame.to_csv(path, index=False)
            contract = {"ground_truth": {"expected_sha256": sha256_file(path), "expected_2025_fields": 4, "expected_2025_winter_rapeseed_fields": 2, "expected_2025_winter_rapeseed_area_ha": 3.0, "positive_name": "Raps (höst)"}}
            loaded, inventory = load_ground_truth(path, contract)
        self.assertEqual(len(loaded), 4)
        self.assertEqual(inventory["winter_rapeseed_fields"], 2)
        self.assertTrue(inventory["opened_after_prediction_lock"])

    def test_sample_join_is_one_to_one_and_requires_positives(self):
        joined = join_sample_ground_truth(selection(), truth(), 2)
        self.assertEqual(joined.is_winter_rapeseed.tolist(), [1, 1, 0, 0])
        with self.assertRaisesRegex(RuntimeError, "too few"):
            join_sample_ground_truth(selection(), truth(), 3)

    def test_no_data_positive_reduces_recall_but_not_precision(self):
        sample = join_sample_ground_truth(selection(), truth(), 2)
        results, confusion = evaluate_predictions(predictions(), sample)
        row = results.iloc[0]
        self.assertAlmostEqual(row.precision_at_0_5, 0.5)
        self.assertAlmostEqual(row.recall_at_0_5, 0.5)
        self.assertEqual(row.no_data_fields, 1)
        self.assertEqual(row.positive_no_data_fields, 1)
        self.assertAlmostEqual(row.empirical_precision_at_frozen_p95, 1.0)
        self.assertAlmostEqual(row.recall_at_frozen_p95, 0.5)
        self.assertEqual(len(confusion), 3)

    def test_frozen_threshold_decisions_are_not_reselected_from_labels(self):
        sample = join_sample_ground_truth(selection(), truth(), 2)
        frame = predictions(); frame["predicted_at_frozen_p95"] = False
        results, _ = evaluate_predictions(frame, sample)
        self.assertTrue(pd.isna(results.iloc[0].empirical_precision_at_frozen_p95))
        self.assertEqual(results.iloc[0].recall_at_frozen_p95, 0.0)

    def test_data_quality_breakdown_preserves_positive_no_data(self):
        sample = join_sample_ground_truth(selection(), truth(), 2)
        quality = data_quality_breakdown(predictions(), sample)
        no_data = quality[quality.data_quality_status == "NO_DATA"].iloc[0]
        self.assertEqual(no_data.sample_fields, 1)
        self.assertEqual(no_data.sample_positive_fields, 1)

    def test_evaluation_source_declares_no_tuning(self):
        source = (SRC / "98_evaluate_rapskartan_2025_blind.py").read_text(encoding="utf-8")
        self.assertIn("Model/feature/calibration/threshold tuning after unblind: NO", source)
        self.assertNotIn("fit_estimator", source)
        self.assertNotIn("threshold_at_precision", source)


if __name__ == "__main__":
    unittest.main()
