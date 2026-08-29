#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerprestation_phase0_akerminne_contract import discover_frozen_or_contract


class AkerMinneContractFallbackTests(unittest.TestCase):
    def test_missing_history_artifact_uses_freeze_contract_identity_domain(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "docs").mkdir(parents=True)
            (repo / "docs" / "AKERMINNE_V1_FREEZE.md").write_text("immutable-contract", encoding="utf-8")

            def strict(*_args, **_kwargs):
                return {"status": "FAIL", "reason": "not retained"}, None, None

            with mock.patch("akerprestation_phase0_akerminne_contract._canonical_history_artifacts", return_value=[]), \
                 mock.patch("akerprestation_phase0_akerminne_contract._freeze_contract_text", return_value="immutable-contract"), \
                 mock.patch("akerprestation_phase0_akerminne_contract._reference_hash_from_discovery", return_value=("same-hash", {"manifest_id": "m1"}, {})), \
                 mock.patch("akerprestation_phase0_akerminne_contract._current_municipality_ids", return_value=({"b1|s1", "b2|s2"}, "same-hash")):
                qa, frame, before = discover_frozen_or_contract(
                    repo, "1264", "Skurup", {"b1|s1", "b2|s2"}, strict
                )

            self.assertEqual(qa["status"], "PASS")
            self.assertEqual(qa["verification_mode"], "freeze_contract_reference_identity")
            self.assertEqual(qa["matched_pilot_ids"], 2)
            self.assertTrue(qa["join_is_one_to_one"])
            self.assertTrue(qa["expected_11_year_rows"])
            self.assertFalse(qa["frozen_history_artifact_available"])
            self.assertEqual(set(frame["current_field_id"]), {"b1|s1", "b2|s2"})
            self.assertEqual(set(frame["history_year"]), {2025})
            self.assertIsNotNone(before)

    def test_invalid_retained_canonical_artifact_is_not_masked_by_contract(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            retained = repo / "akerminne_year_summary_classified.parquet"
            retained.write_bytes(b"bad")

            def strict(*_args, **_kwargs):
                return {"status": "FAIL", "reason": "validation failed"}, None, None

            with mock.patch("akerprestation_phase0_akerminne_contract._canonical_history_artifacts", return_value=[retained]):
                qa, frame, before = discover_frozen_or_contract(
                    repo, "1264", "Skurup", {"b1|s1"}, strict
                )

            self.assertEqual(qa["status"], "FAIL")
            self.assertEqual(qa["verification_mode"], "failed_retained_artifact_validation")
            self.assertIsNone(frame)
            self.assertIsNone(before)


if __name__ == "__main__":
    unittest.main()
