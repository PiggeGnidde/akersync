import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "167_akerpuls_preliminary_fields_2026_map_v1_policyfix.py"
BASE = ROOT / "src" / "166_akerpuls_preliminary_fields_2026_map_v1.py"
FREEZE = ROOT / "src" / "165_akerpuls_preliminary_geometry_v1_freeze.py"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsPreliminaryFields2026MapV1PolicyFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fix = load_module(SCRIPT, "map_v1_policyfix")
        cls.base = load_module(BASE, "map_v1_base_for_fix_test")
        cls.fix_text = SCRIPT.read_text(encoding="utf-8")
        cls.freeze_text = FREEZE.read_text(encoding="utf-8")

    def test_formal_freeze_schema_uses_product_policy(self):
        self.assertIn('"product_policy": POLICY', self.freeze_text)
        self.assertIn('prelim.get("product_policy", {})', self.fix_text)

    def test_fix_preserves_exact_frozen_hashes_and_counts(self):
        self.assertEqual(self.base.EXPECTED_PRELIM_V1_FREEZE_SHA256, "c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376")
        self.assertEqual(self.base.EXPECTED_PROPOSAL_FREEZE_SHA256, "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a")
        self.assertEqual(self.base.EXPECTED_FIELDS_2025, 128636)
        self.assertEqual(self.base.EXPECTED_SPLIT_LINES, 613)
        self.assertEqual(self.base.EXPECTED_NO_GEOMETRY, 5)

    def test_fix_only_replaces_input_verifier_then_delegates(self):
        self.assertIn("mod.verify_frozen_inputs =", self.fix_text)
        self.assertIn("return int(mod.main())", self.fix_text)
        self.assertNotIn("deterministic_k2", self.fix_text)
        self.assertNotIn("polygonize", self.fix_text.lower())
        self.assertNotIn("smoothing\": True", self.fix_text)
        self.assertNotIn("gap_filling\": True", self.fix_text)


if __name__ == "__main__":
    unittest.main()
