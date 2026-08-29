#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "76_verify_akerprestation_phase0_freeze.py"
SPEC = importlib.util.spec_from_file_location("akerprestation_phase0_freeze_verify", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate_contract = MODULE.validate_contract


class FreezeContractTests(unittest.TestCase):
    def _docs(self):
        qa = {
            "status": "PASS",
            "acceptance": {"pass": True},
            "reference_fields": 128636,
            "municipalities_passed": 33,
            "municipalities_total": 33,
            "soil": {
                "classes_present": list(range(1, 11)),
                "unverified_component_rows": 0,
                "missing_fields": 17540,
                "partial_fields": 22775,
                "mixed_fields": 18439,
            },
            "sko": {
                "sko_ids_present": [
                    "0731", "1011", "1111", "1112", "1121", "1122", "1123", "1124", "1131",
                    "1211", "1212", "1213", "1214", "1215", "1216", "1221", "1222", "1321",
                ],
                "boundary_fields": 2195,
                "unverified_component_rows": 0,
                "missing_fields": 0,
            },
            "akerminne_reference": {
                "status": "PASS",
                "matched_ids": 128636,
                "verification_mode": "freeze_contract_reference_identity",
                "freeze_commit": "4b53ab24e9822f1c36c6cc31931dba3c1855fead",
            },
            "gates": {"skurup_pilot_status": "PASS", "real_class123_status": "PASS"},
            "problem_municipalities": [],
            "reference_field_id_digest": "3ef3dd23e1a91dd216f1d99497da8de8297fe16d4902ca0dc7dcaa95a366e1a0",
            "git": {"head_commit": "92c1e92535ac636e50b522f93c0e675c2b6f63ed"},
            "sources": {
                "reference_fields_sha256": "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706",
                "soil_class_sha256": "6f4375a1e0ba1f1abde13ddae70e28b6defa853019e1a3663a9ee6e9903ff4a1",
                "sko_sha256": "04ebf07a2e6b0646af0f65056fe59d198f23965fa12fb896b004e3d8fca02f31",
                "overlay_core_sha256": "ee28c510082ee0c87360ad728d84318ddccac32671f869590309d0cbcdd737b9",
            },
        }
        manifest = {
            "status": "PASS",
            "reference_fields": 128636,
            "git": {"head_commit": "92c1e92535ac636e50b522f93c0e675c2b6f63ed"},
            "sources": dict(qa["sources"]),
            "municipalities": {str(i): {"status": "PASS"} for i in range(33)},
        }
        return qa, manifest

    def test_valid_contract_passes(self):
        qa, manifest = self._docs()
        self.assertEqual(validate_contract(qa, manifest), [])

    def test_changed_source_hash_fails(self):
        qa, manifest = self._docs()
        qa["sources"]["soil_class_sha256"] = "changed"
        errors = validate_contract(qa, manifest)
        self.assertTrue(any("soil_class_sha256" in x for x in errors))

    def test_missing_class_fails(self):
        qa, manifest = self._docs()
        qa["soil"]["classes_present"] = list(range(2, 11))
        errors = validate_contract(qa, manifest)
        self.assertTrue(any("1-10" in x for x in errors))


if __name__ == "__main__":
    unittest.main()
