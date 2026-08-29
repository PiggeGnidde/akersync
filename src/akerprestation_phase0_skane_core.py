#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure QA helpers for the ÅkerPrestation phase 0 full-Skåne run."""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

import pandas as pd

COVERAGE_TOL = 1e-6
VALID_CLASSES = set(range(1, 11))


def field_id_digest(ids: Iterable[str]) -> str:
    values = sorted(str(x) for x in ids)
    payload = "\n".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _flag_count(summary: pd.DataFrame, column: str, flag: str) -> int:
    if column not in summary.columns:
        return 0
    return int(summary[column].fillna("").astype(str).str.split(";").apply(lambda xs: flag in xs).sum())


def municipality_validation(
    *,
    code: str,
    municipality: str,
    expected_ids: set[str],
    soil_summary: pd.DataFrame,
    soil_components: pd.DataFrame,
    sko_summary: pd.DataFrame,
    sko_components: pd.DataFrame,
    soil_manifest: dict[str, Any],
    sko_manifest: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    expected_n = len(expected_ids)

    for name, frame in (("soil", soil_summary), ("sko", sko_summary)):
        if len(frame) != expected_n:
            errors.append(f"{name} summary rows {len(frame)} != expected {expected_n}")
        if "current_field_id" not in frame.columns:
            errors.append(f"{name} summary missing current_field_id")
            continue
        if not frame["current_field_id"].astype(str).is_unique:
            errors.append(f"{name} summary current_field_id is not unique")
        if set(frame["current_field_id"].astype(str)) != set(expected_ids):
            errors.append(f"{name} summary ID set mismatch")

    if int(soil_manifest.get("summary_rows", -1)) != len(soil_summary):
        errors.append("soil checkpoint manifest summary_rows mismatch")
    if int(soil_manifest.get("component_rows", -1)) != len(soil_components):
        errors.append("soil checkpoint manifest component_rows mismatch")
    if int(sko_manifest.get("summary_rows", -1)) != len(sko_summary):
        errors.append("SKO checkpoint manifest summary_rows mismatch")
    if int(sko_manifest.get("component_rows", -1)) != len(sko_components):
        errors.append("SKO checkpoint manifest component_rows mismatch")

    unverified_soil = (
        int(soil_components["soil_class_normalized"].isna().sum())
        if "soil_class_normalized" in soil_components.columns else len(soil_components)
    )
    if unverified_soil:
        errors.append(f"{unverified_soil} unverified soil-class component rows")

    if "soil_class_normalized" in soil_components.columns and len(soil_components):
        observed = set(
            pd.to_numeric(soil_components["soil_class_normalized"], errors="coerce")
            .dropna().astype(int).tolist()
        )
        unexpected = sorted(observed - VALID_CLASSES)
        if unexpected:
            errors.append(f"unexpected normalized soil classes: {unexpected}")

    unverified_sko = (
        int((sko_components["sko_id"].fillna("").astype(str).str.strip() == "").sum())
        if "sko_id" in sko_components.columns else len(sko_components)
    )
    if unverified_sko:
        errors.append(f"{unverified_sko} blank/unverified SKO component rows")

    soil_missing = int((soil_summary["soil_class_coverage_unique"] <= COVERAGE_TOL).sum())
    soil_partial = int(
        (
            (soil_summary["soil_class_coverage_unique"] > COVERAGE_TOL)
            & (soil_summary["soil_class_coverage_unique"] < 1.0 - COVERAGE_TOL)
        ).sum()
    )
    soil_overlap = int((soil_summary["soil_class_coverage_raw"] > 1.0 + COVERAGE_TOL).sum())
    soil_mixed = int(soil_summary["mixed_soil_class"].fillna(False).sum())

    if soil_missing:
        warnings.append(f"WARN_MISSING_SOIL_CLASS: {soil_missing} fields")
    if soil_partial:
        warnings.append(f"WARN_PARTIAL_SOIL_CLASS_COVERAGE: {soil_partial} fields")
    if soil_overlap:
        warnings.append(f"WARN_DUPLICATE_CLASS_OVERLAP: {soil_overlap} fields")

    sko_missing = int((sko_summary["sko_coverage_unique"] <= COVERAGE_TOL).sum())
    sko_partial = int(
        (
            (sko_summary["sko_coverage_unique"] > COVERAGE_TOL)
            & (sko_summary["sko_coverage_unique"] < 1.0 - COVERAGE_TOL)
        ).sum()
    )
    sko_overlap = int((sko_summary["sko_coverage_raw"] > 1.0 + COVERAGE_TOL).sum())
    sko_boundary = int(sko_summary["crosses_sko_boundary"].fillna(False).sum())

    # SKO is an official exhaustive region layer for this purpose. A fully
    # uncovered current field is therefore a hard error, unlike historical
    # soil-class gaps which are legitimate source limitations.
    if sko_missing:
        errors.append(f"{sko_missing} fields have no SKO coverage")
    if sko_partial:
        warnings.append(f"WARN_PARTIAL_SKO_COVERAGE: {sko_partial} fields")
    if sko_overlap:
        warnings.append(f"WARN_DUPLICATE_SKO_OVERLAP: {sko_overlap} fields")

    for name, frame, prefix in (
        ("soil", soil_summary, "soil_class"),
        ("sko", sko_summary, "sko"),
    ):
        geom_col = f"{prefix}_geometry_status"
        if geom_col in frame.columns:
            bad = int((frame[geom_col].fillna("").astype(str) == "GEOMETRY_ERROR").sum())
            if bad:
                errors.append(f"{name}: {bad} field geometry errors")

    return {
        "municipality_code": str(code),
        "municipality": str(municipality),
        "status": "PASS" if not errors else "FAIL",
        "reference_fields": expected_n,
        "errors": errors,
        "warnings": warnings,
        "soil": {
            "component_rows": int(len(soil_components)),
            "missing_fields": soil_missing,
            "partial_fields": soil_partial,
            "mixed_fields": soil_mixed,
            "coverage_raw_gt_1": soil_overlap,
            "unverified_component_rows": unverified_soil,
            "reason_flag_counts": {
                flag: _flag_count(soil_summary, "soil_class_reason_flags", flag)
                for flag in (
                    "MISSING_SOIL_CLASS",
                    "LOW_SOIL_CLASS_COVERAGE",
                    "MULTIPLE_SOIL_CLASSES",
                    "DUPLICATE_CLASS_OVERLAP",
                    "REPAIRED_FIELD_GEOMETRY",
                    "REPAIRED_REFERENCE_GEOMETRY",
                    "GEOMETRY_ERROR",
                    "UNVERIFIED_CLASS_CODE",
                )
            },
        },
        "sko": {
            "component_rows": int(len(sko_components)),
            "missing_fields": sko_missing,
            "partial_fields": sko_partial,
            "boundary_fields": sko_boundary,
            "coverage_raw_gt_1": sko_overlap,
            "unverified_component_rows": unverified_sko,
            "reason_flag_counts": {
                flag: _flag_count(sko_summary, "sko_reason_flags", flag)
                for flag in (
                    "MISSING_SKO",
                    "LOW_SKO_COVERAGE",
                    "MULTIPLE_SKO",
                    "DUPLICATE_SKO_OVERLAP",
                    "REPAIRED_FIELD_GEOMETRY",
                    "REPAIRED_REFERENCE_GEOMETRY",
                    "GEOMETRY_ERROR",
                    "UNVERIFIED_SKO_ID",
                )
            },
        },
    }


def build_class_municipality_rows(
    context: pd.DataFrame,
    components: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if len(components):
        work = components.copy()
        # Components already carry municipality; add only the code here to avoid
        # creating municipality_x/municipality_y suffixes during county aggregation.
        lookup = context[["current_field_id", "municipality_code"]].drop_duplicates()
        work = work.merge(lookup, on="current_field_id", how="left", validate="many_to_one")
        work["soil_class_normalized"] = pd.to_numeric(
            work["soil_class_normalized"], errors="coerce"
        ).astype("Int64")
        grouped = (
            work.dropna(subset=["soil_class_normalized"])
            .groupby(["municipality_code", "municipality", "soil_class_normalized"], dropna=False)
            .agg(
                component_rows=("current_field_id", "size"),
                field_count=("current_field_id", "nunique"),
                intersection_area_m2=("intersection_area_m2", "sum"),
            )
            .reset_index()
        )
        for r in grouped.itertuples(index=False):
            rows.append(
                {
                    "municipality_code": str(r.municipality_code),
                    "municipality": str(r.municipality),
                    "soil_class": str(int(r.soil_class_normalized)),
                    "area_kind": "classified_component_raw",
                    "field_count": int(r.field_count),
                    "component_rows": int(r.component_rows),
                    "area_m2": float(r.intersection_area_m2),
                }
            )

    for (code, municipality), group in context.groupby(
        ["municipality_code", "municipality"], sort=True
    ):
        uncovered_share = (1.0 - group["soil_class_coverage_unique"]).clip(lower=0.0)
        rows.append(
            {
                "municipality_code": str(code),
                "municipality": str(municipality),
                "soil_class": "UNCLASSIFIED",
                "area_kind": "unclassified_unique_gap",
                "field_count": int((uncovered_share > COVERAGE_TOL).sum()),
                "component_rows": 0,
                "area_m2": float((group["field_area_m2"] * uncovered_share).sum()),
            }
        )

    return sorted(
        rows,
        key=lambda r: (
            r["municipality_code"],
            999 if r["soil_class"] == "UNCLASSIFIED" else int(r["soil_class"]),
        ),
    )


def build_sko_distribution_rows(
    context: pd.DataFrame,
    components: pd.DataFrame,
) -> list[dict[str, Any]]:
    if components.empty:
        return []
    # SKO components already carry municipality; add code + dominant convenience field only.
    lookup = context[["current_field_id", "municipality_code", "dominant_sko_id"]].drop_duplicates()
    work = components.merge(lookup, on="current_field_id", how="left", validate="many_to_one")
    grouped = (
        work.groupby(["municipality_code", "municipality", "sko_id"], dropna=False)
        .agg(
            component_rows=("current_field_id", "size"),
            field_count=("current_field_id", "nunique"),
            intersection_area_m2=("intersection_area_m2", "sum"),
        )
        .reset_index()
    )
    dominant = (
        context.groupby(["municipality_code", "municipality", "dominant_sko_id"], dropna=False)
        .size()
        .reset_index(name="dominant_field_count")
        .rename(columns={"dominant_sko_id": "sko_id"})
    )
    grouped = grouped.merge(
        dominant, on=["municipality_code", "municipality", "sko_id"], how="left"
    )
    grouped["dominant_field_count"] = grouped["dominant_field_count"].fillna(0).astype(int)
    rows = []
    for r in grouped.itertuples(index=False):
        rows.append(
            {
                "municipality_code": str(r.municipality_code),
                "municipality": str(r.municipality),
                "sko_id": str(r.sko_id),
                "component_rows": int(r.component_rows),
                "field_count": int(r.field_count),
                "dominant_field_count": int(r.dominant_field_count),
                "intersection_area_m2": float(r.intersection_area_m2),
            }
        )
    return sorted(rows, key=lambda r: (r["municipality_code"], r["sko_id"]))


def problem_field_ids(context: pd.DataFrame, n_each: int = 10) -> list[str]:
    ids: list[str] = []

    def add(frame: pd.DataFrame) -> None:
        for value in frame["current_field_id"].astype(str):
            if value not in ids:
                ids.append(value)

    add(context.nsmallest(n_each, "soil_class_coverage_unique"))
    add(context.nsmallest(n_each, "sko_coverage_unique"))
    add(context.nlargest(n_each, "soil_class_count"))
    add(context[context["crosses_sko_boundary"].fillna(False)].head(n_each))
    add(
        context[
            (context["soil_class_coverage_raw"] > 1.0 + COVERAGE_TOL)
            | (context["sko_coverage_raw"] > 1.0 + COVERAGE_TOL)
        ].head(n_each)
    )
    add(
        context[
            context["reason_flags"].fillna("").astype(str).str.contains(
                "UNVERIFIED|REPAIRED|GEOMETRY_ERROR", regex=True
            )
        ].head(n_each)
    )
    add(context[context["dominant_soil_class"].isin([1, 2, 3, 4, 5])].head(n_each))
    return ids


def overall_acceptance(
    *,
    municipalities_passed: int,
    reference_fields: int,
    unique_reference_fields: int,
    classes_present: list[int],
    unverified_soil_components: int,
    unverified_sko_components: int,
    sko_missing_fields: int,
    id_set_matches: bool,
    freeze_contract_ok: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    if municipalities_passed != 33:
        errors.append(f"municipalities passed {municipalities_passed}/33")
    if reference_fields != 128636:
        errors.append(f"reference rows {reference_fields} != 128636")
    if unique_reference_fields != 128636:
        errors.append(f"unique reference IDs {unique_reference_fields} != 128636")
    if not id_set_matches:
        errors.append("county context ID set differs from current 2025 reference source")
    missing_classes = sorted(VALID_CLASSES - set(int(x) for x in classes_present))
    if missing_classes:
        errors.append(f"real component data missing classes {missing_classes}")
    if unverified_soil_components:
        errors.append(f"{unverified_soil_components} unverified soil components")
    if unverified_sko_components:
        errors.append(f"{unverified_sko_components} unverified SKO components")
    if sko_missing_fields:
        errors.append(f"{sko_missing_fields} fields missing SKO coverage")
    if not freeze_contract_ok:
        errors.append("immutable ÅkerMinne v1 freeze contract evidence failed")
    return {"pass": not errors, "errors": errors}
