#!/usr/bin/env python3
"""Build the separate, municipality-lazy ÅkerNorm V1 web data layer.

The builder consumes only the independently accepted STOPPUNKT C partitions.
It never recalculates the model.  Existing ÅkerPass/ÅkerMinne files are copied
or checked byte-for-byte, and only ``index.html`` plus ``data/akernorm`` are
owned by this phase.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import traceback
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "akernorm-web-v1"
INDEX_SCHEMA = "akernorm-web-index-v1"
MANIFEST_SCHEMA = "akernorm-web-manifest-v1"
EXPECTED_MUNICIPALITIES = 33
EXPECTED_FIELDS = 128_636
EXPECTED_ROWS = 402_922
OWNED_PREFIX = Path("data/akernorm")
ROW_COLUMNS = [
    "crop_code", "crop_name", "history_year_count", "history_component_year_count",
    "history_years", "history_quality", "sko_id", "sko_share",
    "official_sko_norm_t_ha", "akerscore_value", "sko_crop_reference_score",
    "beta_t_ha_per_score", "adjustment_t_ha", "field_akernorm_t_ha",
    "display_akernorm_t_ha", "model_status", "reason_flags", "score_support_status",
]
DICTIONARY_COLUMNS = {
    "crop_name", "history_quality", "sko_id", "model_status", "reason_flags", "score_support_status",
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_head() -> str:
    supplied = os.environ.get("AKERNORM_REPOSITORY_HEAD", "").strip()
    if supplied:
        return supplied
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def stable_json(document: Any, *, compact: bool = False) -> str:
    if compact:
        return json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    if temporary.read_text(encoding="utf-8") != text:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Atomic write verification failed: {path}")
    os.replace(temporary, path)


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return "_".join(part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in plain).split())


def is_owned(relative: Path) -> bool:
    return relative == OWNED_PREFIX or OWNED_PREFIX in relative.parents


def inventory(root: Path, *, exclude_owned: bool = False, exclude_index: bool = False) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if exclude_owned and is_owned(relative):
            continue
        if exclude_index and relative.as_posix() == "index.html":
            continue
        records.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def verify_base_target(base_dist: Path, target_dist: Path) -> list[dict[str, Any]]:
    """Ensure every non-owned/non-index target file is exactly the base file."""
    base = inventory(base_dist, exclude_owned=True, exclude_index=True)
    target = inventory(target_dist, exclude_owned=True, exclude_index=True)
    if base != target:
        base_map = {row["path"]: row for row in base}
        target_map = {row["path"]: row for row in target}
        changed = sorted(
            path for path in set(base_map) | set(target_map)
            if base_map.get(path) != target_map.get(path)
        )
        raise RuntimeError(
            "Target dist differs from the frozen base outside index.html/data/akernorm: "
            + ", ".join(changed[:20])
        )
    return base


def read_stopc(output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = output_root / "manifests/full_skane_manifest.json"
    stopc_path = output_root / "qa/stopc_verification.json"
    for path in (manifest_path, stopc_path):
        if not path.exists():
            raise RuntimeError(f"Missing accepted STOPPUNKT C artifact: {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    stopc = json.loads(stopc_path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "PASS" or stopc.get("status") != "PASS":
        raise RuntimeError("STOPPUNKT C manifest/verifier is not PASS")
    scope = stopc.get("scope", {})
    if not scope.get("full_skane_run") or scope.get("web_changed") or scope.get("sentinel2_changed"):
        raise RuntimeError("STOPPUNKT C scope is not the accepted pre-web scope")
    if int(stopc.get("municipalities", -1)) != EXPECTED_MUNICIPALITIES:
        raise RuntimeError("STOPPUNKT C municipality count differs")
    if int(stopc.get("reference_fields", -1)) != EXPECTED_FIELDS:
        raise RuntimeError("STOPPUNKT C field count differs")
    if int(stopc.get("field_crop_rows", -1)) != EXPECTED_ROWS:
        raise RuntimeError("STOPPUNKT C row count differs")
    return manifest, stopc


def checkpoint_directories(output_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    rows = []
    for path in sorted((output_root / "full_skane/municipalities").glob("*/checkpoint_manifest.json")):
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if document.get("schema_version") != "akernorm-full-skane-municipality-v1" or document.get("status") != "PASS":
            raise RuntimeError(f"Invalid municipality checkpoint: {path}")
        for record in document.get("artifacts", []):
            artifact = path.parent / record["path"]
            if not artifact.exists() or artifact.stat().st_size != int(record["bytes"]) or sha256_file(artifact) != record["sha256"]:
                raise RuntimeError(f"STOPPUNKT C checkpoint artifact differs: {artifact}")
        rows.append((path.parent, document))
    if len(rows) != EXPECTED_MUNICIPALITIES:
        raise RuntimeError(f"Expected 33 municipality checkpoints, found {len(rows)}")
    return rows


def json_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def history_years(value: Any) -> list[int]:
    if isinstance(value, list):
        values = value
    else:
        try:
            values = json.loads(str(value or "[]"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid history_years JSON: {value!r}") from exc
    return [int(year) for year in values]


def status_group(status: str) -> int:
    if status.startswith("FIELD_ADJUSTED"):
        return 0
    if status.startswith("OFFICIAL_SKO_ONLY"):
        return 1
    return 2


def row_sort_key(row: pd.Series) -> tuple[Any, ...]:
    years = history_years(row["history_years"])
    return (
        status_group(str(row["model_status"])),
        -(max(years) if years else 0),
        -int(row["history_year_count"]),
        int(row["crop_code_canonical"]),
        str(row["crop_name"]),
    )


def clean_text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value)


def make_dictionaries(result: pd.DataFrame) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    dictionaries: dict[str, list[str]] = {}
    indexes: dict[str, dict[str, int]] = {}
    source_columns = {
        "crop_name": "crop_name", "history_quality": "history_quality", "sko_id": "sko_id",
        "model_status": "model_status", "reason_flags": "reason_flags", "score_support_status": "score_support_status",
    }
    for target, source in source_columns.items():
        values = sorted({clean_text(value) for value in result[source]})
        dictionaries[target] = values
        indexes[target] = {value: index for index, value in enumerate(values)}
    return dictionaries, indexes


def pack_row(row: pd.Series, indexes: dict[str, dict[str, int]]) -> list[Any]:
    values = [
        int(row["crop_code_canonical"]), indexes["crop_name"][clean_text(row["crop_name"])],
        int(row["history_year_count"]), int(row["history_component_year_count"]),
        history_years(row["history_years"]), indexes["history_quality"][clean_text(row["history_quality"])],
        indexes["sko_id"][clean_text(row["sko_id"])], json_value(row["sko_share"]),
        json_value(row["official_sko_norm_t_ha"]), json_value(row["akerscore_value"]),
        json_value(row["sko_crop_reference_score"]), json_value(row["beta_t_ha_per_score"]),
        json_value(row["adjustment_t_ha"]), json_value(row["field_akernorm_t_ha"]),
        json_value(row["display_akernorm_t_ha"]), indexes["model_status"][clean_text(row["model_status"])],
        indexes["reason_flags"][clean_text(row["reason_flags"])], indexes["score_support_status"][clean_text(row["score_support_status"])],
    ]
    if len(values) != len(ROW_COLUMNS):
        raise AssertionError("Packed ÅkerNorm row/column length mismatch")
    return values


def build_payload(result: pd.DataFrame, coverage: pd.DataFrame, checkpoint: dict[str, Any]) -> dict[str, Any]:
    required = {
        "current_field_id", "crop_code_canonical", "crop_name", "history_year_count",
        "history_component_year_count", "history_years", "history_quality", "sko_id", "sko_share",
        "official_norm_year", "official_sko_norm_t_ha", "akerscore_value", "sko_crop_reference_score",
        "beta_t_ha_per_score", "adjustment_t_ha", "field_akernorm_t_ha", "display_akernorm_t_ha",
        "model_status", "reason_flags", "score_support_status", "model_version", "source_manifest_id",
    }
    missing = sorted(required - set(result.columns))
    if missing:
        raise RuntimeError(f"STOPPUNKT C output lacks web columns: {missing}")
    if result.duplicated(["current_field_id", "crop_code_canonical"]).any():
        raise RuntimeError("STOPPUNKT C output has duplicate field/crop rows")
    field_ids = sorted(coverage["current_field_id"].astype(str).unique())
    if len(field_ids) != int(checkpoint["reference_fields"]):
        raise RuntimeError("Field coverage differs from checkpoint")
    if set(result["current_field_id"].astype(str)) - set(field_ids):
        raise RuntimeError("ÅkerNorm rows contain field outside municipality coverage")
    years = result["official_norm_year"].dropna().astype(int).unique().tolist()
    versions = result["model_version"].dropna().astype(str).unique().tolist()
    source_ids = result["source_manifest_id"].dropna().astype(str).unique().tolist()
    if len(years) != 1 or len(versions) != 1 or len(source_ids) != 1:
        raise RuntimeError("Municipality rows do not share one norm year/model/source")
    dictionaries, indexes = make_dictionaries(result)
    fields: dict[str, list[list[Any]]] = {field_id: [] for field_id in field_ids}
    for field_id, group in result.groupby(result["current_field_id"].astype(str), sort=True):
        ordered = sorted((row for _, row in group.iterrows()), key=row_sort_key)
        fields[str(field_id)] = [pack_row(row, indexes) for row in ordered]
    statuses = Counter(result["model_status"].astype(str))
    return {
        "schema_version": SCHEMA,
        "municipality_code": str(checkpoint["municipality_code"]),
        "municipality": str(checkpoint["municipality"]),
        "official_norm_year": int(years[0]),
        "model_version": versions[0],
        "source_manifest_id": source_ids[0],
        "field_count": len(fields),
        "field_crop_rows": int(len(result)),
        "status_counts": {key: statuses[key] for key in sorted(statuses)},
        "columns": ROW_COLUMNS, "dictionaries": dictionaries,
        "fields": fields,
    }


def build_data(output_root: Path, destination: Path, stopc: dict[str, Any]) -> dict[str, Any]:
    temporary = destination.with_name(destination.name + ".tmp")
    backup = destination.with_name(destination.name + ".previous")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    entries = []
    total_fields = total_rows = total_bytes = 0
    total_statuses: Counter[str] = Counter()
    for directory, checkpoint in checkpoint_directories(output_root):
        result = pd.read_parquet(directory / "field_akernorm_v1.parquet")
        coverage = pd.read_parquet(directory / "field_coverage.parquet")
        payload = build_payload(result, coverage, checkpoint)
        filename = f"{checkpoint['municipality_code']}_{slug(checkpoint['municipality'])}.json"
        path = temporary / filename
        atomic_text(stable_json(payload, compact=True), path)
        record = {
            "municipality_code": str(checkpoint["municipality_code"]),
            "municipality": str(checkpoint["municipality"]),
            "file": f"data/akernorm/{filename}",
            "field_count": payload["field_count"], "field_crop_rows": payload["field_crop_rows"],
            "bytes": path.stat().st_size, "sha256": sha256_file(path),
        }
        entries.append(record)
        total_fields += payload["field_count"]
        total_rows += payload["field_crop_rows"]
        total_bytes += record["bytes"]
        total_statuses.update(payload["status_counts"])
    entries.sort(key=lambda row: row["municipality_code"])
    if (len(entries), total_fields, total_rows) != (EXPECTED_MUNICIPALITIES, EXPECTED_FIELDS, EXPECTED_ROWS):
        raise RuntimeError(f"Web totals differ: {len(entries)}/{total_fields}/{total_rows}")
    index = {
        "schema_version": INDEX_SCHEMA, "status": "PASS",
        "full_manifest_id": stopc["full_manifest_id"], "output_hash": stopc["output_hash"],
        "municipality_count": len(entries), "field_count": total_fields,
        "field_crop_rows": total_rows, "sidecar_bytes": total_bytes,
        "status_counts": {key: total_statuses[key] for key in sorted(total_statuses)},
        "municipalities": entries,
    }
    atomic_text(stable_json(index), temporary / "skane_index.json")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        os.replace(destination, backup)
    os.replace(temporary, destination)
    if backup.exists():
        shutil.rmtree(backup)
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--base-dist", required=True, type=Path)
    parser.add_argument("--dist", default=str(ROOT / "dist"), type=Path)
    parser.add_argument("--patcher", default=str(ROOT / "src/86_patch_akerpass_akernorm_v1_ui.py"), type=Path)
    args = parser.parse_args()
    output_root, base_dist, target_dist = args.output_root.resolve(), args.base_dist.resolve(), args.dist.resolve()
    logs = output_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "web_build_traceback.log").unlink(missing_ok=True)
    try:
        if base_dist == target_dist:
            raise RuntimeError("Base dist and target dist must be separate; the frozen base must remain untouched")
        if not (base_dist / "index.html").exists():
            raise RuntimeError(f"Base dist lacks index.html: {base_dist}")
        full_manifest, stopc = read_stopc(output_root)
        if not target_dist.exists():
            shutil.copytree(base_dist, target_dist)
        base_inventory = verify_base_target(base_dist, target_dist)

        index = build_data(output_root, target_dist / OWNED_PREFIX, stopc)
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("akernorm_web_ui", args.patcher.resolve())
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load UI patcher: {args.patcher}")
        patcher = module_from_spec(spec)
        spec.loader.exec_module(patcher)
        source_html = (base_dist / "index.html").read_text(encoding="utf-8")
        mapping = {row["municipality"]: row["file"] for row in index["municipalities"]}
        patched_html = patcher.patch_html(source_html, mapping)
        atomic_text(patched_html, target_dist / "index.html")
        verify_base_target(base_dist, target_dist)

        artifacts = inventory(target_dist / OWNED_PREFIX)
        manifest = {
            "schema_version": MANIFEST_SCHEMA, "status": "PASS",
            "repository_head": repository_head(),
            "full_manifest_id": full_manifest["manifest_id"], "full_output_hash": stopc["output_hash"],
            "base_dist": str(base_dist), "target_dist": str(target_dist),
            "base_index_sha256": sha256_file(base_dist / "index.html"),
            "patched_index_sha256": sha256_file(target_dist / "index.html"),
            "protected_base_files": base_inventory,
            "municipality_count": index["municipality_count"], "field_count": index["field_count"],
            "field_crop_rows": index["field_crop_rows"], "sidecar_bytes": index["sidecar_bytes"],
            "web_artifacts": artifacts,
            "scope": {"full_skane_run": True, "web_changed": True, "deployment": False, "sentinel2_changed": False},
        }
        manifest["manifest_id"] = "akernorm-web-" + hashlib.sha256(
            stable_json({key: value for key, value in manifest.items() if key != "manifest_id"}).encode("utf-8")
        ).hexdigest()[:16]
        atomic_text(stable_json(manifest), output_root / "manifests/akernorm_web_manifest.json")
        print("=" * 88)
        print("AKERNORM V1 WEB DATA + UI BUILD: PASS")
        print("=" * 88)
        print(f"Municipalities: {index['municipality_count']} · fields: {index['field_count']:,}")
        print(f"Field/crop rows: {index['field_crop_rows']:,} · sidecars: {index['sidecar_bytes']:,} bytes")
        print("Existing AkerScore/AkerVarde/AkerDrift/AkerMinne files: byte-identical")
        print("Deployment/Sentinel-2: NO")
        return 0
    except Exception as exc:
        (logs / "web_build_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"AKERNORM V1 WEB DATA + UI BUILD: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
