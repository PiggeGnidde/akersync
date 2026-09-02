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

from rapskartan_s2_pilot_core import (  # noqa: E402
    ApiCache,
    STATS_URL,
    build_stat_request,
    deterministic_positions,
    image_dimensions,
    load_contract,
    parse_scl_response,
    parse_stat_response,
    period_for_year,
    request_key,
    stat_evalscript,
)


def stats_payload(valid: int = 8, missing: int = 2) -> bytes:
    names = [
        "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12",
        "NDVI", "NDRE", "EVI2", "GNDVI", "LSWI", "NIRV", "YELLOWNESS", "CLD",
    ]
    bands = {
        name: {
            "stats": {
                "sampleCount": valid + missing,
                "noDataCount": missing,
                "min": 0.1,
                "max": 0.9,
                "mean": 0.5,
                "stDev": 0.1,
                "percentiles": {"10.0": 0.2, "50.0": 0.5, "90.0": 0.8},
            }
        }
        for name in names
    }
    return json.dumps({
        "status": "OK",
        "geometryPixelCount": valid + missing,
        "data": [{
            "interval": {"from": "2024-04-10T00:00:00Z", "to": "2024-04-11T00:00:00Z"},
            "outputs": {"default": {"bands": bands}},
        }],
    }).encode()


class RapskartanS2PilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(ROOT)

    def test_contract_is_bounded_and_preblind(self):
        years = {int(x["target_year"]) for x in self.contract["pilot_strata"]}
        self.assertEqual(years, {2020, 2024})
        self.assertNotIn(2025, years)
        self.assertEqual(self.contract["expected_selected_fields"], 24)
        self.assertLessEqual(24, self.contract["resource_guards"]["maximum_selected_fields"])
        self.assertTrue(all(self.contract["forbidden_scope"].values()))

    def test_period_rejects_blind_year(self):
        self.assertEqual(
            period_for_year(2024, self.contract),
            ("2024-03-01T00:00:00Z", "2024-06-11T00:00:00Z"),
        )
        with self.assertRaisesRegex(RuntimeError, "outside the pre-2025"):
            period_for_year(2025, self.contract)

    def test_evalscript_has_all_bands_indices_and_explicit_mask(self):
        script = stat_evalscript(self.contract)
        for name in self.contract["sentinel2"]["bands"]:
            self.assertIn(name, script)
        for name in self.contract["sentinel2"]["indices"]:
            self.assertIn(name, script)
        self.assertIn('bands:["B02","B03"', script)
        self.assertNotIn('{id:"B02"}', script)
        self.assertIn("dataMask", script)
        self.assertIn("s.SCL", script)
        self.assertIn("s.CLD", script)
        for code in self.contract["cloud_mask"]["valid_scl_codes"]:
            self.assertIn(str(code), script)

    def test_stats_request_is_metric_daily_and_causal(self):
        polygon = {"type": "Polygon", "coordinates": [[[400000, 6150000], [400100, 6150000], [400100, 6150100], [400000, 6150100], [400000, 6150000]]]}
        request = build_stat_request(polygon, 2024, self.contract)
        self.assertEqual(request["aggregation"]["resx"], 10)
        self.assertEqual(request["aggregation"]["aggregationInterval"]["of"], "P1D")
        self.assertEqual(request["aggregation"]["aggregationInterval"]["lastIntervalBehavior"], "SKIP")
        self.assertEqual(request["input"]["bounds"]["properties"]["crs"].rsplit("/", 1)[-1], "32633")
        self.assertEqual(request["input"]["data"][0]["dataFilter"]["timeRange"], request["aggregation"]["timeRange"])
        self.assertNotIn("2025", json.dumps(request))

    def test_deterministic_area_positions_include_extremes(self):
        self.assertEqual(deterministic_positions(11, 3), [0, 5, 10])
        self.assertEqual(deterministic_positions(6, 6), [0, 1, 2, 3, 4, 5])
        with self.assertRaises(RuntimeError):
            deterministic_positions(2, 3)

    def test_stat_response_has_explicit_coverage_and_percentiles(self):
        rows = parse_stat_response(
            stats_payload(),
            self.contract,
            field_meta={"pilot_field_id": "x", "target_year": 2024},
            edge_rule="ORIGINAL",
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["acquisition_date"], "2024-04-10")
        self.assertEqual(row["valid_pixels"], 8)
        self.assertAlmostEqual(row["valid_pixel_fraction"], 0.8)
        self.assertEqual(row["data_quality_status"], "VALID")
        self.assertEqual(row["NDVI_p50"], 0.5)

    def test_too_few_pixels_is_not_silently_negative(self):
        rows = parse_stat_response(
            stats_payload(valid=2, missing=8),
            self.contract,
            field_meta={"pilot_field_id": "x", "target_year": 2024},
            edge_rule="BUFFER_20M",
        )
        self.assertEqual(rows[0]["data_quality_status"], "NO_DATA_TOO_FEW_PIXELS")

    def test_scl_response_preserves_class_fractions(self):
        bands = {
            f"SCL_{code}": {"stats": {"sampleCount": 10, "noDataCount": 0, "mean": 0.7 if code == 4 else 0.0}}
            for code in range(12)
        }
        body = json.dumps({
            "data": [{
                "interval": {"from": "2020-05-01T00:00:00Z", "to": "2020-05-02T00:00:00Z"},
                "outputs": {"default": {"bands": bands}},
            }]
        }).encode()
        rows = parse_scl_response(body, field_meta={"pilot_field_id": "x", "target_year": 2020})
        self.assertEqual(rows[0]["scl_4_fraction"], 0.7)
        self.assertEqual(rows[0]["source_valid_pixels"], 10)

    def test_cache_key_is_stable_and_secret_free(self):
        payload = build_stat_request(
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            2020,
            self.contract,
        )
        first = request_key(STATS_URL, payload)
        second = request_key(STATS_URL, json.loads(json.dumps(payload)))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn("CDSE_CLIENT_SECRET", json.dumps(payload))

    def test_cache_rerun_verifies_hashes_without_network(self):
        payload = {"test": "bounded"}
        key = request_key(STATS_URL, payload)
        request_bytes = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        body = b'{"status":"OK"}'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = ApiCache(root, None, offline=True)
            req, response, meta = cache._paths(key, ".json")
            req.parent.mkdir(parents=True)
            req.write_bytes(request_bytes)
            response.write_bytes(body)
            meta.write_text(json.dumps({
                "request_sha256": __import__("hashlib").sha256(request_bytes).hexdigest(),
                "response_sha256": __import__("hashlib").sha256(body).hexdigest(),
            }))
            result = cache.fetch(STATS_URL, payload, response_suffix=".json", accept="application/json")
            self.assertEqual(result.body, body)
            self.assertTrue(result.metadata["cache_hit"])
            self.assertEqual(cache.authenticated_requests, 0)

    def test_image_dimensions_are_bounded(self):
        self.assertEqual(image_dimensions((0, 0, 200, 100), 256), (256, 128))
        width, height = image_dimensions((0, 0, 20, 100), 256)
        self.assertEqual(height, 256)
        self.assertGreaterEqual(width, 32)


if __name__ == "__main__":
    unittest.main()
