from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from akernorm_v1_core import load_config


def load_pilot_module():
    spec = importlib.util.spec_from_file_location("akernorm_v1_pilot", ROOT / "src/81_run_akernorm_v1_pilot.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PILOT = load_pilot_module()
CONFIG = load_config(ROOT / "config/akernorm_v1.json")


def candidates() -> pd.DataFrame:
    specifications = [
        (4, 80, 70, 1.0, "STANDARD", 0, "1264"),
        (4, 60, 70, 1.0, "STANDARD", 0, "1264"),
        (2, 70, 60, 1.0, "STANDARD", 0, "1264"),
        (3, 70, 60, 1.0, "STANDARD", 0, "1230"),
        (20, 70, 60, 1.0, "STANDARD", 0, "1230"),
        (45, 70, None, 1.0, "STANDARD", 0, "1290"),
        (46, 70, None, 1.0, "STANDARD", 0, "1290"),
        (4, 70, 60, .90, "STANDARD", 0, "1230"),
        (20, 70, 60, 1.0, "HISTORY_COMPONENT_ONLY", 1, "1230"),
        (99, 70, None, 1.0, "STANDARD", 0, "1230"),
    ]
    rows = []
    for index, (code, score, reference, share, quality, components, municipality) in enumerate(specifications):
        rows.append({
            "current_field_id": f"f{index}", "crop_code_canonical": code, "crop_name": str(code),
            "history_year_count": 1, "history_component_year_count": components,
            "history_years": "[2025]", "history_quality": quality,
            "municipality_code": municipality, "municipality": "Test",
            "dominant_sko_id": "1214", "dominant_sko_share": share,
            "akerscore_soil_p50": score, "reference_score": reference,
            "reference_status": "INCLUDED" if reference is not None else None,
        })
    return pd.DataFrame(rows)


def official() -> pd.DataFrame:
    return pd.DataFrame([
        {"crop_code_canonical": code, "sko_id": "1214", "status": "PUBLISHED"}
        for code in (2, 3, 4, 20, 45, 46)
    ])


class AkerNormV1PilotTests(unittest.TestCase):
    def test_selection_covers_required_categories_and_is_deterministic(self):
        first_fields, first_coverage = PILOT.select_pilot(candidates(), official(), CONFIG)
        second_fields, second_coverage = PILOT.select_pilot(candidates().sample(frac=1, random_state=7), official(), CONFIG)
        self.assertEqual(first_fields, second_fields)
        pd.testing.assert_frame_equal(first_coverage, second_coverage)
        self.assertTrue(first_coverage.loc[first_coverage["required"], "status"].eq("SELECTED").all())

    def test_selection_contains_kristianstad_potato_and_skurup_grain(self):
        _, coverage = PILOT.select_pilot(candidates(), official(), CONFIG)
        selected = coverage.set_index("category")
        self.assertEqual(selected.loc["MATPOTATIS_KRISTIANSTAD", "current_field_id"], "f5")
        self.assertEqual(selected.loc["STARKELSEPOTATIS_KRISTIANSTAD", "current_field_id"], "f6")
        self.assertIn(selected.loc["HOSTVETE_PREMIUM", "current_field_id"], {"f0", "f1"})

    def test_calculation_emits_only_selected_field_history_rows(self):
        presence = candidates()[[
            "current_field_id", "crop_code_canonical", "crop_name", "history_year_count",
            "history_component_year_count", "history_years", "history_quality",
        ]]
        base = candidates()[[
            "current_field_id", "municipality_code", "municipality", "dominant_sko_id",
            "dominant_sko_share", "akerscore_soil_p50",
        ]]
        norms = pd.DataFrame([{
            "crop_code_canonical": 4, "sko_id": "1214", "status": "PUBLISHED",
            "official_norm_t_ha": 8.0,
        }])
        references = pd.DataFrame([{
            "crop_code_canonical": 4, "sko_id": "1214", "reference_score": 70.0,
            "score_min": 30.0, "score_p05_weighted": 40.0, "score_p95_weighted": 90.0,
            "score_max": 100.0,
        }])
        result = PILOT.calculate_pilot(["f0"], presence, base, norms, references, CONFIG, "source-id")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc[0, "current_field_id"], "f0")
        self.assertAlmostEqual(result.loc[0, "field_akernorm_t_ha"], 8.25)

    def test_invariant_table_passes_for_frozen_beta(self):
        references = pd.DataFrame([{
            "crop_key": "hostvete", "crop_code_canonical": 4, "sko_id": "1214",
            "reference_status": "INCLUDED", "reference_score": 70.0,
            "official_sko_norm_t_ha": 8.0,
        }])
        result = PILOT.invariant_qa(references, CONFIG)
        self.assertEqual(result.loc[0, "center_invariant"], "PASS")
        self.assertEqual(result.loc[0, "difference_invariant"], "PASS")


if __name__ == "__main__":
    unittest.main()
