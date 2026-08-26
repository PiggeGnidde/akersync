from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

ROOT = Path(__file__).resolve().parents[1]
builder = load("akm_web_builder", ROOT / "src" / "57_build_akerminne_web_pilot.py")
patcher = load("akm_ui_patcher", ROOT / "src" / "59_patch_akerpass_akerminne_ui.py")


def classified_rows(status_2020="SINGLE_CROP", coverage_2020=1.0, second_2020=.04):
    rows=[]
    for year in range(2015,2026):
        status="SINGLE_CROP"; coverage=1.0; second=0.0; identity="direct_id"
        if year==2020:
            status=status_2020; coverage=coverage_2020; second=second_2020
        if year==2025:
            identity="reference_year"
        rows.append({
            "history_year":year,"current_field_id":"B|A","status":status,
            "coverage_display":coverage,"dominant_crop_code_raw":"4",
            "dominant_crop_subcategory_raw":None,"first_crop_share_grouped":max(coverage-second,0),
            "second_crop_share":second,"identity_match_confidence":identity,
            "material_overlap_anomaly":False,
        })
    return pd.DataFrame(rows)


def crops_2020(parts):
    return pd.DataFrame([
        {"history_year":2020,"current_field_id":"B|A","crop_code_raw":code,
         "crop_subcategory_raw":None,"crop_share_current":share,"crop_rank":rank}
        for rank,(code,share) in enumerate(parts,1)
    ])


def components_2020(parts):
    return pd.DataFrame([
        {"history_year":2020,"crop_code_raw":code,"crop_subcategory_raw":None,"crop_name":name}
        for code,name in parts
    ])


class WebPayloadTests(unittest.TestCase):
    cfg={"minimum_match_coverage":.01,"complete_coverage_min":.95,"mixed_secondary_crop_min_share":.05,"web_component_min_share":.01}

    def test_small_component_visible_but_not_mixed(self):
        payload=builder.build_payload(classified_rows(),crops_2020([("4",.96),("47",.04),("99",.005)]),components_2020([("4","Vete"),("47","Raps"),("99","Tiny")]),self.cfg)
        row=payload["fields"]["B|A"][5]
        self.assertEqual(row["s"],"SINGLE_CROP")
        self.assertEqual(len(row["x"]),2)
        self.assertAlmostEqual(row["x"][1][1],.04)

    def test_mixed_keeps_second_crop(self):
        payload=builder.build_payload(classified_rows("MIXED_CROPS",1.0,.08),crops_2020([("4",.92),("47",.08)]),components_2020([("4","Vete"),("47","Raps")]),self.cfg)
        row=payload["fields"]["B|A"][5]
        self.assertEqual(row["s"],"MIXED_CROPS")
        self.assertEqual(len(row["x"]),2)

    def test_no_match_has_no_visible_crop(self):
        payload=builder.build_payload(classified_rows("NO_PUBLIC_MATCH",.005,0),crops_2020([("4",.005)]),components_2020([("4","Vete")]),self.cfg)
        row=payload["fields"]["B|A"][5]
        self.assertEqual(row["s"],"NO_PUBLIC_MATCH")
        self.assertNotIn("x",row)

    def test_crop_names_are_deduplicated(self):
        payload=builder.build_payload(classified_rows(),crops_2020([("4",1.0)]),components_2020([("4","Okänd grödkod 4 (2020)"),("4","Okänd grödkod 4 (2020)")]),self.cfg)
        self.assertEqual(payload["crop_names"]["2020|4|"],"Okänd grödkod 4 (2020)")


class UiPatchTests(unittest.TestCase):
    def sample(self):
        return "<style></style><script>function fieldPanel(p){return` <details><summary>Historik / referens</summary>`} async function loadMunicipality(name){const token=1;closeDrawer();selectedFieldLayer=null;try{}}</script>"

    def test_patch_injects_ui_and_loader(self):
        out=patcher.patch_html(self.sample())
        self.assertIn("ÅkerMinne · 2015–2025",out)
        self.assertIn("loadAkerminnePilot(name,token)",out)
        self.assertIn("${akerminneSection(p)}",out)

    def test_patch_is_idempotent(self):
        once=patcher.patch_html(self.sample())
        self.assertEqual(once,patcher.patch_html(once))


if __name__=="__main__":
    unittest.main()
