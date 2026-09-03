from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rapskartan_model_core import load_model_contract  # noqa: E402
from rapskartan_model_training import (  # noqa: E402
    arm_families, crossfit_calibration, expected_calibration_error,
    fit_calibrator, fit_estimator, make_estimator, predict_probability,
    probability_metrics, threshold_at_precision, year_oof_predictions,
)


def synthetic_frame() -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(44)
    for year in range(2018, 2025):
        for index in range(40):
            label = int(index % 5 == 0)
            rows.append({
                "development_field_id": f"{year}-{index}", "target_year": year,
                "geographic_fold": index % 5, "x1": label + rng.normal(0, 0.25),
                "x2": rng.normal(0, 1), "known_history_years": 4,
                "raps_frequency": 0.5 if label else 0.0,
                "is_winter_rapeseed": label, "population_weight": 1.0,
                "area_population_weight": 1.0 + index / 10,
            })
    return pd.DataFrame(rows)


class RapskartanModelTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_model_contract(ROOT)
        cls.frame = synthetic_frame()

    def test_required_baseline_families_are_present(self):
        self.assertIn("PRIOR_FREQUENCY_BASELINE", arm_families("PRIOR_ONLY"))
        self.assertIn("LOGISTIC_REGRESSION", arm_families("SATELLITE_ONLY"))
        self.assertIn("RANDOM_FOREST", arm_families("PRIOR_PLUS_SATELLITE"))

    def test_year_oof_is_complete_deterministic_and_preblind(self):
        first = year_oof_predictions(self.frame, ["x1", "x2"], "LOGISTIC_REGRESSION", self.contract)
        second = year_oof_predictions(self.frame, ["x1", "x2"], "LOGISTIC_REGRESSION", self.contract)
        self.assertTrue(np.array_equal(first, second))
        self.assertTrue(np.isfinite(first).all())
        self.assertTrue(((first >= 0) & (first <= 1)).all())
        self.assertLess(int(self.frame.target_year.max()), 2025)

    def test_crossfit_calibration_is_probability_bounded(self):
        raw = year_oof_predictions(self.frame, ["x1", "x2"], "LOGISTIC_REGRESSION", self.contract)
        for method in ("PLATT", "ISOTONIC"):
            calibrated = crossfit_calibration(raw, self.frame, method, "target_year", self.contract)
            self.assertTrue(np.isfinite(calibrated).all())
            self.assertTrue(((calibrated >= 0) & (calibrated <= 1)).all())

    def test_metrics_include_minority_and_calibration_measures(self):
        probability = np.where(self.frame.is_winter_rapeseed.to_numpy() == 1, 0.9, 0.1)
        metrics = probability_metrics(
            self.frame.is_winter_rapeseed.to_numpy(), probability,
            self.frame.population_weight.to_numpy(), self.frame.area_population_weight.to_numpy(),
        )
        self.assertEqual(metrics["recall_at_95_precision"], 1.0)
        self.assertGreater(metrics["pr_auc"], 0.99)
        self.assertLess(metrics["brier"], 0.02)
        self.assertIn("area_precision_at_0_5", metrics)

    def test_threshold_selection_does_not_treat_empty_as_precision(self):
        result = threshold_at_precision(
            np.array([1, 0, 0, 0]), np.array([0.8, 0.9, 0.7, 0.6]), np.ones(4), 0.95,
        )
        self.assertFalse(result["available"])
        self.assertEqual(result["recall"], 0.0)

    def test_calibration_ece_is_zero_for_exact_bins(self):
        y = np.array([0, 0, 1, 1])
        p = np.array([0, 0, 1, 1], dtype=float)
        self.assertAlmostEqual(expected_calibration_error(y, p, np.ones(4), bins=2), 0.0)

    def test_serialized_bundle_contains_contract_not_training_labels(self):
        estimator = make_estimator("LOGISTIC_REGRESSION", self.contract)
        fit_estimator(estimator, "LOGISTIC_REGRESSION", self.frame[["x1", "x2"]], self.frame.is_winter_rapeseed.to_numpy(), np.ones(len(self.frame)))
        raw = predict_probability(estimator, self.frame[["x1", "x2"]])
        calibrator = fit_calibrator("PLATT", raw, self.frame.is_winter_rapeseed.to_numpy(), np.ones(len(self.frame)), 7)
        bundle = {
            "schema_version": "rapskartan-frozen-model-bundle-v1",
            "training_years": list(range(2018, 2025)), "feature_columns": ["x1", "x2"],
            "estimator": estimator, "calibrator": calibrator,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.joblib"
            joblib.dump(bundle, path)
            loaded = joblib.load(path)
        self.assertNotIn("is_winter_rapeseed", loaded)
        self.assertNotIn(2025, loaded["training_years"])
        calibrated = loaded["calibrator"].predict(predict_probability(loaded["estimator"], self.frame[["x1", "x2"]]))
        self.assertTrue(((calibrated >= 0) & (calibrated <= 1)).all())


if __name__ == "__main__":
    unittest.main()
