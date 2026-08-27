#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare the resumable ÅkerMinne Skåne batch.

This stage does no historical geometry matching. It:
1) validates the frozen 2025 municipality inventory,
2) materializes the verified official annual crop-code CSVs from the
   repository's text-safe payloads,
3) writes a deterministic Skåne execution plan.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MUNICIPALITIES = ROOT / "config" / "akerminne_skane_municipalities.json"
DEFAULT_PROJECT = ROOT / "config" / "local_paths.json"
DEFAULT_DICT_DIR = ROOT / "data" / "reference" / "akerminne_crop_codes_official"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerminne_v1a" / "skane"
EXPECTED_YEARS = list(range(2015, 2026))
EXPECTED_OFFICIAL_ROWS = 1572


def _atomic_text(text: str, path: Path, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _atomic_bytes(data: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    if tmp.read_bytes() != data:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Write verification failed: {path}")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _raw_text(v: Any) -> str | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else (s or None)


def load_municipalities(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    municipalities = doc.get("municipalities") or []
    codes = [str(x["code"]) for x in municipalities]
    names = [str(x["name"]) for x in municipalities]
    if len(municipalities) != 33 or len(set(codes)) != 33 or len(set(names)) != 33:
        raise RuntimeError("Skåne municipality config must contain exactly 33 unique codes/names")
    if any(len(c) != 4 or not c.isdigit() for c in codes):
        raise RuntimeError("Municipality codes must be four digits")
    return doc


def materialize_official_crop_codes(dict_dir: Path, out_dir: Path) -> dict[str, Any]:
    manifest_path = dict_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    years_meta = manifest.get("years") or {}
    if sorted(map(int, years_meta)) != EXPECTED_YEARS:
        raise RuntimeError("Official crop-code manifest must contain exactly 2015-2025")

    rows_total = 0
    files: dict[str, Any] = {}
    for year in EXPECTED_YEARS:
        meta = years_meta[str(year)]
        payload = dict_dir / meta["payload_file"]
        encoded = payload.read_text(encoding="ascii").strip()
        raw = gzip.decompress(base64.b64decode(encoded, validate=True))
        sha = hashlib.sha256(raw).hexdigest()
        if sha != str(meta["normalized_sha256"]):
            raise RuntimeError(f"{year}: normalized SHA-256 mismatch")
        frame = pd.read_csv(pd.io.common.BytesIO(raw), dtype=str, encoding="utf-8-sig")
        expected_rows = int(meta["normalized_rows"])
        if len(frame) != expected_rows:
            raise RuntimeError(f"{year}: expected {expected_rows} official rows, got {len(frame)}")
        required = {"crop_code_raw", "crop_subcategory_raw", "crop_name", "crop_group"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise RuntimeError(f"{year}: normalized official table missing {missing}")
        keys = []
        for row in frame.itertuples(index=False):
            code = _raw_text(row.crop_code_raw)
            sub = _raw_text(row.crop_subcategory_raw)
            if code is not None:
                keys.append((code, sub))
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"{year}: duplicate exact crop code/subcode keys")
        target = out_dir / f"crop_codes_{year}.csv"
        _atomic_bytes(raw, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise RuntimeError(f"{year}: materialized SHA-256 mismatch")
        rows_total += len(frame)
        files[str(year)] = {
            "path": str(target),
            "rows": len(frame),
            "keys": len(keys),
            "sha256": sha,
        }

    if rows_total != EXPECTED_OFFICIAL_ROWS or rows_total != int(manifest["total_normalized_rows"]):
        raise RuntimeError(f"Official crop-code rows must total {EXPECTED_OFFICIAL_ROWS}; got {rows_total}")
    return {
        "loaded_years": EXPECTED_YEARS,
        "rows": rows_total,
        "files": files,
        "source_manifest": str(manifest_path),
    }


def current_inventory(project: dict[str, Any], municipality_doc: dict[str, Any]) -> tuple[pd.DataFrame, int]:
    skifte_path = Path(project["skiften"])
    print(f"Reading frozen 2025 current fields: {skifte_path}")
    skiften = gpd.read_file(skifte_path)
    if "region_kod" not in skiften.columns:
        block_path = Path(project["blocks"])
        print(f"  region_kod absent on skiften; deriving via blockid from {block_path}")
        blocks = gpd.read_file(block_path)
        if "region_kod" not in blocks.columns:
            raise RuntimeError("Neither current skiften nor blocks contains region_kod")
        block_map = (
            blocks.assign(blockid_s=blocks["blockid"].astype(str))
            .drop_duplicates("blockid_s")
            .set_index("blockid_s")["region_kod"]
            .astype(str)
            .to_dict()
        )
        skiften = skiften.copy()
        skiften["region_kod"] = skiften["blockid"].astype(str).map(block_map)
    if skiften["region_kod"].isna().any():
        raise RuntimeError("Current 2025 fields contain missing region_kod after derivation")

    skiften = skiften.copy()
    skiften["municipality_code"] = skiften["region_kod"].astype(str).str[:4]
    configured = {str(x["code"]): str(x["name"]) for x in municipality_doc["municipalities"]}
    rows = []
    total = 0
    for code, name in configured.items():
        g = skiften[skiften["municipality_code"] == code]
        count = int(len(g))
        if count <= 0:
            raise RuntimeError(f"{name} ({code}): zero current 2025 fields")
        total += count
        rows.append({"code": code, "name": name, "current_fields": count})
    frame = pd.DataFrame(rows).sort_values(["current_fields", "code"], kind="mergesort").reset_index(drop=True)
    return frame, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipalities", default=str(DEFAULT_MUNICIPALITIES))
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT))
    ap.add_argument("--dict-dir", default=str(DEFAULT_DICT_DIR))
    ap.add_argument("--output-root", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    mun_doc = load_municipalities(Path(args.municipalities))
    project = load_config(args.project_local_config)
    out = Path(args.output_root)
    reference_dir = out / "reference" / "crop_codes"
    official = materialize_official_crop_codes(Path(args.dict_dir), reference_dir)
    inventory, total = current_inventory(project, mun_doc)
    expected_total = int(mun_doc["expected_current_fields_total"])
    if total != expected_total:
        raise RuntimeError(f"Frozen 2025 Skåne field count mismatch: expected {expected_total:,}, got {total:,}")

    skurup = inventory[inventory["code"] == "1264"]
    if len(skurup) != 1 or int(skurup.iloc[0]["current_fields"]) != 2944:
        raise RuntimeError("Skurup control count must remain 2,944")

    inv_path = out / "skane_current_inventory.csv"
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    inventory.to_csv(inv_path, index=False, encoding="utf-8-sig")

    by_code = {str(r.code): int(r.current_fields) for r in inventory.itertuples(index=False)}
    municipalities = []
    for item in mun_doc["municipalities"]:
        code, name = str(item["code"]), str(item["name"])
        municipalities.append({"code": code, "name": name, "current_fields": by_code[code]})
    plan = {
        "schema_version": "akerminne-skane-plan-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "reference_year": int(mun_doc["reference_year"]),
        "years": EXPECTED_YEARS,
        "historical_download_years": list(range(2015, 2025)),
        "expected_current_fields_total": expected_total,
        "current_fields_total": total,
        "municipality_count": len(municipalities),
        "municipalities": municipalities,
        "order_small_first": [str(r.code) for r in inventory.itertuples(index=False)],
        "smoke_codes": [str(x) for x in mun_doc.get("smoke_codes", [])],
        "official_crop_codes": official,
        "project_current_source": str(project["skiften"]),
    }
    plan_path = out / "skane_plan.json"
    _atomic_text(json.dumps(plan, ensure_ascii=False, indent=2), plan_path)

    print("=" * 78)
    print("ÅkerMinne v1a · Skåne PREPARE: PASS")
    print("=" * 78)
    print(f"Municipalities: {len(municipalities)}")
    print(f"Current 2025 fields: {total:,}")
    print(f"Official annual crop rows: {official['rows']:,} across {len(official['loaded_years'])} years")
    print(f"Smoke municipalities: {', '.join(plan['smoke_codes'])}")
    print(f"Plan: {plan_path}")
    print(f"Inventory: {inv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
