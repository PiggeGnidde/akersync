import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "163_akerpuls_d2c_p95_geometry_audit_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("p95_geometry_audit_freeze", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CP95GeometryAuditFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_exact_labels_and_lineage_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_PROPOSAL_FREEZE_SHA256, "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a")
        self.assertEqual(self.m.EXPECTED_LABELS_SHA256, "3b9be03ea440eebf581e4f80e5a84a825a81a972ab0a44f4dfd3a2c16254d76a")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA256, "75515e0f1bd7f0466657317d7176be535f73da06a3505f2bad68b3190b33b428")
        self.assertEqual(self.m.EXPECTED_ROWS, 100)

    def test_predeclared_analysis_is_locked(self):
        p = self.m.PREDECLARED_ANALYSIS
        self.assertEqual(p["split_positive_for_geometry"], ["TYDLIG_SPLIT", "MÖJLIG_SPLIT"])
        self.assertEqual(p["line_strict_positive"], ["RATT_GRANS"])
        self.assertEqual(p["line_broad_positive"], ["RATT_GRANS", "NARA_GRANS"])
        self.assertEqual(p["line_negative"], ["FEL_GRANS"])
        self.assertEqual(p["line_excluded"], ["EJ_BEDOMBAR", "EJ_TILLAMPLIG"])

    def test_observed_count_tables_are_locked(self):
        self.assertEqual(self.m.EXPECTED_SPLIT_COUNTS, {
            "TYDLIG_SPLIT": 64, "MÖJLIG_SPLIT": 16, "TVEKSAM": 12,
            "FALSK_SPLIT": 8, "EJ_BEDÖMBAR": 0,
        })
        self.assertEqual(self.m.EXPECTED_LINE_COUNTS, {
            "RATT_GRANS": 76, "NARA_GRANS": 5, "FEL_GRANS": 2,
            "EJ_BEDOMBAR": 0, "EJ_TILLAMPLIG": 17,
        })

    def test_freeze_stage_does_not_open_or_join_blind_key(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv", text)
        self.assertNotIn("merge(key", text)
        self.assertNotIn("read_csv(key", text)
        self.assertIn('"blind_key_opened_by_this_stage": False', text)
        self.assertIn('"reveal_executed": False', text)

    def test_no_model_or_geometry_generation_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("rasterio", text)
        self.assertNotIn("to_file(", text)
        self.assertNotIn("geopandas", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("boto3", text)

    def test_next_step_is_reveal_only_after_freeze(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("NEXT=REVEAL_AND_ANALYZE_P95_GEOMETRY_AUDIT", text)
        self.assertIn('"blind_key_opened": False', text)


if __name__ == "__main__":
    unittest.main()
