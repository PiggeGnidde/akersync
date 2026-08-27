from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load("akm_base_patch_skane_test", SRC / "59_patch_akerpass_akerminne_ui.py")
copyrev = load("akm_copy_patch_skane_test", SRC / "61_revise_akerminne_ui_copy.py")
skanepatch = load("akm_skane_patch_test", SRC / "68_patch_akerpass_akerminne_skane_ui.py")
regression = load("akm_skane_regression_test", SRC / "66_verify_akerminne_skurup_regression.py")
webbuild = load("akm_skane_webbuild_test", SRC / "67_build_akerminne_skane_web.py")


def sample_html():
    return '<style></style><script>function fieldPanel(p){return` <details><summary>Historik / referens</summary>`} async function loadMunicipality(name){const token=1;closeDrawer();selectedFieldLayer=null;try{}}</script>'


def mapping33():
    cfg = json.loads((ROOT / "config" / "akerminne_skane_municipalities.json").read_text(encoding="utf-8"))
    return {str(x["name"]): f"data/akerminne/{x['code']}_{webbuild._slug(str(x['name']))}.json" for x in cfg["municipalities"]}


class SkaneUiPatchTests(unittest.TestCase):
    def revised_base(self):
        return copyrev.revise_html(base.patch_html(sample_html()))

    def test_mapping_contains_exactly_33_and_accented_names(self):
        m = mapping33()
        self.assertEqual(len(m), 33)
        self.assertEqual(m["Hässleholm"], "data/akerminne/1293_hassleholm.json")
        self.assertEqual(m["Östra Göinge"], "data/akerminne/1256_ostra_goinge.json")

    def test_skane_patch_removes_skurup_only_gate(self):
        out = skanepatch.patch_html(self.revised_base(), mapping33())
        self.assertIn("AKERMINNE_SKANE_UI_R2", out)
        self.assertIn('if(!AKERMINNE_PILOT_FILES[p.kommun])return"";', out)
        self.assertIn('"Kristianstad":"data/akerminne/1290_kristianstad.json"', out)
        self.assertNotIn('p.kommun!=="Skurup"', out)
        self.assertNotIn("field_count!==2944", out)

    def test_skane_patch_is_idempotent(self):
        once = skanepatch.patch_html(self.revised_base(), mapping33())
        self.assertEqual(once, skanepatch.patch_html(once, mapping33()))

    def test_load_mapping_from_plan(self):
        cfg = json.loads((ROOT / "config" / "akerminne_skane_municipalities.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.json"
            path.write_text(json.dumps({"municipalities": cfg["municipalities"]}, ensure_ascii=False), encoding="utf-8")
            m = skanepatch.load_mapping(path)
            self.assertEqual(len(m), 33)
            self.assertEqual(m["Skurup"], "data/akerminne/1264_skurup.json")


class RegressionHelperTests(unittest.TestCase):
    def test_compare_frame_accepts_reordered_identical_rows(self):
        a = pd.DataFrame([
            {"id": "A", "year": 2020, "status": "X", "coverage": .5},
            {"id": "B", "year": 2020, "status": "Y", "coverage": 1.0},
        ])
        b = a.iloc[::-1].reset_index(drop=True)
        result = regression._compare_frame(a, b, ["id", "year"], ["status"], ["coverage"], "sample")
        self.assertEqual(result["rows"], 2)

    def test_compare_frame_rejects_numeric_change(self):
        a = pd.DataFrame([{"id": "A", "year": 2020, "status": "X", "coverage": .5}])
        b = pd.DataFrame([{"id": "A", "year": 2020, "status": "X", "coverage": .6}])
        with self.assertRaises(RuntimeError):
            regression._compare_frame(a, b, ["id", "year"], ["status"], ["coverage"], "sample")


class WebNamingTests(unittest.TestCase):
    def test_ascii_sidecar_slugs_are_stable(self):
        self.assertEqual(webbuild._slug("Hässleholm"), "hassleholm")
        self.assertEqual(webbuild._slug("Höör"), "hoor")
        self.assertEqual(webbuild._slug("Båstad"), "bastad")


if __name__ == "__main__":
    unittest.main()
