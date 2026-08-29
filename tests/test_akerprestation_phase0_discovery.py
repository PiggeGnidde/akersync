from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from akerprestation_phase0_discovery_core import (
    EXPECTED_BASE_COMMIT,
    EXPECTED_BASE_TAG,
    EXPECTED_REFERENCE_FIELDS,
    SCHEMA_VERSION,
    choose_sko_id_field,
    find_sko_feature_type,
    infer_arable_class_domain,
    leading_zero_evidence,
    renderer_class_domain,
    sha256_file,
    text_id,
)


class Phase0DiscoveryCoreTests(unittest.TestCase):
    def test_frozen_baseline_contract_is_explicit(self):
        self.assertEqual(EXPECTED_BASE_TAG, "akerminne-v1.0")
        self.assertEqual(EXPECTED_BASE_COMMIT, "4b53ab24e9822f1c36c6cc31931dba3c1855fead")
        self.assertEqual(EXPECTED_REFERENCE_FIELDS, 128636)
        self.assertEqual(SCHEMA_VERSION, "akerprestation-phase0-discovery-v0a")

    def test_renderer_domain_keeps_class_1_to_10_and_excludes_forest_from_arable(self):
        values = [
            {"value": i, "label": (
                "1 (åkermark, låg bördighet)" if i == 1 else
                "10 (åkermark, hög bördighet)" if i == 10 else
                "11 (skogsmark, hög bonitet)" if i == 11 else str(i)
            )}
            for i in range(1, 14)
        ]
        metadata = {"drawingInfo": {"renderer": {"uniqueValueInfos": values}}}
        rows = renderer_class_domain(metadata)
        self.assertEqual([row["value"] for row in rows], list(range(1, 14)))
        self.assertEqual(infer_arable_class_domain(rows), list(range(1, 11)))

    def test_sko_feature_type_is_discovered_by_title_not_hardcoded(self):
        xml = b'''<?xml version="1.0" encoding="UTF-8"?>
        <WFS_Capabilities xmlns="http://www.opengis.net/wfs/2.0">
          <FeatureTypeList>
            <FeatureType><Name>open:region</Name><Title>Region</Title></FeatureType>
            <FeatureType><Name>open:sko</Name><Title>Sk\xc3\xb6rdeomr\xc3\xa5den</Title></FeatureType>
          </FeatureTypeList>
        </WFS_Capabilities>'''
        result = find_sko_feature_type(xml)
        self.assertEqual(result["name"], "open:sko")

    def test_sko_id_selection_prefers_sko_code(self):
        describe = {"fields": [
            {"name": "fid", "type": "xsd:long"},
            {"name": "sko_kod", "type": "xsd:string"},
            {"name": "namn", "type": "xsd:string"},
        ]}
        features = [{"properties": {"fid": 1, "sko_kod": "0731", "namn": "x"}}]
        self.assertEqual(choose_sko_id_field(features, describe), "sko_kod")

    def test_leading_zero_is_preserved_as_string_evidence(self):
        result = leading_zero_evidence(["0731", "1111", "1211"])
        self.assertTrue(result["has_leading_zero"])
        self.assertIn("0731", result["sample"])

    def test_text_id_only_removes_numeric_dot_zero_suffix(self):
        self.assertEqual(text_id("0731"), "0731")
        self.assertEqual(text_id("1211.0"), "1211")

    def test_sha256_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.txt"
            p.write_text("phase0\n", encoding="utf-8")
            self.assertEqual(sha256_file(p), sha256_file(p))


if __name__ == "__main__":
    unittest.main()
