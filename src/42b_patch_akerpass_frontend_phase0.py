#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch generated ÅkerPass HTML with phase-0 reference fields.

The source MVP template remains untouched. This script only changes the generated dist/index.html
and fails loudly unless the exact legacy markers are found once.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common import load_config

OLD_LABEL = "Historisk jordbruksklass 1971 — referensdata"
NEW_LABEL = "Historisk jordbruksklass — referensdata"
OLD_FALLBACK = "Ej klass 5–10 i importerat underlag"
NEW_FALLBACK = "Ingen historisk klass i referensunderlaget"
MARK_USE = '["Markanvändning 2025",p.land_use_label?esc(p.land_use_label):null]'
SKO_ROW = '["Skördeområde (SKO)",p.sko_id?esc(p.sko_id):null]'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Frontend phase0 patch: väntade exakt 1 {label}, hittade {count}")
    return text.replace(old, new, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    dist_dir = root / config.get("dist_dir", "dist")
    path = dist_dir / "index.html"
    if not path.exists():
        raise FileNotFoundError(path)

    html = path.read_text(encoding="utf-8")
    html = replace_once(html, OLD_LABEL, NEW_LABEL, "historisk klass-label")
    html = replace_once(html, OLD_FALLBACK, NEW_FALLBACK, "historisk klass-fallback")
    html = replace_once(html, MARK_USE, f"{SKO_ROW},{MARK_USE}", "Markanvändning-rad")

    if OLD_LABEL in html or OLD_FALLBACK in html:
        raise RuntimeError("Frontend phase0 patch lämnade kvar gammal 1971/5–10-text")
    if html.count(NEW_LABEL) != 1 or html.count(SK0 := "Skördeområde (SKO)") != 1:
        raise RuntimeError(f"Frontend phase0 patch saknar unik ny UI-rad: {SK0}")

    path.write_text(html, encoding="utf-8")
    print("AKERPASS PHASE0 FRONTEND PATCH: OK")
    print("  Historisk jordbruksklass — referensdata")
    print("  Skördeområde (SKO)")
    print("  Exakt årtal 1971 visas inte längre")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
