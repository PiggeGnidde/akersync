from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_b2", ROOT / "src/95_akervatten_b2_nadia_validate.py"
)
assert spec and spec.loader
B2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B2)


class TestAkerVattenB2Nadia(unittest.TestCase):
    def test_recognizes_nadia_subid_label(self):
        requested = {"101","103","106","107","11"}
        self.assertEqual(B2.requested_ids_in_cell("Subid 101", requested), {"101"})
        self.assertEqual(B2.requested_ids_in_cell("SUB ID: 11", requested), {"11"})

    def test_recognizes_bare_numeric_id(self):
        requested = {"101"}
        self.assertEqual(B2.requested_ids_in_cell(101.0, requested), {"101"})

    def test_does_not_match_unrelated_number(self):
        requested = {"101"}
        self.assertEqual(B2.requested_ids_in_cell("Aroid ABC-101-XYZ", requested), set())


if __name__ == "__main__":
    unittest.main()
