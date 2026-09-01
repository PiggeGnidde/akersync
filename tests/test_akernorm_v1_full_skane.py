from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

try:
    import pyarrow  # noqa: F401
except ImportError:
    pyarrow = None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def load_full_module():
    spec = importlib.util.spec_from_file_location("akernorm_v1_full", ROOT / "src/83_run_akernorm_v1_full_skane.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


FULL = load_full_module()


def load_verifier_module():
    spec = importlib.util.spec_from_file_location("akernorm_v1_stopc", ROOT / "src/84_verify_akernorm_v1_full_skane.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


class AkerNormV1FullSkaneTests(unittest.TestCase):
    def test_field_coverage_reconciles_fields_without_history(self):
        fields = pd.DataFrame([
            {"current_field_id": "f1", "municipality_code": "1290", "municipality": "Test"},
            {"current_field_id": "f2", "municipality_code": "1290", "municipality": "Test"},
        ])
        result = pd.DataFrame([{
            "current_field_id": "f1", "crop_code_canonical": 4,
            "field_akernorm_t_ha": 8.0, "model_status": "FIELD_ADJUSTED",
        }])
        coverage = FULL.build_field_coverage(fields, result)
        self.assertEqual(len(coverage), 2)
        self.assertEqual(coverage.set_index("current_field_id").loc["f1", "field_status"], "HAS_NUMERIC_AKERNORM")
        self.assertEqual(coverage.set_index("current_field_id").loc["f2", "field_status"], "NO_DISPLAYABLE_CROP_HISTORY")

    @unittest.skipUnless(pyarrow is not None, "pyarrow is required for Parquet checkpoint test")
    def test_checkpoint_validation_rejects_tampered_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output = pd.DataFrame([{
                "current_field_id": "f1", "crop_code_canonical": 4,
                "municipality_code": "1290",
            }])
            coverage = pd.DataFrame([{"current_field_id": "f1"}])
            FULL.atomic_parquet(output, directory / "field_akernorm_v1.parquet")
            FULL.atomic_parquet(coverage, directory / "field_coverage.parquet")
            manifest = {
                "schema_version": FULL.CHECKPOINT_SCHEMA, "status": "PASS", "run_key": "key",
                "municipality_code": "1290", "field_crop_rows": 1,
                "artifacts": FULL.checkpoint_artifacts(directory),
            }
            FULL.atomic_json(manifest, directory / "checkpoint_manifest.json")
            self.assertIsNotNone(FULL.validate_checkpoint(directory, "key", {"f1"}, "1290"))
            (directory / "field_akernorm_v1.parquet").write_bytes(b"tampered")
            self.assertIsNone(FULL.validate_checkpoint(directory, "key", {"f1"}, "1290"))

    def test_output_hash_is_order_independent_and_content_sensitive(self):
        first = {
            "municipality_code": "1290", "reference_fields": 2, "field_crop_rows": 3,
            "artifacts": [{"path": "x", "bytes": 1, "sha256": "a" * 64}],
        }
        second = {
            "municipality_code": "1264", "reference_fields": 1, "field_crop_rows": 2,
            "artifacts": [{"path": "x", "bytes": 1, "sha256": "b" * 64}],
        }
        self.assertEqual(FULL.output_hash([first, second]), FULL.output_hash([second, first]))
        changed = json.loads(json.dumps(second))
        changed["artifacts"][0]["sha256"] = "c" * 64
        self.assertNotEqual(FULL.output_hash([first, second]), FULL.output_hash([first, changed]))

    def test_problem_rows_keep_blocked_and_extreme_cases(self):
        frame = pd.DataFrame([
            {
                "current_field_id": "f1", "municipality_code": "1290", "crop_code_canonical": 4,
                "model_status": "UNAVAILABLE_LOW_SKO_SHARE", "score_support_status": "NOT_APPLICABLE",
                "field_akernorm_t_ha": None,
            },
            {
                "current_field_id": "f2", "municipality_code": "1290", "crop_code_canonical": 4,
                "model_status": "FIELD_ADJUSTED", "score_support_status": "ABOVE_OBSERVED_MAX",
                "field_akernorm_t_ha": 25.0,
            },
            {
                "current_field_id": "f3", "municipality_code": "1290", "crop_code_canonical": 4,
                "model_status": "FIELD_ADJUSTED", "score_support_status": "WITHIN_P05_P95",
                "field_akernorm_t_ha": 8.0,
            },
        ])
        result = FULL.problem_rows(frame)
        self.assertEqual(set(result["current_field_id"]), {"f1", "f2"})
        self.assertIn("BLOCKED_UNAVAILABLE", result.iloc[0]["qa_categories"])
        self.assertIn("AGRONOMIC_QA_EXTREME", result.iloc[1]["qa_categories"])

    def test_independent_comparison_detects_numeric_change(self):
        expected = pd.DataFrame([{"current_field_id": "f1", "crop_code_canonical": 4, "value": 8.0}])
        actual = expected.copy()
        VERIFIER.compare_frames(actual, expected, "test")
        actual.loc[0, "value"] = 8.01
        with self.assertRaisesRegex(RuntimeError, "independent recomputation"):
            VERIFIER.compare_frames(actual, expected, "test")


if __name__ == "__main__":
    unittest.main()
