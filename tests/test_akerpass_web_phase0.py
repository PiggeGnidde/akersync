from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENRICH = runpy.run_path(str(ROOT / "src" / "41b_enrich_akerpass_phase0_web.py"), run_name="phase0_enrich")
PATCH = runpy.run_path(str(ROOT / "src" / "42b_patch_akerpass_frontend_phase0.py"), run_name="phase0_patch")


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


def test_enrichment_preserves_leading_zero_sko_and_class_1_10():
    props = {"id": "1|A", "model_versions": {"akerscore": "unchanged"}}
    ENRICH["enrich_properties"](props, base_row())
    assert props["historic_class"] == 3
    assert props["historic_class_status"] == "class_1_10"
    assert props["sko_id"] == "0731"
    assert isinstance(props["sko_id"], str)
    assert props["model_versions"]["akerscore"] == "unchanged"
    assert props["model_versions"]["akerprestation_phase0"] == "akerprestation-phase0-v0a"


def test_missing_historic_class_is_explicit_and_not_imputed():
    props = {"id": "2|B"}
    ENRICH["enrich_properties"](props, base_row(dominant_soil_class=None, dominant_soil_class_share=0.0))
    assert props["historic_class"] is None
    assert props["historic_class_status"] == "not_classified_in_historic_reference"
    assert props["historic_class_status_label"] == "Ingen historisk klass i referensunderlaget"


def test_frontend_patch_requires_exactly_one_marker():
    replace_once = PATCH["replace_once"]
    assert replace_once("abc OLD def", "OLD", "NEW", "test") == "abc NEW def"
    try:
        replace_once("OLD OLD", "OLD", "NEW", "test")
    except RuntimeError:
        pass
    else:
        raise AssertionError("duplicate marker must fail")
