from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("akernorm_freeze", ROOT / "src/88_verify_akernorm_v1_freeze.py")
FREEZE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(FREEZE)


class AkerNormV1FreezeTests(unittest.TestCase):
    def test_locked_product_identity(self):
        self.assertEqual(FREEZE.TAG, "akernorm-v1.0")
        self.assertEqual(FREEZE.EXPECTED_MUNICIPALITIES, 33)
        self.assertEqual(FREEZE.EXPECTED_FIELDS, 128_636)
        self.assertEqual(FREEZE.EXPECTED_ROWS, 402_922)
        self.assertEqual(len(FREEZE.FULL_OUTPUT_HASH), 64)

    def test_all_three_frozen_inputs_are_hash_locked(self):
        self.assertEqual(
            set(FREEZE.EXPECTED_INPUTS),
            {"field_static_context_selected.csv.gz", "akerminne_2015_2025_selected.csv.gz", "akerscore_soil_skiften_selected.csv.gz"},
        )
        self.assertTrue(all(len(value) == 64 for value in FREEZE.EXPECTED_INPUTS.values()))

    def test_freeze_commit_is_metadata_only(self):
        self.assertEqual(
            FREEZE.FREEZE_FILES,
            {"FREEZE_AKERNORM_V1.bat", "docs/AKERNORM_V1_FREEZE.md", "src/88_verify_akernorm_v1_freeze.py", "tests/test_akernorm_v1_freeze.py"},
        )

    def test_scope_accepts_complete_akernorm_freeze(self):
        FREEZE.verify_scope(sorted(FREEZE.FREEZE_FILES | {"src/85_build_akernorm_v1_web.py", "analysis/akernorm_v1_discovery/README.md"}))

    def test_scope_rejects_non_akernorm_path(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected paths"):
            FREEZE.verify_scope(sorted(FREEZE.FREEZE_FILES | {"src/unrelated_product.py"}))

    def test_scope_rejects_sentinel(self):
        with self.assertRaisesRegex(RuntimeError, "Sentinel-2"):
            FREEZE.verify_scope(sorted(FREEZE.FREEZE_FILES | {"analysis/akernorm_v1_discovery/sentinel_probe.txt"}))

    def test_manifest_record_hash_and_size_are_enforced(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "artifact.bin"
            path.write_bytes(b"akernorm")
            good = {"path": "artifact.bin", "bytes": 8, "sha256": FREEZE.sha256_file(path)}
            FREEZE.verify_record(root, good)
            with self.assertRaisesRegex(RuntimeError, "differs"):
                FREEZE.verify_record(root, {**good, "bytes": 9})


if __name__ == "__main__":
    unittest.main()
