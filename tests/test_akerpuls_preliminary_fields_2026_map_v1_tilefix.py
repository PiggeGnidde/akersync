import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "168_akerpuls_preliminary_fields_2026_map_v1_tilefix.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_prelim_2026_map_tilefix", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsPreliminaryFields2026MapV1TileFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_current_osm_tile_url_is_exact_and_legacy_subdomains_are_removed(self):
        html = self.m.fixed_make_html(self.m.base_original, ["fields_001.js"])
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", html)
        self.assertNotIn("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", html)

    def test_critical_leaflet_layout_css_is_embedded(self):
        html = self.m.fixed_make_html(self.m.base_original, ["fields_001.js"])
        self.assertIn("AKERPULS_LEAFLET_CRITICAL_CSS", html)
        self.assertIn(".leaflet-tile-container", html)
        self.assertIn("position:absolute", html)
        self.assertIn(".leaflet-pane>canvas", html)
        self.assertIn(".leaflet-tile-loaded", html)

    def test_geometry_and_model_logic_are_not_changed_here(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("smoothing\": True", text)
        self.assertNotIn("gap_filling\": True", text)
        self.assertIn("product_policy", (ROOT / "src" / "167_akerpuls_preliminary_fields_2026_map_v1_policyfix.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
