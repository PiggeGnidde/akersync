import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "184_akerpuls_m4_2026_prior_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_2026_freeze", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM42026PriorFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_source_run_and_m4_freeze_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_SOURCE_GIT_HEAD, "89c1b5b2ba9c8ff4eed338db4a2fa98ff76a9bb5")
        self.assertEqual(self.m.EXPECTED_M4_V1B_FREEZE_SHA256, "94ea57736b7aa472c1bca959aeb848b0e764240d3d47202c2a2a4dc144ed7b9a")

    def test_key_artefact_hashes_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_MODEL_SHA256, "5feaa68f2c021b250d9ef6c0fcc0e1abb615329d89d0027bc9fe25af6d04c7a0")
        self.assertEqual(self.m.EXPECTED_PARQUET_SHA256, "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8")
        self.assertEqual(self.m.EXPECTED_CSV_GZ_SHA256, "d88d316dc71395ed2ecf095b58d8775707b1f6ff6ea310c272984be1b6b77805")

    def test_population_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_ROWS, 128636)
        self.assertEqual(self.m.EXPECTED_CLASSES, 16)
        self.assertEqual(self.m.EXPECTED_TRAIN_N, 954786)
        self.assertEqual(sum(self.m.EXPECTED_TOP1_COUNTS.values()), 128636)

    def test_freeze_does_not_fit_or_predict(self):
        low = self.text.lower()
        self.assertNotIn(".fit(", low)
        self.assertNotIn("predict_proba(", low)
        self.assertIn('"model_fit_executed_in_freeze": False', self.text)
        self.assertIn('"prediction_executed_in_freeze": False', self.text)

    def test_blind_guards_are_frozen(self):
        self.assertIn('"2026_crop_labels_used": False', self.text)
        self.assertIn('"2026_satellite_used": False', self.text)
        self.assertIn('"merge_m0_used": False', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "FROZEN_AKERPULS_M4_2026_PRIOR_V1")


if __name__ == "__main__":
    unittest.main()
