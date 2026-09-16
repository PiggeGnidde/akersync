import importlib.util
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "158_akerpuls_d2c_visual_audit_viewer_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("d2c_audit_viewer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CVisualAuditViewerV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_exact_frozen_lineage_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_D2C_STATUS, "FROZEN_FULL_SKANE_QA_RANKING_V1")
        self.assertEqual(self.m.EXPECTED_D2C_FREEZE_SHA256, "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950")
        self.assertEqual(self.m.EXPECTED_D1_SNAPSHOT_INDEX_SHA256, "a3a26d1f454a8c0d65e326a913b0d10d91c54d4ba9886315ec5d5dd1e35cafff")
        self.assertEqual(self.m.EXPECTED_D1_VRT_INDEX_SHA256, "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979")
        self.assertEqual((self.m.EXPECTED_AUDIT_ROWS, self.m.EXPECTED_P95_AUDIT, self.m.EXPECTED_P90_ONLY_AUDIT), (100, 50, 50))

    def test_snapshot_and_band_contract_is_exact(self):
        self.assertEqual([x[0] for x in self.m.SNAPSHOTS], ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"])
        self.assertEqual(self.m.EXPECTED_BANDS, ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "VALID", "NDVI", "LSWI", "SOURCE_DATE_INDEX"])
        self.assertEqual(self.m.EXPECTED_EPSG, 32633)

    def test_square_bounds_preserves_common_extent(self):
        self.assertEqual(self.m.square_bounds((0, 0, 100, 50), 10), (-10.0, -35.0, 110.0, 85.0))

    def test_boundary_and_halo(self):
        mask = np.zeros((7, 7), dtype=bool)
        mask[2:5, 2:5] = True
        boundary, halo = self.m.boundary_and_halo(mask)
        self.assertEqual(int(boundary.sum()), 8)
        self.assertGreater(int(halo.sum()), int(boundary.sum()))

    def test_joint_stretch_is_shared_across_dates(self):
        first = np.ones((3, 4, 4), dtype=np.float32)
        second = np.ones((3, 4, 4), dtype=np.float32) * 2.0
        first[:, 0, 0] = 0.0
        second[:, -1, -1] = 3.0
        valid = np.ones((4, 4), dtype=bool)
        out = self.m.joint_rgb_stretch([first, second], [valid, valid])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].shape, (4, 4, 3))
        self.assertEqual(out[0].dtype, np.uint8)
        self.assertLess(float(out[0].mean()), float(out[1].mean()))

    def test_html_is_blind_offline_and_exports_labels(self):
        html = self.m.build_html([{"blind_index": 1, "image": "images/a.jpg"}], "abc123")
        self.assertIn("TYDLIG_SPLIT", html)
        self.assertIn("MÖJLIG_SPLIT", html)
        self.assertIn("EJ_BEDÖMBAR", html)
        self.assertIn("Exportera frysta etiketter CSV", html)
        self.assertIn("localStorage", html)
        self.assertNotIn("fusion_score", html)
        self.assertNotIn("P95_HIGH_PRIORITY", html)
        self.assertNotIn("tile.openstreetmap.org", html)
        self.assertNotIn("arcgisonline.com", html)

    def test_source_has_no_model_or_network_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("boto3", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("urllib", text)
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("empirical_midrank", text)
        self.assertNotIn("to_file(", text)


if __name__ == "__main__":
    unittest.main()
