#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPrestation phase 0: checkpointed full-Skåne static context build.

Scope is intentionally limited to static agricultural class 1-10 and SKO
context for the frozen 2025 reference fields. No web, satellite, norm yield,
yield model or ÅkerPrestation score is produced here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
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
    CHECKPOINT_VERSION,
    SOIL_SPEC,
    SKO_SPEC,
    atomic_json,
    atomic_parquet,
    checkpoint_valid,
    combine_context,
    field_id,
    overlay_fields,
    sha256_file as overlay_sha256_file,
)
from akerprestation_phase0_skane_core import (
    build_class_municipality_rows,
    build_sko_distribution_rows,
    field_id_digest,
    municipality_validation,
    overall_acceptance,
    problem_field_ids,
)

PHASE = ROOT / "data" / "derived" / "akerprestation_phase0"
PROJECT_CONFIG = ROOT / "config" / "local_paths.json"
MUNICIPALITY_CONFIG = ROOT / "config" / "akerminne_skane_municipalities.json"
SOIL_SOURCE = PHASE / "discovery" / "source" / "jord_skogsklassificering_class1_10.gpkg"
SKO_SOURCE = PHASE / "discovery" / "source" / "jordbruksverket_sko.gpkg"
PILOT_QA = PHASE / "pilot_skurup" / "phase0_pilot_qa.json"
REAL123_QA = PHASE / "qa" / "real_class123" / "qa.json"
OVERLAY_CORE = ROOT / "src" / "akerprestation_phase0_overlay_core.py"
FREEZE_DOC = ROOT / "docs" / "AKERMINNE_V1_FREEZE.md"

OUT = PHASE / "skane"
QA_DIR = PHASE / "qa" / "skane"
MUNI_QA_DIR = QA_DIR / "municipalities"
MANIFEST_PATH = PHASE / "manifests" / "skane_phase0_manifest.json"
LOG_PATH = PHASE / "logs" / "skane_phase0.log"
SCHEMA = "akerprestation-phase0-skane-v0a"
EXPECTED_FIELDS = 128636
EXPECTED_MUNICIPALITIES = 33
REFERENCE_YEAR = 2025
COVERAGE_TOL = 1e-6


class Logger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("w", encoding="utf-8")

    def __call__(self, message: str) -> None:
        line = str(message)
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_slug(text: str) -> str:
    s = (
        text.replace("Å", "A").replace("Ä", "A").replace("Ö", "O")
        .replace("å", "a").replace("ä", "a").replace("ö", "o")
    )
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")


def municipality_config() -> list[dict[str, str]]:
    doc = load_json(MUNICIPALITY_CONFIG)
    rows = [{"code": str(x["code"]), "name": str(x["name"])} for x in doc.get("municipalities") or []]
    if len(rows) != EXPECTED_MUNICIPALITIES:
        raise RuntimeError(f"Expected 33 municipality config rows; got {len(rows)}")
    if len({x["code"] for x in rows}) != len(rows):
        raise RuntimeError("Duplicate municipality code in config")
    return rows


def add_ids(fields: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = fields.copy()
    out["current_field_id"] = [field_id(b, s) for b, s in zip(out["blockid"], out["skiftesbeteckning"])]
    out["municipality_code"] = out["region_kod"].astype(str).str[:4]
    return out


def checkpoint_paths(municipality: str, layer: str) -> tuple[Path, Path, Path]:
    # Deliberately identical to the Skurup pilot path so that checkpoint can be reused.
    d = PHASE / "checkpoints" / municipality / layer
    return d / "summary.parquet", d / "components.parquet", d / "checkpoint_manifest.json"


def checkpoint_expected(layer: str, municipality: str, field_source_hash: str, reference_source_hash: str) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_VERSION,
        "layer": layer,
        "municipality": municipality,
        "reference_year": REFERENCE_YEAR,
        "field_source_sha256": field_source_hash,
        "reference_source_sha256": reference_source_hash,
        "overlay_core_sha256": overlay_sha256_file(OVERLAY_CORE),
    }


def build_or_resume(
    fields: gpd.GeoDataFrame,
    reference: gpd.GeoDataFrame,
    layer: str,
    municipality: str,
    field_source_hash: str,
    reference_source_hash: str,
    progress_every: int,
    resume: bool,
    log: Logger,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], bool]:
    spec = SOIL_SPEC if layer == "soil_class" else SKO_SPEC
    s_path, c_path, m_path = checkpoint_paths(municipality, layer)
    expected = checkpoint_expected(layer, municipality, field_source_hash, reference_source_hash)
    expected_ids = set(fields["current_field_id"].astype(str))

    if resume and checkpoint_valid(s_path, c_path, m_path, expected):
        summary = pd.read_parquet(s_path)
        components = pd.read_parquet(c_path)
        if set(summary["current_field_id"].astype(str)) == expected_ids:
            log(f"[{municipality}][{layer}] checkpoint HIT - validated and reused")
            return summary, components, load_json(m_path), True
        log(f"[{municipality}][{layer}] WARN_CHECKPOINT_FIELD_ID_MISMATCH - rebuilding")

    t0 = time.perf_counter()
    summary, components, layer_qa = overlay_fields(
        fields, reference, spec, municipality, REFERENCE_YEAR, progress_every, log
    )
    if set(summary["current_field_id"].astype(str)) != expected_ids:
        raise RuntimeError(f"{municipality}/{layer}: overlay summary ID set mismatch")

    atomic_parquet(summary, s_path)
    atomic_parquet(components, c_path)
    manifest = {
        **expected,
        "municipality_field_id_digest": field_id_digest(expected_ids),
        "summary_rows": int(len(summary)),
        "component_rows": int(len(components)),
        "summary_sha256": sha256_file(s_path),
        "components_sha256": sha256_file(c_path),
        "elapsed_seconds": round(time.perf_counter() - t0, 3),
        "qa": layer_qa,
        "created_utc": utc_now(),
    }
    atomic_json(manifest, m_path)
    if not checkpoint_valid(s_path, c_path, m_path, expected):
        raise RuntimeError(f"{municipality}/{layer}: freshly written checkpoint failed validation")
    log(f"[{municipality}][{layer}] checkpoint WRITTEN + VALIDATED")
    return summary, components, manifest, False


def output_hashes(paths: list[Path]) -> dict[str, str]:
    return {str(p.relative_to(PHASE)).replace("\\", "/"): sha256_file(p) for p in paths}


def atomic_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.geojson")
    tmp.unlink(missing_ok=True)
    gdf.to_file(tmp, driver="GeoJSON")
    os.replace(tmp, path)


def area_reconciliation(context: pd.DataFrame, components: pd.DataFrame, prefix: str) -> dict[str, float]:
    raw_uncovered = float((context["field_area_m2"] * (1.0 - context[f"{prefix}_coverage_unique"])).sum())
    nonnegative_uncovered = float(
        (context["field_area_m2"] * (1.0 - context[f"{prefix}_coverage_unique"]).clip(lower=0.0)).sum()
    )
    return {
        "total_field_area_m2": float(context["field_area_m2"].sum()),
        "total_intersection_area_m2": float(components["intersection_area_m2"].sum()) if len(components) else 0.0,
        "total_uncovered_area_m2_raw_formula": raw_uncovered,
        "total_uncovered_area_m2_nonnegative": nonnegative_uncovered,
        "total_duplicate_overlap_area_m2": float(context[f"{prefix}_duplicate_overlap_area_m2"].sum()),
    }


def write_problem_geojson(all_fields: gpd.GeoDataFrame, context: pd.DataFrame, ids: list[str], path: Path) -> None:
    selected = all_fields[all_fields["current_field_id"].astype(str).isin(set(ids))][
        ["current_field_id", "blockid", "skiftesbeteckning", "municipality_code", "geometry"]
    ].copy()
    attrs = context[context["current_field_id"].astype(str).isin(set(ids))].copy()
    out = selected.merge(attrs, on=["current_field_id", "municipality_code"], how="left", validate="one_to_one")
    write_geojson(out, path)


def write_markdown(qa: dict[str, Any], path: Path) -> None:
    lines = [
        "# ÅkerPrestation fas 0 – Skåne läns-QA", "",
        f"**Status:** `{qa['status']}`  ",
        f"**Referensskiften:** {qa['reference_fields']:,}  ",
        f"**Kommuner:** {qa['municipalities_passed']}/{qa['municipalities_total']} PASS  ",
        f"**ÅkerMinne join:** {qa['akerminne_reference']['matched_ids']:,}/{qa['reference_fields']:,} via `{qa['akerminne_reference']['verification_mode']}`  ", "",
        "## Jordbruksklass", "",
        f"- Klasser i verkliga komponenter: {', '.join(map(str, qa['soil']['classes_present']))}",
        f"- Blandklassfält: {qa['soil']['mixed_fields']:,}",
        f"- Helt oklassade fält: {qa['soil']['missing_fields']:,}",
        f"- Partiell unik täckning: {qa['soil']['partial_fields']:,}",
        f"- Okända klasskomponenter: {qa['soil']['unverified_component_rows']:,}",
        f"- `coverage_raw > 1`: {qa['soil']['coverage_raw_gt_1']:,}",
        f"- Oklassad unik area (icke-negativ): {qa['soil']['area_reconciliation']['total_uncovered_area_m2_nonnegative']:.1f} m²", "",
        "## SKO", "",
        f"- SKO-ID i verkliga komponenter: {len(qa['sko']['sko_ids_present'])}",
        f"- Råa SKO-gränsfält: {qa['sko']['boundary_fields']:,}",
        f"- Helt saknad SKO-täckning: {qa['sko']['missing_fields']:,}",
        f"- Okända/blank SKO-komponenter: {qa['sko']['unverified_component_rows']:,}",
        f"- `coverage_raw > 1`: {qa['sko']['coverage_raw_gt_1']:,}", "",
        "## Problemkommuner", "",
    ]
    if qa["problem_municipalities"]:
        lines.extend([f"- {x}" for x in qa["problem_municipalities"]])
    else:
        lines.append("- Inga.")
    lines += [
        "", "## Artefakter", "",
        "- `skane/field_static_context.parquet` – exakt en statisk rad per 2025-skifte.",
        "- `skane/field_soil_class_components.parquet` – alla positiva råa klasskomponenter.",
        "- `skane/field_sko_components.parquet` – alla positiva råa SKO-komponenter.",
        "- `skane/sko_boundary_fields.parquet` och `.geojson` – samtliga råa SKO-gränsfält.",
        "- `qa/skane/soil_class_by_municipality.csv` – klassareal och oklassad unik area per kommun.",
        "- `qa/skane/sko_distribution.csv` – SKO-fördelning.",
        "- `qa/skane/municipality_qa.csv` – PASS/FAIL och QA per kommun.",
        "- `qa/skane/problem_fields.geojson` – deterministiskt problemurval.", "",
        "## STOPPUNKT C", "",
        "Ingen webb, tagg, merge, satellitmodell, normskörd eller ÅkerPrestation-score har startats.",
        "Invänta Bengts beslut om fas 0-freeze och eventuellt separat GO WEB FAS 0.", "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--progress-every", type=int, default=5000)
    ap.add_argument("--force-municipality-code")
    ap.add_argument("--force-layer", choices=["soil_class", "sko", "both"], default="both")
    args = ap.parse_args()

    log = Logger(LOG_PATH)
    t_run = time.perf_counter()
    try:
        repo = repository_snapshot(ROOT)
        if repo["branch"] != "feature/akerprestation-foundation-v0a":
            raise RuntimeError(f"Unexpected branch: {repo['branch']}")
        if repo["akerminne_v1_base_commit"] != EXPECTED_BASE_COMMIT:
            raise RuntimeError("Frozen ÅkerMinne base mismatch")

        for prereq in (PILOT_QA, REAL123_QA, PROJECT_CONFIG, MUNICIPALITY_CONFIG, SOIL_SOURCE, SKO_SOURCE, FREEZE_DOC):
            if not prereq.exists():
                raise FileNotFoundError(prereq)
        pilot_qa = load_json(PILOT_QA)
        real123_qa = load_json(REAL123_QA)
        if pilot_qa.get("status") != "PASS":
            raise RuntimeError("STOPPUNKT B pilot QA is not PASS")
        if real123_qa.get("status") != "PASS":
            raise RuntimeError("STOPPUNKT B.1 real class 1/2/3 QA is not PASS")

        project = load_json(PROJECT_CONFIG)
        fields_path = Path(project["skiften"])
        field_source_hash = sha256_file(fields_path)
        pilot_hash = str((pilot_qa.get("source_hashes") or {}).get("reference_fields") or "")
        b1_hash = str((real123_qa.get("sources") or {}).get("reference_fields_sha256") or "")
        if field_source_hash != pilot_hash or field_source_hash != b1_hash:
            raise RuntimeError("2025 reference field source hash differs from passed pilot/B.1 gates")

        log("=" * 96)
        log("ÅkerPrestation phase 0 · FULL SKÅNE · static class 1-10 + SKO")
        log("=" * 96)
        log(f"Base: {EXPECTED_BASE_TAG} {EXPECTED_BASE_COMMIT}")
        log(f"HEAD: {repo['head_commit']}")
        log(f"Progress: per municipality and every {args.progress_every:,} fields inside each layer")
        log("[inputs] loading all current 2025 Skåne fields...")
        fields = gpd.read_file(fields_path).to_crs(3006)
        fields = add_ids(fields)
        if len(fields) != EXPECTED_FIELDS:
            raise RuntimeError(f"Expected {EXPECTED_FIELDS:,} current fields; got {len(fields):,}")
        if not fields["current_field_id"].is_unique:
            raise RuntimeError("current_field_id is not unique")
        log(f"[inputs] current fields: {len(fields):,}")

        municipalities = municipality_config()
        configured_codes = {x["code"] for x in municipalities}
        if args.force_municipality_code and str(args.force_municipality_code) not in configured_codes:
            raise RuntimeError(f"Unknown --force-municipality-code {args.force_municipality_code}")
        field_codes = set(fields["municipality_code"].astype(str))
        unexpected_codes = sorted(field_codes - configured_codes)
        if unexpected_codes:
            raise RuntimeError(f"Current fields contain municipality codes outside config: {unexpected_codes}")

        log("[inputs] loading verified class 1-10 and SKO source caches...")
        soil_ref = gpd.read_file(SOIL_SOURCE, layer="class1_10")
        sko_ref = gpd.read_file(SKO_SOURCE, layer="sko")
        soil_hash = sha256_file(SOIL_SOURCE)
        sko_hash = sha256_file(SKO_SOURCE)
        log(f"[inputs] soil polygons: {len(soil_ref):,}; SKO polygons: {len(sko_ref):,}")

        MUNI_QA_DIR.mkdir(parents=True, exist_ok=True)
        all_context: list[pd.DataFrame] = []
        all_soil_components: list[pd.DataFrame] = []
        all_sko_components: list[pd.DataFrame] = []
        municipality_qas: list[dict[str, Any]] = []
        total_done = 0

        for number, item in enumerate(municipalities, 1):
            code = item["code"]
            municipality = item["name"]
            subset = fields[fields["municipality_code"].astype(str) == code].copy()
            if subset.empty:
                raise RuntimeError(f"{municipality} ({code}) has zero current fields")
            expected_ids = set(subset["current_field_id"].astype(str))
            log("")
            log(f"[{number:02d}/{len(municipalities)}] {municipality} ({code}) · {len(subset):,} fields · county progress {total_done:,}/{EXPECTED_FIELDS:,}")
            t_muni = time.perf_counter()

            force_this = str(args.force_municipality_code or "") == code
            if force_this:
                log(f"[{municipality}] force municipality requested; layer={args.force_layer}")
            soil_resume = args.resume and not (force_this and args.force_layer in {"soil_class", "both"})
            sko_resume = args.resume and not (force_this and args.force_layer in {"sko", "both"})
            soil_summary, soil_components, soil_manifest, soil_reused = build_or_resume(
                subset, soil_ref, "soil_class", municipality, field_source_hash,
                soil_hash, args.progress_every, soil_resume, log
            )
            sko_summary, sko_components, sko_manifest, sko_reused = build_or_resume(
                subset, sko_ref, "sko", municipality, field_source_hash,
                sko_hash, args.progress_every, sko_resume, log
            )

            muni_qa = municipality_validation(
                code=code, municipality=municipality, expected_ids=expected_ids,
                soil_summary=soil_summary, soil_components=soil_components,
                sko_summary=sko_summary, sko_components=sko_components,
                soil_manifest=soil_manifest, sko_manifest=sko_manifest,
            )
            muni_qa["soil_checkpoint_reused"] = bool(soil_reused)
            muni_qa["sko_checkpoint_reused"] = bool(sko_reused)
            muni_qa["elapsed_seconds_this_invocation"] = round(time.perf_counter() - t_muni, 3)
            muni_qa["field_id_digest"] = field_id_digest(expected_ids)
            muni_path = MUNI_QA_DIR / f"{code}_{safe_slug(municipality)}.json"
            atomic_json(muni_qa, muni_path)
            if muni_qa["status"] != "PASS":
                log(f"[{municipality}] MUNICIPALITY QA: FAIL")
                for err in muni_qa["errors"]:
                    log(f"ERROR_MUNICIPALITY_{code}: {err}")
                raise RuntimeError(f"{municipality} municipality validation failed")

            context = combine_context(soil_summary, sko_summary, f"skane-phase0-{repo['head_commit'][:12]}")
            context["municipality_code"] = code
            if set(context["current_field_id"].astype(str)) != expected_ids:
                raise RuntimeError(f"{municipality}: combined context ID mismatch")
            atomic_parquet(context, PHASE / "checkpoints" / municipality / "context.parquet")

            all_context.append(context)
            all_soil_components.append(soil_components)
            all_sko_components.append(sko_components)
            municipality_qas.append(muni_qa)
            total_done += len(subset)
            log(f"[{number:02d}/{len(municipalities)}] {municipality}: PASS · soil={'HIT' if soil_reused else 'WRITTEN'} · sko={'HIT' if sko_reused else 'WRITTEN'} · county progress {total_done:,}/{EXPECTED_FIELDS:,} ({100*total_done/EXPECTED_FIELDS:.1f}%)")

        context = pd.concat(all_context, ignore_index=True, sort=False)
        soil_components = pd.concat(all_soil_components, ignore_index=True, sort=False)
        sko_components = pd.concat(all_sko_components, ignore_index=True, sort=False)
        context = context.sort_values("current_field_id", kind="mergesort").reset_index(drop=True)
        soil_components = soil_components.sort_values(["current_field_id", "component_rank"], kind="mergesort").reset_index(drop=True)
        sko_components = sko_components.sort_values(["current_field_id", "component_rank"], kind="mergesort").reset_index(drop=True)

        expected_all_ids = set(fields["current_field_id"].astype(str))
        if len(context) != EXPECTED_FIELDS or not context["current_field_id"].is_unique:
            raise RuntimeError("County context does not contain 128,636 unique rows")
        if set(context["current_field_id"].astype(str)) != expected_all_ids:
            raise RuntimeError("County context ID set differs from current 2025 field source")

        OUT.mkdir(parents=True, exist_ok=True)
        QA_DIR.mkdir(parents=True, exist_ok=True)
        context_path = OUT / "field_static_context.parquet"
        soil_comp_path = OUT / "field_soil_class_components.parquet"
        sko_comp_path = OUT / "field_sko_components.parquet"
        atomic_parquet(context, context_path)
        atomic_parquet(soil_components, soil_comp_path)
        atomic_parquet(sko_components, sko_comp_path)

        boundary = context[context["crosses_sko_boundary"].fillna(False)].copy()
        boundary_path = OUT / "sko_boundary_fields.parquet"
        atomic_parquet(boundary, boundary_path)
        boundary_geo = fields[fields["current_field_id"].astype(str).isin(set(boundary["current_field_id"].astype(str)))][
            ["current_field_id", "blockid", "skiftesbeteckning", "municipality_code", "geometry"]
        ].copy()
        boundary_geo = boundary_geo.merge(
            boundary[["current_field_id", "dominant_sko_id", "dominant_sko_share", "sko_count", "sko_coverage_raw", "sko_coverage_unique", "reason_flags"]],
            on="current_field_id", how="left", validate="one_to_one"
        )
        boundary_geo_path = OUT / "sko_boundary_fields.geojson"
        write_geojson(boundary_geo, boundary_geo_path)

        class_csv = QA_DIR / "soil_class_by_municipality.csv"
        atomic_csv(pd.DataFrame(build_class_municipality_rows(context, soil_components)), class_csv)
        sko_csv = QA_DIR / "sko_distribution.csv"
        atomic_csv(pd.DataFrame(build_sko_distribution_rows(context, sko_components)), sko_csv)

        muni_table = pd.DataFrame([
            {
                "municipality_code": q["municipality_code"], "municipality": q["municipality"], "status": q["status"],
                "reference_fields": q["reference_fields"], "soil_missing_fields": q["soil"]["missing_fields"],
                "soil_partial_fields": q["soil"]["partial_fields"], "soil_mixed_fields": q["soil"]["mixed_fields"],
                "soil_coverage_raw_gt_1": q["soil"]["coverage_raw_gt_1"], "sko_missing_fields": q["sko"]["missing_fields"],
                "sko_boundary_fields": q["sko"]["boundary_fields"], "sko_coverage_raw_gt_1": q["sko"]["coverage_raw_gt_1"],
                "soil_checkpoint_reused": q["soil_checkpoint_reused"], "sko_checkpoint_reused": q["sko_checkpoint_reused"],
                "elapsed_seconds_this_invocation": q["elapsed_seconds_this_invocation"],
            } for q in municipality_qas
        ])
        muni_csv = QA_DIR / "municipality_qa.csv"
        atomic_csv(muni_table, muni_csv)

        pids = problem_field_ids(context)
        problem_path = QA_DIR / "problem_fields.geojson"
        write_problem_geojson(fields, context, pids, problem_path)

        classes_present = sorted(pd.to_numeric(soil_components["soil_class_normalized"], errors="coerce").dropna().astype(int).unique().tolist())
        sko_ids_present = sorted(x for x in sko_components["sko_id"].astype(str).str.strip().unique().tolist() if x)
        unverified_soil = int(soil_components["soil_class_normalized"].isna().sum())
        unverified_sko = int((sko_components["sko_id"].astype(str).str.strip() == "").sum())
        soil_missing = int((context["soil_class_coverage_unique"] <= COVERAGE_TOL).sum())
        soil_partial = int(((context["soil_class_coverage_unique"] > COVERAGE_TOL) & (context["soil_class_coverage_unique"] < 1.0 - COVERAGE_TOL)).sum())
        sko_missing = int((context["sko_coverage_unique"] <= COVERAGE_TOL).sum())

        freeze_hash_before = sha256_file(FREEZE_DOC)
        freeze_text = FREEZE_DOC.read_text(encoding="utf-8")
        freeze_contract_ok = "128,636" in freeze_text and "1,414,996" in freeze_text and "2015–2025" in freeze_text
        problem_municipalities = [f"{q['municipality']} ({q['municipality_code']})" for q in municipality_qas if q["status"] != "PASS"]
        acceptance = overall_acceptance(
            municipalities_passed=sum(q["status"] == "PASS" for q in municipality_qas),
            reference_fields=len(context), unique_reference_fields=context["current_field_id"].nunique(),
            classes_present=classes_present, unverified_soil_components=unverified_soil,
            unverified_sko_components=unverified_sko, sko_missing_fields=sko_missing,
            id_set_matches=(set(context["current_field_id"].astype(str)) == expected_all_ids),
            freeze_contract_ok=freeze_contract_ok,
        )

        qa = {
            "schema_version": SCHEMA, "created_utc": utc_now(), "status": "PASS" if acceptance["pass"] else "FAIL",
            "acceptance": acceptance, "reference_fields": int(len(context)), "reference_field_id_digest": field_id_digest(expected_all_ids),
            "municipalities_total": len(municipality_qas), "municipalities_passed": int(sum(q["status"] == "PASS" for q in municipality_qas)),
            "problem_municipalities": problem_municipalities,
            "context_status_counts": {str(k): int(v) for k, v in context["context_status"].value_counts().sort_index().items()},
            "soil": {
                "classes_present": classes_present, "unverified_component_rows": unverified_soil,
                "mixed_fields": int(context["mixed_soil_class"].fillna(False).sum()), "missing_fields": soil_missing,
                "partial_fields": soil_partial, "coverage_raw_gt_1": int((context["soil_class_coverage_raw"] > 1.0 + COVERAGE_TOL).sum()),
                "area_reconciliation": area_reconciliation(context, soil_components, "soil_class"),
            },
            "sko": {
                "sko_ids_present": sko_ids_present, "unverified_component_rows": unverified_sko,
                "boundary_fields": int(context["crosses_sko_boundary"].fillna(False).sum()), "missing_fields": sko_missing,
                "coverage_raw_gt_1": int((context["sko_coverage_raw"] > 1.0 + COVERAGE_TOL).sum()),
                "area_reconciliation": area_reconciliation(context, sko_components, "sko"),
            },
            "akerminne_reference": {
                "status": "PASS" if freeze_contract_ok else "FAIL", "verification_mode": "freeze_contract_reference_identity",
                "freeze_tag": EXPECTED_BASE_TAG, "freeze_commit": EXPECTED_BASE_COMMIT, "freeze_contract": str(FREEZE_DOC),
                "freeze_contract_sha256": freeze_hash_before, "frozen_history_artifact_available": False,
                "matched_ids": int(len(context)), "unmatched_ids": [], "reference_field_source_sha256": field_source_hash,
                "note": "Canonical generated ÅkerMinne history parquet is not retained locally. Identity is verified against the immutable v1 freeze contract and the exact 2025 reference source used by the passed pilot and class 1/2/3 gate.",
            },
            "gates": {"skurup_pilot_status": pilot_qa.get("status"), "real_class123_status": real123_qa.get("status")},
            "git": {"branch": repo["branch"], "head_commit": repo["head_commit"], "base_tag": EXPECTED_BASE_TAG, "base_commit": EXPECTED_BASE_COMMIT},
            "sources": {
                "reference_fields": str(fields_path), "reference_fields_sha256": field_source_hash,
                "soil_class": str(SOIL_SOURCE), "soil_class_sha256": soil_hash,
                "sko": str(SKO_SOURCE), "sko_sha256": sko_hash, "overlay_core_sha256": overlay_sha256_file(OVERLAY_CORE),
            },
            "elapsed_seconds_this_invocation": round(time.perf_counter() - t_run, 3), "problem_field_count": len(pids),
            "output_sizes_bytes": {},
            "scope_guardrail": "Static Skåne phase 0 only. No web, merge, tag, satellite, norm yield, yield model or ÅkerPrestation score.",
        }

        qa_json = QA_DIR / "qa.json"
        qa_md = QA_DIR / "qa.md"
        atomic_json(qa, qa_json)
        write_markdown(qa, qa_md)
        outputs = [context_path, soil_comp_path, sko_comp_path, boundary_path, boundary_geo_path, class_csv, sko_csv, muni_csv, problem_path, qa_json, qa_md]
        for p in outputs:
            qa["output_sizes_bytes"][str(p.relative_to(PHASE)).replace("\\", "/")] = p.stat().st_size
        atomic_json(qa, qa_json)
        write_markdown(qa, qa_md)

        freeze_hash_after = sha256_file(FREEZE_DOC)
        if freeze_hash_before != freeze_hash_after:
            raise RuntimeError("Frozen ÅkerMinne contract changed during run")

        manifest = {
            "schema_version": SCHEMA, "created_utc": utc_now(), "status": qa["status"], "reference_year": REFERENCE_YEAR,
            "reference_fields": int(len(context)),
            "municipalities": {q["municipality_code"]: {"name": q["municipality"], "status": q["status"], "reference_fields": q["reference_fields"], "soil_checkpoint_reused": q["soil_checkpoint_reused"], "sko_checkpoint_reused": q["sko_checkpoint_reused"]} for q in municipality_qas},
            "git": qa["git"], "sources": qa["sources"], "akerminne_reference": qa["akerminne_reference"],
            "outputs": output_hashes(outputs), "scope_guardrail": qa["scope_guardrail"],
        }
        atomic_json(manifest, MANIFEST_PATH)

        log("")
        log("=" * 96)
        log(f"ÅkerPrestation phase 0 FULL SKÅNE: {qa['status']}")
        log("=" * 96)
        log(f"Municipalities PASS: {qa['municipalities_passed']}/{qa['municipalities_total']}")
        log(f"Reference fields: {qa['reference_fields']:,}/{EXPECTED_FIELDS:,}")
        log(f"Soil classes present: {classes_present}")
        log(f"Unverified soil components: {unverified_soil:,}")
        log(f"Soil missing fields: {soil_missing:,}; partial fields: {soil_partial:,}")
        log(f"SKO IDs present: {len(sko_ids_present):,}")
        log(f"SKO boundary fields: {qa['sko']['boundary_fields']:,}")
        log(f"Unverified SKO components: {unverified_sko:,}; missing SKO fields: {sko_missing:,}")
        log(f"ÅkerMinne reference join: {len(context):,}/{EXPECTED_FIELDS:,}; contract={freeze_contract_ok}")
        log(f"Problem municipalities: {len(problem_municipalities)}")
        if not freeze_contract_ok:
            log("ERROR_FREEZE_CONTRACT: immutable ÅkerMinne contract evidence incomplete")
        for err in acceptance["errors"]:
            log(f"ERROR_SKANE_ACCEPTANCE: {err}")
        if qa["status"] != "PASS":
            return 1
        log("STOPPUNKT C: no web/tag/merge/satellite/yield-model phase executed")
        log(f"QA: {qa_md}")
        log(f"Manifest: {MANIFEST_PATH}")
        return 0
    except Exception as exc:
        log(f"ERROR_SKANE_EXCEPTION: {type(exc).__name__}: {exc}")
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
