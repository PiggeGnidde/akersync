#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import pandas as pd

from akernorm_v1_core import (
    MODEL_CONTRACT_SCHEMA,
    MODEL_MANIFEST_SCHEMA,
    SOURCE_MANIFEST_SCHEMA,
    artifact_records,
    atomic_csv,
    atomic_json,
    build_reference_table,
    conservation_qa,
    load_config,
    sha256_file,
    verify_presence_threshold,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/akernorm_v1.json"
AKERMINNE_CONFIG_PATH = ROOT / "config/akerminne_v1a.json"


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True, encoding="utf-8").strip()


def verify_repository(config: dict) -> dict:
    if git("branch", "--show-current") != "feature/akernorm-product-v1a":
        raise RuntimeError("Model freeze must run on feature/akernorm-product-v1a")
    if git("status", "--short"):
        raise RuntimeError("Working tree is not clean before model freeze")
    checks = {}
    for label in ("context", "validation"):
        expected = config[label]["commit"]
        actual = git("rev-list", "-n", "1", config[label]["tag"])
        if actual != expected:
            raise RuntimeError(f"{label} tag mismatch: expected {expected}, got {actual}")
        checks[f"{label}_tag_commit"] = actual
    head = git("rev-parse", "HEAD")
    checks.update({"branch": git("branch", "--show-current"), "head": head})
    return checks


def verify_stop_a(stop_a: Path) -> dict:
    manifest_path = stop_a / "discovery_manifest.json"
    verifier_log = stop_a / "logs/reproduction_verify.log"
    if not manifest_path.exists():
        raise RuntimeError(f"Missing STOPPUNKT A manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "PASS":
        raise RuntimeError(f"STOPPUNKT A status is not PASS: {manifest.get('status')}")
    scope = manifest.get("scope", {})
    forbidden = [name for name, value in scope.items() if bool(value)]
    if forbidden:
        raise RuntimeError(f"STOPPUNKT A scope contains later-phase work: {forbidden}")
    for name, record in manifest.get("artifact_hashes", {}).items():
        path = stop_a / name
        if not path.exists() or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"STOPPUNKT A artifact hash mismatch: {name}")
    if not verifier_log.exists() or "REPRODUCTION VERIFIER: PASS" not in verifier_log.read_text(encoding="utf-8-sig"):
        raise RuntimeError("Independent STOPPUNKT A verifier PASS log is missing")
    if (stop_a / "logs/fatal_traceback.log").exists():
        raise RuntimeError("STOPPUNKT A contains fatal_traceback.log")
    return manifest


def verify_frozen_inputs(input_dir: Path, config: dict) -> dict:
    records = {}
    for name, expected in config["frozen_inputs"].items():
        path = input_dir / name
        if not path.exists():
            raise RuntimeError(f"Missing frozen input: {path}")
        digest = sha256_file(path)
        if digest != expected["sha256"]:
            raise RuntimeError(f"Frozen input SHA mismatch for {name}: {digest}")
        actual_rows = sum(len(chunk) for chunk in pd.read_csv(path, usecols=[0], chunksize=250_000))
        if actual_rows != int(expected["rows"]):
            raise RuntimeError(f"Frozen input row mismatch for {name}: {actual_rows}")
        records[name] = {"path": str(path), "rows": actual_rows, "sha256": digest}
    return records


def copy_source_snapshot(stop_a: Path, output_root: Path) -> tuple[Path, dict]:
    source_from = stop_a / "source"
    source_manifest_from = stop_a / "official_norm_source_manifest.json"
    if not source_from.exists() or not source_manifest_from.exists():
        raise RuntimeError("STOPPUNKT A official source snapshot is incomplete")
    discovery_source = json.loads(source_manifest_from.read_text(encoding="utf-8-sig"))
    source_to = output_root / "source"
    source_to.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sorted(source_from.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_from)
        target = source_to / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        shutil.copyfile(source, temporary)
        if sha256_file(source) != sha256_file(temporary):
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Byte copy failed for source snapshot: {relative}")
        os.replace(temporary, target)
        copied.append(relative)
    normalized = source_to / "normalized/official_norm_yield_2026_normalized.csv"
    expected_hash = discovery_source["normalized_sha256"]
    if not normalized.exists() or sha256_file(normalized) != expected_hash:
        raise RuntimeError("Frozen normalized official norm table differs from STOPPUNKT A")
    manifest = {
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "manifest_id": f"akernorm-source-2026-{expected_hash[:16]}",
        "status": "FROZEN_CANDIDATE_STOPB",
        "source": "Jordbruksverket PxWeb",
        "table": discovery_source["table"],
        "api_url": discovery_source["api_url"],
        "official_norm_year": 2026,
        "retrieved_at_utc": discovery_source["retrieved_at_utc"],
        "raw_unit": discovery_source["raw_unit"],
        "normalized_unit": discovery_source["normalized_unit"],
        "conversion": discovery_source["conversion"],
        "metadata_raw_sha256": discovery_source["metadata_raw_sha256"],
        "normalized_sha256": expected_hash,
        "stop_a_manifest_sha256": sha256_file(stop_a / "discovery_manifest.json"),
        "artifacts": artifact_records(source_to, copied),
    }
    atomic_json(manifest, output_root / "manifests/source_manifest.json")
    return normalized, manifest


def normalized_for_engine(path: Path) -> pd.DataFrame:
    source = pd.read_csv(path, dtype={"sko_id": str})
    return source.rename(columns={
        "crop_code_canonical": "canonical_crop_code",
        "norm_raw_value": "raw_value",
        "norm_raw_unit": "raw_unit",
        "official_norm_t_ha": "norm_t_ha",
        "status": "value_status",
    })


def compare_reproduced_references(reference: pd.DataFrame, stop_a: Path) -> pd.DataFrame:
    rows = []
    for crop_key in ("hostvete", "varkorn", "havre", "hostraps"):
        path = stop_a / f"reproduction/{crop_key}/base/sko_fit_table.csv"
        if not path.exists():
            raise RuntimeError(f"Missing reproduced fit table: {path}")
        fit = pd.read_csv(path, dtype={"sko_id": str})
        fit["sko_id"] = fit["sko_id"].astype(str).str.zfill(4)
        actual = reference[
            reference["crop_key"].eq(crop_key)
            & reference["reference_status"].eq("INCLUDED")
        ].copy()
        merged = fit.merge(
            actual, on="sko_id", how="outer", suffixes=("_analysis", "_freeze"),
            indicator=True, validate="one_to_one",
        )
        for _, item in merged.iterrows():
            present = item["_merge"] == "both"
            checks = {
                "field_years": present and int(item["field_years_analysis"]) == int(item["field_years_freeze"]),
                "unique_fields": present and int(item["unique_fields_analysis"]) == int(item["unique_fields_freeze"]),
                "reference_score": present and abs(float(item["mean_akerscore_areaweighted"]) - float(item["reference_score"])) <= 1e-12,
                "official_norm": present and abs(float(item["norm_t_ha"]) - float(item["official_sko_norm_t_ha"])) <= 1e-12,
            }
            area_column = next((name for name in ("wheat_area_fieldyear_ha", "crop_area_fieldyear_ha") if name in merged.columns), None)
            if area_column is not None:
                checks["area_year_weight"] = present and abs(
                    float(item[area_column]) * 10_000.0 - float(item["area_year_weight_m2"])
                ) <= max(1e-6, abs(float(item["area_year_weight_m2"])) * 1e-12)
            rows.append({
                "crop_key": crop_key,
                "sko_id": item["sko_id"],
                "analysis_field_years": None if not present else int(item["field_years_analysis"]),
                "frozen_field_years": None if not present else int(item["field_years_freeze"]),
                "analysis_reference_score": None if not present else float(item["mean_akerscore_areaweighted"]),
                "frozen_reference_score": None if not present else float(item["reference_score"]),
                "status": "PASS" if all(checks.values()) else "MISMATCH",
                "checks": ";".join(name for name, value in checks.items() if not value),
            })
    result = pd.DataFrame(rows).sort_values(["crop_key", "sko_id"], kind="mergesort").reset_index(drop=True)
    if not result["status"].eq("PASS").all():
        bad = result[result["status"].ne("PASS")].head(20).to_dict("records")
        raise RuntimeError(f"Frozen reference differs from STOPPUNKT A reproduction: {bad}")
    return result


def model_contract(config: dict, source_manifest: dict, reference: pd.DataFrame, stop_a_manifest: dict) -> dict:
    crop_rows = []
    for crop in config["crops"]:
        key = crop["crop_key"]
        supported = reference[
            reference["crop_key"].eq(key) & reference["reference_status"].eq("INCLUDED")
        ]
        crop_rows.append({**crop, "supported_sko_count": int(len(supported)), "supported_sko_ids": supported["sko_id"].tolist()})
    return {
        "schema_version": MODEL_CONTRACT_SCHEMA,
        "model_name": config["model_name"],
        "model_version": config["model_version"],
        "status": config["status"],
        "context": config["context"],
        "validation": config["validation"],
        "analysis": config["analysis"],
        "stop_a_repository_head": stop_a_manifest["repository"]["head"],
        "akerscore_dataset": config["akerscore_dataset"],
        "akerminne_version": config["akerminne_version"],
        "akerminne_years": config["akerminne_years"],
        "sko_overlay_version": config["sko_overlay_version"],
        "official_norm_source": {
            "table": source_manifest["table"],
            "year": source_manifest["official_norm_year"],
            "api_url": source_manifest["api_url"],
            "query_and_raw_responses": "source/queries and source/raw",
            "normalized_unit": source_manifest["normalized_unit"],
            "normalized_sha256": source_manifest["normalized_sha256"],
            "source_manifest_id": source_manifest["manifest_id"],
            "query_artifacts": [row for row in source_manifest["artifacts"] if "/queries/" in f"/{row['path']}"],
            "raw_response_artifacts": [row for row in source_manifest["artifacts"] if "/raw/" in f"/{row['path']}"],
        },
        "crop_code_mapping": [{
            "crop_key": row["crop_key"], "canonical_code": row["canonical_code"],
            "canonical_name": row["canonical_name"], "pxweb_label": row["pxweb_label"],
        } for row in config["crops"]],
        "crops": crop_rows,
        "formula": "official_sko_norm_t_ha + beta_t_ha_per_score * (akerscore_value - sko_crop_reference_score)",
        "reference_population": config["reference_population"],
        "minimum_dominant_sko_share": config["minimum_dominant_sko_share"],
        "crop_presence": config["crop_presence"],
        "display": config["display"],
        "allowed_extrapolation": config["allowed_extrapolation"],
        "disallowed": config["disallowed"],
        "known_limitations": config["known_limitations"],
        "output_schema_version": config["output_schema_version"],
        "generated_at_utc": source_manifest["retrieved_at_utc"],
        "code_sha256": sha256_file(ROOT / "src/akernorm_v1_core.py"),
        "config_sha256": sha256_file(CONFIG_PATH),
    }


def write_qa(path: Path, reference: pd.DataFrame, conservation: pd.DataFrame, comparison: pd.DataFrame, contract: dict) -> None:
    lines = [
        "# ÅkerNorm V1 – model freeze QA (STOPPUNKT B candidate)", "",
        "- Status: `PASS`", f"- Model: `{contract['model_version']}`",
        f"- Official normalized source SHA256: `{contract['official_norm_source']['normalized_sha256']}`",
        f"- Crop/SKO reference rows: `{len(reference)}`",
        f"- Reproduced analysis rows checked: `{len(comparison)}` all PASS",
        f"- Conservation rows: `{len(conservation)}` all PASS",
        "- Global regression intercept used as local base: `NO`",
        "- Climate selected: `NO`", "- Potato score-adjusted: `NO`",
        "- Full Skåne field run: `NO`", "- Web/Sentinel-2: `NO`", "",
        "## Frozen coefficients", "",
        "| Crop | Mode | beta t/ha/score | +10 score | supported SKO |", "|---|---|---:|---:|---:|",
    ]
    for crop in contract["crops"]:
        beta = "—" if crop["beta_t_ha_per_score"] is None else str(crop["beta_t_ha_per_score"])
        effect = "—" if crop["effect_t_ha_per_10_score"] is None else str(crop["effect_t_ha_per_10_score"])
        lines.append(f"| {crop['canonical_name']} | `{crop['model_mode']}` | {beta} | {effect} | {crop['supported_sko_count']} |")
    lines += ["", "## STOPPUNKT B scope", "", "This is the frozen candidate model and reference population. No full Skåne or web phase has run."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-a-dir", required=True, type=Path)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_root.resolve()
    logs = output / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "model_freeze_traceback.log").unlink(missing_ok=True)
    try:
        config = load_config(CONFIG_PATH)
        verify_presence_threshold(config, AKERMINNE_CONFIG_PATH)
        repository = verify_repository(config)
        stop_a_manifest = verify_stop_a(args.stop_a_dir.resolve())
        input_records = verify_frozen_inputs(args.input_dir.resolve(), config)
        normalized_path, source_manifest = copy_source_snapshot(args.stop_a_dir.resolve(), output)
        official = normalized_for_engine(normalized_path)
        context = pd.read_csv(args.input_dir / "field_static_context_selected.csv.gz", low_memory=False)
        history = pd.read_csv(args.input_dir / "akerminne_2015_2025_selected.csv.gz", low_memory=False)
        score = pd.read_csv(args.input_dir / "akerscore_soil_skiften_selected.csv.gz", low_memory=False)
        reference, selected = build_reference_table(context, history, score, official, config)
        reference["context_input_sha256"] = input_records["field_static_context_selected.csv.gz"]["sha256"]
        reference["history_input_sha256"] = input_records["akerminne_2015_2025_selected.csv.gz"]["sha256"]
        reference["score_input_sha256"] = input_records["akerscore_soil_skiften_selected.csv.gz"]["sha256"]
        reference["official_norm_source_sha256"] = source_manifest["normalized_sha256"]
        comparison = compare_reproduced_references(reference, args.stop_a_dir.resolve())
        conservation = conservation_qa(selected, config)
        if conservation.empty or not conservation["status"].eq("PASS").all():
            raise RuntimeError("Reference-population conservation check failed")
        model_dir = output / "model"
        qa_dir = output / "qa"
        atomic_csv(reference, model_dir / "sko_crop_score_reference.csv")
        atomic_csv(comparison, model_dir / "reference_reproduction_comparison.csv")
        atomic_csv(conservation, model_dir / "reference_conservation_qa.csv")
        contract = model_contract(config, source_manifest, reference, stop_a_manifest)
        atomic_json(contract, model_dir / "akernorm_model_contract_v1.json")
        write_qa(qa_dir / "model_reproduction_qa.md", reference, conservation, comparison, contract)
        relative = [
            "model/sko_crop_score_reference.csv", "model/reference_reproduction_comparison.csv",
            "model/reference_conservation_qa.csv", "model/akernorm_model_contract_v1.json",
            "qa/model_reproduction_qa.md", "manifests/source_manifest.json",
        ]
        manifest = {
            "schema_version": MODEL_MANIFEST_SCHEMA,
            "manifest_id": f"akernorm-model-{sha256_file(model_dir / 'akernorm_model_contract_v1.json')[:16]}",
            "status": "PASS",
            "model_version": config["model_version"],
            "generated_at_utc": source_manifest["retrieved_at_utc"],
            "repository": repository,
            "stop_a_manifest_sha256": sha256_file(args.stop_a_dir / "discovery_manifest.json"),
            "frozen_inputs": input_records,
            "source_manifest_id": source_manifest["manifest_id"],
            "reference_rows": int(len(reference)),
            "reproduction_rows": int(len(comparison)),
            "conservation_rows": int(len(conservation)),
            "scope": {"model_frozen": True, "pilot_run": False, "full_skane_run": False, "web_changed": False, "sentinel2_changed": False},
            "artifacts": artifact_records(output, relative),
        }
        atomic_json(manifest, output / "manifests/model_manifest.json")
        print("=" * 88)
        print("AKERNORM V1 MODEL FREEZE CANDIDATE: PASS")
        print("=" * 88)
        print(f"Output: {output}")
        print(f"Reference rows: {len(reference)}")
        print(f"Reproduction rows: {len(comparison)} all PASS")
        print(f"Conservation rows: {len(conservation)} all PASS")
        print("No full Skane, web or Sentinel-2 work ran.")
        return 0
    except Exception as exc:
        (logs / "model_freeze_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc(), file=sys.stderr)
        print(f"AKERNORM V1 MODEL FREEZE CANDIDATE: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
