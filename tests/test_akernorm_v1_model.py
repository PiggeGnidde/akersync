from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.akernorm_v1_core import (
    build_history_presence,
    build_reference_table,
    calculate_field_crop,
    conservation_qa,
    display_round,
    joined_flags,
    load_config,
    normalize_official_norms,
    score_support_status,
    validate_config,
    weighted_mean,
    weighted_quantile,
)
from src.akernorm_v1_discovery_core import build_crop_code_contract


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config/akernorm_v1.json")


def crop(code: int):
    return next(row for row in CONFIG["crops"] if int(row["canonical_code"]) == code)


def field(score=70.0, share=1.0, sko="1214"):
    return {"current_field_id": "f1", "municipality_code": "1264", "municipality": "Skurup",
            "dominant_sko_id": sko, "dominant_sko_share": share, "akerscore_soil_p50": score}


def presence(code=4, quality="STANDARD"):
    return {"crop_code_canonical": code, "crop_name": crop(code)["canonical_name"] if code in {2,3,4,20,45,46} else "Other",
            "history_year_count": 2, "history_component_year_count": 0, "history_years": "[2024,2025]",
            "history_quality": quality}


def norm(value=8.0):
    return {"norm_t_ha": value}


def reference(value=60.0):
    return {"reference_score": value, "score_min": 30.0, "score_p05_weighted": 40.0,
            "score_p95_weighted": 90.0, "score_max": 100.0}


class AkerNormV1ModelTests(unittest.TestCase):
    def test_raw_norm_unit_conversion_to_t_per_ha(self):
        raw = 8123
        self.assertEqual(raw / 1000.0, 8.123)

    def test_missing_official_norm_remains_missing(self):
        frame = pd.DataFrame([{"crop_key":"hostvete","canonical_crop_code":4,"sko_id":"1214",
                               "raw_value":np.nan,"raw_unit":None,"norm_t_ha":np.nan,
                               "value_status":"MISSING_OR_SUPPRESSED"}])
        result = normalize_official_norms(frame)
        self.assertTrue(pd.isna(result.loc[0, "norm_t_ha"]))

    def test_annual_crop_code_contract_has_all_six_codes(self):
        contract = build_crop_code_contract(ROOT)
        self.assertEqual(contract["status"], "PASS")
        for item in contract["crops"]:
            self.assertEqual(len(item["annual_mappings"]), 11)
            self.assertTrue(all(row["status"] == "PASS" for row in item["annual_mappings"]))
        self.assertEqual({int(row["canonical_code"]) for row in CONFIG["crops"]}, {2, 3, 4, 20, 45, 46})

    def test_area_year_weighted_reference_score(self):
        self.assertEqual(weighted_mean([50, 80], [1, 3]), 72.5)

    def test_same_field_repeated_years_remains_repeated(self):
        context = pd.DataFrame([{"current_field_id":"f1","dominant_sko_id":"1214","dominant_sko_share":1.0}])
        history = pd.DataFrame([
            {"current_field_id":"f1","history_year":2024,"current_area_m2":100,"dominant_crop_code_raw":4,"dominant_crop_name":"Vete (höst)","status":"SINGLE_CROP"},
            {"current_field_id":"f1","history_year":2025,"current_area_m2":100,"dominant_crop_code_raw":4,"dominant_crop_name":"Vete (höst)","status":"SINGLE_CROP"},
        ])
        score = pd.DataFrame([{"current_field_id":"f1","akerscore_soil_p50":70}])
        norms = pd.DataFrame([{"crop_key":"hostvete","canonical_crop_code":4,"sko_id":"1214","raw_value":8000,"raw_unit":"kg/ha","norm_t_ha":8,"value_status":"PUBLISHED"}])
        refs, selected = build_reference_table(context, history, score, norms, CONFIG)
        self.assertEqual(len(selected), 2)
        self.assertEqual(int(refs.loc[0, "field_years"]), 2)
        self.assertEqual(int(refs.loc[0, "unique_fields"]), 1)

    def test_center_score_equals_official_norm(self):
        row = calculate_field_crop(field(score=60), presence(), norm(), reference(), crop(4), CONFIG, "s")
        self.assertEqual(row["field_akernorm_t_ha"], 8.0)

    def test_plus_ten_score_equals_frozen_crop_effects(self):
        for code, expected in ((4,.25),(2,.4),(3,.24),(20,.05)):
            row = calculate_field_crop(field(score=70), presence(code), norm(), reference(), crop(code), CONFIG, "s")
            self.assertAlmostEqual(row["adjustment_t_ha"], expected, places=12)

    def test_negative_score_coefficient_rejected(self):
        config = copy.deepcopy(CONFIG)
        config["crops"][0]["beta_t_ha_per_score"] = -0.1
        with self.assertRaisesRegex(ValueError, "non-negative"):
            validate_config(config)

    def test_unsupported_crop_has_no_beta(self):
        row = calculate_field_crop(field(), {**presence(4), "crop_code_canonical":99, "crop_name":"Sockerbetor"}, norm(), None, None, CONFIG, "s")
        self.assertEqual(row["model_status"], "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP")
        self.assertIsNone(row["beta_t_ha_per_score"])

    def test_table_potato_is_never_score_adjusted(self):
        row = calculate_field_crop(field(score=99), presence(45), norm(48), reference(), crop(45), CONFIG, "s")
        self.assertEqual(row["model_status"], "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP")
        self.assertIsNone(row["field_akernorm_t_ha"])

    def test_starch_potato_is_never_score_adjusted(self):
        row = calculate_field_crop(field(score=99), presence(46), norm(42), reference(), crop(46), CONFIG, "s")
        self.assertIsNone(row["adjustment_t_ha"])

    def test_low_sko_share_blocks_adjustment(self):
        row = calculate_field_crop(field(share=.949), presence(), norm(), reference(), crop(4), CONFIG, "s")
        self.assertEqual(row["model_status"], "UNAVAILABLE_LOW_SKO_SHARE")
        self.assertIsNone(row["field_akernorm_t_ha"])

    def test_missing_score_is_status_not_zero(self):
        row = calculate_field_crop(field(score=None), presence(), norm(), reference(), crop(4), CONFIG, "s")
        self.assertEqual(row["model_status"], "UNAVAILABLE_MISSING_AKERSCORE")
        self.assertIsNone(row["field_akernorm_t_ha"])

    def test_missing_reference_gives_official_only(self):
        row = calculate_field_crop(field(), presence(), norm(), None, crop(4), CONFIG, "s")
        self.assertEqual(row["model_status"], "OFFICIAL_SKO_ONLY_REFERENCE_UNAVAILABLE")

    def test_crop_outside_history_is_not_created(self):
        history = pd.DataFrame([{"current_field_id":"f1","history_year":2025,"dominant_crop_code_raw":4,"dominant_crop_name":"Vete (höst)","status":"SINGLE_CROP"}])
        result = build_history_presence(history, None, CONFIG)
        self.assertEqual(result["crop_code_canonical"].tolist(), [4])

    def test_material_component_is_quality_marked(self):
        history = pd.DataFrame([{"current_field_id":"f1","history_year":2025,"dominant_crop_code_raw":4,"dominant_crop_name":"Vete (höst)","status":"MIXED_CROPS"}])
        components = pd.DataFrame([
            {"current_field_id":"f1","history_year":2025,"crop_code_raw":4,"crop_share_current":.7},
            {"current_field_id":"f1","history_year":2025,"crop_code_raw":20,"crop_share_current":.3},
        ])
        result = build_history_presence(history, components, CONFIG)
        rape = result[result["crop_code_canonical"].eq(20)].iloc[0]
        self.assertEqual(rape["history_quality"], "HISTORY_COMPONENT_ONLY")

    def test_component_below_frozen_threshold_is_absent(self):
        history = pd.DataFrame([{"current_field_id":"f1","history_year":2025,"dominant_crop_code_raw":4,"dominant_crop_name":"Vete (höst)","status":"MIXED_CROPS"}])
        components = pd.DataFrame([{"current_field_id":"f1","history_year":2025,"crop_code_raw":20,"crop_share_current":.049}])
        result = build_history_presence(history, components, CONFIG)
        self.assertNotIn(20, result["crop_code_canonical"].tolist())

    def test_display_rounding_does_not_change_machine_value(self):
        row = calculate_field_crop(field(score=67), presence(), norm(), reference(), crop(4), CONFIG, "s")
        self.assertAlmostEqual(row["field_akernorm_t_ha"], 8.175)
        self.assertEqual(row["display_akernorm_t_ha"], 8.2)
        self.assertEqual(display_round(8.25), 8.3)

    def test_reason_flags_are_deterministic(self):
        self.assertEqual(joined_flags(["Z", "A", "Z", ""]), "A;Z")

    def test_score_support_flags_and_no_clamp(self):
        self.assertEqual(score_support_status(20, reference()), "BELOW_OBSERVED_MIN")
        row = calculate_field_crop(field(score=20), presence(), norm(), reference(), crop(4), CONFIG, "s")
        self.assertAlmostEqual(row["field_akernorm_t_ha"], 7.0)
        self.assertEqual(row["score_support_status"], "BELOW_OBSERVED_MIN")

    def test_weighted_quantiles_are_deterministic(self):
        self.assertEqual(weighted_quantile([10,20,30], [1,1,8], [.05,.5,.95]), [10.,30.,30.])

    def test_conservation_property(self):
        selected = pd.DataFrame({"crop_code_canonical":[4,4],"dominant_sko_id":["1214","1214"],
                                 "akerscore_soil_p50":[50.,80.],"weight_m2":[1.,3.]})
        result = conservation_qa(selected, CONFIG)
        self.assertEqual(result.loc[0, "status"], "PASS")
        self.assertLessEqual(result.loc[0, "absolute_error_t_ha"], 1e-12)

    def test_two_field_difference_invariant(self):
        first = calculate_field_crop(field(score=80), presence(), norm(), reference(), crop(4), CONFIG, "s")
        second = calculate_field_crop(field(score=55), presence(), norm(), reference(), crop(4), CONFIG, "s")
        self.assertAlmostEqual(first["field_akernorm_t_ha"] - second["field_akernorm_t_ha"], .025 * 25)

    def test_missing_norm_is_unavailable(self):
        row = calculate_field_crop(field(), presence(), None, reference(), crop(4), CONFIG, "s")
        self.assertEqual(row["model_status"], "UNAVAILABLE_NO_OFFICIAL_NORM")


if __name__ == "__main__":
    unittest.main()
