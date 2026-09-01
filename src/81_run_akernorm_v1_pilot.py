#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from akernorm_v1_core import (
    artifact_records,
    atomic_csv,
    atomic_json,
    atomic_parquet,
    build_history_presence,
    calculate_field_crop,
    load_config,
    normalized_id,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/akernorm_v1.json"
EXPECTED_YEARS = list(range(2015, 2026))
EXPECTED_WEB_COMPONENT_MIN_SHARE = 0.01


def load_grouped_components(skane_root: Path) -> tuple[pd.DataFrame, list[dict]]:
    paths = sorted(skane_root.rglob("akerminne_crop_areas_grouped.parquet"), key=lambda p: str(p).lower())
    if not paths:
        raise RuntimeError(f"No canonical ÅkerMinne grouped crop artifacts under {skane_root}")
    frames = []
    sources = []
    for path in paths:
        manifest = path.parent / "build_manifest.json"
        classified = path.parent / "akerminne_year_summary_classified.parquet"
        if not manifest.exists() or not classified.exists():
            raise RuntimeError(f"Incomplete canonical ÅkerMinne municipality output: {path.parent}")
        document = json.loads(manifest.read_text(encoding="utf-8-sig"))
        frame = pd.read_parquet(path, columns=[
            "current_field_id", "history_year", "crop_code_raw", "crop_share_current"
        ])
        frames.append(frame)
        sources.append({
            "source_mode": "CANONICAL_PARQUET",
            "municipality_code": str(document.get("municipality_code", "")),
            "municipality": str(document.get("municipality", "")),
            "path": str(path), "rows": int(len(frame)), "sha256": sha256_file(path),
            "build_manifest_sha256": sha256_file(manifest),
        })
    grouped = pd.concat(frames, ignore_index=True)
    grouped["crop_share_current"] = pd.to_numeric(grouped["crop_share_current"], errors="coerce")
    grouped = grouped.groupby(
        ["current_field_id", "history_year", "crop_code_raw"], as_index=False, dropna=False, sort=True
    )["crop_share_current"].sum()
    return grouped, sources


def load_web_sidecar_components(
    sidecar_root: Path,
    expected_field_ids: set[str],
    config: dict,
    expected_municipalities: int = 33,
) -> tuple[pd.DataFrame, list[dict]]:
    """Recover material crop presence from the frozen ÅkerMinne web contract.

    The web contract retains components at >=1%, while crop presence uses the
    already-frozen >=5% materiality rule. It is therefore lossless for the
    product decision made here, even when the larger canonical Parquets are no
    longer retained.
    """
    index_path = sidecar_root / "skane_index.json"
    if not index_path.exists():
        raise RuntimeError(f"Missing frozen ÅkerMinne web index: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    expected_field_count = len(expected_field_ids)
    expected_field_years = expected_field_count * len(EXPECTED_YEARS)
    checks = {
        "schema": index.get("schema_version") == "akerminne-skane-web-index-v1",
        "reference_year": int(index.get("reference_year", -1)) == 2025,
        "municipalities": int(index.get("municipality_count", -1)) == expected_municipalities,
        "fields": int(index.get("field_count", -1)) == expected_field_count,
        "field_years": int(index.get("field_years", -1)) == expected_field_years,
        "years": index.get("years") == EXPECTED_YEARS,
        "entries": len(index.get("municipalities") or []) == expected_municipalities,
        "unique_municipality_codes": len({
            str(row.get("municipality_code")) for row in (index.get("municipalities") or [])
        }) == expected_municipalities,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(f"Frozen ÅkerMinne web index contract failed: {failed}")

    visible_required = float(config["crop_presence"]["mixed_component_min_share"])
    seen_fields: set[str] = set()
    component_rows: list[dict] = []
    sources = [{
        "source_mode": "FROZEN_WEB_SIDECAR",
        "path": str(index_path), "rows": expected_municipalities,
        "bytes": index_path.stat().st_size, "sha256": sha256_file(index_path),
    }]
    total_bytes = 0
    total_index_fields = 0
    total_index_field_years = 0
    for entry in sorted(index["municipalities"], key=lambda row: str(row["municipality_code"])):
        path = sidecar_root / Path(str(entry["file"])).name
        if not path.exists():
            raise RuntimeError(f"Missing frozen ÅkerMinne municipality sidecar: {path}")
        if path.stat().st_size != int(entry["size_bytes"]):
            raise RuntimeError(f"ÅkerMinne sidecar byte count differs from index: {path}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        thresholds = payload.get("thresholds") or {}
        visible = float(thresholds.get("visible_component", -1))
        material = float(thresholds.get("mixed_secondary_crop", -1))
        payload_fields = payload.get("fields") or {}
        sidecar_checks = {
            "schema": payload.get("schema_version") == "akerminne-web-v1a",
            "municipality": str(payload.get("municipality")) == str(entry["municipality"]),
            "municipality_code": str(payload.get("municipality_code")) == str(entry["municipality_code"]),
            "reference_year": int(payload.get("reference_year", -1)) == 2025,
            "field_count": int(payload.get("field_count", -1)) == int(entry["field_count"]) == len(payload_fields),
            "field_years": int(entry.get("field_years", -1)) == len(payload_fields) * len(EXPECTED_YEARS),
            "years": payload.get("years") == EXPECTED_YEARS,
            "visible_threshold": math.isclose(
                visible, EXPECTED_WEB_COMPONENT_MIN_SHARE, abs_tol=1e-15
            ),
            "material_threshold": math.isclose(material, visible_required, abs_tol=1e-15),
        }
        failed = sorted(name for name, passed in sidecar_checks.items() if not passed)
        if failed:
            raise RuntimeError(f"Frozen ÅkerMinne sidecar contract failed for {path.name}: {failed}")
        for field_id, field_history in payload_fields.items():
            field_id = str(field_id)
            if field_id in seen_fields:
                raise RuntimeError(f"Field ID occurs in several ÅkerMinne sidecars: {field_id}")
            if field_id not in expected_field_ids:
                raise RuntimeError(f"ÅkerMinne sidecar contains unknown frozen field ID: {field_id}")
            if len(field_history) != len(EXPECTED_YEARS) or [int(item["y"]) for item in field_history] != EXPECTED_YEARS:
                raise RuntimeError(f"ÅkerMinne sidecar has incomplete year sequence: {field_id}")
            seen_fields.add(field_id)
            for item in field_history:
                year = int(item["y"])
                for component in item.get("x") or []:
                    if not isinstance(component, list) or len(component) != 2:
                        raise RuntimeError(f"Malformed ÅkerMinne component for {field_id}/{year}")
                    crop_key, share_raw = component
                    parts = str(crop_key).split("|", 2)
                    if len(parts) != 3 or int(parts[0]) != year or not parts[1]:
                        raise RuntimeError(f"Malformed ÅkerMinne crop key: {crop_key}")
                    share = float(share_raw)
                    if share + 1e-12 < visible:
                        raise RuntimeError(f"ÅkerMinne component is below declared visible threshold: {field_id}/{year}")
                    if share + 1e-12 >= visible_required:
                        component_rows.append({
                            "current_field_id": field_id, "history_year": year,
                            "crop_code_raw": parts[1], "crop_share_current": share,
                        })
        total_index_fields += int(entry["field_count"])
        total_index_field_years += int(entry["field_years"])
        total_bytes += path.stat().st_size
        sources.append({
            "source_mode": "FROZEN_WEB_SIDECAR",
            "municipality_code": str(entry["municipality_code"]),
            "municipality": str(entry["municipality"]), "path": str(path),
            "rows": int(entry["field_years"]), "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    if seen_fields != expected_field_ids:
        missing = sorted(expected_field_ids - seen_fields)[:20]
        raise RuntimeError(f"ÅkerMinne sidecars do not reconcile to frozen field IDs; missing sample: {missing}")
    if (
        total_index_fields != expected_field_count
        or total_index_field_years != expected_field_years
        or total_bytes != int(index.get("sidecar_bytes", -1))
    ):
        raise RuntimeError("ÅkerMinne sidecar totals differ from frozen index")
    grouped = pd.DataFrame(component_rows)
    if grouped.empty:
        raise RuntimeError("Frozen ÅkerMinne sidecars contain no material crop components")
    grouped = grouped.groupby(
        ["current_field_id", "history_year", "crop_code_raw"], as_index=False, sort=True
    )["crop_share_current"].sum()
    return grouped, sources


def load_component_source(
    source_root: Path,
    expected_field_ids: set[str],
    config: dict,
) -> tuple[pd.DataFrame, list[dict], str]:
    if (source_root / "skane_index.json").exists():
        grouped, sources = load_web_sidecar_components(source_root, expected_field_ids, config)
        return grouped, sources, "FROZEN_WEB_SIDECAR"
    grouped, sources = load_grouped_components(source_root)
    return grouped, sources, "CANONICAL_PARQUET"


def source_norms(output_root: Path) -> pd.DataFrame:
    path = output_root / "source/normalized/official_norm_yield_2026_normalized.csv"
    if not path.exists():
        raise RuntimeError("Run model freeze first; frozen normalized source is missing")
    frame = pd.read_csv(path, dtype={"sko_id": str})
    frame["sko_id"] = frame["sko_id"].map(lambda value: normalized_id(value, 4))
    frame["crop_code_canonical"] = pd.to_numeric(frame["crop_code_canonical"], errors="raise").astype(int)
    return frame


def candidate_table(presence: pd.DataFrame, base: pd.DataFrame, references: pd.DataFrame) -> pd.DataFrame:
    candidates = presence.merge(base, on="current_field_id", how="left", validate="many_to_one")
    ref = references[["crop_code_canonical", "sko_id", "reference_score", "reference_status"]].rename(
        columns={"sko_id": "dominant_sko_id"}
    )
    candidates = candidates.merge(ref, on=["crop_code_canonical", "dominant_sko_id"], how="left", validate="many_to_one")
    return candidates.sort_values(["current_field_id", "crop_code_canonical"], kind="mergesort").reset_index(drop=True)


def choose_first(frame: pd.DataFrame, used: set[tuple[str, int]], prefer_code: str | None = None) -> pd.Series | None:
    pool = frame.copy()
    if prefer_code and pool["municipality_code"].astype(str).eq(prefer_code).any():
        pool = pool[pool["municipality_code"].astype(str).eq(prefer_code)]
    pool = pool.sort_values(["municipality_code", "current_field_id", "crop_code_canonical"], kind="mergesort")
    for _, row in pool.iterrows():
        key = (str(row["current_field_id"]), int(row["crop_code_canonical"]))
        if key not in used:
            used.add(key)
            return row
    if not pool.empty:
        row = pool.iloc[0]
        used.add((str(row["current_field_id"]), int(row["crop_code_canonical"])))
        return row
    return None


def select_pilot(candidates: pd.DataFrame, official: pd.DataFrame, config: dict) -> tuple[list[str], pd.DataFrame]:
    adjusted = {int(row["canonical_code"]) for row in config["crops"] if row["model_mode"].startswith("FIELD_ADJUSTED")}
    published_keys = set(zip(
        official.loc[official["status"].eq("PUBLISHED"), "crop_code_canonical"].astype(int),
        official.loc[official["status"].eq("PUBLISHED"), "sko_id"].astype(str),
    ))
    c = candidates.copy()
    c["published_norm"] = [
        (int(code), str(sko)) in published_keys for code, sko in zip(c["crop_code_canonical"], c["dominant_sko_id"])
    ]
    used: set[tuple[str, int]] = set()
    selections = []
    specifications = [
        ("HOSTVETE_PREMIUM", c[(c["crop_code_canonical"].eq(4)) & (c["akerscore_soil_p50"] > c["reference_score"])], "1264", True),
        ("HOSTVETE_DISCOUNT", c[(c["crop_code_canonical"].eq(4)) & (c["akerscore_soil_p50"] < c["reference_score"])], "1264", True),
        ("VARKORN", c[c["crop_code_canonical"].eq(2)], "1264", True),
        ("HAVRE", c[c["crop_code_canonical"].eq(3)], None, True),
        ("HOSTRAPS", c[c["crop_code_canonical"].eq(20)], None, True),
        ("MATPOTATIS_KRISTIANSTAD", c[(c["crop_code_canonical"].eq(45)) & c["published_norm"] & c["municipality_code"].astype(str).eq("1290")], None, True),
        ("STARKELSEPOTATIS_KRISTIANSTAD", c[(c["crop_code_canonical"].eq(46)) & c["published_norm"] & c["municipality_code"].astype(str).eq("1290")], None, True),
        ("LOW_SKO_SHARE", c[(c["crop_code_canonical"].isin(adjusted)) & (c["dominant_sko_share"] < .95) & c["published_norm"]], None, True),
        ("HISTORY_COMPONENT_ONLY", c[c["history_quality"].eq("HISTORY_COMPONENT_ONLY")], None, True),
        ("MIXED_AKERMINNE", c[c["history_component_year_count"].gt(0)], None, True),
        ("NO_OFFICIAL_NORM", c[~c["published_norm"]], None, True),
        ("HISTORY_LOW_COVERAGE", c[c["history_quality"].eq("HISTORY_LOW_COVERAGE")], None, False),
        ("MISSING_AKERSCORE", c[c["akerscore_soil_p50"].isna()], None, False),
    ]
    for category, pool, preferred, required in specifications:
        row = choose_first(pool, used, preferred)
        if row is None:
            selections.append({"category": category, "required": required, "status": "NOT_PRESENT_IN_FROZEN_INPUT", "current_field_id": "", "crop_code_canonical": None})
        else:
            selections.append({"category": category, "required": required, "status": "SELECTED", "current_field_id": str(row["current_field_id"]), "crop_code_canonical": int(row["crop_code_canonical"])})
    coverage = pd.DataFrame(selections)
    missing_required = coverage[coverage["required"] & coverage["status"].ne("SELECTED")]
    if not missing_required.empty:
        raise RuntimeError(f"Pilot coverage is incomplete: {missing_required['category'].tolist()}")
    selected_fields = sorted(set(coverage.loc[coverage["status"].eq("SELECTED"), "current_field_id"]))
    return selected_fields, coverage


def calculate_pilot(
    selected_fields: list[str], presence: pd.DataFrame, base: pd.DataFrame,
    official: pd.DataFrame, references: pd.DataFrame, config: dict, source_manifest_id: str,
) -> pd.DataFrame:
    crop_config = {int(row["canonical_code"]): row for row in config["crops"]}
    official_lookup = {
        (int(row.crop_code_canonical), normalized_id(row.sko_id, 4)): {
            **row._asdict(), "norm_t_ha": row.official_norm_t_ha,
        }
        for row in official.itertuples(index=False)
    }
    reference_lookup = {
        (int(row.crop_code_canonical), normalized_id(row.sko_id, 4)): row._asdict()
        for row in references.itertuples(index=False)
    }
    base_lookup = base.set_index("current_field_id").to_dict("index")
    rows = []
    for item in presence[presence["current_field_id"].isin(selected_fields)].itertuples(index=False):
        p = item._asdict()
        field = {"current_field_id": item.current_field_id, **base_lookup[str(item.current_field_id)]}
        key = (int(item.crop_code_canonical), normalized_id(field["dominant_sko_id"], 4))
        rows.append(calculate_field_crop(
            field, p, official_lookup.get(key), reference_lookup.get(key),
            crop_config.get(int(item.crop_code_canonical)), config, source_manifest_id,
        ))
    result = pd.DataFrame(rows).sort_values(["municipality_code", "current_field_id", "crop_code_canonical"], kind="mergesort").reset_index(drop=True)
    if result.duplicated(["current_field_id", "crop_code_canonical"]).any():
        raise RuntimeError("Pilot produced duplicate field/crop rows")
    return result


def invariant_qa(references: pd.DataFrame, config: dict) -> pd.DataFrame:
    crops = {int(row["canonical_code"]): row for row in config["crops"]}
    rows = []
    included = references[references["reference_status"].eq("INCLUDED")]
    for item in included.itertuples(index=False):
        crop = crops[int(item.crop_code_canonical)]
        beta = float(crop["beta_t_ha_per_score"])
        centered = float(item.official_sko_norm_t_ha) + beta * (float(item.reference_score) - float(item.reference_score))
        difference = (float(item.official_sko_norm_t_ha) + beta * 10) - float(item.official_sko_norm_t_ha)
        rows.append({
            "crop_key": item.crop_key, "sko_id": item.sko_id,
            "centered_value": centered, "official_value": float(item.official_sko_norm_t_ha),
            "plus_ten_difference": difference, "expected_plus_ten": beta * 10,
            "center_invariant": "PASS" if centered == float(item.official_sko_norm_t_ha) else "FAIL",
            "difference_invariant": "PASS" if math.isclose(difference, beta * 10, abs_tol=1e-12) else "FAIL",
        })
    result = pd.DataFrame(rows)
    if result.empty or not (result["center_invariant"].eq("PASS") & result["difference_invariant"].eq("PASS")).all():
        raise RuntimeError("Pilot model invariants failed")
    return result


def qa_summary(pilot: pd.DataFrame) -> pd.DataFrame:
    numeric = pilot[pilot["field_akernorm_t_ha"].notna()]
    rows = []
    for (code, name), group in numeric.groupby(["crop_code_canonical", "crop_name"], sort=True):
        values = group["field_akernorm_t_ha"].astype(float)
        adjustments = group["adjustment_t_ha"].astype(float)
        rows.append({
            "crop_code_canonical": int(code), "crop_name": name, "rows": int(len(group)),
            "min_t_ha": float(values.min()), "p05_t_ha": float(values.quantile(.05)),
            "p50_t_ha": float(values.quantile(.5)), "p95_t_ha": float(values.quantile(.95)),
            "max_t_ha": float(values.max()), "min_adjustment_t_ha": float(adjustments.min()),
            "max_adjustment_t_ha": float(adjustments.max()),
            "non_positive": int(values.le(0).sum()),
        })
    return pd.DataFrame(rows)


def write_pilot_qa(
    path: Path, pilot: pd.DataFrame, coverage: pd.DataFrame,
    summary: pd.DataFrame, component_source_mode: str,
) -> None:
    status_counts = pilot["model_status"].value_counts().sort_index()
    support_counts = pilot["score_support_status"].value_counts().sort_index()
    warnings = []
    outside = pilot[pilot["score_support_status"].isin(["BELOW_OBSERVED_MIN", "ABOVE_OBSERVED_MAX"])]
    if len(outside):
        warnings.append(f"{len(outside)} pilot rows are outside observed score min/max; no clamp was applied.")
    lines = [
        "# ÅkerNorm V1 – bounded production pilot QA", "", "- Status: `PASS`",
        f"- Selected fields: `{pilot['current_field_id'].nunique()}`", f"- Field/crop rows: `{len(pilot)}`",
        f"- ÅkerMinne component source: `{component_source_mode}`",
        "- Full Skåne field run: `NO`", "- Web/Sentinel-2: `NO`", "",
        "## Pilot coverage", "", "| Category | Required | Status | Field | Crop code |", "|---|---:|---|---|---:|",
    ]
    for row in coverage.itertuples(index=False):
        code = "—" if pd.isna(row.crop_code_canonical) else int(row.crop_code_canonical)
        lines.append(f"| {row.category} | {row.required} | `{row.status}` | `{row.current_field_id}` | {code} |")
    lines += ["", "## Status reconciliation", ""] + [f"- `{key}`: {value}" for key, value in status_counts.items()]
    lines += ["", "## Score support", ""] + [f"- `{key}`: {value}" for key, value in support_counts.items()]
    lines += ["", "## Numeric crop summary", ""]
    if summary.empty:
        lines.append("No numeric rows.")
    else:
        lines += [
            "| Crop | Rows | Min | P05 | P50 | P95 | Max | Min adjustment | Max adjustment | Non-positive |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in summary.itertuples(index=False):
            lines.append(
                f"| {row.crop_name} | {row.rows} | {row.min_t_ha:.6g} | {row.p05_t_ha:.6g} | "
                f"{row.p50_t_ha:.6g} | {row.p95_t_ha:.6g} | {row.max_t_ha:.6g} | "
                f"{row.min_adjustment_t_ha:.6g} | {row.max_adjustment_t_ha:.6g} | {row.non_positive} |"
            )
    if warnings:
        lines += ["", "## WARN", ""] + [f"- `WARN`: {message}" for message in warnings]
    lines += ["", "## STOPPUNKT B", "", "No full Skåne run or web integration is authorized by this pilot."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--akerminne-skane-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_root.resolve()
    logs = output / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "pilot_traceback.log").unlink(missing_ok=True)
    try:
        config = load_config(CONFIG_PATH)
        model_manifest_path = output / "manifests/model_manifest.json"
        if not model_manifest_path.exists():
            raise RuntimeError("Model manifest is missing; run FREEZE_AKERNORM_V1_MODEL.bat first")
        model_manifest = json.loads(model_manifest_path.read_text(encoding="utf-8-sig"))
        if model_manifest.get("status") != "PASS":
            raise RuntimeError("Model manifest is not PASS")
        source_manifest = json.loads((output / "manifests/source_manifest.json").read_text(encoding="utf-8-sig"))
        official = source_norms(output)
        references = pd.read_csv(output / "model/sko_crop_score_reference.csv", dtype={"sko_id": str})
        references["sko_id"] = references["sko_id"].map(lambda value: normalized_id(value, 4))
        context = pd.read_csv(args.input_dir / "field_static_context_selected.csv.gz", low_memory=False)
        history = pd.read_csv(args.input_dir / "akerminne_2015_2025_selected.csv.gz", low_memory=False)
        score = pd.read_csv(args.input_dir / "akerscore_soil_skiften_selected.csv.gz", low_memory=False)
        context["current_field_id"] = context["current_field_id"].astype(str)
        context["dominant_sko_id"] = context["dominant_sko_id"].map(lambda value: normalized_id(value, 4))
        context["dominant_sko_share"] = pd.to_numeric(context["dominant_sko_share"], errors="coerce")
        score["current_field_id"] = score["current_field_id"].astype(str)
        score["akerscore_soil_p50"] = pd.to_numeric(score["akerscore_soil_p50"], errors="coerce")
        base_columns = ["current_field_id", "municipality_code", "municipality", "dominant_sko_id", "dominant_sko_share"]
        missing = sorted(set(base_columns) - set(context.columns))
        if missing:
            raise RuntimeError(f"Frozen context lacks pilot columns: {missing}")
        base = context[base_columns].merge(score[["current_field_id", "akerscore_soil_p50"]], on="current_field_id", how="left", validate="one_to_one")
        grouped, component_sources, component_source_mode = load_component_source(
            args.akerminne_skane_root.resolve(), set(context["current_field_id"]), config
        )
        presence = build_history_presence(history, grouped, config)
        candidates = candidate_table(presence, base, references)
        selected_fields, coverage = select_pilot(candidates, official, config)
        pilot = calculate_pilot(selected_fields, presence, base, official, references, config, source_manifest["manifest_id"])
        invariants = invariant_qa(references, config)
        summary = qa_summary(pilot)
        pilot_dir, qa_dir = output / "pilot", output / "qa"
        atomic_parquet(pilot, pilot_dir / "field_akernorm_v1_pilot.parquet")
        atomic_csv(pilot, pilot_dir / "field_akernorm_v1_pilot.csv")
        atomic_csv(coverage, pilot_dir / "pilot_coverage.csv")
        atomic_csv(invariants, qa_dir / "pilot_invariants.csv")
        atomic_csv(summary, qa_dir / "pilot_crop_summary.csv")
        examples = pilot[pilot["field_akernorm_t_ha"].notna()].copy()
        examples["formula"] = examples.apply(
            lambda row: f"{row.official_sko_norm_t_ha:.12g} + {row.beta_t_ha_per_score:.12g} * ({row.akerscore_value:.12g} - {row.sko_crop_reference_score:.12g}) = {row.field_akernorm_t_ha:.12g} t/ha",
            axis=1,
        )
        atomic_csv(examples, qa_dir / "pilot_example_calculations.csv")
        write_pilot_qa(qa_dir / "pilot_qa.md", pilot, coverage, summary, component_source_mode)
        relative = [
            "pilot/field_akernorm_v1_pilot.parquet", "pilot/field_akernorm_v1_pilot.csv",
            "pilot/pilot_coverage.csv", "qa/pilot_invariants.csv", "qa/pilot_crop_summary.csv",
            "qa/pilot_example_calculations.csv", "qa/pilot_qa.md",
        ]
        manifest = {
            "schema_version": "akernorm-pilot-manifest-v1", "status": "PASS",
            "model_manifest_id": model_manifest["manifest_id"], "source_manifest_id": source_manifest["manifest_id"],
            "generated_at_utc": source_manifest["retrieved_at_utc"],
            "selected_fields": int(pilot["current_field_id"].nunique()), "field_crop_rows": int(len(pilot)),
            "status_counts": {str(k): int(v) for k, v in pilot["model_status"].value_counts().sort_index().items()},
            "score_support_counts": {str(k): int(v) for k, v in pilot["score_support_status"].value_counts().sort_index().items()},
            "component_source_mode": component_source_mode,
            "component_sources": component_sources,
            "scope": {"pilot_run": True, "full_skane_run": False, "web_changed": False, "sentinel2_changed": False},
            "artifacts": artifact_records(output, relative),
        }
        atomic_json(manifest, output / "manifests/pilot_manifest.json")
        print("=" * 88)
        print("AKERNORM V1 BOUNDED PRODUCTION PILOT: PASS")
        print("=" * 88)
        print(f"Selected fields: {pilot['current_field_id'].nunique()}")
        print(f"Field/crop rows: {len(pilot)}")
        print(f"AkerMinne component source: {component_source_mode}")
        print("No full Skane, web or Sentinel-2 work ran.")
        return 0
    except Exception as exc:
        (logs / "pilot_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"AKERNORM V1 BOUNDED PRODUCTION PILOT: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
