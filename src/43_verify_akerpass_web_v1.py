#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static acceptance checks for the generated ÅkerPass V1 distribution."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import MUN_CODES, load_config


FORBIDDEN_KEY = re.compile(
    r"(^|_)(pred_kr_ha|base_kr_ha|predicted_price|estimated_sek|kopeskilling|"
    r"purchase_price|price_kr|value_kr|rate_per_ha)(_|$)", re.IGNORECASE
)
FORBIDDEN_UI = (
    re.compile(r"\bSEK\b", re.IGNORECASE),
    re.compile(r"\bkr(?:/ha)?\b", re.IGNORECASE),
    re.compile(r"600[\s\u00a0.]?000"),
)


def walk(value: Any):
    if isinstance(value, dict):
        for field, child in value.items():
            yield field, child
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def check_document(path: Path) -> tuple[int, int, int, int, int, float | None, float | None]:
    document = json.loads(path.read_text(encoding="utf-8"))
    fields = document.get("fields", {}).get("features", [])
    blocks = document.get("blocks", {}).get("features", [])
    score_count = value_count = over_100 = 0
    values: list[float] = []
    for field, _ in walk(document):
        if FORBIDDEN_KEY.search(str(field)):
            raise RuntimeError(f"{path.name}: förbjudet publikt fält {field}")
    for feature in fields:
        p = feature.get("properties") or {}
        if p.get("akerdrift") is not None:
            raise RuntimeError(f"{path.name}: ÅkerDrift får inte ha fabricerat värde")
        score = p.get("akerscore")
        if score is not None:
            score_count += 1
            if not 0 <= float(score) <= 100:
                raise RuntimeError(f"{path.name}: ÅkerScore utanför 0–100")
        value = p.get("akervarde")
        applicability = p.get("akervarde_applicability")
        land_use_group = p.get("land_use_group")
        if p.get("crop_year") != 2025:
            raise RuntimeError(f"{path.name}: grödans årtal är inte 2025")
        historic_class = p.get("historic_class")
        historic_status = p.get("historic_class_status")
        if historic_class is None and historic_status != "not_in_imported_class_5_10":
            raise RuntimeError(f"{path.name}: historisk klass saknar tydlig 5–10-status")
        if historic_class is not None and not 5 <= float(historic_class) <= 10:
            raise RuntimeError(f"{path.name}: historisk klass ligger utanför importerat 5–10-underlag")
        if land_use_group != "arable" and applicability == "applicable":
            raise RuntimeError(f"{path.name}: icke-åkermark har tillämpligt ÅkerVärde")
        if applicability != "applicable" and any(
            p.get(field) is not None for field in ("akervarde", "akervarde_p10", "akervarde_p90")
        ):
            raise RuntimeError(f"{path.name}: ÅkerVärde visas utanför målpopulationen")
        if value is not None:
            value_count += 1
            numeric_value = float(value)
            values.append(numeric_value)
            over_100 += int(numeric_value > 100)
        if p.get("akerscore_p10") is not None and p.get("akerscore_p90") is not None:
            if float(p["akerscore_p10"]) > float(p["akerscore_p90"]):
                raise RuntimeError(f"{path.name}: omvänt ÅkerScore-intervall")
        if p.get("akervarde_p10") is not None and p.get("akervarde_p90") is not None:
            if float(p["akervarde_p10"]) > float(p["akervarde_p90"]):
                raise RuntimeError(f"{path.name}: omvänt ÅkerVärde-intervall")
    return (
        len(fields), len(blocks), score_count, value_count, over_100,
        min(values) if values else None,
        max(values) if values else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    dist_dir = root / config.get("dist_dir", "dist")
    index = dist_dir / "index.html"
    manifest_path = dist_dir / "municipalities.json"
    if not index.exists() or not manifest_path.exists():
        raise FileNotFoundError("Saknar dist/index.html eller dist/municipalities.json")

    html = index.read_text(encoding="utf-8")
    required_ui = (
        "ÅkerScore", "ÅkerVärde", "ÅkerDrift", "Kommer senare",
        "Inomfältsvariation P10–P90", "Prediktionsintervall P10–P90",
        "watchPosition", "clearWatch", "Blockgränser", "closeDrawer",
        "Gröda 2025", "Ej tillämpligt", "akervarde_applicability",
        "Historisk jordbruksklass 1971", "Ej klass 5–10 i importerat",
        "map.panTo(target,{animate:false})", "updateGps(position,true,!followHasFix)",
        "updateGps(position,true,true)",
    )
    missing_ui = [text for text in required_ui if text not in html]
    if missing_ui:
        raise RuntimeError("Frontend saknar: " + ", ".join(missing_ui))
    if 'rel="stylesheet" href="https://unpkg.com/leaflet' in html:
        raise RuntimeError("Frontend får inte vara beroende av extern Leaflet-CSS")
    for marker in (
        ".leaflet-pane,.leaflet-tile",
        ".leaflet-tile-container",
        ".leaflet-control{position:relative",
    ):
        if marker not in html:
            raise RuntimeError("Frontend saknar inbakad Leaflet-layout: " + marker)
    # The public scale must support values above 100 even when this particular
    # frozen model/data snapshot happens not to produce one. Never fabricate a
    # field value merely to exercise the upper legend.
    for marker in ('label:">150"', "max:Infinity", 'activeLayer===\"score\"?properties.akerscore:properties.akervarde'):
        if marker not in html:
            raise RuntimeError("Frontend saknar stöd för obegränsat ÅkerVärde: " + marker)
    for pattern in FORBIDDEN_UI:
        if pattern.search(html):
            raise RuntimeError(f"Publik UI innehåller förbjuden monetär text: {pattern.pattern}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    municipalities = manifest.get("municipalities", {})
    if set(municipalities) != set(MUN_CODES) or manifest.get("municipality_count") != 33:
        raise RuntimeError("Kommunmanifestet innehåller inte exakt Skånes 33 kommuner")

    totals = [0, 0, 0, 0, 0]
    value_min = value_max = None
    for municipality, meta in municipalities.items():
        path = dist_dir / meta["file"]
        if not path.exists():
            raise FileNotFoundError(path)
        result = check_document(path)
        if result[0] != int(meta["fields"]) or result[1] != int(meta["blocks"]):
            raise RuntimeError(f"{municipality}: manifestantal stämmer inte")
        totals = [a + b for a, b in zip(totals, result[:5])]
        if result[5] is not None:
            value_min = result[5] if value_min is None else min(value_min, result[5])
            value_max = result[6] if value_max is None else max(value_max, result[6])

    if totals[0] <= 0 or totals[2] <= 0 or totals[3] <= 0:
        raise RuntimeError("Publik build saknar skiften, ÅkerScore eller ÅkerVärde")
    if totals[0] != int(manifest.get("field_count", -1)) or totals[1] != int(manifest.get("block_count", -1)):
        raise RuntimeError("Totala manifestantal stämmer inte")

    print("AKERPASS QA: OK")
    print(f"  Kommuner: 33")
    print(f"  Skiften/block: {totals[0]:,}/{totals[1]:,}")
    print(f"  ÅkerScore/ÅkerVärde: {totals[2]:,}/{totals[3]:,}")
    print(f"  ÅkerVärde min/max: {value_min:.1f}/{value_max:.1f}")
    print(f"  ÅkerVärde över 100: {totals[4]:,}")
    if totals[4] == 0:
        print("  OBS: aktuell data når inte över 100; skalan/legenden har ändå verifierat stöd utan cap.")
    print("  Monetära UI-/exportfält: 0")
    print("  Mobilpanel + GPS watch/clear: statiskt verifierade")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
