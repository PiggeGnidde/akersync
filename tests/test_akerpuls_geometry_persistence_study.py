import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "129_akerpuls_geometry_persistence_study.py"
CONFIG = ROOT / "config" / "akerpuls_geometry_persistence_study_v0.json"

spec = importlib.util.spec_from_file_location("geometry_persistence_study", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class TestGeometryPersistenceStudy(unittest.TestCase):
    def test_contract_is_frozen_akerminne_zero_pu(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["reference_year"], 2025)
        self.assertEqual(cfg["history_years"], list(range(2015, 2025)))
        self.assertEqual(cfg["expected_current_fields"], 128636)
        self.assertEqual(cfg["expected_municipalities"], 33)
        self.assertEqual(set(cfg["identity_classes"]["strict_same"]), {"direct_id", "one_to_one_strict"})
        self.assertFalse(cfg["guards"]["modify_frozen_akerminne"])
        self.assertFalse(cfg["guards"]["sentinel_api_calls"])
        self.assertFalse(cfg["guards"]["sentinel_hub_pu"])
        self.assertFalse(cfg["guards"]["product_prior_freeze"])

    def test_poisson_binomial_pmf(self):
        pmf = mod.poisson_binomial_pmf([0.5, 0.5])
        np.testing.assert_allclose(pmf, [0.25, 0.5, 0.25], atol=1e-12)
        self.assertAlmostEqual(float(pmf.sum()), 1.0, places=12)

    def test_recent_true_streak(self):
        x = np.array([
            [True, True, True],
            [True, False, True],
            [False, True, True],
            [True, True, False],
        ])
        got = mod.recent_true_streak(x)
        np.testing.assert_array_equal(got, [3, 1, 2, 0])


if __name__ == "__main__":
    unittest.main()
