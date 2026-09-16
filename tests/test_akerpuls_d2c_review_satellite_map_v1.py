import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "157_akerpuls_d2c_review_satellite_map_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("d2c_satmap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CReviewSatelliteMapV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_exact_parent_freeze_is_pinned(self):
        self.assertEqual(clsval := self.m.EXPECTED_D2C_STATUS, "FROZEN_FULL_SKANE_QA_RANKING_V1")
        self.assertEqual(self.m.EXPECTED_FREEZE_SHA256, "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950")
        self.assertEqual(self.m.EXPECTED_P90PLUS, 1136)
        self.assertEqual(self.m.EXPECTED_P95, 618)
        self.assertEqual(clsval, self.m.EXPECTED_D2C_STATUS)

    def test_output_is_separate_from_frozen_original(self):
        self.assertEqual(self.m.SOURCE_GEOJSON, "d2c_review_p90plus_wgs84.geojson")
        self.assertEqual(self.m.OUTPUT_HTML, "d2c_review_p90plus_satellite_map.html")
        self.assertNotEqual(self.m.OUTPUT_HTML, "d2c_review_p90plus_map.html")

    def test_html_uses_esri_not_osm_volunteer_tiles(self):
        sample = '{"type":"FeatureCollection","features":[]}'
        html = self.m.build_html(sample)
        self.assertIn("World_Imagery/MapServer/tile", html)
        self.assertIn("World_Street_Map/MapServer/tile", html)
        self.assertNotIn("tile.openstreetmap.org", html)
        self.assertIn("Esri World Imagery", html)
        self.assertIn("post-freeze visualization only", html)

    def test_source_has_no_model_or_network_client_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("boto3", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("urllib", text)
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("empirical_midrank", text)
        self.assertNotIn("to_file(", text)
        self.assertNotIn("to_csv(", text)


if __name__ == "__main__":
    unittest.main()
