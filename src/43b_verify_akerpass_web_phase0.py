#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance checks for ÅkerPass WEB FAS 0: class 1–10 + SKO reference display."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import MUN_CODES, load_config

PHASE0_VERSION = "akerprestation-phase0-v0a"
EXPECTED_FIELDS = 128_636
EXPECTED_CLASSES = set(range(1, 11))
EXPECTED_SKO_IDS = {
    "0731", "1011", "1111", "1112", "1121", "1122", "1123", "1124", "1131",
    "1211", "1212", "1213", "1214", "1215", "1216", "1221", "1222", "1321",
}
EXPECTED_MISSING_CLASS = 17_540
EXPECTED_SKO_BOUNDARY = 2_195


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    dist_dir = root / config.get("dist_dir", "dist")

    manifest_path = dist_dir / "municipalities.json"
    index_path = dist_dir / "index.html"
    if not manifest_path.exists() or not index_path.exists():
        raise FileNotFoundError("Saknar dist/municipalities.json eller dist/index.html")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("akerprestation_phase0_version") != PHASE0_VERSION:
        raise RuntimeError("Kommunmanifest saknar korrekt ÅkerPrestation phase0-version")
    if manifest.get("historic_class_domain") != "1-10":
        raise RuntimeError("Kommunmanifest anger inte historisk klassdomän 1–10")
    if manifest.get("sko_id_type") != "string":
        raise RuntimeError("Kommunmanifest garanterar inte SKO som text")
    municipalities = manifest.get("municipalities") or {}
    if set(municipalities) != set(MUN_CODES) or manifest.get("municipality_count") != 33:
        raise RuntimeError("Kommunmanifest innehåller inte exakt Skånes 33 kommuner")

    ids: set[str] = set()
    classes: set[int] = set()
    sko_ids: set[str] = set()
    missing_class = 0
    sko_missing = 0
    sko_boundary = 0
    leading_zero_seen = False

    for municipality, meta in municipalities.items():
        path = dist_dir / meta["file"]
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("static_context_version") != PHASE0_VERSION:
            raise RuntimeError(f"{municipality}: fel static_context_version")
        features = (document.get("fields") or {}).get("features") or []
        if len(features) != int(meta.get("fields", -1)):
            raise RuntimeError(f"{municipality}: fältantal mismatch")

        for feature in features:
            p = feature.get("properties") or {}
            fid = str(p.get("id") or feature.get("id") or "")
            if not fid or fid in ids:
                raise RuntimeError(f"Ogiltigt/dubbelt publikt field id: {fid!r}")
            ids.add(fid)

            models = p.get("model_versions") or {}
            if models.get("akerprestation_phase0") != PHASE0_VERSION:
                raise RuntimeError(f"{municipality} {fid}: phase0-version saknas i model_versions")

            cls = p.get("historic_class")
            status = p.get("historic_class_status")
            label = p.get("historic_class_status_label")
            if cls is None:
                missing_class += 1
                if status != "not_classified_in_historic_reference":
                    raise RuntimeError(f"{fid}: saknad klass har fel status")
                if label != "Ingen historisk klass i referensunderlaget":
                    raise RuntimeError(f"{fid}: saknad klass har fel publik label")
            else:
                cls_int = int(cls)
                if cls_int not in EXPECTED_CLASSES:
                    raise RuntimeError(f"{fid}: historisk klass utanför 1–10")
                classes.add(cls_int)
                if status != "class_1_10":
                    raise RuntimeError(f"{fid}: klassad rad har fel status")

            sko = p.get("sko_id")
            if not isinstance(sko, str) or not sko:
                sko_missing += 1
            else:
                if sko not in EXPECTED_SKO_IDS:
                    raise RuntimeError(f"{fid}: okänt SKO-ID {sko!r}")
                sko_ids.add(sko)
                leading_zero_seen |= sko.startswith("0")
            sko_boundary += int(bool(p.get("crosses_sko_boundary", False)))

    if len(ids) != EXPECTED_FIELDS or len(ids) != int(manifest.get("field_count", -1)):
        raise RuntimeError(f"Publika skiften {len(ids):,}; väntat {EXPECTED_FIELDS:,}")
    if classes != EXPECTED_CLASSES:
        raise RuntimeError(f"Publika historiska klasser är {sorted(classes)}, väntat 1–10")
    if missing_class != EXPECTED_MISSING_CLASS:
        raise RuntimeError(f"Saknade historiska klasser {missing_class:,}; väntat {EXPECTED_MISSING_CLASS:,}")
    if sko_missing != 0:
        raise RuntimeError(f"Publika skiften utan SKO: {sko_missing:,}")
    if sko_ids != EXPECTED_SKO_IDS:
        raise RuntimeError(f"Publik SKO-domän avviker: {sorted(sko_ids)}")
    if not leading_zero_seen or "0731" not in sko_ids:
        raise RuntimeError("Ledande nolla i SKO 0731 har inte bevarats")
    if sko_boundary != EXPECTED_SKO_BOUNDARY:
        raise RuntimeError(f"Råa SKO-gränsfält {sko_boundary:,}; väntat {EXPECTED_SKO_BOUNDARY:,}")

    html = index_path.read_text(encoding="utf-8")
    required = (
        "Historisk jordbruksklass — referensdata",
        "Skördeområde (SKO)",
        "Ingen historisk klass i referensunderlaget",
        "p.sko_id?esc(p.sko_id):null",
    )
    missing = [x for x in required if x not in html]
    if missing:
        raise RuntimeError("Frontend saknar WEB FAS 0-markörer: " + ", ".join(missing))
    forbidden = (
        "Historisk jordbruksklass 1971",
        "Ej klass 5–10 i importerat underlag",
        "Ej klass 5–10 i importerat 1971-underlag",
    )
    present = [x for x in forbidden if x in html]
    if present:
        raise RuntimeError("Frontend innehåller gammal klass-/årtalssemantik: " + ", ".join(present))

    print("VERIFY_AKERPASS_WEB_PHASE0: PASS")
    print(f"  Kommuner: 33/33")
    print(f"  Skiften: {len(ids):,}/{EXPECTED_FIELDS:,}")
    print("  Historisk jordbruksklass: 1–10")
    print(f"  Explicit oklassade skiften: {missing_class:,}")
    print(f"  SKO-ID:n: {len(sko_ids)} · saknade: {sko_missing}")
    print(f"  Råa SKO-gränsfält: {sko_boundary:,}")
    print("  SKO 0731: ledande nolla verifierad")
    print("  UI: Historik / referens innehåller klass + SKO; '1971' borttaget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
