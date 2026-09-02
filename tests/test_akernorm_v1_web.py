from __future__ import annotations

import importlib.util
import json
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


BUILD = load("akernorm_web_build_test", "src/85_build_akernorm_v1_web.py")


def record(field: str, code: int, name: str, status: str, *, years=None, norm=7.0, score=80.0,
           reference=75.0, beta=.02, adjustment=.1, value=7.1, display=7.1,
           quality="STANDARD", reasons="", support="WITHIN_P05_P95") -> dict:
    years = years or [2020, 2025]
    return {
        "schema_version": "akernorm-field-v1", "current_field_id": field,
        "municipality_code": "1290", "municipality": "Kristianstad",
        "crop_code_canonical": code, "crop_name": name,
        "history_year_count": len(years), "history_component_year_count": 0,
        "history_years": json.dumps(years, separators=(",", ":")), "history_quality": quality,
        "sko_id": "1222", "sko_share": 1.0, "official_norm_year": 2026,
        "official_sko_norm_t_ha": norm, "akerscore_value": score,
        "sko_crop_reference_score": reference, "beta_t_ha_per_score": beta,
        "adjustment_t_ha": adjustment, "field_akernorm_t_ha": value,
        "display_akernorm_t_ha": display, "model_status": status,
        "reason_flags": reasons, "score_support_status": support,
        "model_version": "akernorm-v1.0-rc1", "source_manifest_id": "source-id",
    }


class AkerNormWebTests(unittest.TestCase):
    def test_payload_covers_contract_cases_and_empty_field(self):
        rows = [
            record("w-premium", 4, "Vete (höst)", "FIELD_ADJUSTED", adjustment=.3, value=7.3, display=7.3),
            record("w-discount", 4, "Vete (höst)", "FIELD_ADJUSTED", adjustment=-.2, value=6.8, display=6.8),
            record("barley", 2, "Korn (vår)", "FIELD_ADJUSTED"),
            record("oats", 3, "Havre", "FIELD_ADJUSTED_HIGHER_UNCERTAINTY"),
            record("rape", 20, "Raps (höst)", "FIELD_ADJUSTED_WEAK_EFFECT", beta=.005),
            record("table-potato", 45, "Matpotatis", "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP", score=None, reference=None, beta=None, adjustment=None, value=None, display=None),
            record("starch-potato", 46, "Stärkelsepotatis", "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP", score=None, reference=None, beta=None, adjustment=None, value=None, display=None),
            record("component", 8, "Råg", "UNAVAILABLE_NO_OFFICIAL_NORM", norm=None, score=None, reference=None, beta=None, adjustment=None, value=None, display=None, quality="HISTORY_COMPONENT_ONLY", reasons="HISTORY_COMPONENT_ONLY;NO_PUBLISHED_2026_NORM_FOR_CROP_SKO"),
            record("low-sko", 4, "Vete (höst)", "UNAVAILABLE_LOW_SKO_SHARE", score=80, reference=75, beta=.02, adjustment=None, value=None, display=None, reasons="DOMINANT_SKO_SHARE_BELOW_0_95"),
            record("missing-score", 4, "Vete (höst)", "UNAVAILABLE_MISSING_AKERSCORE", score=None, reference=75, beta=.02, adjustment=None, value=None, display=None, reasons="MISSING_AKERSCORE_SOIL_P50", support="MISSING_AKERSCORE"),
            record("sugarbeet", 6, "Sockerbetor", "UNAVAILABLE_NO_OFFICIAL_NORM", norm=None, score=None, reference=None, beta=None, adjustment=None, value=None, display=None),
        ]
        coverage = pd.DataFrame({"current_field_id": [row["current_field_id"] for row in rows] + ["no-crops"]})
        checkpoint = {"municipality_code": "1290", "municipality": "Kristianstad", "reference_fields": len(coverage)}
        payload = BUILD.build_payload(pd.DataFrame(rows), coverage, checkpoint)
        self.assertEqual(payload["field_count"], 12)
        self.assertEqual(payload["field_crop_rows"], 11)
        self.assertEqual(payload["fields"]["no-crops"], [])
        self.assertEqual(payload["columns"], BUILD.ROW_COLUMNS)
        self.assertEqual(payload["status_counts"]["OFFICIAL_SKO_ONLY_UNVALIDATED_CROP"], 2)

    def test_payload_sorts_adjusted_then_official_then_unavailable(self):
        rows = [
            record("f", 6, "Sockerbetor", "UNAVAILABLE_NO_OFFICIAL_NORM", years=[2025], norm=None, value=None, display=None),
            record("f", 45, "Matpotatis", "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP", years=[2024], value=None, display=None),
            record("f", 4, "Vete (höst)", "FIELD_ADJUSTED", years=[2019]),
            record("f", 2, "Korn (vår)", "FIELD_ADJUSTED", years=[2025]),
        ]
        payload = BUILD.build_payload(pd.DataFrame(rows), pd.DataFrame({"current_field_id": ["f"]}), {"municipality_code": "1290", "municipality": "Kristianstad", "reference_fields": 1})
        status_index = payload["columns"].index("model_status")
        code_index = payload["columns"].index("crop_code")
        packed = payload["fields"]["f"]
        statuses = payload["dictionaries"]["model_status"]
        self.assertEqual([statuses[row[status_index]] for row in packed], ["FIELD_ADJUSTED", "FIELD_ADJUSTED", "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP", "UNAVAILABLE_NO_OFFICIAL_NORM"])
        self.assertEqual([row[code_index] for row in packed[:2]], [2, 4])

if __name__ == "__main__":
    unittest.main()
