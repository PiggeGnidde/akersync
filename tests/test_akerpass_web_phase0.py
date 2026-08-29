from __future__ import annotations

import runpy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

ENRICH = runpy.run_path(str(SRC / "41b_enrich_akerpass_phase0_web.py"), run_name="phase0_enrich")
PATCH = runpy.run_path(str(SRC / "42b_patch_akerpass_frontend_phase0.py"), run_name="phase0_patch")


def base_row(**overrides):
    row = {
        "dominant_soil_class": 3,
        "dominant_soil_class_share": 0.75,
        "soil_class_count": 2,
        "soil_class_coverage_unique": 0.98,
        "unclassified_soil_share": 0.02,
        "mixed_soil_class": True,
        "dominant_sko_id": "0731",
        "dominant_sko_share": 1.0,
        "sko_count": 1,
        "sko_coverage_unique": 1.0,
        "crosses_sko_boundary": False,
        "context_status": "COMPLETE_MIXED_SOIL_CLASS",
        "reason_flags": "MULTIPLE_SOIL_CLASSES",
        "source_manifest_id": "freeze-test",
    }
    row.update(overrides)
    return row


class AkerpassWebPhase0Tests(unittest.TestCase):
    def test_enrichment_preserves_leading_zero_sko_and_class_1_10(self):
        props = {"id": "1|A", "model_versions": {"akerscore": "unchanged"}}
        ENRICH["enrich_properties"](props, base_row())
        self.assertEqual(props["historic_class"], 3)
        self.assertEqual(props["historic_class_status"], "class_1_10")
        self.assertEqual(props["sko_id"], "0731")
        self.assertIsInstance(props["sko_id"], str)
        self.assertEqual(props["model_versions"]["akerscore"], "unchanged")
        self.assertEqual(
            props["model_versions"]["akerprestation_phase0"],
            "akerprestation-phase0-v0a",
        )

    def test_missing_historic_class_is_explicit_and_not_imputed(self):
        props = {"id": "2|B"}
        ENRICH["enrich_properties"](
            props,
            base_row(
                dominant_soil_class=None,
                dominant_soil_class_share=0.0,
                soil_class_count=0,
                soil_class_coverage_unique=0.0,
                unclassified_soil_share=1.0,
                mixed_soil_class=False,
            ),
        )
        self.assertIsNone(props["historic_class"])
        self.assertEqual(
            props["historic_class_status"],
            "not_classified_in_historic_reference",
        )
        self.assertEqual(
            props["historic_class_status_label"],
            "Ingen historisk klass i referensunderlaget",
        )

    def test_microscopic_class_touch_at_phase0_missing_tolerance_is_suppressed(self):
        props = {"id": "tiny|A"}
        ENRICH["enrich_properties"](
            props,
            base_row(
                dominant_soil_class=6,
                dominant_soil_class_share=1.0,
                soil_class_count=1,
                soil_class_coverage_unique=5e-7,
                unclassified_soil_share=0.9999995,
                mixed_soil_class=False,
            ),
        )
        self.assertIsNone(props["historic_class"])
        self.assertEqual(props["historic_class_status"], "not_classified_in_historic_reference")
        self.assertIsNone(props["historic_class_dominant_share"])
        self.assertEqual(props["historic_class_count"], 0)
        self.assertFalse(props["historic_class_mixed"])

    def test_class_above_phase0_missing_tolerance_is_kept(self):
        props = {"id": "small|A"}
        ENRICH["enrich_properties"](
            props,
            base_row(
                dominant_soil_class=6,
                dominant_soil_class_share=1.0,
                soil_class_count=1,
                soil_class_coverage_unique=2e-6,
                unclassified_soil_share=0.999998,
                mixed_soil_class=False,
            ),
        )
        self.assertEqual(props["historic_class"], 6)
        self.assertEqual(props["historic_class_status"], "class_1_10")

    def test_sko_source_and_dominant_domains_are_distinct(self):
        source_ids = ENRICH["EXPECTED_SKO_SOURCE_IDS"]
        dominant_ids = ENRICH["EXPECTED_DOMINANT_SKO_IDS"]
        self.assertEqual(len(source_ids), 18)
        self.assertEqual(len(dominant_ids), 17)
        self.assertIn("1011", source_ids)
        self.assertNotIn("1011", dominant_ids)
        self.assertIn("0731", dominant_ids)

    def test_frontend_patch_requires_exactly_one_marker(self):
        replace_once = PATCH["replace_once"]
        self.assertEqual(
            replace_once("abc OLD def", "OLD", "NEW", "test"),
            "abc NEW def",
        )
        with self.assertRaises(RuntimeError):
            replace_once("OLD OLD", "OLD", "NEW", "test")


if __name__ == "__main__":
    unittest.main()
