#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerprestation_phase0_skane_core import (
    build_class_municipality_rows,
    field_id_digest,
    municipality_validation,
    overall_acceptance,
)


class SkanePhase0CoreTests(unittest.TestCase):
    def test_field_id_digest_is_order_independent(self):
        self.assertEqual(field_id_digest(["b", "a"]), field_id_digest(["a", "b"]))

    def test_municipality_allows_historical_soil_gap_but_not_missing_sko(self):
        ids = {"b1|s1", "b2|s2"}
        soil_summary = pd.DataFrame([
            {"current_field_id": "b1|s1", "soil_class_coverage_unique": 1.0, "soil_class_coverage_raw": 1.0, "mixed_soil_class": False, "soil_class_geometry_status": "OK", "soil_class_reason_flags": ""},
            {"current_field_id": "b2|s2", "soil_class_coverage_unique": 0.0, "soil_class_coverage_raw": 0.0, "mixed_soil_class": False, "soil_class_geometry_status": "OK", "soil_class_reason_flags": "MISSING_SOIL_CLASS"},
        ])
        soil_components = pd.DataFrame([{"current_field_id": "b1|s1", "soil_class_normalized": 4}])
        sko_summary = pd.DataFrame([
            {"current_field_id": x, "sko_coverage_unique": 1.0, "sko_coverage_raw": 1.0, "crosses_sko_boundary": False, "sko_geometry_status": "OK", "sko_reason_flags": ""}
            for x in sorted(ids)
        ])
        sko_components = pd.DataFrame([{"current_field_id": x, "sko_id": "1211"} for x in sorted(ids)])
        qa = municipality_validation(
            code="1264", municipality="Skurup", expected_ids=ids,
            soil_summary=soil_summary, soil_components=soil_components,
            sko_summary=sko_summary, sko_components=sko_components,
            soil_manifest={"summary_rows": 2, "component_rows": 1},
            sko_manifest={"summary_rows": 2, "component_rows": 2},
        )
        self.assertEqual(qa["status"], "PASS")
        self.assertEqual(qa["soil"]["missing_fields"], 1)

        sko_summary.loc[sko_summary["current_field_id"] == "b2|s2", "sko_coverage_unique"] = 0.0
        qa2 = municipality_validation(
            code="1264", municipality="Skurup", expected_ids=ids,
            soil_summary=soil_summary, soil_components=soil_components,
            sko_summary=sko_summary, sko_components=sko_components,
            soil_manifest={"summary_rows": 2, "component_rows": 1},
            sko_manifest={"summary_rows": 2, "component_rows": 2},
        )
        self.assertEqual(qa2["status"], "FAIL")
        self.assertTrue(any("no SKO coverage" in x for x in qa2["errors"]))

    def test_unverified_class_component_is_hard_fail(self):
        ids = {"a"}
        soil_summary = pd.DataFrame([{"current_field_id": "a", "soil_class_coverage_unique": 1.0, "soil_class_coverage_raw": 1.0, "mixed_soil_class": False, "soil_class_geometry_status": "OK", "soil_class_reason_flags": ""}])
        soil_components = pd.DataFrame([{"current_field_id": "a", "soil_class_normalized": pd.NA}])
        sko_summary = pd.DataFrame([{"current_field_id": "a", "sko_coverage_unique": 1.0, "sko_coverage_raw": 1.0, "crosses_sko_boundary": False, "sko_geometry_status": "OK", "sko_reason_flags": ""}])
        sko_components = pd.DataFrame([{"current_field_id": "a", "sko_id": "0731"}])
        qa = municipality_validation(
            code="x", municipality="X", expected_ids=ids,
            soil_summary=soil_summary, soil_components=soil_components,
            sko_summary=sko_summary, sko_components=sko_components,
            soil_manifest={"summary_rows": 1, "component_rows": 1},
            sko_manifest={"summary_rows": 1, "component_rows": 1},
        )
        self.assertEqual(qa["status"], "FAIL")

    def test_class_municipality_rows_preserve_unclassified_gap(self):
        context = pd.DataFrame([{"current_field_id": "a", "municipality_code": "1", "municipality": "M", "field_area_m2": 100.0, "soil_class_coverage_unique": 0.75}])
        components = pd.DataFrame([{"current_field_id": "a", "soil_class_normalized": 3, "intersection_area_m2": 75.0}])
        rows = build_class_municipality_rows(context, components)
        classified = next(x for x in rows if x["soil_class"] == "3")
        gap = next(x for x in rows if x["soil_class"] == "UNCLASSIFIED")
        self.assertAlmostEqual(classified["area_m2"], 75.0)
        self.assertAlmostEqual(gap["area_m2"], 25.0)

    def test_overall_acceptance_requires_full_domain(self):
        ok = overall_acceptance(
            municipalities_passed=33, reference_fields=128636, unique_reference_fields=128636,
            classes_present=list(range(1, 11)), unverified_soil_components=0,
            unverified_sko_components=0, sko_missing_fields=0, id_set_matches=True,
            freeze_contract_ok=True,
        )
        self.assertTrue(ok["pass"])
        bad = overall_acceptance(
            municipalities_passed=33, reference_fields=128636, unique_reference_fields=128636,
            classes_present=list(range(2, 11)), unverified_soil_components=0,
            unverified_sko_components=0, sko_missing_fields=0, id_set_matches=True,
            freeze_contract_ok=True,
        )
        self.assertFalse(bad["pass"])


if __name__ == "__main__":
    unittest.main()
