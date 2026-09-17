import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "177_akerpuls_m4_source_artifact_preflight_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_source_preflight", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4SourceArtifactPreflightV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_m0_freeze_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_M0_FREEZE_SHA256,
            "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051",
        )

    def test_exact_technical_note_artefact_names_are_searched(self):
        for name in (
            "AKERPULS_VAXTFOLJDSMODELL_STUDIE.md",
            "vaxfoljd_model_report_stoppunkt_c_final.md",
            "vaxfoljd_descriptive_report.md",
            "raps_soft_ablation_final.md",
            "vaxfoljd_manifest.json",
        ):
            self.assertIn(name, self.text)

    def test_historical_roots_include_work_and_akerminne(self):
        self.assertIn(r"C:\AkerSyncRepo\work", self.text)
        self.assertIn(r"C:\AkerSync-Minne", self.text)
        self.assertIn(r"C:\AkerSync-Prestation", self.text)

    def test_read_only_no_execution_or_mutation(self):
        low = self.text.lower()
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn("lightgbm.train(", low)
        self.assertNotIn("to_file(", low)
        self.assertIn('"model_executed": False', self.text)
        self.assertIn('"m4_prediction_executed": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_status_stops_before_reproduction(self):
        self.assertEqual(self.m.STATUS, "PASS_M4_SOURCE_ARTEFACT_DISCOVERY_STOP")
        self.assertIn("REVIEW_ORIGINAL_M4_SOURCE_ARTEFACTS_BEFORE_REPRODUCTION_GATE", self.text)


if __name__ == "__main__":
    unittest.main()
