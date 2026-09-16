import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "159_akerpuls_d2c_human_audit_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("d2c_audit_freeze", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CHumanAuditFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_exact_lineage_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_D2C_FREEZE_SHA256,
            "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950",
        )
        self.assertEqual(
            self.m.EXPECTED_LABELS_SHA256,
            "c5918bb3f74e205182e7f04612b3d48dac6f6cde103f94502759db222645041f",
        )
        self.assertEqual(
            self.m.EXPECTED_BLIND_KEY_SHA256,
            "ee5f5bd3795f06040a2036e66d2a448b7c21986900d83454a702f412dad70200",
        )

    def test_predeclared_interpretation_is_locked(self):
        self.assertEqual(self.m.STRICT_POSITIVE, {"TYDLIG_SPLIT"})
        self.assertEqual(self.m.BROAD_POSITIVE, {"TYDLIG_SPLIT", "MÖJLIG_SPLIT"})

    def test_revealed_count_table_is_locked(self):
        self.assertEqual(
            self.m.EXPECTED_COUNTS["P95_HIGH_PRIORITY"],
            {"TYDLIG_SPLIT": 19, "MÖJLIG_SPLIT": 20, "TVEKSAM": 8, "FALSK_SPLIT": 3, "EJ_BEDÖMBAR": 0},
        )
        self.assertEqual(
            self.m.EXPECTED_COUNTS["P90_ONLY"],
            {"TYDLIG_SPLIT": 10, "MÖJLIG_SPLIT": 9, "TVEKSAM": 18, "FALSK_SPLIT": 13, "EJ_BEDÖMBAR": 0},
        )

    def test_fisher_exact_matches_frozen_audit(self):
        broad = self.m.fisher_two_sided(39, 11, 19, 31)
        strict = self.m.fisher_two_sided(19, 31, 10, 40)
        self.assertAlmostEqual(broad, 9.545925522270668e-05, places=14)
        self.assertAlmostEqual(strict, 0.07693831551808866, places=14)

    def test_population_weights(self):
        self.assertEqual(self.m.P95_POP, 618)
        self.assertEqual(self.m.P90_ONLY_POP, 518)
        self.assertEqual(self.m.P90PLUS_POP, 1136)
        w95 = self.m.P95_POP / self.m.P90PLUS_POP
        w90 = self.m.P90_ONLY_POP / self.m.P90PLUS_POP
        strict = w95 * 0.38 + w90 * 0.20
        broad = w95 * 0.78 + w90 * 0.38
        self.assertAlmostEqual(strict, 0.2979225352112676)
        self.assertAlmostEqual(broad, 0.5976056338028168)

    def test_source_has_no_geometry_generation_or_model_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("rasterio", text)
        self.assertNotIn("geopandas", text)
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("split_line(", text)
        self.assertNotIn("to_file(", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("boto3", text)


if __name__ == "__main__":
    unittest.main()
