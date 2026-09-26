from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_a2", ROOT / "src/93_akervatten_a2_source_inventory.py"
)
assert spec and spec.loader
A2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A2)


class TestAkerVattenA2SourceInventory(unittest.TestCase):
    def test_parse_wcs_capabilities(self):
        xml = b"""<wcs:Capabilities xmlns:wcs="http://www.opengis.net/wcs/2.0" xmlns:ows="http://www.opengis.net/ows/2.0">
          <ows:ServiceIdentification><ows:ServiceTypeVersion>2.0.1</ows:ServiceTypeVersion></ows:ServiceIdentification>
          <wcs:Contents><wcs:CoverageSummary><wcs:CoverageId>foo</wcs:CoverageId></wcs:CoverageSummary></wcs:Contents>
          <wcs:ServiceMetadata><wcs:formatSupported>image/tiff</wcs:formatSupported></wcs:ServiceMetadata>
        </wcs:Capabilities>"""
        q = A2.parse_wcs_capabilities(xml)
        self.assertIn("foo", q["coverage_ids"])
        self.assertIn("image/tiff", q["formats"])
        self.assertIn("2.0.1", q["versions"])

    def test_parse_wfs_capabilities(self):
        xml = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:x="urn:x" version="2.0.0">
          <wfs:FeatureTypeList><wfs:FeatureType>
            <wfs:Name>x:test</wfs:Name><wfs:Title>Test</wfs:Title><wfs:DefaultCRS>urn:ogc:def:crs:EPSG::3006</wfs:DefaultCRS>
          </wfs:FeatureType></wfs:FeatureTypeList>
        </wfs:WFS_Capabilities>"""
        q = A2.parse_wfs_capabilities(xml)
        self.assertEqual(q["version"], "2.0.0")
        self.assertEqual(q["feature_types"][0]["name"], "x:test")
        self.assertIn("urn:ogc:def:crs:EPSG::3006", q["crs"])

    def test_feature_properties(self):
        doc = {"numberMatched": 7, "features": [{"properties": {"omrade_id": 123, "url_tidsserie": "x"}}]}
        props, n = A2.get_properties_from_feature_collection(doc)
        self.assertEqual(n, 7)
        self.assertEqual(props["omrade_id"], 123)

    def test_html_terms_case_insensitive(self):
        ok, missing = A2.html_contains_all(
            "<html>Lokal vattenföring SUBID eller AROID Från år Till och med år Total vattenföring</html>",
            ["lokal vattenföring", "subid eller aroid", "från år", "till och med år", "total vattenföring"],
        )
        self.assertTrue(ok)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
