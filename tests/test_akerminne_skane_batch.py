from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prep = load("akm_skane_prepare", ROOT / "src" / "62_prepare_akerminne_skane.py")
build = load("akm_skane_build", ROOT / "src" / "63_build_akerminne_municipality.py")
run = load("akm_skane_run", ROOT / "src" / "64_run_akerminne_skane.py")
verify = load("akm_skane_verify", ROOT / "src" / "65_verify_akerminne_skane.py")

MUN_CONFIG = ROOT / "config" / "akerminne_skane_municipalities.json"
DICT_DIR = ROOT / "data" / "reference" / "akerminne_crop_codes_official"


class SkaneConfigTests(unittest.TestCase):
    def test_exactly_33_unique_municipalities(self):
        doc = prep.load_municipalities(MUN_CONFIG)
        self.assertEqual(len(doc["municipalities"]), 33)
        self.assertEqual(len({x["code"] for x in doc["municipalities"]}), 33)
        self.assertEqual(doc["expected_current_fields_total"], 128636)
        self.assertEqual(doc["smoke_codes"], ["1262", "1286"])

    def test_official_payloads_materialize_to_11_verified_csvs(self):
        with tempfile.TemporaryDirectory() as td:
            meta = prep.materialize_official_crop_codes(DICT_DIR, Path(td))
            self.assertEqual(meta["loaded_years"], list(range(2015, 2026)))
            self.assertEqual(meta["rows"], 1572)
            self.assertEqual(len(list(Path(td).glob("crop_codes_*.csv"))), 11)

    def test_slug_is_ascii_stable(self):
        self.assertEqual(build._slug("Östra Göinge"), "ostra_goinge")
        self.assertEqual(run._slug("Ängelholm"), "angelholm")
        self.assertEqual(verify._slug("Åstorp"), "astorp")


class SkaneRunnerTests(unittest.TestCase):
    def sample_plan(self):
        return {
            "municipalities": [
                {"code": "1262", "name": "Lomma", "current_fields": 10},
                {"code": "1286", "name": "Ystad", "current_fields": 20},
                {"code": "1290", "name": "Kristianstad", "current_fields": 30},
            ],
            "order_small_first": ["1262", "1286", "1290"],
        }

    def test_selection_preserves_explicit_smoke_order(self):
        selected = run.select_municipalities(self.sample_plan(), "1286,1262", None)
        self.assertEqual([x["code"] for x in selected], ["1286", "1262"])

    def test_selection_uses_small_first_and_limit(self):
        selected = run.select_municipalities(self.sample_plan(), None, 2)
        self.assertEqual([x["code"] for x in selected], ["1262", "1286"])

    def test_complete_manifest_requires_11_field_years(self):
        item = {"code": "1262", "name": "Lomma", "current_fields": 10}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = run.municipality_dir(root, item)
            d.mkdir(parents=True)
            manifest = {"schema_version": run.SCHEMA_VERSION, "municipality_code": "1262", "current_fields": 10, "field_years": 110}
            (d / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(run.is_complete(root, item))
            manifest["field_years"] = 100
            (d / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertFalse(run.is_complete(root, item))

    def test_nested_qa_totals(self):
        rows = [
            {"historical_status_counts": {"SINGLE_CROP": 5, "MIXED_CROPS": 1}},
            {"historical_status_counts": {"SINGLE_CROP": 7, "NO_PUBLIC_MATCH": 2}},
        ]
        self.assertEqual(verify._sum_nested(rows, "historical_status_counts"), {"MIXED_CROPS": 1, "NO_PUBLIC_MATCH": 2, "SINGLE_CROP": 12})


if __name__ == "__main__":
    unittest.main()
