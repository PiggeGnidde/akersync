import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "178_akerpuls_m4_reimplementation_input_profile_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_reimpl_profile", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4ReimplementationInputProfileV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_frozen_m0_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_M0_FREEZE_SHA256,
            "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051",
        )

    def test_all_three_source_hashes_are_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_INPUTS["akerminne_2015_2025_selected.csv.gz"],
            "05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf",
        )
        self.assertEqual(
            self.m.EXPECTED_INPUTS["field_static_context_selected.csv.gz"],
            "31db31b79b53a4c0aa32621fb7bfa44165ea65b6b46371c32e4e19935f59feea",
        )
        self.assertEqual(
            self.m.EXPECTED_INPUTS["akerscore_soil_skiften_selected.csv.gz"],
            "71dfd711a4243b3cbe465de7eaa013725b2d2f9be3a8890d213a89bc095427da",
        )

    def test_target_class_order_is_frozen(self):
        self.assertEqual(len(self.m.TARGET_CLASSES), 16)
        self.assertEqual(self.m.TARGET_CLASSES[0], "höstraps")
        self.assertEqual(self.m.TARGET_CLASSES[-1], "annan gröda")

    def test_stage_is_read_only(self):
        low = self.text.lower()
        self.assertNotIn("lgbmclassifier(", low)
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn(".fit(", low)
        self.assertIn('"model_executed": False', self.text)
        self.assertIn('"m4_prediction_executed": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_censuses_are_guarded(self):
        self.assertIn('!= 1414996', self.text)
        self.assertIn('!= 128636', self.text)

    def test_status_stops_before_model_reimplementation(self):
        self.assertEqual(self.m.STATUS, "PASS_M4_REIMPLEMENTATION_INPUT_PROFILE_STOP")
        self.assertIn("DESIGN_AND_RUN_M4_REIMPLEMENTATION_REPRODUCTION_GATE", self.text)


if __name__ == "__main__":
    unittest.main()
