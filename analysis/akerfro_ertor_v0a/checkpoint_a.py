#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · STOPPUNKT A.

Audits the frozen ÅkerMinne official annual crop-code dictionaries and prints
2015–2025 pea/legume counts from frozen Skåne ÅkerMinne field-year outputs.
No geometry or frozen model artifact is recomputed or modified.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from akerminne_history_core import CropRegistry  # noqa: E402
from analysis.akerfro_ertor_v0a.crop_groups import (  # noqa: E402
    CONSERVART,
    FABA_BEAN,
    OTHER_LEGUME,
    OTHER_PEA,
    PRIMARY_GROUPS,
    akerfro_crop_group,
)

YEARS = list(range(2015, 2026))
DEFAULT_DICT_DIR = ROOT / "data" / "reference" / "akerminne_crop_codes_official"
DEFAULT_AKERMINNE_ROOT = ROOT.parent / "AkerSync-Minne"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a"
DEFAULT_CONFIG = ROOT / "config" / "akerfro_ertor_v0a.json"


def raw_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else (text or None)


def load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    years = [int(x) for x in cfg.get("years", [])]
    if years != YEARS:
        raise RuntimeError(f"Config years must be exactly {YEARS}; got {years}")
    if cfg.get("target_crop_group") != CONSERVART:
        raise RuntimeError("STOPPUNKT A target_crop_group must be CONSERVART")
    return cfg


def load_official_tables(dict_dir: Path) -> tuple[dict[int, pd.DataFrame], dict[str, Any]]:
    manifest_path = dict_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    years_meta = manifest.get("years") or {}
    if sorted(map(int, years_meta)) != YEARS:
        raise RuntimeError("Official crop-code manifest must contain exactly 2015-2025")

    tables: dict[int, pd.DataFrame] = {}
    for year in YEARS:
        meta = years_meta[str(year)]
        payload_path = dict_dir / str(meta["payload_file"])
        encoded = payload_path.read_text(encoding="ascii").strip()
        raw = gzip.decompress(base64.b64decode(encoded, validate=True))
        sha = hashlib.sha256(raw).hexdigest()
        if sha != str(meta["normalized_sha256"]):
            raise RuntimeError(f"{year}: normalized SHA-256 mismatch")
        frame = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig")
        if len(frame) != int(meta["normalized_rows"]):
            raise RuntimeError(
                f"{year}: expected {meta['normalized_rows']} official rows, got {len(frame)}"
            )
        required = {"crop_code_raw", "crop_subcategory_raw", "crop_name", "crop_group"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise RuntimeError(f"{year}: normalized official table missing {missing}")
        frame = frame.copy()
        frame["year"] = year
        frame["source_file"] = str(meta["source_filename"])
        tables[year] = frame
    return tables, manifest


def materialize_registry(tables: dict[int, pd.DataFrame], out_dir: Path) -> CropRegistry:
    target = out_dir / "_official_crop_codes_materialized"
    target.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        path = target / f"crop_codes_{year}.csv"
        tables[year].drop(columns=["year", "source_file"]).to_csv(
            path, index=False, encoding="utf-8-sig"
        )
    registry, meta = CropRegistry.from_directory(target)
    if meta.get("loaded_years") != YEARS:
        raise RuntimeError(f"CropRegistry did not load all annual tables: {meta}")
    return registry


def build_mapping_audit(tables: dict[int, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for year in YEARS:
        frame = tables[year]
        for row in frame.itertuples(index=False):
            name = raw_text(row.crop_name)
            group = akerfro_crop_group(name)
            if group is None:
                continue
            code = raw_text(row.crop_code_raw)
            sub = raw_text(row.crop_subcategory_raw)
            rows.append(
                {
                    "year": year,
                    "official_crop_code": code,
                    "official_crop_subcategory": sub,
                    "official_crop_name": name,
                    "akerfro_group": group,
                    "source_file": str(row.source_file),
                    "notes": "official annual undercode" if sub else "official annual main code",
                }
            )
    audit = pd.DataFrame(rows)
    if audit.empty:
        raise RuntimeError("No ÅkerFrö-relevant labels found in official annual crop tables")
    audit = audit.sort_values(
        ["year", "akerfro_group", "official_crop_code", "official_crop_subcategory"],
        kind="mergesort",
        na_position="first",
    ).reset_index(drop=True)

    # Every year must resolve exactly one main official label for each primary group.
    main = audit[audit["official_crop_subcategory"].isna()]
    for year in YEARS:
        for group in PRIMARY_GROUPS:
            found = main[(main["year"] == year) & (main["akerfro_group"] == group)]
            if len(found) != 1:
                raise RuntimeError(
                    f"{year}: expected exactly one main-code mapping for {group}; got {len(found)}"
                )
    return audit


def validate_registry_semantics(registry: CropRegistry, audit: pd.DataFrame) -> None:
    primary = audit[
        audit["akerfro_group"].isin(PRIMARY_GROUPS)
        & audit["official_crop_subcategory"].isna()
    ]
    for row in primary.itertuples(index=False):
        rec = registry.lookup(row.year, row.official_crop_code, None)
        if rec is None:
            raise RuntimeError(
                f"{row.year}/{row.official_crop_code}: missing from reused ÅkerMinne CropRegistry"
            )
        if raw_text(rec.crop_name) != raw_text(row.official_crop_name):
            raise RuntimeError(
                f"{row.year}/{row.official_crop_code}: registry label mismatch "
                f"{rec.crop_name!r} != {row.official_crop_name!r}"
            )
        if akerfro_crop_group(rec.crop_name) != row.akerfro_group:
            raise RuntimeError(f"{row.year}/{row.official_crop_code}: semantic group mismatch")


def load_frozen_history(akerminne_root: Path, cfg: dict[str, Any]) -> tuple[pd.DataFrame, list[Path]]:
    municipal_root = (
        akerminne_root
        / "data"
        / "derived"
        / "akerminne_v1a"
        / "skane"
        / "municipalities"
    )
    files = sorted(municipal_root.glob("*/akerminne_year_summary_classified.parquet"))
    expected_municipalities = int(cfg["expected_municipalities"])
    if len(files) != expected_municipalities:
        raise RuntimeError(
            f"Expected {expected_municipalities} municipality summaries under {municipal_root}; "
            f"found {len(files)}"
        )

    cols = [
        "history_year",
        "current_field_id",
        "dominant_crop_name",
        "dominant_crop_known",
        "status",
    ]
    frames: list[pd.DataFrame] = []
    for path in files:
        frame = pd.read_parquet(path, columns=cols)
        frame = frame.copy()
        frame["municipality_dir"] = path.parent.name
        frames.append(frame)
    history = pd.concat(frames, ignore_index=True)
    history["history_year"] = pd.to_numeric(history["history_year"], errors="raise").astype(int)

    got_years = sorted(history["history_year"].unique().tolist())
    if got_years != YEARS:
        raise RuntimeError(f"Frozen history years mismatch: expected {YEARS}, got {got_years}")
    expected_rows = int(cfg["expected_field_years"])
    if len(history) != expected_rows:
        raise RuntimeError(f"Expected {expected_rows:,} field-years, got {len(history):,}")
    fields = int(history["current_field_id"].nunique())
    expected_fields = int(cfg["expected_current_fields"])
    if fields != expected_fields:
        raise RuntimeError(f"Expected {expected_fields:,} unique current fields, got {fields:,}")
    return history, files


def yearly_counts(history: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    x = history.copy()
    x["akerfro_group"] = x["dominant_crop_name"].map(akerfro_crop_group)
    x["is_clean"] = x["status"].eq("SINGLE_CROP")
    known = x["dominant_crop_known"].fillna(False).astype(bool)

    rows: list[dict[str, Any]] = []
    for year in YEARS:
        g = x[x["history_year"] == year]
        clean = g["is_clean"]
        rows.append(
            {
                "year": year,
                "n_field_years": int(len(g)),
                "n_conservart": int((clean & g["akerfro_group"].eq(CONSERVART)).sum()),
                "n_other_pea": int((clean & g["akerfro_group"].eq(OTHER_PEA)).sum()),
                "n_faba_bean": int((clean & g["akerfro_group"].eq(FABA_BEAN)).sum()),
                "n_other_legume": int((clean & g["akerfro_group"].eq(OTHER_LEGUME)).sum()),
                "n_unknown_or_unmapped": int((~known.loc[g.index]).sum()),
                "n_conservart_all_dominant": int(g["akerfro_group"].eq(CONSERVART).sum()),
                "n_single_crop": int(clean.sum()),
            }
        )
    counts = pd.DataFrame(rows)
    positive_fields = int(
        x[x["is_clean"] & x["akerfro_group"].eq(CONSERVART)]["current_field_id"].nunique()
    )
    return counts, positive_fields


def print_primary_mapping(audit: pd.DataFrame) -> None:
    primary = audit[
        audit["akerfro_group"].isin(PRIMARY_GROUPS)
        & audit["official_crop_subcategory"].isna()
    ].copy()
    print("\nPRIMARY OFFICIAL MAPPINGS (resolved year by year)")
    print(primary[["year", "official_crop_code", "official_crop_name", "akerfro_group"]].to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--dict-dir", default=str(DEFAULT_DICT_DIR))
    ap.add_argument("--akerminne-root", default=str(DEFAULT_AKERMINNE_ROOT))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tables, manifest = load_official_tables(Path(args.dict_dir))
    audit = build_mapping_audit(tables)
    registry = materialize_registry(tables, out)
    validate_registry_semantics(registry, audit)

    audit_path = out / "crop_mapping_audit.csv"
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")

    history, municipal_files = load_frozen_history(Path(args.akerminne_root), cfg)
    counts, positive_fields = yearly_counts(history)
    counts_path = out / "yearly_counts.csv"
    counts.to_csv(counts_path, index=False, encoding="utf-8-sig")

    checkpoint = {
        "schema_version": "akerfro-ertor-checkpoint-a-v0a",
        "target_crop_group": CONSERVART,
        "official_dictionary_manifest_schema": manifest.get("schema_version"),
        "official_source": manifest.get("source"),
        "official_years": YEARS,
        "annual_lookup_contract": "year + official code/subcode -> official name -> ÅkerFrö semantic group",
        "cross_year_crop_code_fallback": False,
        "municipality_files": len(municipal_files),
        "field_years": int(len(history)),
        "unique_current_fields": int(history["current_field_id"].nunique()),
        "unique_clean_conservart_fields_2015_2025": positive_fields,
        "outputs": {
            "crop_mapping_audit": str(audit_path),
            "yearly_counts": str(counts_path),
        },
        "status": "PASS",
    }
    checkpoint_path = out / "checkpoint_a.json"
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("ÅkerFrö – Ärter MVP v0a · STOPPUNKT A")
    print("=" * 78)
    print(f"Official annual dictionaries: {len(tables)} (2015-2025)")
    print("Target semantic group: CONSERVART")
    print("Crop-code rule: SAME-YEAR LOOKUP ONLY; no cross-year numeric shortcut")
    print_primary_mapping(audit)
    print("\nFROZEN ÅKERMINNE HISTORY COUNTS")
    print(counts.to_string(index=False))
    print(f"\nUnique current fields with >=1 clean CONSERVART year: {positive_fields:,}")
    print(f"Mapping audit: {audit_path}")
    print(f"Yearly counts: {counts_path}")
    print(f"Checkpoint: {checkpoint_path}")
    print("=" * 78)
    print("STOPPUNKT A: PASS")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
