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


def check_document(path: Path) -> tuple[int, int, int, int, int]:
    document = json.loads(path.read_text(encoding="utf-8"))
    fields = document.get("fields", {}).get("features", [])
    blocks = document.get("blocks", {}).get("features", [])
    score_count = value_count = over_100 = 0
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
        if value is not None:
            value_count += 1
            over_100 += int(float(value) > 100)
        if p.get("akerscore_p10") is not None and p.get("akerscore_p90") is not None:
            if float(p["akerscore_p10"]) > float(p["akerscore_p90"]):
                raise RuntimeError(f"{path.name}: omvänt ÅkerScore-intervall")
        if p.get("akervarde_p10") is not None and p.get("akervarde_p90") is not None:
            if float(p["akervarde_p10"]) > float(p["akervarde_p90"]):
                raise RuntimeError(f"{path.name}: omvänt ÅkerVärde-intervall")
    return len(fields), len(blocks), score_count, value_count, over_100


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    parser.add_argument("--allow-no-value-over-100", action="store_true", help="Only for tiny synthetic QA fixtures")
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
    )
    missing_ui = [text for text in required_ui if text not in html]
    if missing_ui:
        raise RuntimeError("Frontend saknar: " + ", ".join(missing_ui))
    for pattern in FORBIDDEN_UI:
        if pattern.search(html):
            raise RuntimeError(f"Publik UI innehåller förbjuden monetär text: {pattern.pattern}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    municipalities = manifest.get("municipalities", {})
    if set(municipalities) != set(MUN_CODES) or manifest.get("municipality_count") != 33:
        raise RuntimeError("Kommunmanifestet innehåller inte exakt Skånes 33 kommuner")

    totals = [0, 0, 0, 0, 0]
    for municipality, meta in municipalities.items():
        path = dist_dir / meta["file"]
        if not path.exists():
            raise FileNotFoundError(path)
        result = check_document(path)
        if result[0] != int(meta["fields"]) or result[1] != int(meta["blocks"]):
            raise RuntimeError(f"{municipality}: manifestantal stämmer inte")
        totals = [a + b for a, b in zip(totals, result)]

    if totals[0] <= 0 or totals[2] <= 0 or totals[3] <= 0:
        raise RuntimeError("Publik build saknar skiften, ÅkerScore eller ÅkerVärde")
    if totals[4] <= 0 and not args.allow_no_value_over_100:
        raise RuntimeError("Ingen ÅkerVärde-observation över 100; kontrollera indexnormaliseringen")
    if totals[0] != int(manifest.get("field_count", -1)) or totals[1] != int(manifest.get("block_count", -1)):
        raise RuntimeError("Totala manifestantal stämmer inte")

    print("AKERPASS QA: OK")
    print(f"  Kommuner: 33")
    print(f"  Skiften/block: {totals[0]:,}/{totals[1]:,}")
    print(f"  ÅkerScore/ÅkerVärde: {totals[2]:,}/{totals[3]:,}")
    print(f"  ÅkerVärde över 100: {totals[4]:,}")
    print("  Monetära UI-/exportfält: 0")
    print("  Mobilpanel + GPS watch/clear: statiskt verifierade")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
