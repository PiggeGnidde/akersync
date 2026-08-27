#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEFAULT_SKANE = ROOT / "data" / "derived" / "akerminne_v1a" / "skane"
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_OUT = ROOT / "dist" / "data" / "akerminne"
EXPECTED_FIELDS = 128636
EXPECTED_FIELD_YEARS = 1414996
EXPECTED_YEARS = list(range(2015, 2026))


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    return "".join(ch if ch.isalnum() else "_" for ch in str(text).translate(trans).lower()).strip("_")


def _load_builder():
    path = SRC / "57_build_akerminne_web_pilot.py"
    spec = importlib.util.spec_from_file_location("akerminne_web_builder_for_skane", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _atomic_json(doc: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    check = json.loads(tmp.read_text(encoding="utf-8"))
    if check.get("schema_version") != doc.get("schema_version"):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"JSON verification failed: {path}")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _load_plan(skane_root: Path) -> dict[str, Any]:
    path = skane_root / "skane_plan.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if int(doc.get("municipality_count", -1)) != 33 or int(doc.get("current_fields_total", -1)) != EXPECTED_FIELDS:
        raise RuntimeError("Skåne plan is not the frozen 33 municipality / 128,636 field plan")
    return doc


def build_all(skane_root: Path, out_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    builder = _load_builder()
    plan = _load_plan(skane_root)
    history_cfg = config.get("history_status") or {}
    reference_year = int(config.get("reference_year", 2025))
    if reference_year != 2025:
        raise RuntimeError("ÅkerMinne v1a web contract requires reference year 2025")

    entries: list[dict[str, Any]] = []
    total_fields = total_field_years = total_bytes = 0
    for item in plan["municipalities"]:
        code, name = str(item["code"]), str(item["name"])
        expected_fields = int(item["current_fields"])
        slug = _slug(name)
        mdir = skane_root / "municipalities" / f"{code}_{slug}"
        classified_path = mdir / "akerminne_year_summary_classified.parquet"
        crop_path = mdir / "akerminne_crop_areas_grouped.parquet"
        components_path = mdir / "akerminne_components.parquet"
        manifest_path = mdir / "build_manifest.json"
        for path in (classified_path, crop_path, components_path, manifest_path):
            if not path.exists():
                raise FileNotFoundError(f"{name}: missing {path}")
        build_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(build_manifest.get("current_fields", -1)) != expected_fields or int(build_manifest.get("field_years", -1)) != expected_fields * 11:
            raise RuntimeError(f"{name}: municipality build manifest is incomplete")
        if int(build_manifest.get("unknown_crop_combinations", -1)) != 0:
            raise RuntimeError(f"{name}: unknown crop combinations must be zero before web packaging")

        classified = pd.read_parquet(classified_path)
        crops = pd.read_parquet(crop_path)
        components = pd.read_parquet(components_path)
        payload = builder.build_payload(
            classified, crops, components, history_cfg,
            municipality=name, municipality_code=code, reference_year=reference_year,
        )
        if int(payload["field_count"]) != expected_fields:
            raise RuntimeError(f"{name}: sidecar field count {payload['field_count']:,} != {expected_fields:,}")
        if payload.get("years") != EXPECTED_YEARS:
            raise RuntimeError(f"{name}: invalid sidecar year sequence")
        filename = f"{code}_{slug}.json"
        target = out_dir / filename
        _atomic_json(payload, target)
        size = target.stat().st_size
        entries.append({
            "municipality": name,
            "municipality_code": code,
            "file": f"data/akerminne/{filename}",
            "field_count": expected_fields,
            "field_years": expected_fields * 11,
            "size_bytes": size,
            "crop_label_count": len(payload.get("crop_names") or {}),
        })
        total_fields += expected_fields
        total_field_years += expected_fields * 11
        total_bytes += size
        print(f"{code} {name}: {expected_fields:,} fields · {size/1024/1024:.2f} MiB")

    if len(entries) != 33 or total_fields != EXPECTED_FIELDS or total_field_years != EXPECTED_FIELD_YEARS:
        raise RuntimeError(f"Skåne web totals invalid: municipalities={len(entries)}, fields={total_fields}, field-years={total_field_years}")
    index = {
        "schema_version": "akerminne-skane-web-index-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "reference_year": 2025,
        "years": EXPECTED_YEARS,
        "municipality_count": len(entries),
        "field_count": total_fields,
        "field_years": total_field_years,
        "sidecar_bytes": total_bytes,
        "municipalities": entries,
    }
    _atomic_json(index, out_dir / "skane_index.json")
    return index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skane-root", default=str(DEFAULT_SKANE))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    index = build_all(Path(args.skane_root), Path(args.out_dir), config)
    print("=" * 78)
    print("ÅkerMinne v1a · SKÅNE WEB DATA: PASS")
    print("=" * 78)
    print(f"Municipalities: {index['municipality_count']}/33")
    print(f"Fields/field-years: {index['field_count']:,}/{index['field_years']:,}")
    print(f"Sidecar total: {index['sidecar_bytes']/1024/1024:.1f} MiB")
    print(f"Index: {Path(args.out_dir) / 'skane_index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
