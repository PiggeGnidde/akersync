from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
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


def write_sidecar_fixture(
    root: Path, *, visible_threshold: float = .01, material_threshold: float = .05,
) -> None:
    years = list(range(2015, 2026))
    fields = {}
    for field_id, dominant_code in (("f1", "4"), ("f2", "2")):
        history = []
        for year in years:
            components = [[f"{year}|{dominant_code}|", 1.0]]
            status = "SINGLE_CROP"
            if field_id == "f1" and year == 2020:
                components = [[f"{year}|4|", .94], [f"{year}|20|", .06]]
                status = "MIXED_CROPS"
            history.append({"y": year, "s": status, "c": 1.0, "i": "direct_id", "x": components})
        fields[field_id] = history
    sidecar = {
        "schema_version": "akerminne-web-v1a",
        "municipality": "Test",
        "municipality_code": "1290",
        "reference_year": 2025,
        "years": years,
        "field_count": 2,
        "thresholds": {
            "minimum_match": .01,
            "complete_coverage": .95,
            "mixed_secondary_crop": material_threshold,
            "visible_component": visible_threshold,
        },
        "crop_names": {},
        "fields": fields,
    }
    sidecar_path = root / "1290_test.json"
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
    size = sidecar_path.stat().st_size
    index = {
        "schema_version": "akerminne-skane-web-index-v1",
        "reference_year": 2025,
        "years": years,
        "municipality_count": 1,
        "field_count": 2,
        "field_years": 22,
        "sidecar_bytes": size,
        "municipalities": [{
            "municipality": "Test", "municipality_code": "1290",
            "file": "data/akerminne/1290_test.json", "field_count": 2,
            "field_years": 22, "size_bytes": size,
        }],
    }
    (root / "skane_index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


class AkerNormV1PilotTests(unittest.TestCase):
    def test_frozen_web_sidecars_preserve_material_crop_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_sidecar_fixture(root)
            grouped, sources, municipalities = PILOT.load_web_sidecar_components(
                root, {"f1", "f2"}, CONFIG, expected_municipalities=1,
            )
        material = grouped[
            grouped["current_field_id"].eq("f1")
            & grouped["history_year"].eq(2020)
            & grouped["crop_code_raw"].eq("20")
        ]
        self.assertEqual(len(material), 1)
        self.assertAlmostEqual(float(material.iloc[0]["crop_share_current"]), .06)
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(source["source_mode"] == "FROZEN_WEB_SIDECAR" for source in sources))
        self.assertTrue(all(len(source["sha256"]) == 64 for source in sources))
        self.assertEqual(set(municipalities["current_field_id"]), {"f1", "f2"})
        self.assertTrue(municipalities["municipality_code"].eq("1290").all())

    def test_frozen_web_sidecars_reject_changed_thresholds(self):
        cases = [
            ({"visible_threshold": .02}, "visible_threshold"),
            ({"material_threshold": .06}, "material_threshold"),
        ]
        for kwargs, expected_error in cases:
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_sidecar_fixture(root, **kwargs)
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    PILOT.load_web_sidecar_components(
                        root, {"f1", "f2"}, CONFIG, expected_municipalities=1,
                    )

    def test_pilot_base_uses_verified_sidecar_municipality_mapping(self):
        context = pd.DataFrame([{
            "current_field_id": "f1", "dominant_sko_id": "1214", "dominant_sko_share": 1.0,
        }])
        score = pd.DataFrame([{"current_field_id": "f1", "akerscore_soil_p50": 75.0}])
        municipalities = pd.DataFrame([{
            "current_field_id": "f1", "municipality_code": "1290", "municipality": "Kristianstad",
        }])
        result = PILOT.build_pilot_base(context, score, municipalities)
        self.assertEqual(result.loc[0, "municipality_code"], "1290")
        self.assertEqual(result.loc[0, "municipality"], "Kristianstad")

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
