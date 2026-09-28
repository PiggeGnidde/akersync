from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def load(name: str, path: str):
    spec=importlib.util.spec_from_file_location(name, ROOT/path)
    assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BUILD=load("akervatten_web_build_test","src/111_build_akervatten_web_v0a.py")
PATCH=load("akervatten_web_patch_test","src/112_patch_akervatten_web_v0a_ui.py")


def sample_row(block="1",skifte="A",kommun="Lomma"):
    return {
        "blockid":block,"skiftesbeteckning":skifte,"kommun":kommun,
        "mark_torka_score_0_100":82.1,
        "mark_vata_score_0_100":24.2,
        "groundwater_small_availability_score_0_100":61.0,
        "groundwater_drought_history_score_0_100":73.0,
        "surfacewater_drought_history_score_0_100":55.0,
        "large_gw_relation":"DIRECT_MAGAZINE",
        "large_gw_magazine_count":2,
        "large_gw_magazine_names":"Testmagasin",
        "large_gw_highest_mapped_capacity_class":"60 000–200 000 l/h",
        "large_gw_highest_mapped_capacity_lower_lps":16.6667,
        "large_gw_highest_mapped_capacity_upper_lps":55.5556,
        "large_gw_highest_mapped_capacity_position":"S1",
        "large_gw_highest_mapped_capacity_aquifer":"por- och sprickakvifer",
        "large_gw_highest_mapped_capacity_rock":"kalksten",
        "water_legal_status":"NOT_ASSESSED",
        "water_overall_verdict":"NOT_CREATED",
    }


class AkerVattenWebTests(unittest.TestCase):
    def test_payload_contract(self):
        f=pd.DataFrame([sample_row(),sample_row("2","B")])
        p=BUILD.build_field_payload(f)
        self.assertEqual(p["schema_version"],BUILD.SCHEMA)
        self.assertEqual(p["field_count"],2)
        self.assertEqual(set(p["fields"]),{"1|A","2|B"})
        self.assertEqual(p["columns"],BUILD.ROW_COLUMNS)

    def test_nonfinite_becomes_null(self):
        f=pd.DataFrame([sample_row()])
        f.loc[0,"large_gw_highest_mapped_capacity_upper_lps"]=float("inf")
        p=BUILD.build_field_payload(f)
        text=BUILD.stable_json(p,compact=True)
        self.assertNotIn("Infinity",text)
        self.assertNotIn("NaN",text)
        self.assertIn("null",text)

    def test_patch_preserves_akerfro_and_adds_water(self):
        akn="$"+"{akernormSection(p)}"
        akf="$"+"{akerfroSection(p)}"
        tick=chr(96)
        fro_controls=(
            '<label class="akf-history"><input id="akfHistoryOutline" type="checkbox"> '
            'Markera historiska konservärtsfält 2015–2025</label>\n  </div>'
        )
        html=(
            '<html><head><!-- AKERNORM_WEB_UI_V1 --><!-- AKERFRO_ERTOR_WEB_UI_V0A --></head><body>'
            '<button class="layer-button" type="button" data-layer="fro" title="Konservärt 2026 · kandidatfält">ÅkerFrö</button>'
            +fro_controls+
            '<script>function fieldPanel(p){return'+tick+' '+akn+'\n '+akf+
            '\n <details><summary>Historik / referens</summary>'+tick+'}</script>'
            '</body></html>'
        )
        mapping={}
        for i in range(33):
            n="Kristianstad" if i==0 else "Lomma" if i==1 else f"Kommun{i}"
            mapping[n]=f"data/akervatten/{i}.json"
        regional={
            "groundwater_history":"data/akervatten/groundwater_history.geojson",
            "surfacewater_history":"data/akervatten/surfacewater_history.geojson",
            "large_groundwater":"data/akervatten/large_groundwater.geojson",
        }
        out=PATCH.patch_html(html,mapping,regional)
        self.assertIn("AKERNORM_WEB_UI_V1",out)
        self.assertIn("AKERFRO_ERTOR_WEB_UI_V0A",out)
        self.assertIn("AKERVATTEN_WEB_UI_V0A",out)
        self.assertIn('data-layer="vatten"',out)
        self.assertIn("$"+"{akervattenSection(p)}",out)
        self.assertIn("Ingen totalscore",out)

    def test_patch_rejects_non_akerfro_base(self):
        with self.assertRaisesRegex(RuntimeError,"ÅkerFrö base marker"):
            PATCH.patch_html("<html></html>",{},{})


if __name__=="__main__":
    unittest.main()
