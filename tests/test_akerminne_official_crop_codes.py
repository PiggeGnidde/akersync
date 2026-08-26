from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location(
    "akerminne_official_crop_codes",
    ROOT / "src" / "60_apply_akerminne_official_crop_codes.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load official crop-code module")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

DICT_DIR = ROOT / "data" / "reference" / "akerminne_crop_codes_official"
MANIFEST = DICT_DIR / "manifest.json"


class OfficialCropCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables, cls.meta = mod.load_official_tables(DICT_DIR, MANIFEST)

    def test_all_years_and_total_rows(self):
        self.assertEqual(sorted(self.tables), list(range(2015, 2026)))
        self.assertEqual(self.meta["manifest"]["total_normalized_rows"], 1572)
        self.assertEqual(sum(v["rows"] for v in self.meta["verified"].values()), 1572)

    def test_2015_winter_wheat_anchor(self):
        self.assertEqual(mod.lookup(self.tables, 2015, "4", None), ("Vete (höst)", None))

    def test_2019_matlok_undercode_anchor(self):
        self.assertEqual(mod.lookup(self.tables, 2019, "74", "119"), ("Matlök", None))

    def test_no_cross_year_undercode_fallback(self):
        self.assertNotEqual(mod.lookup(self.tables, 2018, "74", "119"), ("Matlök", None))
        self.assertEqual(mod.lookup(self.tables, 2018, "74", "119"), ("Grönsaksodling (köksväxter)", None))

    def test_unknown_stays_explicit(self):
        self.assertIsNone(mod.lookup(self.tables, 2015, "999999", None))
        self.assertEqual(mod.unknown_crop_label("999999", 2015), "Okänd grödkod 999999 (2015)")

    def test_relabel_is_label_only(self):
        components = pd.DataFrame({
            "history_year": [2015],
            "current_field_id": ["A|1"],
            "crop_code_raw": ["4"],
            "crop_subcategory_raw": [None],
            "crop_name": ["Okänd grödkod 4 (2015)"],
            "crop_group": ["UNKNOWN"],
            "crop_known": [False],
            "intersection_m2": [123.0],
            "share_current": [0.5],
        })
        after = mod.relabel_components(components, self.tables)
        mod.assert_label_only(components, after, mod.COMP_LABEL_COLUMNS)
        self.assertEqual(after.loc[0, "crop_name"], "Vete (höst)")
        self.assertTrue(bool(after.loc[0, "crop_known"]))
        self.assertEqual(after.loc[0, "intersection_m2"], 123.0)
        self.assertEqual(after.loc[0, "share_current"], 0.5)


if __name__ == "__main__":
    unittest.main()
