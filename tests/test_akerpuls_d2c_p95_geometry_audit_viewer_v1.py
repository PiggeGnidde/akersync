import importlib.util
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "162_akerpuls_d2c_p95_geometry_audit_viewer_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("p95_geometry_audit_viewer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CP95GeometryAuditViewerV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_exact_freeze_and_population_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_PROPOSAL_FREEZE_SHA256, "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a")
        self.assertEqual(self.m.EXPECTED_SOURCE_PROPOSAL_MANIFEST_SHA256, "c8aa8fedc73d723394eb1844358aefd7f60b0e5b163785d079d1876b1831d1a1")
        self.assertEqual((self.m.EXPECTED_LINE_POPULATION, self.m.EXPECTED_NO_INTERFACE, self.m.EXPECTED_SAMPLE), (613, 5, 100))
        self.assertEqual(self.m.EXPECTED_D1_SNAPSHOT_INDEX_SHA256, "a3a26d1f454a8c0d65e326a913b0d10d91c54d4ba9886315ec5d5dd1e35cafff")
        self.assertEqual(self.m.EXPECTED_D1_VRT_INDEX_SHA256, "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979")

    def test_predeclared_double_audit_semantics_are_locked(self):
        self.assertEqual(self.m.SPLIT_LABELS, ["TYDLIG_SPLIT", "MÖJLIG_SPLIT", "TVEKSAM", "FALSK_SPLIT", "EJ_BEDÖMBAR"])
        self.assertEqual(self.m.LINE_LABELS, ["RATT_GRANS", "NARA_GRANS", "FEL_GRANS", "EJ_BEDOMBAR", "EJ_TILLAMPLIG"])
        self.assertEqual(self.m.PREDECLARED_ANALYSIS["line_strict_positive"], ["RATT_GRANS"])
        self.assertEqual(self.m.PREDECLARED_ANALYSIS["line_broad_positive"], ["RATT_GRANS", "NARA_GRANS"])
        self.assertEqual(self.m.PREDECLARED_ANALYSIS["split_positive_for_geometry"], ["TYDLIG_SPLIT", "MÖJLIG_SPLIT"])

    def test_snapshot_and_band_contract_is_exact(self):
        self.assertEqual([x[0] for x in self.m.SNAPSHOTS], ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"])
        self.assertEqual(self.m.EXPECTED_BANDS, ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "VALID", "NDVI", "LSWI", "SOURCE_DATE_INDEX"])
        self.assertEqual(self.m.EXPECTED_EPSG, 32633)

    def test_hash_sampling_is_deterministic_and_separate_from_blind_order(self):
        self.assertEqual(self.m.sample_hash("abc"), self.m.sample_hash("abc"))
        self.assertNotEqual(self.m.sample_hash("abc"), self.m.sample_hash("def"))
        self.assertNotEqual(self.m.sample_hash("abc"), self.m.blind_hash("abc"))

    def test_square_bounds_boundary_and_halo(self):
        self.assertEqual(self.m.square_bounds((0, 0, 100, 50), 10), (-10.0, -35.0, 110.0, 85.0))
        mask = np.zeros((7, 7), dtype=bool)
        mask[2:5, 2:5] = True
        boundary, halo = self.m.boundary_and_halo(mask)
        self.assertEqual(int(boundary.sum()), 8)
        self.assertGreater(int(halo.sum()), int(boundary.sum()))
        line = np.zeros((7, 7), dtype=bool); line[3, 2:5] = True
        self.assertGreater(int(self.m.mask_halo(line).sum()), int(line.sum()))

    def test_joint_stretch_is_shared_across_dates(self):
        first = np.ones((3, 4, 4), dtype=np.float32)
        second = np.ones((3, 4, 4), dtype=np.float32) * 2.0
        first[:, 0, 0] = 0.0; second[:, -1, -1] = 3.0
        valid = np.ones((4, 4), dtype=bool)
        out = self.m.joint_rgb_stretch([first, second], [valid, valid])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].shape, (4, 4, 3))
        self.assertEqual(out[0].dtype, np.uint8)
        self.assertLess(float(out[0].mean()), float(out[1].mean()))

    def test_html_is_blind_offline_double_label_and_export(self):
        html = self.m.build_html([{"blind_index": 1, "primary_image": "images/a.jpg", "diagnostic_image": "images/b.jpg"}], "abc123")
        for text in ("TYDLIG_SPLIT", "FALSK_SPLIT", "RATT_GRANS", "NARA_GRANS", "FEL_GRANS", "EJ_TILLAMPLIG", "Exportera geometri-audit CSV", "localStorage"):
            self.assertIn(text, html)
        self.assertNotIn("fusion_score", html)
        self.assertNotIn("parent_field_id_2025", html)
        self.assertNotIn("prototype_p_splitmerge_2026", html)
        self.assertNotIn("tile.openstreetmap.org", html)
        self.assertNotIn("arcgisonline.com", html)

    def test_source_has_no_model_network_or_geometry_mutation_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("boto3", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("urllib", text)
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("empirical_midrank", text)
        self.assertNotIn("to_file(", text)
        self.assertNotIn("simplify(", text)
        self.assertNotIn("buffer(", text)


if __name__ == "__main__":
    unittest.main()
