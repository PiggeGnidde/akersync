import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "164_akerpuls_d2c_p95_geometry_audit_reveal_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("p95_geometry_audit_reveal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CP95GeometryAuditRevealV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_exact_frozen_lineage_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256,
                         "089cd1d90daa9252e93ddbe4004c7afad5f0c00ec8d54293b43fc6915e4983f0")
        self.assertEqual(self.m.EXPECTED_PROPOSAL_FREEZE_SHA256,
                         "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a")
        self.assertEqual(self.m.EXPECTED_LABELS_SHA256,
                         "3b9be03ea440eebf581e4f80e5a84a825a81a972ab0a44f4dfd3a2c16254d76a")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA256,
                         "75515e0f1bd7f0466657317d7176be535f73da06a3505f2bad68b3190b33b428")
        self.assertEqual((self.m.EXPECTED_ROWS, self.m.EXPECTED_LINE_POPULATION,
                          self.m.EXPECTED_P95_POPULATION, self.m.EXPECTED_NO_INTERFACE),
                         (100, 613, 618, 5))

    def test_predeclared_endpoints_remain_locked(self):
        p = self.m.PREDECLARED_ANALYSIS
        self.assertEqual(p["split_positive_for_geometry"], ["TYDLIG_SPLIT", "MÖJLIG_SPLIT"])
        self.assertEqual(p["line_strict_positive"], ["RATT_GRANS"])
        self.assertEqual(p["line_broad_positive"], ["RATT_GRANS", "NARA_GRANS"])
        self.assertEqual(p["line_negative"], ["FEL_GRANS"])
        self.assertEqual(p["line_excluded"], ["EJ_BEDOMBAR", "EJ_TILLAMPLIG"])

    def test_reveal_requires_exact_blind_key_and_deterministic_sample(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv", text)
        self.assertIn("sha256_file(kp) != EXPECTED_BLIND_KEY_SHA256", text)
        self.assertIn("Recreate the deterministic sample from the entire 613-line population", text)
        self.assertIn("sample_population_sha256", text)

    def test_primary_geometry_endpoint_and_cueing_caveat_are_explicit(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("conditional_on_split_positive_line_strict", text)
        self.assertIn("conditional_on_split_positive_line_broad", text)
        self.assertIn("cyan line", text.lower())
        self.assertIn("not independent ground truth", text)
        self.assertIn("LINE_PLACEMENT_PRIMARY_ENDPOINT", text)

    def test_no_model_or_geometry_mutation_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("rasterio", text)
        self.assertNotIn("geopandas", text)
        self.assertNotIn("to_file(", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("boto3", text)
        self.assertIn('"model_executed": False', text)
        self.assertIn('"thresholds_tuned": False', text)
        self.assertIn('"fusion_refit": False', text)
        self.assertIn('"official_2025_geometry_replaced": False', text)

    def test_reveal_is_descriptive_not_retuning(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Descriptive only", text)
        self.assertIn("post_reveal_exploratory_spearman", text)
        self.assertIn("NEXT=INTERPRET_AND_DECIDE_SMOOTHING_OR_GEOMETRY_ADOPTION_POLICY", text)


if __name__ == "__main__":
    unittest.main()
