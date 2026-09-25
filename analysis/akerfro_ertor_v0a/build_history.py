#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · STOPPUNKT B.

Build field-level pea/legume history from frozen ÅkerMinne Skåne outputs.

Primary positive history is deliberately conservative:
  status == SINGLE_CROP and semantic group == CONSERVART.

Mixed/complex target occurrences are preserved separately and never silently
promoted into the primary positive set.

No ÅkerMinne geometry, matching, status, ÅkerScore or ÅkerDrift artifact is
recomputed or modified.
"""
from __future__ import annotations

import argparse
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
    akerfro_crop_group,
)

YEARS = list(range(2015, 2026))
HISTORY_END_YEAR = 2025
DEFAULT_CONFIG = ROOT / "config" / "akerfro_ertor_v0a.json"
DEFAULT_AKERMINNE_ROOT = ROOT.parent / "AkerSync-Minne"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerfro_ertor_v0a"


def _years(values: pd.Series) -> list[int]:
    if values.empty:
        return []
    return sorted({int(v) for v in values.dropna().tolist()})


def _first(years: list[int]) -> int | None:
    return years[0] if years else None


def _last(years: list[int]) -> int | None:
    return years[-1] if years else None


def load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    years = [int(x) for x in cfg.get("years", [])]
    if years != YEARS:
        raise RuntimeError(f"Config years must be exactly {YEARS}; got {years}")
    if cfg.get("target_crop_group") != CONSERVART:
        raise RuntimeError("target_crop_group must be CONSERVART")
    if cfg.get("positive_history_statuses") != ["SINGLE_CROP"]:
        raise RuntimeError("STOPPUNKT B primary positive status must remain SINGLE_CROP")
    return cfg


def load_registry(akerminne_root: Path) -> CropRegistry:
    directory = (
        akerminne_root
        / "data"
        / "derived"
        / "akerminne_v1a"
        / "skane"
        / "reference"
        / "crop_codes"
    )
    registry, meta = CropRegistry.from_directory(directory)
    if meta.get("loaded_years") != YEARS:
        raise RuntimeError(
            f"Frozen ÅkerMinne crop registry must contain 2015-2025; got {meta.get('loaded_years')}"
        )
    return registry


def municipality_dirs(akerminne_root: Path, cfg: dict[str, Any]) -> list[Path]:
    root = (
        akerminne_root
        / "data"
        / "derived"
        / "akerminne_v1a"
        / "skane"
        / "municipalities"
    )
    dirs = sorted(p for p in root.iterdir() if p.is_dir())
    expected = int(cfg["expected_municipalities"])
    if len(dirs) != expected:
        raise RuntimeError(f"Expected {expected} municipality directories under {root}; got {len(dirs)}")
    return dirs


def load_frozen_summary(dirs: list[Path], cfg: dict[str, Any]) -> pd.DataFrame:
    cols = [
        "municipality",
        "history_year",
        "current_field_id",
        "current_block_id",
        "current_skiftesbeteckning",
        "current_area_m2",
        "dominant_crop_name",
        "dominant_crop_known",
        "status",
        "identity_match_confidence",
        "coverage_display",
    ]
    frames: list[pd.DataFrame] = []
    for directory in dirs:
        path = directory / "akerminne_year_summary_classified.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path, columns=cols)
        frame = frame.copy()
        frame["municipality_dir"] = directory.name
        frames.append(frame)

    history = pd.concat(frames, ignore_index=True)
    history["history_year"] = pd.to_numeric(history["history_year"], errors="raise").astype(int)
    if sorted(history["history_year"].unique().tolist()) != YEARS:
        raise RuntimeError("Frozen summary does not contain exactly 2015-2025")
    expected_rows = int(cfg["expected_field_years"])
    if len(history) != expected_rows:
        raise RuntimeError(f"Expected {expected_rows:,} field-years; got {len(history):,}")
    expected_fields = int(cfg["expected_current_fields"])
    fields = int(history["current_field_id"].nunique())
    if fields != expected_fields:
        raise RuntimeError(f"Expected {expected_fields:,} unique current fields; got {fields:,}")
    if history.duplicated(["history_year", "current_field_id"]).any():
        raise RuntimeError("Duplicate history_year/current_field_id rows in frozen summary")
    history["akerfro_group"] = history["dominant_crop_name"].map(akerfro_crop_group)
    history["is_clean"] = history["status"].eq("SINGLE_CROP")
    return history


def load_target_components(
    dirs: list[Path],
    summary: pd.DataFrame,
    registry: CropRegistry,
) -> pd.DataFrame:
    cols = [
        "history_year",
        "current_field_id",
        "crop_code_raw",
        "crop_subcategory_raw",
        "crop_area_m2",
        "crop_share_current",
        "crop_rank",
    ]
    frames: list[pd.DataFrame] = []
    for directory in dirs:
        path = directory / "akerminne_crop_areas_grouped.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path, columns=cols)
        if len(frame):
            frame = frame.copy()
            frame["municipality_dir"] = directory.name
            frames.append(frame)

    if not frames:
        return pd.DataFrame()
    crops = pd.concat(frames, ignore_index=True)
    crops["history_year"] = pd.to_numeric(crops["history_year"], errors="raise").astype(int)

    names: list[str | None] = []
    groups: list[str | None] = []
    for row in crops.itertuples(index=False):
        rec = registry.lookup(row.history_year, row.crop_code_raw, row.crop_subcategory_raw)
        name = rec.crop_name if rec else None
        names.append(name)
        groups.append(akerfro_crop_group(name))
    crops["official_crop_name"] = names
    crops["akerfro_group"] = groups

    target = crops[crops["akerfro_group"].eq(CONSERVART)].copy()
    if target.empty:
        raise RuntimeError("No CONSERVART components found in frozen grouped crop areas")

    meta_cols = [
        "history_year",
        "current_field_id",
        "municipality",
        "status",
        "identity_match_confidence",
        "coverage_display",
    ]
    meta = summary[meta_cols]
    target = target.merge(
        meta,
        on=["history_year", "current_field_id"],
        how="left",
        validate="many_to_one",
    )
    if target["status"].isna().any():
        raise RuntimeError("Target components could not be joined to frozen summary status")

    grouped = (
        target.groupby(
            [
                "history_year",
                "current_field_id",
                "municipality",
                "status",
                "identity_match_confidence",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            target_crop_area_m2=("crop_area_m2", "sum"),
            target_crop_share_current=("crop_share_current", "sum"),
            target_component_rows=("crop_code_raw", "size"),
        )
        .sort_values(["history_year", "current_field_id"], kind="mergesort")
        .reset_index(drop=True)
    )
    grouped["is_clean_positive"] = grouped["status"].eq("SINGLE_CROP")
    return grouped


def clean_positive_field_years(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary[
        summary["is_clean"] & summary["akerfro_group"].eq(CONSERVART)
    ].copy()
    keep = [
        "history_year",
        "municipality",
        "current_field_id",
        "current_block_id",
        "current_skiftesbeteckning",
        "current_area_m2",
        "dominant_crop_name",
        "status",
        "identity_match_confidence",
        "coverage_display",
    ]
    return out[keep].sort_values(
        ["history_year", "current_field_id"], kind="mergesort"
    ).reset_index(drop=True)


def build_field_history(summary: pd.DataFrame) -> pd.DataFrame:
    clean = summary[summary["is_clean"]].copy()
    current = (
        summary.sort_values(["current_field_id", "history_year"], kind="mergesort")
        .groupby("current_field_id", sort=True)
        .tail(1)
        [[
            "current_field_id",
            "municipality",
            "current_block_id",
            "current_skiftesbeteckning",
            "current_area_m2",
        ]]
        .drop_duplicates("current_field_id")
        .set_index("current_field_id")
    )

    rows: list[dict[str, Any]] = []
    for field_id, g in clean.groupby("current_field_id", sort=True):
        target_years = _years(g.loc[g["akerfro_group"].eq(CONSERVART), "history_year"])
        other_pea_years = _years(g.loc[g["akerfro_group"].eq(OTHER_PEA), "history_year"])
        faba_years = _years(g.loc[g["akerfro_group"].eq(FABA_BEAN), "history_year"])
        other_legume_years = _years(g.loc[g["akerfro_group"].eq(OTHER_LEGUME), "history_year"])
        legume_years = sorted(set(target_years + other_pea_years + faba_years + other_legume_years))
        last_target = _last(target_years)
        rows.append(
            {
                "current_field_id": field_id,
                "n_target_pea_years_2015_2025": len(target_years),
                "first_target_pea_year": _first(target_years),
                "last_target_pea_year": last_target,
                "years_since_last_target_pea": (
                    HISTORY_END_YEAR - last_target if last_target is not None else None
                ),
                "target_pea_years_list": target_years,
                "n_other_pea_years": len(other_pea_years),
                "other_pea_years_list": other_pea_years,
                "n_faba_bean_years": len(faba_years),
                "faba_bean_years_list": faba_years,
                "n_other_legume_years": len(other_legume_years),
                "other_legume_years_list": other_legume_years,
                "legume_years_list": legume_years,
                "usable_history_years": int(len(g)),
                "history_end_year": HISTORY_END_YEAR,
            }
        )

    out = pd.DataFrame(rows).set_index("current_field_id")
    # Fields with zero SINGLE_CROP years must still remain in the candidate universe.
    out = current.join(out, how="left")

    list_cols = [
        "target_pea_years_list",
        "other_pea_years_list",
        "faba_bean_years_list",
        "other_legume_years_list",
        "legume_years_list",
    ]
    for col in list_cols:
        out[col] = out[col].map(lambda x: x if isinstance(x, list) else [])
    count_cols = [
        "n_target_pea_years_2015_2025",
        "n_other_pea_years",
        "n_faba_bean_years",
        "n_other_legume_years",
        "usable_history_years",
    ]
    for col in count_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["history_end_year"] = HISTORY_END_YEAR
    return out.reset_index().sort_values("current_field_id", kind="mergesort").reset_index(drop=True)


def validate_stop_a_anchors(
    positives: pd.DataFrame,
    field_history: pd.DataFrame,
    cfg: dict[str, Any],
) -> None:
    anchors = cfg.get("checkpoint_a_anchors") or {}
    expected_fy = int(anchors["clean_conservart_field_years"])
    expected_fields = int(anchors["unique_clean_conservart_fields"])
    if len(positives) != expected_fy:
        raise RuntimeError(
            f"STOPPUNKT A anchor mismatch: expected {expected_fy:,} clean CONSERVART field-years; "
            f"got {len(positives):,}"
        )
    fields = int((field_history["n_target_pea_years_2015_2025"] > 0).sum())
    if fields != expected_fields:
        raise RuntimeError(
            f"STOPPUNKT A anchor mismatch: expected {expected_fields:,} positive fields; got {fields:,}"
        )


def make_summary(
    summary: pd.DataFrame,
    positives: pd.DataFrame,
    field_history: pd.DataFrame,
    target_components: pd.DataFrame,
) -> dict[str, Any]:
    yearly_clean = {
        str(year): int((positives["history_year"] == year).sum()) for year in YEARS
    }
    mixed = target_components[~target_components["is_clean_positive"]].copy()
    mixed_by_status = {
        str(k): int(v)
        for k, v in mixed["status"].value_counts(dropna=False).sort_index().items()
    }
    repeated = field_history[field_history["n_target_pea_years_2015_2025"] >= 2]
    return {
        "schema_version": "akerfro-ertor-pea-history-v0a",
        "history_years": YEARS,
        "history_end_year": HISTORY_END_YEAR,
        "primary_positive_definition": "SINGLE_CROP + semantic CONSERVART",
        "field_years": int(len(summary)),
        "current_fields": int(len(field_history)),
        "clean_conservart_field_years": int(len(positives)),
        "unique_clean_conservart_fields": int(
            (field_history["n_target_pea_years_2015_2025"] > 0).sum()
        ),
        "fields_with_2plus_clean_conservart_years": int(len(repeated)),
        "max_clean_conservart_years_on_one_field": int(
            field_history["n_target_pea_years_2015_2025"].max()
        ),
        "clean_conservart_by_year": yearly_clean,
        "mixed_or_complex_target_field_years": int(len(mixed)),
        "mixed_or_complex_target_by_status": mixed_by_status,
        "method_note": (
            "Non-use is unlabeled, not negative. The 2017 processor transition around Bjuv "
            "is an external-demand/logistics caution, not an agronomic negative label."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--akerminne-root", default=str(DEFAULT_AKERMINNE_ROOT))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    akerminne_root = Path(args.akerminne_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    dirs = municipality_dirs(akerminne_root, cfg)
    registry = load_registry(akerminne_root)
    summary = load_frozen_summary(dirs, cfg)
    positives = clean_positive_field_years(summary)
    target_components = load_target_components(dirs, summary, registry)
    field_history = build_field_history(summary)
    validate_stop_a_anchors(positives, field_history, cfg)

    mixed = target_components[~target_components["is_clean_positive"]].copy()

    field_path = out / "pea_history_by_field.parquet"
    positive_path = out / "pea_positive_field_years.parquet"
    mixed_path = out / "pea_mixed_or_complex_target_field_years.parquet"
    summary_path = out / "pea_history_summary.json"

    field_history.to_parquet(field_path, index=False)
    positives.to_parquet(positive_path, index=False)
    mixed.to_parquet(mixed_path, index=False)

    report = make_summary(summary, positives, field_history, target_components)
    report["outputs"] = {
        "pea_history_by_field": str(field_path),
        "pea_positive_field_years": str(positive_path),
        "pea_mixed_or_complex_target_field_years": str(mixed_path),
    }
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("ÅkerFrö – Ärter MVP v0a · STOPPUNKT B")
    print("=" * 78)
    print("Primary positive definition: SINGLE_CROP + semantic CONSERVART")
    print(f"Current fields: {len(field_history):,}")
    print(f"Clean CONSERVART field-years: {len(positives):,}")
    print(
        "Unique current fields with >=1 clean CONSERVART year: "
        f"{int((field_history['n_target_pea_years_2015_2025'] > 0).sum()):,}"
    )
    repeated = field_history[field_history["n_target_pea_years_2015_2025"] >= 2]
    print(f"Fields with >=2 clean CONSERVART years: {len(repeated):,}")
    print(
        "Maximum clean CONSERVART years on one current field: "
        f"{int(field_history['n_target_pea_years_2015_2025'].max())}"
    )
    print(f"Mixed/complex target field-years kept separate: {len(mixed):,}")
    print("\nCLEAN CONSERVART BY YEAR")
    print(
        positives.groupby("history_year").size().reindex(YEARS, fill_value=0)
        .rename("n_clean_conservart").to_string()
    )
    print(f"\nField history: {field_path}")
    print(f"Positive field-years: {positive_path}")
    print(f"Mixed/complex target history: {mixed_path}")
    print(f"Summary: {summary_path}")
    print("=" * 78)
    print("STOPPUNKT B: PASS")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
