#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply official Jordbruksverket annual crop-code labels to the frozen Skurup ÅkerMinne pilot.

Label-only operation: geometry, intersections, coverage and identity matching are asserted unchanged.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parents[1]
DICT_DIR = ROOT / "data" / "reference" / "akerminne_crop_codes_official"
MANIFEST = DICT_DIR / "manifest.json"
PILOT = ROOT / "data" / "derived" / "akerminne_v1a" / "pilot_skurup"
REPORT_DIR = ROOT / "data" / "derived" / "akerminne_v1a" / "crop_codes_official"
COMP_LABEL_COLUMNS = {"crop_name", "crop_group", "crop_known"}
SUMMARY_LABEL_COLUMNS = {"dominant_crop_name", "dominant_crop_group", "dominant_crop_known", "reason_flags"}


def raw_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    s = str(value).strip()
    return s[:-2] if s.endswith(".0") else (s or None)


def unknown_crop_label(code: str | None, year: int) -> str:
    return f"Okänd grödkod {code if code is not None else 'saknas'} ({int(year)})"


def load_official_tables(directory: Path, manifest_path: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    years = list(range(2015, 2026))
    meta_years = manifest.get("years") or {}
    if sorted(map(int, meta_years)) != years:
        raise RuntimeError("Official crop-code manifest must contain exactly 2015-2025")
    tables: dict[int, dict[tuple[str | None, str | None], tuple[str, str | None]]] = {}
    verified: dict[str, Any] = {}
    for year in years:
        meta = meta_years[str(year)]
        path = directory / meta["payload_file"]
        if not path.exists():
            raise FileNotFoundError(path)
        encoded = path.read_text(encoding="ascii").strip()
        raw = gzip.decompress(base64.b64decode(encoded, validate=True))
        sha = hashlib.sha256(raw).hexdigest()
        if sha != meta["normalized_sha256"]:
            raise RuntimeError(f"{year}: normalized SHA-256 mismatch: {sha}")
        frame = pd.read_csv(pd.io.common.BytesIO(raw), dtype=str, encoding="utf-8-sig")
        if len(frame) != int(meta["normalized_rows"]):
            raise RuntimeError(f"{year}: expected {meta['normalized_rows']} rows, got {len(frame)}")
        required = {"crop_code_raw", "crop_subcategory_raw", "crop_name", "crop_group"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise RuntimeError(f"{year}: normalized dictionary missing {missing}")
        table = {}
        for row in frame.itertuples(index=False):
            code, sub = raw_text(row.crop_code_raw), raw_text(row.crop_subcategory_raw)
            name, group = raw_text(row.crop_name), raw_text(row.crop_group)
            if code is None or name is None:
                continue
            old = table.get((code, sub))
            if old is not None and old[0] != name:
                raise RuntimeError(f"{year}: conflicting official names for {(code, sub)}")
            table[(code, sub)] = (name, group)
        tables[year] = table
        verified[str(year)] = {"rows": len(frame), "keys": len(table), "sha256": sha, "payload_file": str(path)}
    if sum(x["rows"] for x in verified.values()) != int(manifest["total_normalized_rows"]):
        raise RuntimeError("Official crop-code total row count mismatch")
    return tables, {"manifest": manifest, "verified": verified}


def lookup(tables, year: int, code: Any, subcategory: Any):
    c, s = raw_text(code), raw_text(subcategory)
    table = tables.get(int(year), {})
    if (c, s) in table:
        return table[(c, s)]
    if s is not None and (c, None) in table:  # same-year fallback only
        return table[(c, None)]
    return None


def relabel_components(components: pd.DataFrame, tables) -> pd.DataFrame:
    out = components.copy()
    names, groups, known = [], [], []
    for row in out.itertuples(index=False):
        year, code = int(row.history_year), raw_text(row.crop_code_raw)
        rec = lookup(tables, year, code, row.crop_subcategory_raw)
        names.append(rec[0] if rec else unknown_crop_label(code, year))
        groups.append(rec[1] if rec else "UNKNOWN")
        known.append(bool(rec))
    out["crop_name"], out["crop_group"], out["crop_known"] = names, groups, known
    return out


def relabel_summary(summary: pd.DataFrame, components: pd.DataFrame, tables) -> pd.DataFrame:
    out = summary.copy()
    unknown_pairs = set(zip(
        components.loc[~components["crop_known"], "history_year"].astype(int),
        components.loc[~components["crop_known"], "current_field_id"].astype(str),
    ))
    names, groups, known, flags_out = [], [], [], []
    for row in out.itertuples(index=False):
        year, code = int(row.history_year), raw_text(row.dominant_crop_code_raw)
        rec = lookup(tables, year, code, row.dominant_crop_subcategory_raw) if code is not None else None
        names.append(rec[0] if rec else (unknown_crop_label(code, year) if code is not None else None))
        groups.append(rec[1] if rec else ("UNKNOWN" if code is not None else None))
        known.append(bool(rec))
        flags = [f for f in str(getattr(row, "reason_flags", "") or "").split(";") if f and f != "UNKNOWN_CODE"]
        if (year, str(row.current_field_id)) in unknown_pairs:
            flags.append("UNKNOWN_CODE")
        flags_out.append(";".join(flags))
    out["dominant_crop_name"], out["dominant_crop_group"] = names, groups
    out["dominant_crop_known"], out["reason_flags"] = known, flags_out
    return out


def assert_label_only(before: pd.DataFrame, after: pd.DataFrame, mutable: set[str]) -> None:
    if len(before) != len(after) or list(before.columns) != list(after.columns):
        raise AssertionError("Relabel changed row count or schema")
    invariant = [c for c in before.columns if c not in mutable]
    assert_frame_equal(before[invariant].reset_index(drop=True), after[invariant].reset_index(drop=True), check_exact=True)


def _write_verified_tmp(frame: pd.DataFrame, target: Path) -> Path:
    tmp = target.with_name(target.stem + ".official.tmp.parquet")
    tmp.unlink(missing_ok=True)
    frame.to_parquet(tmp, index=False)
    check = pd.read_parquet(tmp)
    assert_frame_equal(frame.reset_index(drop=True), check.reset_index(drop=True), check_exact=True)
    return tmp


def unknown_report(components: pd.DataFrame) -> pd.DataFrame:
    x = components[(~components["crop_known"]) & components["crop_code_raw"].notna()].copy()
    if x.empty:
        return pd.DataFrame(columns=["history_year", "crop_code_raw", "crop_subcategory_raw", "component_rows", "current_field_count", "intersection_m2"])
    return (x.groupby(["history_year", "crop_code_raw", "crop_subcategory_raw"], dropna=False)
             .agg(component_rows=("current_field_id", "size"), current_field_count=("current_field_id", "nunique"), intersection_m2=("intersection_m2", "sum"))
             .reset_index().sort_values(["history_year", "crop_code_raw", "crop_subcategory_raw"], kind="mergesort"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary-dir", default=str(DICT_DIR))
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--pilot-dir", default=str(PILOT))
    ap.add_argument("--report-dir", default=str(REPORT_DIR))
    args = ap.parse_args()
    dictionary_dir, manifest_path = Path(args.dictionary_dir), Path(args.manifest)
    pilot, report_dir = Path(args.pilot_dir), Path(args.report_dir)
    summary_path, components_path = pilot / "akerminne_year_summary.parquet", pilot / "akerminne_components.parquet"
    for path in (manifest_path, summary_path, components_path):
        if not path.exists():
            raise FileNotFoundError(path)

    tables, meta = load_official_tables(dictionary_dir, manifest_path)
    if lookup(tables, 2015, "4", None) != ("Vete (höst)", None):
        raise RuntimeError("2015 anchor failed: code 4")
    if lookup(tables, 2019, "74", "119") != ("Matlök", None):
        raise RuntimeError("2019 undercode anchor failed: 74/119")
    if lookup(tables, 2018, "74", "119") == ("Matlök", None):
        raise RuntimeError("Cross-year fallback detected")

    summary_before, components_before = pd.read_parquet(summary_path), pd.read_parquet(components_path)
    if len(summary_before) != 32384 or len(components_before) != 73328:
        raise RuntimeError(f"Unexpected pilot dimensions: summary={len(summary_before):,}, components={len(components_before):,}")
    components_after = relabel_components(components_before, tables)
    summary_after = relabel_summary(summary_before, components_after, tables)
    assert_label_only(components_before, components_after, COMP_LABEL_COLUMNS)
    assert_label_only(summary_before, summary_after, SUMMARY_LABEL_COLUMNS)

    comp_backup = pilot / "akerminne_components.before_official_crop_codes.parquet"
    sum_backup = pilot / "akerminne_year_summary.before_official_crop_codes.parquet"
    if not comp_backup.exists():
        components_before.to_parquet(comp_backup, index=False)
    if not sum_backup.exists():
        summary_before.to_parquet(sum_backup, index=False)
    comp_tmp = _write_verified_tmp(components_after, components_path)
    sum_tmp = _write_verified_tmp(summary_after, summary_path)
    components_path.unlink(missing_ok=True); comp_tmp.replace(components_path)
    summary_path.unlink(missing_ok=True); sum_tmp.replace(summary_path)

    report_dir.mkdir(parents=True, exist_ok=True)
    unknown = unknown_report(components_after)
    unknown.to_csv(report_dir / "unknown_crop_codes_after_official.csv", index=False, encoding="utf-8-sig")
    by_year = []
    for year, g in components_after.groupby("history_year", sort=True):
        by_year.append({"year": int(year), "component_rows": int(len(g)), "known_rows": int(g["crop_known"].sum()), "unknown_rows": int((~g["crop_known"]).sum()), "known_pct": float(100*g["crop_known"].mean()) if len(g) else 0.0})
    report = {
        "schema_version": "akerminne-official-crop-labels-v1",
        "dictionary_years": sorted(tables), "dictionary_rows": int(meta["manifest"]["total_normalized_rows"]),
        "component_rows": int(len(components_after)), "known_component_rows": int(components_after["crop_known"].sum()),
        "unknown_component_rows": int((~components_after["crop_known"]).sum()), "unknown_combinations": int(len(unknown)),
        "by_year": by_year,
        "invariants": {"geometry_or_mapping_columns_changed": False, "component_rows": int(len(components_after)), "summary_rows": int(len(summary_after))},
    }
    (report_dir / "official_crop_code_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# ÅkerMinne – official crop codes 2015–2025", "",
             f"- Dictionary years: `{', '.join(map(str, report['dictionary_years']))}`",
             f"- Official normalized rows: `{report['dictionary_rows']:,}`",
             f"- ÅkerMinne component rows: `{report['component_rows']:,}`",
             f"- Known after official dictionaries: `{report['known_component_rows']:,}`",
             f"- Unknown after official dictionaries: `{report['unknown_component_rows']:,}`",
             f"- Remaining unknown code/subcode combinations: `{report['unknown_combinations']:,}`",
             "- Geometry/mapping/coverage columns changed: `NO`", "",
             "| Year | components | known | unknown | known % |", "|---:|---:|---:|---:|---:|"]
    for r in by_year:
        lines.append(f"| {r['year']} | {r['component_rows']} | {r['known_rows']} | {r['unknown_rows']} | {r['known_pct']:.2f}% |")
    report_md = report_dir / "official_crop_code_report.md"
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 78); print("ÅkerMinne official annual crop codes 2015-2025: PASS"); print("=" * 78)
    print(f"Official dictionary rows: {report['dictionary_rows']:,}")
    print(f"Component rows: {report['component_rows']:,}")
    print(f"Known/unknown: {report['known_component_rows']:,}/{report['unknown_component_rows']:,}")
    print(f"Remaining unknown combinations: {report['unknown_combinations']:,}")
    print("Geometry/mapping/coverage changed: NO"); print(f"Report: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
