#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "dist" / "index.html"
DEFAULT_PLAN = ROOT / "data" / "derived" / "akerminne_v1a" / "skane" / "skane_plan.json"
BASE_MARKER = "AKERMINNE_PILOT_UI_V1A"
COPY_MARKER = "AKERMINNE_PILOT_UI_COPY_R1"
SKANE_MARKER = "AKERMINNE_SKANE_UI_R2"

OLD_FILES = 'const AKERMINNE_PILOT_FILES={"Skurup":"data/akerminne/1264_skurup.json"};'
OLD_SECTION = 'function akerminneSection(p){if(p.kommun!=="Skurup")return"";'
OLD_VALIDATE = 'if(data.municipality!==name||data.field_count!==2944)throw new Error("Ogiltig ÅkerMinne pilotpayload");'
OLD_MISSING = '<div class="akm-status-loading">Pilotdata saknas.</div>'


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    return "".join(ch if ch.isalnum() else "_" for ch in str(text).translate(trans).lower()).strip("_")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {count}")
    return text.replace(old, new, 1)


def load_mapping(plan_path: Path) -> dict[str, str]:
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    municipalities = doc.get("municipalities") or []
    if len(municipalities) != 33:
        raise RuntimeError("Skåne UI patch requires exactly 33 municipalities")
    mapping: dict[str, str] = {}
    for item in municipalities:
        name, code = str(item["name"]), str(item["code"])
        if name in mapping:
            raise RuntimeError(f"Duplicate municipality name: {name}")
        mapping[name] = f"data/akerminne/{code}_{_slug(name)}.json"
    return mapping


def patch_html(html: str, mapping: dict[str, str]) -> str:
    if SKANE_MARKER in html:
        return html
    if BASE_MARKER not in html or COPY_MARKER not in html:
        raise RuntimeError("ÅkerMinne base UI + copy revision R1 must be applied before Skåne R2")
    if len(mapping) != 33 or "Skurup" not in mapping:
        raise RuntimeError("Skåne mapping must contain exactly 33 municipalities including Skurup")

    mapping_js = json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))
    out = _replace_once(
        html,
        OLD_FILES,
        f"/* {SKANE_MARKER} */\nconst AKERMINNE_PILOT_FILES={mapping_js};",
        "municipality sidecar map",
    )
    out = _replace_once(
        out,
        OLD_SECTION,
        'function akerminneSection(p){if(!AKERMINNE_PILOT_FILES[p.kommun])return"";',
        "all-Skåne section gate",
    )
    out = _replace_once(
        out,
        OLD_VALIDATE,
        'if(data.municipality!==name||!Number.isInteger(data.field_count)||data.field_count<1||!data.fields||Object.keys(data.fields).length!==data.field_count)throw new Error("Ogiltig ÅkerMinne payload");',
        "generic payload validation",
    )
    if OLD_MISSING in out:
        out = _replace_once(out, OLD_MISSING, '<div class="akm-status-loading">ÅkerMinne-data saknas.</div>', "missing-data copy")

    required = (
        SKANE_MARKER,
        '"Kristianstad":"data/akerminne/1290_kristianstad.json"',
        '"Hässleholm":"data/akerminne/1293_hassleholm.json"',
        '"Skurup":"data/akerminne/1264_skurup.json"',
        'if(!AKERMINNE_PILOT_FILES[p.kommun])return"";',
        "Object.keys(data.fields).length!==data.field_count",
    )
    missing = [item for item in required if item not in out]
    if missing:
        raise RuntimeError("Skåne UI patch missing: " + ", ".join(missing))
    if 'p.kommun!=="Skurup"' in out or "field_count!==2944" in out:
        raise RuntimeError("Skurup-only UI guard remains after Skåne patch")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    ap.add_argument("--plan", default=str(DEFAULT_PLAN))
    args = ap.parse_args()
    path = Path(args.index)
    if not path.exists():
        raise FileNotFoundError(path)
    mapping = load_mapping(Path(args.plan))
    original = path.read_text(encoding="utf-8")
    patched = patch_html(original, mapping)
    if patched == original:
        print("AKERMINNE SKÅNE UI PATCH: already present")
        return 0
    tmp = path.with_suffix(".akm-skane-r2.tmp.html")
    tmp.write_text(patched, encoding="utf-8")
    if tmp.read_text(encoding="utf-8") != patched:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Skåne UI patch write verification failed")
    path.unlink(missing_ok=True)
    tmp.replace(path)
    print(f"AKERMINNE SKÅNE UI PATCH: OK · {path}")
    print(f"Municipality sidecars wired: {len(mapping)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
