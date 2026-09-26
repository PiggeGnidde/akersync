from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BUILD = load("akerfro_web_build_test", "src/88_build_akerfro_web_v0a.py")
PATCH = load("akerfro_web_patch_test", "src/89_patch_akerfro_web_v0a_ui.py")


def sample_row(field_id: str, municipality: str, rank: int, cls: str = "A_STRONG_CANDIDATE") -> dict:
    return {
        "current_field_id": field_id,
        "municipality": municipality,
        "artkandidat_class": cls,
        "artmatch_score": 85.5,
        "rotation_status": "ROTATION_OK",
        "crop_2025_name": "Vete (höst)",
        "predecessor_prior": "POSITIVE",
        "predecessor_enrichment_ratio": 2.3,
        "field_area_ha": 8.5,
        "area_fit_score": 100.0,
        "distance_bjuv_km": 18.0,
        "bjuv_proximity_score": 100.0,
        "area_logistics_score": 100.0,
        "area_logistics_band": "HIGH",
        "operational_priority_rank": rank,
        "is_positive": False,
        "last_conservart_any_component_year": None,
        "last_other_pea_clean_year": None,
        "last_faba_bean_clean_year": None,
    }


class AkerFroWebV0aTests(unittest.TestCase):
    def test_municipality_payload_roundtrip_contract(self):
        frame = pd.DataFrame([
            sample_row("1|A", "Lomma", 1),
            sample_row("2|B", "Lomma", 2, "B_PHYSICAL_CANDIDATE"),
        ])
        payload = BUILD.build_municipality_payload(frame)
        self.assertEqual(payload["schema_version"], BUILD.SCHEMA)
        self.assertEqual(payload["municipality"], "Lomma")
        self.assertEqual(payload["field_count"], 2)
        self.assertEqual(set(payload["fields"]), {"1|A", "2|B"})
        self.assertEqual(payload["columns"], BUILD.ROW_COLUMNS)
        self.assertEqual(payload["class_counts"]["A_STRONG_CANDIDATE"], 1)
        self.assertEqual(payload["class_counts"]["B_PHYSICAL_CANDIDATE"], 1)

    def test_top1000_uses_operational_rank(self):
        rows = [sample_row(f"{i}|A", "Lomma", i) for i in range(1001, 0, -1)]
        payload = BUILD.build_top1000(pd.DataFrame(rows))
        self.assertEqual(payload["count"], 1000)
        self.assertEqual(payload["rows"][0]["rank"], 1)
        self.assertEqual(payload["rows"][-1]["rank"], 1000)

    def test_ui_patch_preserves_akernorm_and_adds_akerfro(self):
        akn = "$" + "{akernormSection(p)}"
        tick = chr(96)
        html = (
            '<html><head><!-- AKERNORM_WEB_UI_V1 --></head><body>'
            '<button class="layer-button" type="button" data-layer="drift" '
            'title="Strukturell maskinell brukbarhet">ÅkerDrift</button>'
            '<div id="layerHint" class="hint"></div>'
            '<script>function fieldPanel(p){return'
            + tick + ' ' + akn
            + '\n <details><summary>Historik / referens</summary>' + tick + '}</script>'
            '</body></html>'
        )
        mapping = {}
        for i in range(33):
            name = "Kristianstad" if i == 0 else "Lomma" if i == 1 else f"Kommun{i}"
            mapping[name] = f"data/akerfro/{i}.json"
        patched = PATCH.patch_html(html, mapping, "data/akerfro/skane_top1000.json")
        self.assertIn("AKERNORM_WEB_UI_V1", patched)
        self.assertIn("AKERFRO_ERTOR_WEB_UI_V0A", patched)
        self.assertIn('data-layer="fro"', patched)
        self.assertIn("assets/akerfro_v0a.css", patched)
        self.assertIn("assets/akerfro_v0a.js", patched)
        self.assertIn("$" + "{akerfroSection(p)}", patched)
        self.assertIn("Top 1000", patched)

    def test_ui_patch_rejects_non_akernorm_base(self):
        with self.assertRaisesRegex(RuntimeError, "ÅkerNorm base marker"):
            PATCH.patch_html("<html></html>", {}, "x")


if __name__ == "__main__":
    unittest.main()
