#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C0 feature/source inventory.

Read-only inventory of frozen/static candidate feature tables. It reports
schemas, row counts, candidate join keys, duplicate-key QA and join coverage
against the 128,636 ÅkerFrö current fields.

No model is fitted and no frozen artifact is modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY = ROOT / "data" / "derived" / "akerfro_ertor_v0a" / "pea_history_by_field.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "feature_inventory_c0"

DEFAULT_SOURCES = {
    "akerprestation_static": Path(
        r"C:\AkerSync-Prestation\data\derived\akerprestation_phase0\skane\field_static_context.parquet"
    ),
    "akerprestation_sko": Path(
        r"C:\AkerSync-Prestation\data\derived\akerprestation_phase0\skane\field_sko_components.parquet"
    ),
    "akerprestation_soil_class": Path(
        r"C:\AkerSync-Prestation\data\derived\akerprestation_phase0\skane\field_soil_class_components.parquet"
    ),
    "akerscore_csv": Path(
        r"C:\AkerSync-Minne\data\derived\akerscore_soil_v0c\akerscore_soil_skiften.csv"
    ),
    "akerdrift_fast_v1": Path(
        r"C:\AkerSync-Minne\data\derived\akerdrift_fast_v1\akerdrift_fast_v1.parquet"
    ),
}

ID_CANDIDATES = [
    "current_field_id",
    "field_id",
    "field_key",
    "skifte_id",
]

BLOCK_CANDIDATES = ["current_block_id", "blockid", "block_id"]
SKIFTE_CANDIDATES = [
    "current_skiftesbeteckning",
    "skiftesbeteckning",
    "skifte",
]


def text_id(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".csv", ".gz"} or path.name.lower().endswith(".csv.gz"):
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Unsupported table type: {path}")


def derived_key(frame: pd.DataFrame) -> tuple[pd.Series | None, str | None]:
    for col in ID_CANDIDATES:
        if col in frame.columns:
            return frame[col].map(text_id), col

    block = next((c for c in BLOCK_CANDIDATES if c in frame.columns), None)
    skifte = next((c for c in SKIFTE_CANDIDATES if c in frame.columns), None)
    if block and skifte:
        return (
            frame[block].map(text_id) + "|" + frame[skifte].map(text_id),
            f"{block}|{skifte}",
        )
    return None, None


def dtype_family(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    return "other"


def inspect_source(name: str, path: Path, universe: set[str]) -> tuple[dict[str, Any], pd.DataFrame]:
    if not path.exists():
        report = {
            "source": name,
            "path": str(path),
            "exists": False,
            "rows": None,
            "columns": None,
            "join_key": None,
            "unique_keys": None,
            "duplicate_key_rows": None,
            "join_hits": None,
            "join_coverage_pct": None,
            "numeric_columns": [],
        }
        return report, pd.DataFrame()

    frame = read_table(path)
    key, key_rule = derived_key(frame)

    schema_rows = []
    for col in frame.columns:
        s = frame[col]
        schema_rows.append({
            "source": name,
            "column": col,
            "dtype": str(s.dtype),
            "family": dtype_family(s),
            "non_null": int(s.notna().sum()),
            "coverage_pct": 100.0 * float(s.notna().mean()) if len(s) else 0.0,
            "n_unique": int(s.nunique(dropna=True)),
        })
    schema = pd.DataFrame(schema_rows)

    numeric = schema.loc[schema["family"].eq("numeric"), "column"].tolist()
    if key is None:
        report = {
            "source": name,
            "path": str(path),
            "exists": True,
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "join_key": None,
            "unique_keys": None,
            "duplicate_key_rows": None,
            "join_hits": 0,
            "join_coverage_pct": 0.0,
            "numeric_columns": numeric,
        }
        return report, schema

    key = key.astype(str)
    nonempty = key.ne("")
    valid_key = key[nonempty]
    unique_keys = set(valid_key.unique().tolist())
    dup_rows = int(valid_key.duplicated(keep=False).sum())
    hits = len(universe & unique_keys)
    report = {
        "source": name,
        "path": str(path),
        "exists": True,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "join_key": key_rule,
        "unique_keys": int(len(unique_keys)),
        "duplicate_key_rows": dup_rows,
        "join_hits": int(hits),
        "join_coverage_pct": 100.0 * hits / len(universe) if universe else 0.0,
        "numeric_columns": numeric,
    }
    return report, schema


def candidate_paths() -> dict[str, Path]:
    out = dict(DEFAULT_SOURCES)

    # Known alternate ÅkerDrift output names from earlier project versions.
    drift_dir = Path(r"C:\AkerSync-Minne\data\derived")
    if drift_dir.exists():
        patterns = [
            "*akerdrift*/*.parquet",
            "*akerdrift*/*.csv",
            "*akerdrift*/*/*.parquet",
            "*akerdrift*/*/*.csv",
        ]
        seen = {str(p).lower() for p in out.values()}
        n = 0
        for pattern in patterns:
            for path in sorted(drift_dir.glob(pattern)):
                key = str(path).lower()
                if key in seen:
                    continue
                if path.is_file():
                    n += 1
                    out[f"akerdrift_discovered_{n:02d}"] = path
                    seen.add(key)
                if n >= 12:
                    return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=str(DEFAULT_HISTORY))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    history_path = Path(args.history)
    if not history_path.exists():
        raise FileNotFoundError(f"{history_path} missing; run STOPPUNKT B first")
    hist = pd.read_parquet(history_path)
    if "current_field_id" not in hist.columns:
        raise RuntimeError("ÅkerFrö history lacks current_field_id")
    universe = set(hist["current_field_id"].map(text_id))
    universe.discard("")
    if len(universe) != 128636:
        raise RuntimeError(f"Expected 128,636 ÅkerFrö fields, got {len(universe):,}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    reports = []
    schemas = []
    for name, path in candidate_paths().items():
        report, schema = inspect_source(name, path, universe)
        reports.append(report)
        if len(schema):
            schemas.append(schema)

    inv = pd.DataFrame([
        {k: v for k, v in r.items() if k != "numeric_columns"}
        for r in reports
    ])
    inv_path = out / "source_inventory.csv"
    inv.to_csv(inv_path, index=False, encoding="utf-8-sig")

    schema = pd.concat(schemas, ignore_index=True) if schemas else pd.DataFrame()
    schema_path = out / "column_inventory.csv"
    schema.to_csv(schema_path, index=False, encoding="utf-8-sig")

    doc = {
        "schema_version": "akerfro-ertor-feature-inventory-c0-v0a",
        "current_field_universe": len(universe),
        "sources": reports,
        "outputs": {
            "source_inventory": str(inv_path),
            "column_inventory": str(schema_path),
        },
    }
    json_path = out / "feature_inventory.json"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 96)
    print("ÅkerFrö – Ärter MVP v0a · C0 FEATURE INVENTORY")
    print("=" * 96)
    print(f"ÅkerFrö current-field universe: {len(universe):,}")
    print()
    show_cols = [
        "source", "exists", "rows", "columns", "join_key",
        "unique_keys", "duplicate_key_rows", "join_hits", "join_coverage_pct",
    ]
    print(inv[show_cols].to_string(index=False, formatters={
        "join_coverage_pct": lambda v: "" if pd.isna(v) else f"{v:.2f}%"
    }))

    print("\nNUMERIC CANDIDATE COLUMNS")
    for r in reports:
        if r["exists"]:
            print(f"\n[{r['source']}]")
            print(", ".join(r["numeric_columns"]) if r["numeric_columns"] else "(none)")

    print(f"\nSource inventory: {inv_path}")
    print(f"Column inventory: {schema_path}")
    print(f"JSON: {json_path}")
    print("=" * 96)
    print("C0 FEATURE INVENTORY: PASS")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
