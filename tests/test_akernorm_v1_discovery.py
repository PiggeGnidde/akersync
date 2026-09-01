from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.akernorm_v1_discovery_core import (
    CONTEXT_COMMIT,
    VALIDATION_COMMIT,
    _find_var,
    artifact_hashes,
    build_crop_code_contract,
    score_only_core_metrics,
)


ROOT = Path(__file__).resolve().parents[1]


class AkerNormDiscoveryTests(unittest.TestCase):
    def test_pxweb_dimension_resolution_is_exact(self):
        metadata = {
            "variables": [
                {"code": "Skördeområde", "text": "Skördeområde"},
                {"code": "Gröda", "text": "Gröda"},
                {"code": "Variabel", "text": "Variabel"},
                {"code": "År", "text": "År"},
            ]
        }
        self.assertEqual(_find_var(metadata, "År")["code"], "År")

    def test_pxweb_dimension_resolution_rejects_non_exact_match(self):
        metadata = {"variables": [{"code": "Variabel", "text": "Variabel"}]}
        with self.assertRaisesRegex(RuntimeError, "expected one exact code/text match"):
            _find_var(metadata, "År")

    def test_crop_codes_are_stable_2015_2025(self):
        contract = build_crop_code_contract(ROOT)
        self.assertEqual(contract["status"], "PASS")
        self.assertEqual(len(contract["crops"]), 6)
        for crop in contract["crops"]:
            self.assertEqual(len(crop["annual_mappings"]), 11)
            self.assertTrue(all(row["status"] == "PASS" for row in crop["annual_mappings"]))

    def test_expected_file_is_discovery_only(self):
        document = json.loads((ROOT / "analysis/akernorm_v1_discovery/expected_reproduction_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "DISCOVERY_ONLY_NOT_A_MODEL_CONTRACT")
        self.assertEqual(len(document["comparisons"]), 11)

    def test_geographic_core_uses_same_positive_linear_algorithm(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sko.csv"
            frame = pd.DataFrame({
                "sko_id": ["0731", "1111", "1112", "1121", "1321"],
                "mean_akerscore_areaweighted": [10.0, 20.0, 30.0, 40.0, 50.0],
                "norm_t_ha": [1.0, 2.0, 3.0, 4.0, 5.0],
            })
            frame.to_csv(path, index=False)
            result = score_only_core_metrics(path, {"0731", "1321"})
            self.assertEqual(result["n_sko"], 3)
            self.assertAlmostEqual(result["effect_t_ha_per_10_score"], 1.0)
            self.assertAlmostEqual(result["r2"], 1.0)
            self.assertAlmostEqual(result["loocv_rmse_t_ha"], 0.0)

    def test_artifact_manifest_excludes_logs_and_itself(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data.txt").write_text("x", encoding="utf-8")
            (root / "discovery_manifest.json").write_text("{}", encoding="utf-8")
            (root / "logs").mkdir()
            (root / "logs/run.log").write_text("log", encoding="utf-8")
            hashes = artifact_hashes(root)
            self.assertEqual(set(hashes), {"data.txt"})

    def test_frozen_commits_are_full_hashes(self):
        self.assertEqual(len(CONTEXT_COMMIT), 40)
        self.assertEqual(len(VALIDATION_COMMIT), 40)


if __name__ == "__main__":
    unittest.main()
