from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


value_builder = load_script("akervarde_public", "40_build_akervarde_public_index.py")
data_builder = load_script("akerpass_public", "41_build_akerpass_public_data.py")
verifier = load_script("akerpass_verify", "43_verify_akerpass_web_v1.py")


class PublicValueIndexTests(unittest.TestCase):
    def test_reference_rate_becomes_index_100_without_effects(self):
        coefficients = {
            "arable_log_rate0": math.log(600_000),
            "arable_year_centered": 0.0,
            "arable_log_area_20": 0.0,
            "arable_lat_centered": 0.0,
            "arable_lon_centered": 0.0,
        }
        features = pd.DataFrame({
            "blockid": ["1"], "skiftesbeteckning": ["A"], "kommun": ["Lomma"],
            "area_ha": [20.0], "lat": [55.5], "lon": [13.0],
        })
        public = value_builder.compute_public_index(features, coefficients)
        self.assertEqual(list(public.columns), list(value_builder.PUBLIC_COLUMNS))
        self.assertAlmostEqual(public.loc[0, "akervarde"], 100.0, places=4)
        self.assertAlmostEqual(public.loc[0, "akervarde_p10"], 82.56, places=4)
        self.assertAlmostEqual(public.loc[0, "akervarde_p90"], 148.86, places=4)
        self.assertFalse(any("price" in column or "kr" in column for column in public.columns))


class PublicFieldTests(unittest.TestCase):
    def test_field_merge_keeps_three_dimensions_separate(self):
        source = {
            "type": "Feature",
            "properties": {"blockid": "7", "skiftesbeteckning": "B", "grdkod_mar": 4, "inside_pct": 99.8},
            "geometry": {"type": "Polygon", "coordinates": [[[13, 55], [13.1, 55], [13.1, 55.1], [13, 55]]]},
        }
        result = data_builder.build_field_feature(
            source, "Lomma", {"7|B": {"clay": [30, 2, 25, 30, 35, 31, 100, 20]}},
            {"7|B": {"area_ha": 12.3, "rectangularity": .8}},
            {"7|B": {"akerscore_soil_p10": 88, "akerscore_soil_p50": 93, "akerscore_soil_p90": 97, "soil_coverage_pct": 100, "soil_pixels_total": 20, "soil_pixels_valid": 20}},
            {"7|B": {"akervarde": 70, "akervarde_p10": 57.792, "akervarde_p90": 104.202, "akervarde_model_version": "akervarde-v1.0-rc1"}},
            {"7|B": {"akerdrift_score": 84, "drift_status": "OK", "drift_model_version": "akerdrift-fast-v2-hybrid-rc1", "drift_score_source": "FAST_V2_ROUTECAL", "fast_v1_akerdrift_score": 79, "score_delta_hybrid_minus_v1": 5, "geometry_score": 88, "drift_terrain_factor": .95}},
            {"7": {"elev_mean_m": 10}}, {"7": {"twi_mean": 8}}, {"4": "Vete (höst)"},
        )
        props = result["properties"]
        self.assertEqual(props["model_versions"]["product"], "akerpass-mvp-v1.1")
        self.assertEqual(props["model_versions"]["dataset"], "akerpass-public-v1.1")
        self.assertEqual(props["akerscore"], 93)
        self.assertEqual(props["akervarde"], 70)
        self.assertEqual(props["akervarde_applicability"], "applicable")
        self.assertEqual(props["land_use_group"], "arable")
        self.assertEqual(props["crop_year"], 2025)
        self.assertEqual(props["akerdrift"], 84)
        self.assertEqual(props["akerdrift_status"], "OK")
        self.assertEqual(props["akerdrift_details"]["geometry_score"], 88)
        self.assertNotIn("score_source", props["akerdrift_details"])
        self.assertNotIn("fast_v1_score", props["akerdrift_details"])
        self.assertNotIn("hybrid_delta_vs_v1", props["akerdrift_details"])
        self.assertEqual(props["historic_class"], None)
        self.assertEqual(props["historic_class_status"], "not_in_imported_class_5_10")
        data_builder.assert_public_keys(result)

    def test_pasture_suppresses_all_three_arable_dimensions(self):
        source = {
            "type": "Feature",
            "properties": {"blockid": "8", "skiftesbeteckning": "A", "grdkod_mar": 52},
            "geometry": {"type": "Polygon", "coordinates": [[[13, 55], [13.1, 55], [13.1, 55.1], [13, 55]]]},
        }
        result = data_builder.build_field_feature(
            source, "Vellinge", {"8|A": {}}, {"8|A": {"area_ha": 229}},
            {"8|A": {"akerscore_soil_p10": 20, "akerscore_soil_p50": 26, "akerscore_soil_p90": 34, "soil_pixels_total": 100, "soil_pixels_valid": 100}},
            {"8|A": {"akervarde": 96, "akervarde_p10": 79, "akervarde_p90": 143}},
            {"8|A": {"akerdrift_score": 75, "drift_status": "OK", "drift_model_version": "akerdrift-fast-v2-hybrid-rc1", "drift_score_source": "FAST_V1_FALLBACK_OUTSIDE_CALIBRATION"}},
            {}, {}, {"52": "Betesmark"},
        )
        props = result["properties"]
        self.assertIsNone(props["akerscore"])
        self.assertIsNone(props["akerscore_p10"])
        self.assertIsNone(props["akerscore_p90"])
        self.assertIsNone(props["akervarde"])
        self.assertIsNone(props["akervarde_p10"])
        self.assertIsNone(props["akervarde_p90"])
        self.assertEqual(props["land_use_group"], "pasture")
        self.assertEqual(props["arable_applicability"], "not_applicable")
        self.assertEqual(props["akervarde_applicability"], "not_applicable")
        self.assertIsNone(props["akerdrift"])
        self.assertEqual(props["akerdrift_status"], "NOT_APPLICABLE_LAND_USE")
        self.assertEqual(props["akerdrift_details"], {})

    def test_flowering_arable_code_remains_applicable(self):
        use = data_builder.land_use("318")
        self.assertEqual(use["group"], "arable")
        self.assertEqual(use["arable_applicability"], "applicable")
        self.assertEqual(use["akervarde_applicability"], "applicable")

    def test_missing_score_reports_insufficient_soil_pixels(self):
        status, reason = data_builder.score_status({"soil_pixels_total": 10, "soil_pixels_valid": 2})
        self.assertEqual(status, "insufficient_valid_soil_pixels")
        self.assertIn("Färre än tre", reason)


class VerificationTests(unittest.TestCase):
    def test_chunk_accepts_value_above_100(self):
        document = {
            "product_version": "akerpass-mvp-v1.1",
            "dataset_version": "akerpass-public-v1.1",
            "fields": {"features": [{"properties": {
                "akerscore": 95, "akerscore_p10": 90, "akerscore_p90": 98,
                "akervarde": 125, "akervarde_p10": 103, "akervarde_p90": 186,
                "akervarde_applicability": "applicable", "land_use_group": "arable", "crop_year": 2025,
                "arable_applicability": "applicable",
                "historic_class": 9, "historic_class_status": "class_5_10",
                "akerdrift": 84, "akerdrift_status": "OK",
                "akerdrift_details": {"geometry_score": 88, "drift_terrain_factor": .95},
                "model_versions": {
                    "product": "akerpass-mvp-v1.1",
                    "akerscore": "akerscore-soil-v0c",
                    "akervarde": "akervarde-v1.0-rc1",
                    "akerdrift": "akerdrift-fast-v2-hybrid-rc1",
                    "dataset": "akerpass-public-v1.1",
                },
            }}]},
            "blocks": {"features": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            fields, blocks, scores, values, drifts, over_100, value_min, value_max = verifier.check_document(path)
        self.assertEqual((fields, blocks, scores, values, drifts, over_100), (1, 0, 1, 1, 1, 1))
        self.assertEqual((value_min, value_max), (125, 125))

    def test_synthetic_33_municipality_build(self):
        persistent = os.environ.get("AKERPASS_TEST_OUTPUT")
        context = nullcontext(persistent) if persistent else tempfile.TemporaryDirectory()
        with context as tmp:
            work = Path(tmp)
            work.mkdir(parents=True, exist_ok=True)
            derived = work / "derived"
            dist = work / "dist"
            public = derived / "akerpass_public_v1"
            score_dir = derived / "akerscore_soil_v0c"
            public.mkdir(parents=True)
            score_dir.mkdir(parents=True)

            geometry_payload = {}
            soil_payload = {}
            geometry_rows = []
            score_rows = []
            value_rows = []
            topo_rows = []
            hydro_rows = []
            drift_rows = []
            for index, (municipality, code) in enumerate(data_builder.MUN_CODES.items()):
                blockid = f"{code}0001"
                skifte = "A"
                x = 12.5 + index * 0.01
                y = 55.5 + index * 0.005
                polygon = {"type": "Polygon", "coordinates": [[[x, y], [x + .004, y], [x + .004, y + .003], [x, y + .003], [x, y]]]}
                geometry_payload[municipality] = {
                    "blocks": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"blockid": blockid}, "geometry": polygon}]},
                    "skiften": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"blockid": blockid, "skiftesbeteckning": skifte, "grdkod_mar": 4, "inside_pct": 100}, "geometry": polygon}]},
                }
                soil_payload[municipality] = {"skiften": {f"{blockid}|{skifte}": {
                    "clay": [30, 2, 25, 30, 35, 30, 100, 20],
                    "silt": [40, 2, 35, 40, 45, 40, 100, 20],
                    "sand": [30, 2, 25, 30, 35, 30, 100, 20],
                    "organic": [4, 0, 100, 20],
                }}}
                geometry_rows.append({"kommun": municipality, "blockid": blockid, "skiftesbeteckning": skifte, "area_ha": 12, "rectangularity": .9, "convexity": .95, "compactness_4piA_P2": .7, "mbr_aspect_ratio": 1.5})
                score_rows.append({"blockid": blockid, "skiftesbeteckning": skifte, "akerscore_soil_p10": 80, "akerscore_soil_p50": 90, "akerscore_soil_p90": 96, "soil_coverage_pct": 100, "soil_pixels_total": 20, "soil_pixels_valid": 20, "historic_class_qa": 9})
                value_rows.append({"kommun": municipality, "blockid": blockid, "skiftesbeteckning": skifte, "akervarde": 125, "akervarde_p10": 103.2, "akervarde_p90": 186.1, "akervarde_model_version": "akervarde-v1.0-rc1"})
                topo_rows.append({"municipality": municipality, "blockid": blockid, "elev_mean_m": 20, "slope_mean_deg": 1})
                hydro_rows.append({"municipality": municipality, "blockid": blockid, "twi_mean": 8, "twi_p90": 12})
                drift_rows.append({
                    "kommun": municipality, "block_id": blockid, "skifte_id": skifte,
                    "akerdrift_score": 84, "drift_model_version": "akerdrift-fast-v2-hybrid-rc1",
                    "drift_score_source": "FAST_V2_ROUTECAL",
                    "fast_v1_akerdrift_score": 79, "score_delta_hybrid_minus_v1": 5,
                    "drift_status": "OK", "geometry_score": 88,
                    "drift_terrain_factor": .95, "drift_slope_coverage": 1.0,
                    "drift_twi_status": "OK",
                })

            (derived / "geometry_payload.json").write_text(json.dumps(geometry_payload), encoding="utf-8")
            (derived / "soil_payload.json").write_text(json.dumps(soil_payload), encoding="utf-8")
            pd.DataFrame(geometry_rows).to_csv(derived / "geometry_v1a_skiften.csv", index=False)
            pd.DataFrame(score_rows).to_csv(score_dir / "akerscore_soil_skiften.csv", index=False)
            pd.DataFrame(value_rows).to_csv(public / "akervarde_public_skiften.csv", index=False)
            pd.DataFrame(topo_rows).to_csv(derived / "topography_features_blocks.csv", index=False)
            pd.DataFrame(hydro_rows).to_csv(derived / "hydrology_features_final.csv", index=False)
            drift_dir = derived / "akerdrift_fast_v2_hybrid_rc1"
            drift_dir.mkdir()
            pd.DataFrame(drift_rows).to_parquet(drift_dir / "akerdrift_fast_v2_hybrid_rc1_skane.parquet", index=False)
            config = work / "config.json"
            config.write_text(json.dumps({"build_dir": str(derived), "dist_dir": str(dist)}), encoding="utf-8")

            for script in ("41_build_akerpass_public_data.py", "42_build_akerpass_frontend.py", "43_verify_akerpass_web_v1.py"):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "src" / script), "--config", str(config)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            manifest = json.loads((dist / "municipalities.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["municipality_count"], 33)
            self.assertEqual(manifest["field_count"], 33)
            self.assertEqual(manifest["product_version"], "akerpass-mvp-v1.1")
            self.assertEqual(manifest["dataset_version"], "akerpass-public-v1.1")
            self.assertEqual(manifest["akervarde_model_version"], "akervarde-v1.0-rc1")
            self.assertEqual(manifest["akerdrift_model_version"], "akerdrift-fast-v2-hybrid-rc1")


if __name__ == "__main__":
    unittest.main()
