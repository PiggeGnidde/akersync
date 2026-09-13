import importlib.util
import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "144_akerpuls_d1s3c_independent_holdout_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3c_independent_holdout_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3c", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3CIndependentHoldoutV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_contract_is_non_mutating_and_not_authorized(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3c-independent-backend-holdout-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        self.assertEqual(self.cfg["expected_final_execution_contract_sha256"], "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19")

    def test_backend_semantics_are_frozen(self):
        sem = self.cfg["candidate_backend_semantics"]
        self.assertEqual(sem["scene_order"], "REVERSED")
        self.assertEqual(sem["coverage"], "SCL_NONZERO")
        self.assertEqual(sem["reflectance"], "SCALE_OFFSET")
        self.assertEqual(sem["resampling"], "NEAREST")
        self.assertTrue(sem["frozen_before_holdout_results"])

    def test_spread_selection_is_deterministic(self):
        df = pd.DataFrame([
            {"tile_id":"A","minx":0,"maxx":10,"miny":0,"maxy":10},
            {"tile_id":"B","minx":100,"maxx":110,"miny":0,"maxy":10},
            {"tile_id":"C","minx":0,"maxx":10,"miny":100,"maxy":110},
            {"tile_id":"D","minx":100,"maxx":110,"miny":100,"maxy":110},
            {"tile_id":"E","minx":50,"maxx":60,"miny":50,"maxy":60},
        ])
        one = self.m.deterministic_spread(df, 4)["tile_id"].tolist()
        two = self.m.deterministic_spread(df.sample(frac=1, random_state=9), 4)["tile_id"].tolist()
        self.assertEqual(one, two)
        self.assertEqual(len(one), 4)

    def test_holdout_sample_size_is_fixed(self):
        sel = self.cfg["selection"]
        self.assertEqual(sel["maximum_dates"], 3)
        self.assertEqual(sel["requests_per_date"], 4)
        self.assertEqual(sel["strategy"], "DETERMINISTIC_CENTROID_PLUS_FARTHEST_POINT_SPREAD")


if __name__ == "__main__":
    unittest.main()
