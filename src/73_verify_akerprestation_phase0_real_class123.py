#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real-source integration verification for historical agricultural classes 1-3.

This is intentionally a tiny gate after the Skurup pilot. It does NOT run a
municipality or Skåne batch. It finds real 2025 fields outside Skurup that
intersect source polygons for classes 1, 2 and 3, then runs the exact existing
class 1-10 overlay on small candidate batches and requires five fields whose
dominant class is each target class.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from akerprestation_phase0_discovery_core import (
    EXPECTED_BASE_COMMIT,
    EXPECTED_BASE_TAG,
    load_json,
    repository_snapshot,
    sha256_file,
)
from akerprestation_phase0_overlay_core import (
    SOIL_SPEC,
    field_id,
    overlay_fields,
    prepare_geometries,
)

PROJECT_CONFIG = ROOT / "config" / "local_paths.json"
MUNICIPALITY_CONFIG = ROOT / "config" / "akerminne_skane_municipalities.json"
PHASE_ROOT = ROOT / "data" / "derived" / "akerprestation_phase0"
SOIL_SOURCE = PHASE_ROOT / "discovery" / "source" / "jord_skogsklassificering_class1_10.gpkg"
OUT_DIR = PHASE_ROOT / "qa" / "real_class123"
TARGET_CLASSES = (1, 2, 3)
REQUIRED_PER_CLASS = 5
CANDIDATE_BATCH = 50
MAX_EXACT_CANDIDATES_PER_CLASS = 300
SCHEMA_VERSION = "akerprestation-phase0-real-class123-v0a"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(str(message), flush=True)


def municipality_map() -> dict[str, str]:
    doc = load_json(MUNICIPALITY_CONFIG)
    return {str(x["code"]): str(x["name"]) for x in doc.get("municipalities") or []}


def add_ids(fields: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = fields.copy()
    out["current_field_id"] = [
        field_id(block, skifte)
        for block, skifte in zip(out["blockid"], out["skiftesbeteckning"])
    ]
    return out


def rank_real_candidates(
    fields: gpd.GeoDataFrame,
    fixed_reference: gpd.GeoDataFrame,
    target_class: int,
) -> gpd.GeoDataFrame:
    """Find real non-Skurup candidates, ranked by target-class share estimate."""
    target = fixed_reference[
        pd.to_numeric(fixed_reference["KLASS"], errors="coerce") == int(target_class)
    ].copy()
    if target.empty:
        raise RuntimeError(f"Class {target_class}: no source polygons")

    try:
        target_union = target.geometry.union_all()
    except Exception:
        target_union = target.geometry.unary_union

    indexes = list(fields.sindex.query(target_union, predicate="intersects"))
    candidates = fields.iloc[sorted(set(map(int, indexes)))].copy()
    candidates = candidates[
        ~candidates["region_kod"].astype(str).str.startswith("1264")
    ].copy()
    if candidates.empty:
        return candidates

    # This rank is only candidate prioritisation. Acceptance below always comes
    # from the exact full class 1-10 overlay.
    intersection = candidates.geometry.intersection(target_union)
    candidates["_target_intersection_m2"] = intersection.area.astype(float)
    candidates["_target_share_est"] = (
        candidates["_target_intersection_m2"] / candidates.geometry.area.astype(float)
    )
    candidates = candidates[candidates["_target_intersection_m2"] > 0].copy()
    candidates = candidates.sort_values(
        ["_target_share_est", "_target_intersection_m2", "current_field_id"],
        ascending=[False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return candidates


def select_dominant_target_rows(
    summary: pd.DataFrame,
    target_class: int,
    required: int = REQUIRED_PER_CLASS,
) -> pd.DataFrame:
    accepted = summary[
        pd.to_numeric(summary["dominant_soil_class"], errors="coerce") == int(target_class)
    ].copy()
    accepted = accepted[
        accepted["soil_class_coverage_unique"] > 0
    ].copy()
    accepted = accepted.sort_values(
        ["dominant_soil_class_share", "soil_class_coverage_unique", "current_field_id"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    return accepted.head(required).copy()


def exact_select_for_class(
    fields: gpd.GeoDataFrame,
    soil_reference: gpd.GeoDataFrame,
    fixed_reference: gpd.GeoDataFrame,
    target_class: int,
) -> tuple[pd.DataFrame, pd.DataFrame, gpd.GeoDataFrame, dict[str, Any]]:
    candidates = rank_real_candidates(fields, fixed_reference, target_class)
    log(
        f"[class {target_class}] source polygons: "
        f"{int((pd.to_numeric(fixed_reference['KLASS'], errors='coerce') == target_class).sum()):,}; "
        f"real non-Skurup candidates: {len(candidates):,}"
    )
    if len(candidates) < REQUIRED_PER_CLASS:
        raise RuntimeError(
            f"Class {target_class}: only {len(candidates)} real non-Skurup candidate fields"
        )

    seen_summary: list[pd.DataFrame] = []
    seen_components: list[pd.DataFrame] = []
    processed = 0
    accepted = pd.DataFrame()

    upper = min(len(candidates), MAX_EXACT_CANDIDATES_PER_CLASS)
    while processed < upper and len(accepted) < REQUIRED_PER_CLASS:
        batch_end = min(processed + CANDIDATE_BATCH, upper)
        batch = candidates.iloc[processed:batch_end].copy()
        log(
            f"[class {target_class}] exact full 1-10 overlay candidates "
            f"{processed + 1:,}-{batch_end:,}/{upper:,}"
        )
        summary, components, _qa = overlay_fields(
            batch,
            soil_reference,
            SOIL_SPEC,
            f"RealClass{target_class}",
            reference_year=2025,
            progress_every=25,
            progress=log,
        )
        seen_summary.append(summary)
        seen_components.append(components)
        all_summary = pd.concat(seen_summary, ignore_index=True)
        accepted = select_dominant_target_rows(all_summary, target_class)
        log(
            f"[class {target_class}] accepted dominant real fields: "
            f"{len(accepted)}/{REQUIRED_PER_CLASS}"
        )
        processed = batch_end

    if len(accepted) < REQUIRED_PER_CLASS:
        raise RuntimeError(
            f"Class {target_class}: only {len(accepted)} dominant fields found after "
            f"{processed} exact candidates"
        )

    all_summary = pd.concat(seen_summary, ignore_index=True)
    all_components = pd.concat(seen_components, ignore_index=True)
    accepted_ids = set(accepted["current_field_id"].astype(str))
    selected_components = all_components[
        all_components["current_field_id"].astype(str).isin(accepted_ids)
    ].copy()

    selected_fields = candidates[
        candidates["current_field_id"].astype(str).isin(accepted_ids)
    ].copy()
    selected_fields = selected_fields.merge(
        accepted[
            [
                "current_field_id",
                "dominant_soil_class",
                "dominant_soil_class_share",
                "soil_class_coverage_raw",
                "soil_class_coverage_unique",
                "soil_class_count",
                "soil_class_reason_flags",
            ]
        ],
        on="current_field_id",
        how="left",
        validate="one_to_one",
    )
    selected_fields["verification_target_class"] = int(target_class)

    target_component = selected_components[
        pd.to_numeric(selected_components["soil_class_normalized"], errors="coerce")
        == int(target_class)
    ]
    target_ids = set(target_component["current_field_id"].astype(str))
    if target_ids != accepted_ids:
        raise RuntimeError(
            f"Class {target_class}: accepted field without positive target component"
        )

    qa = {
        "target_class": int(target_class),
        "source_polygon_count": int(
            (pd.to_numeric(fixed_reference["KLASS"], errors="coerce") == target_class).sum()
        ),
        "candidate_field_count": int(len(candidates)),
        "exact_candidate_fields_processed": int(processed),
        "selected_field_count": int(len(accepted)),
        "selected_ids": accepted["current_field_id"].astype(str).tolist(),
        "dominant_share_min": float(accepted["dominant_soil_class_share"].min()),
        "dominant_share_max": float(accepted["dominant_soil_class_share"].max()),
        "coverage_unique_min": float(accepted["soil_class_coverage_unique"].min()),
        "component_rows_selected": int(len(selected_components)),
    }
    return accepted, selected_components, selected_fields, qa


def main() -> int:
    try:
        repo = repository_snapshot(ROOT)
        if repo["akerminne_v1_base_commit"] != EXPECTED_BASE_COMMIT:
            raise RuntimeError("Frozen ÅkerMinne base mismatch")
        if not PROJECT_CONFIG.exists():
            raise FileNotFoundError(PROJECT_CONFIG)
        if not SOIL_SOURCE.exists():
            raise FileNotFoundError(
                f"{SOIL_SOURCE} missing; approved discovery cache is required"
            )

        project = load_json(PROJECT_CONFIG)
        fields_path = Path(project["skiften"])
        log("=" * 88)
        log("ÅkerPrestation phase 0 · REAL CLASS 1/2/3 INTEGRATION GATE")
        log("=" * 88)
        log(f"Base: {EXPECTED_BASE_TAG} {EXPECTED_BASE_COMMIT}")
        log(f"HEAD: {repo['head_commit']}")
        log("[inputs] loading current 2025 Skåne fields...")
        fields = gpd.read_file(fields_path).to_crs(3006)
        fields = add_ids(fields)
        if len(fields) != 128636 or not fields["current_field_id"].is_unique:
            raise RuntimeError(
                f"Expected 128,636 unique current fields; got {len(fields):,}"
            )
        log(f"[inputs] current fields loaded: {len(fields):,}")

        log("[inputs] loading verified class 1-10 source cache...")
        soil_reference = gpd.read_file(SOIL_SOURCE, layer="class1_10")
        fixed_reference, geom_qa = prepare_geometries(
            soil_reference, "soil_class_real_class123_gate"
        )
        log(
            f"[inputs] class source: {len(fixed_reference):,} polygons; "
            f"repaired={geom_qa['repaired']}; failed={geom_qa['failed']}"
        )
        if geom_qa["failed"]:
            raise RuntimeError(
                f"Class source has {geom_qa['failed']} unrepaired geometries"
            )

        fmap = municipality_map()
        summaries: list[pd.DataFrame] = []
        components: list[pd.DataFrame] = []
        geoms: list[gpd.GeoDataFrame] = []
        classes_qa: dict[str, Any] = {}

        for target_class in TARGET_CLASSES:
            summary, comp, selected_fields, qa = exact_select_for_class(
                fields, soil_reference, fixed_reference, target_class
            )
            summary = summary.copy()
            summary["verification_target_class"] = int(target_class)
            comp = comp.copy()
            comp["verification_target_class"] = int(target_class)
            selected_fields = selected_fields.copy()
            selected_fields["municipality_code"] = (
                selected_fields["region_kod"].astype(str).str[:4]
            )
            selected_fields["municipality"] = (
                selected_fields["municipality_code"].map(fmap)
            )
            summaries.append(summary)
            components.append(comp)
            geoms.append(selected_fields)
            classes_qa[str(target_class)] = qa

        selected_summary = pd.concat(summaries, ignore_index=True)
        selected_components = pd.concat(components, ignore_index=True)
        selected_geoms = gpd.GeoDataFrame(
            pd.concat(geoms, ignore_index=True),
            geometry="geometry",
            crs=fields.crs,
        )

        selected_ids = selected_summary["current_field_id"].astype(str)
        errors: list[str] = []
        if len(selected_summary) != REQUIRED_PER_CLASS * len(TARGET_CLASSES):
            errors.append("selected row count is not 15")
        if not selected_ids.is_unique:
            errors.append("selected current_field_id is not unique")
        if selected_geoms["region_kod"].astype(str).str.startswith("1264").any():
            errors.append("Skurup field leaked into outside-Skurup verification")
        if selected_components["soil_class_normalized"].isna().any():
            errors.append("unverified class component present")
        for target_class in TARGET_CLASSES:
            rows = selected_summary[
                selected_summary["verification_target_class"] == target_class
            ]
            if len(rows) != REQUIRED_PER_CLASS:
                errors.append(f"class {target_class}: selected count != 5")
            if not (
                pd.to_numeric(rows["dominant_soil_class"], errors="coerce")
                == target_class
            ).all():
                errors.append(f"class {target_class}: non-dominant selected row present")

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        summary_path = OUT_DIR / "selected_fields.parquet"
        component_path = OUT_DIR / "selected_components.parquet"
        geojson_path = OUT_DIR / "selected_fields.geojson"
        qa_path = OUT_DIR / "qa.json"
        report_path = OUT_DIR / "qa.md"

        selected_summary.to_parquet(summary_path, index=False)
        selected_components.to_parquet(component_path, index=False)
        tmp_geo = geojson_path.with_suffix(".tmp.geojson")
        selected_geoms.to_file(tmp_geo, driver="GeoJSON")
        os.replace(tmp_geo, geojson_path)

        qa_doc = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS" if not errors else "FAIL",
            "created_utc": utc_now(),
            "scope": "15 real fields only: 5 each dominant class 1, 2, 3; outside Skurup",
            "git": {
                "base_tag": EXPECTED_BASE_TAG,
                "base_commit": EXPECTED_BASE_COMMIT,
                "head_commit": repo["head_commit"],
                "branch": repo["branch"],
            },
            "sources": {
                "reference_fields": str(fields_path),
                "reference_fields_sha256": sha256_file(fields_path),
                "soil_class": str(SOIL_SOURCE),
                "soil_class_sha256": sha256_file(SOIL_SOURCE),
            },
            "reference_geometry_qa": geom_qa,
            "classes": classes_qa,
            "selected_rows": int(len(selected_summary)),
            "selected_unique_ids": int(selected_ids.nunique()),
            "selected_municipalities": sorted(
                {
                    str(x)
                    for x in selected_geoms["municipality"].dropna().astype(str)
                }
            ),
            "unverified_component_rows": int(
                selected_components["soil_class_normalized"].isna().sum()
            ),
            "errors": errors,
            "outputs": {
                "selected_fields": str(summary_path),
                "selected_components": str(component_path),
                "selected_geojson": str(geojson_path),
            },
            "guardrail": (
                "No municipality batch, no Skåne batch, no SKO recomputation, "
                "no web, no satellite, no yield model."
            ),
        }
        qa_path.write_text(
            json.dumps(qa_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        lines = [
            "# ÅkerPrestation fas 0 – verklig klass 1/2/3-verifiering",
            "",
            f"**Status:** `{qa_doc['status']}`",
            "",
            "Exakt overlay mot hela historiska klasslagret 1–10 på 15 verkliga 2025-skiften utanför Skurup.",
            "",
        ]
        for target_class in TARGET_CLASSES:
            q = classes_qa[str(target_class)]
            lines += [
                f"## Klass {target_class}",
                "",
                f"- Verkliga kandidatskiften: {q['candidate_field_count']:,}",
                f"- Exakt testade kandidater: {q['exact_candidate_fields_processed']:,}",
                f"- Godkända dominant klass {target_class}: {q['selected_field_count']}",
                f"- Min dominantandel: {q['dominant_share_min']:.6f}",
                f"- Min unik klasstäckning: {q['coverage_unique_min']:.6f}",
                "- Valda skiften: " + ", ".join(f"`{x}`" for x in q["selected_ids"]),
                "",
            ]
        lines += [
            "## Guardrail",
            "",
            qa_doc["guardrail"],
            "",
            "## STOPPUNKT B.1",
            "",
            "Ingen full Skånekörning har startats.",
            "",
        ]
        report_path.write_text("\n".join(lines), encoding="utf-8")

        log("=" * 88)
        log(
            "REAL CLASS 1/2/3 INTEGRATION GATE: "
            + ("PASS" if not errors else "FAIL")
        )
        log("=" * 88)
        for target_class in TARGET_CLASSES:
            q = classes_qa[str(target_class)]
            log(
                f"Class {target_class}: {q['selected_field_count']}/5 real dominant fields; "
                f"min dominant share={q['dominant_share_min']:.4f}; "
                f"min coverage={q['coverage_unique_min']:.4f}"
            )
        log(f"Selected municipalities: {', '.join(qa_doc['selected_municipalities'])}")
        log(f"Unverified component rows: {qa_doc['unverified_component_rows']}")
        if errors:
            for error in errors:
                log("ERROR_CLASS123_GATE: " + error)
            return 1
        log("STOPPUNKT B.1: no Skåne/web phase executed")
        log(f"QA: {report_path}")
        return 0
    except Exception as exc:
        log(f"ERROR_CLASS123_GATE_EXCEPTION: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
