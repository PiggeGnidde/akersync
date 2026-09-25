#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from akerminne_history_core import CropRecord, CropRegistry
from analysis.akerfro_ertor_v0a.crop_groups import (
    CONSERVART,
    FABA_BEAN,
    OTHER_PEA,
    akerfro_crop_group,
)


def load_checkpoint_module():
    path = ROOT / "analysis" / "akerfro_ertor_v0a" / "checkpoint_a.py"
    spec = importlib.util.spec_from_file_location("akerfro_checkpoint_a", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerFroYearSpecificCropCodes(unittest.TestCase):
    def test_registry_never_falls_back_across_years(self):
        reg = CropRegistry(
            {
                2015: {("31", None): CropRecord("Vete (höst)")},
                2025: {("31", None): CropRecord("Konservärter")},
            }
        )
        self.assertEqual(reg.lookup(2015, 31, None).crop_name, "Vete (höst)")
        self.assertEqual(reg.lookup(2025, 31, None).crop_name, "Konservärter")
        self.assertIsNone(reg.lookup(2020, 31, None))

    def test_semantic_group_uses_name_not_numeric_code(self):
        self.assertEqual(akerfro_crop_group("Konservärter"), CONSERVART)
        self.assertEqual(akerfro_crop_group("Ärter (ej konservärter)"), OTHER_PEA)
        self.assertEqual(akerfro_crop_group("Åkerbönor"), FABA_BEAN)
        self.assertIsNone(akerfro_crop_group("Vete (höst)"))

    def test_repo_official_payloads_have_all_primary_groups_each_year(self):
        mod = load_checkpoint_module()
        tables, _ = mod.load_official_tables(mod.DEFAULT_DICT_DIR)
        audit = mod.build_mapping_audit(tables)
        main = audit[audit["official_crop_subcategory"].isna()]
        for year in mod.YEARS:
            found = set(main.loc[main["year"] == year, "akerfro_group"])
            self.assertTrue({CONSERVART, OTHER_PEA, FABA_BEAN}.issubset(found), year)

    def test_code_31_is_verified_per_year_not_assumed(self):
        mod = load_checkpoint_module()
        tables, _ = mod.load_official_tables(mod.DEFAULT_DICT_DIR)
        for year in mod.YEARS:
            rows = tables[year]
            hit = rows[
                rows["crop_code_raw"].astype(str).str.replace(".0", "", regex=False).eq("31")
                & rows["crop_subcategory_raw"].isna()
            ]
            self.assertEqual(len(hit), 1, year)
            self.assertEqual(hit.iloc[0]["crop_name"], "Konservärter", year)


if __name__ == "__main__":
    unittest.main()
