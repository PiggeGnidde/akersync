#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPrestation phase 0 discovery only.

Inspects the frozen ÅkerMinne v1 lineage, the previously used historical
agricultural-class source and Jordbruksverket's official SKO WFS. It creates
source/schema/provenance reports only. It deliberately does NOT create any
per-field static-context overlay, pilot, Skåne run or web output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from akerprestation_phase0_discovery_core import (
    EXPECTED_BASE_COMMIT,
    EXPECTED_BASE_TAG,
    EXPECTED_FEATURE_BRANCH,
    EXPECTED_REFERENCE_FIELDS,
    EXPECTED_REFERENCE_YEAR,
    JVB_GIS_INFO_URL,
    JVB_OPEN_WFS,
    SCHEMA_VERSION,
    SOIL_CLASS_LAYER_URL,
    SOIL_CLASS_PROJECT_SOURCE_NOTE,
    class_area_summary,
    class_counts_from_arcgis,
    discover_candidate_files,
    download_arcgis_class_geojson,
    download_sko_geojson,
    find_sko_feature_type,
    geometry_schema,
    http_bytes,
    http_json,
    infer_arable_class_domain,
    leading_zero_evidence,
    load_json,
    overlap_summary,
    path_roots,
    raw_sko_ids,
    renderer_class_domain,
    repository_snapshot,
    sha256_file,
    stable_json_dump,
    source_coverage_against_fields,
    utc_now,
    wfs_describe_feature_type,
    choose_sko_id_field,
    SKO_FILE_RE,
    SOIL_CLASS_FILE_RE,
)


def import_geo():
    try:
        import geopandas as gpd
        from shapely.geometry import shape
    except Exception as exc:
        raise RuntimeError(
            "geopandas/shapely saknas eller kan inte importeras. Kör repositoryts "
            "INSTALL_REQUIREMENTS.bat och återkör discovery."
        ) from exc
    return gpd, shape


def write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def field_key_diagnostics(fields, columns: list[str]) -> dict:
    if not all(column in fields.columns for column in columns):
        return {"status": "WARN_MISSING_KEY_COLUMNS", "required": columns}
    keys = fields[columns].astype(str).agg("|".join, axis=1)
    return {
        "status": "OK" if not keys.duplicated().any() else "WARN_DUPLICATE_FIELD_KEYS",
        "key_columns": columns,
        "row_count": int(len(keys)),
        "unique_key_count": int(keys.nunique(dropna=False)),
        "duplicate_key_count": int(keys.duplicated(keep=False).sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-config", default="config/local_paths.json")
    parser.add_argument("--akerminne-local", default="config/akerminne_local.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    project_cfg_path = root / args.project_config
    akerminne_cfg_path = root / args.akerminne_local
    if not project_cfg_path.exists():
        raise FileNotFoundError(project_cfg_path)
    if not akerminne_cfg_path.exists():
        raise FileNotFoundError(akerminne_cfg_path)

    project_cfg = load_json(project_cfg_path)
    akerminne_cfg = load_json(akerminne_cfg_path)
    build_dir = Path(project_cfg.get("build_dir", "data/derived"))
    if not build_dir.is_absolute():
        build_dir = root / build_dir
    phase_root = build_dir / "akerprestation_phase0"
    outdir = phase_root / "discovery"
    source_dir = outdir / "source"
    manifest_dir = phase_root / "manifests"
    outdir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    repo = repository_snapshot(root)
    warnings: list[str] = []
    blockers: list[str] = []
    errors: list[str] = []

    if repo["branch"] != EXPECTED_FEATURE_BRANCH:
        warnings.append(
            f"WARN_BRANCH_NAME: expected {EXPECTED_FEATURE_BRANCH}, got {repo['branch']}"
        )
    if not repo["working_tree_clean"]:
        errors.append("ERROR_DIRTY_WORKTREE: tracked/untracked Git changes present before discovery")

    gpd, shape = import_geo()

    fields_value = str(project_cfg.get("skiften") or "").strip()
    fields_path = Path(fields_value) if fields_value else Path("__MISSING_SKIFTEN_PATH__")
    field_schema: dict = {"path": fields_value, "exists": bool(fields_value) and fields_path.exists()}
    fields = None
    if fields_value and fields_path.exists():
        fields = gpd.read_file(fields_path)
        field_schema.update(geometry_schema(fields))
        field_schema["reference_year"] = EXPECTED_REFERENCE_YEAR
        field_schema["key_diagnostics"] = field_key_diagnostics(
            fields, ["blockid", "skiftesbeteckning"]
        )
        if len(fields) != EXPECTED_REFERENCE_FIELDS:
            warnings.append(
                f"WARN_REFERENCE_FIELD_COUNT: local 2025 file has {len(fields)} rows; "
                f"frozen ÅkerMinne v1 has {EXPECTED_REFERENCE_FIELDS}"
            )
    else:
        errors.append(f"ERROR_MISSING_2025_FIELDS: {fields_value or '<not configured>'}")

    roots = path_roots(project_cfg, akerminne_cfg, root)
    local_soil_candidates = discover_candidate_files(roots, SOIL_CLASS_FILE_RE)
    local_sko_candidates = discover_candidate_files(roots, SKO_FILE_RE)

    soil_schema: dict = {
        "schema_version": SCHEMA_VERSION,
        "source_name": "Jord- och skogsklassificering Skåne",
        "source_url": SOIL_CLASS_LAYER_URL,
        "source_role": "previously_used_project_source",
        "source_note": SOIL_CLASS_PROJECT_SOURCE_NOTE,
        "previously_implemented_arable_classes": [5, 6, 7, 8, 9, 10],
        "class5_already_implemented": True,
        "new_requested_classes": [1, 2, 3, 4],
        "local_candidate_files": local_soil_candidates,
    }
    soil_cache = source_dir / "jord_skogsklassificering_class1_10.gpkg"
    try:
        metadata = http_json(SOIL_CLASS_LAYER_URL, {"f": "pjson"})
        renderer_domain = renderer_class_domain(metadata)
        arable_domain = infer_arable_class_domain(renderer_domain)
        soil_schema.update({
            "service_geometry_type": metadata.get("geometryType"),
            "service_spatial_reference": (metadata.get("extent") or {}).get("spatialReference"),
            "service_fields": [
                {"name": row.get("name"), "type": row.get("type"), "alias": row.get("alias")}
                for row in metadata.get("fields") or []
            ],
            "renderer_domain": renderer_domain,
            "verified_arable_domain": arable_domain,
            "raw_class_counts": class_counts_from_arcgis(),
            "service_description": metadata.get("description"),
            "max_record_count": metadata.get("maxRecordCount"),
        })
        if arable_domain != list(range(1, 11)):
            blockers.append(
                "BLOCKED_MISSING_VERIFIED_CLASS_1_5_SOURCE: verified source did not expose arable classes 1-10"
            )
        geojson = download_arcgis_class_geojson(1, 10)
        rows, geoms = [], []
        for feature in geojson.get("features") or []:
            rows.append(feature.get("properties") or {})
            geoms.append(shape(feature.get("geometry")))
        classes = gpd.GeoDataFrame(rows, geometry=geoms, crs=4326).to_crs(3006)
        if soil_cache.exists():
            soil_cache.unlink()
        classes.to_file(soil_cache, layer="class1_10", driver="GPKG")
        soil_schema["downloaded_geometry"] = geometry_schema(classes)
        soil_schema["area_by_raw_class"] = class_area_summary(classes, "KLASS")
        soil_schema["source_overlap_qa"] = overlap_summary(classes, "KLASS")
        if fields is not None:
            try:
                soil_schema["coverage_against_2025_fields"] = source_coverage_against_fields(fields, classes)
            except Exception as exc:
                soil_schema["coverage_against_2025_fields"] = {"status": "WARN", "error": str(exc)}
                warnings.append("WARN_SOIL_CLASS_FIELD_COVERAGE: " + str(exc))
        soil_schema["generated_source_cache"] = str(soil_cache)
        soil_schema["generated_source_cache_sha256"] = sha256_file(soil_cache)
        soil_schema["why_1_4_missing_today"] = (
            "Existing repo code explicitly queries/trains/publishes classes 5-10. "
            "The verified source itself exposes arable classes 1-10, so classes 1-4 "
            "are filtered out by the current implementation rather than absent from the source."
        )
        soil_schema["classification_year_status"] = (
            "SOURCE_VERSION_UNKNOWN: project calls this historic/1970-1971 classification, "
            "but the ArcGIS layer metadata inspected here does not state an exact classification year."
        )
        warnings.append(
            "WARN_SOURCE_VERSION_UNKNOWN_SOIL_CLASS: exact classification year is not stated by the ArcGIS layer metadata"
        )
    except Exception as exc:
        soil_schema["status"] = "BLOCKED"
        soil_schema["error"] = str(exc)
        blockers.append("BLOCKED_MISSING_VERIFIED_CLASS_1_5_SOURCE: " + str(exc))
    else:
        soil_schema["status"] = "PASS"

    sko_schema: dict = {
        "schema_version": SCHEMA_VERSION,
        "source_name": "Jordbruksverket open data – skördeområden (SKO)",
        "official_gis_info_url": JVB_GIS_INFO_URL,
        "wfs_url": JVB_OPEN_WFS,
        "source_role": "official_reproducible_vector_source",
        "local_candidate_files": local_sko_candidates,
    }
    sko_cache = source_dir / "jordbruksverket_sko.gpkg"
    try:
        capabilities = http_bytes(
            JVB_OPEN_WFS,
            {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"},
        )
        feature_type = find_sko_feature_type(capabilities)
        describe = wfs_describe_feature_type(feature_type["name"])
        sko_geojson = download_sko_geojson(feature_type["name"])
        features = sko_geojson.get("features") or []
        id_field = choose_sko_id_field(features, describe)
        ids = raw_sko_ids(features, id_field)
        sko = gpd.GeoDataFrame.from_features(features, crs=3006)
        if sko.crs is None:
            sko = sko.set_crs(3006)
        else:
            sko = sko.to_crs(3006)
        if sko_cache.exists():
            sko_cache.unlink()
        sko.to_file(sko_cache, layer="sko", driver="GPKG")
        sko_schema.update({
            "feature_type": feature_type,
            "describe_feature_type": describe,
            "identified_id_field": id_field,
            "id_format_evidence": leading_zero_evidence(ids),
            "geometry": geometry_schema(sko),
            "source_overlap_qa": overlap_summary(sko, id_field),
            "generated_source_cache": str(sko_cache),
            "generated_source_cache_sha256": sha256_file(sko_cache),
        })
        if id_field is None:
            blockers.append("BLOCKED_SKO_ID_NOT_IDENTIFIED")
        if fields is not None:
            try:
                sko_schema["coverage_against_2025_fields"] = source_coverage_against_fields(fields, sko)
            except Exception as exc:
                sko_schema["coverage_against_2025_fields"] = {"status": "WARN", "error": str(exc)}
                warnings.append("WARN_SKO_FIELD_COVERAGE: " + str(exc))
            try:
                field_bounds = fields.to_crs(3006).geometry.union_all().envelope
                subset = sko[sko.geometry.intersects(field_bounds)]
                sko_schema["bbox_intersecting_2025_skane_fields"] = {
                    "count": int(len(subset)),
                    "ids": [
                        str(value) for value in subset[id_field].tolist()
                    ] if id_field and id_field in subset.columns else [],
                }
            except Exception as exc:
                warnings.append("WARN_SKO_SKANE_SUBSET: " + str(exc))
        sko_schema["status"] = "PASS"
    except Exception as exc:
        sko_schema["status"] = "BLOCKED"
        sko_schema["error"] = str(exc)
        blockers.append("BLOCKED_MISSING_VERIFIED_SKO_SOURCE: " + str(exc))

    repo["local_data_discovery"] = {
        "search_roots": [str(path) for path in roots],
        "soil_class_candidates": local_soil_candidates,
        "sko_candidates": local_sko_candidates,
        "reference_field_schema": field_schema,
    }
    stable_json_dump(repo, outdir / "repository_summary.json")
    stable_json_dump(soil_schema, outdir / "soil_class_schema.json")
    stable_json_dump(sko_schema, outdir / "sko_schema.json")

    source_hashes = []
    for label, path in [
        ("2025_reference_fields", fields_path),
        ("soil_class_generated_cache", soil_cache),
        ("sko_generated_cache", sko_cache),
    ]:
        if path.exists() and path.is_file():
            source_hashes.append({
                "label": label,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })

    overall = "PASS"
    if blockers:
        overall = "PASS_WITH_BLOCKERS"
    elif warnings:
        overall = "PASS_WITH_WARNINGS"
    if errors:
        overall = "FAIL"

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": f"phase0-discovery-{repo['head_commit'][:12]}",
        "created_utc": utc_now(),
        "status": overall,
        "git": {
            "base_tag": EXPECTED_BASE_TAG,
            "base_commit": EXPECTED_BASE_COMMIT,
            "branch": repo["branch"],
            "head_commit": repo["head_commit"],
            "origin": repo["origin"],
        },
        "sources": {
            "reference_fields": str(fields_path),
            "soil_class": SOIL_CLASS_LAYER_URL,
            "sko": JVB_OPEN_WFS,
            "source_hashes": source_hashes,
        },
        "warnings": warnings,
        "blockers": blockers,
        "errors": errors,
        "scope_guardrail": (
            "Discovery only. No per-field SKO/class overlay, no Skurup pilot, "
            "no Skåne expansion and no web changes were produced."
        ),
    }
    manifest_path = manifest_dir / "discovery_manifest.json"
    stable_json_dump(manifest, manifest_path)

    lines = [
        "# ÅkerPrestation fas 0 – discoveryrapport",
        "",
        f"**Status:** `{overall}`  ",
        f"**Schema:** `{SCHEMA_VERSION}`  ",
        f"**Git-bas:** `{EXPECTED_BASE_TAG}` → `{EXPECTED_BASE_COMMIT}`  ",
        f"**Discovery-HEAD:** `{repo['head_commit']}`  ",
        f"**Branch:** `{repo['branch']}`",
        "",
        "## Fryst ÅkerMinne v1-bas",
        "",
        f"- Referensår: {EXPECTED_REFERENCE_YEAR}.",
        f"- Fryst antal referensskiften: {EXPECTED_REFERENCE_FIELDS:,}.",
        "- Fryst historik muteras inte av denna discovery.",
        "",
        "## Jordbruksklass",
        "",
        "- Klass 5 är redan implementerad i befintlig ÅkerPass/ÅkerScore-linje tillsammans med 6–10.",
        "- Nuvarande kod filtrerar uttryckligen klass 5–10.",
        f"- Verifierad källdomän: {soil_schema.get('verified_arable_domain')}.",
        "- Fas 0-kompletteringen gäller därför klass 1–4, inte klass 5.",
        f"- Källa: {SOIL_CLASS_LAYER_URL}",
        f"- Status: `{soil_schema.get('status')}`.",
        "",
        "## SKO",
        "",
        f"- Källa: Jordbruksverkets öppna WFS `{JVB_OPEN_WFS}`.",
        f"- Identifierat lager: `{(sko_schema.get('feature_type') or {}).get('name')}`.",
        f"- Identifierat SKO-ID-fält: `{sko_schema.get('identified_id_field')}`.",
        f"- Status: `{sko_schema.get('status')}`.",
        "",
        "## Lokal 2025-referens",
        "",
        f"- Fil: `{fields_value}`.",
        f"- Antal objekt: `{field_schema.get('feature_count')}`.",
        f"- CRS: `{field_schema.get('crs')}`.",
        f"- Nyckel-QA: `{(field_schema.get('key_diagnostics') or {}).get('status')}`.",
        "",
        "## Discoveryartefakter",
        "",
        "- `repository_summary.json`",
        "- `soil_class_schema.json`",
        "- `sko_schema.json`",
        "- `../manifests/discovery_manifest.json`",
        "",
        "## WARN / ERROR / BLOCKED",
        "",
    ]
    issue_lines = warnings + errors + blockers
    lines.extend([f"- `{item}`" for item in issue_lines] if issue_lines else ["- Inga."])
    lines += [
        "",
        "## STOPPUNKT A",
        "",
        "Ingen overlaymotor, Skuruppilot, Skånekörning eller webbimplementation har byggts.",
        "Nästa huvudsteg kräver Bengts uttryckliga GO efter granskning av denna discovery.",
    ]
    write_markdown(outdir / "discovery_report.md", lines)

    print("=" * 88)
    print("ÅkerPrestation phase 0 DISCOVERY ONLY")
    print("=" * 88)
    print("Base:", EXPECTED_BASE_TAG, EXPECTED_BASE_COMMIT)
    print("Branch:", repo["branch"])
    print("HEAD:", repo["head_commit"])
    print("Class 5 already implemented: YES")
    print("Requested new class scope after discovery: 1-4")
    print("Soil class source status:", soil_schema.get("status"))
    print("SKO source status:", sko_schema.get("status"))
    print("Overall:", overall)
    for item in warnings:
        print(item)
    for item in errors:
        print(item)
    for item in blockers:
        print(item)
    print("Report:", outdir / "discovery_report.md")
    print("Manifest:", manifest_path)
    print("STOPPUNKT A: no later phase executed")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR_DISCOVERY_EXCEPTION:", exc, file=sys.stderr)
        raise
