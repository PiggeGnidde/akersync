#!/usr/bin/env python3
"""Full-2025 Rapskartan product helpers with a local Sentinel-2 scene archive.

The module does not read crop ground truth.  It reuses the frozen pre-blind
models and thresholds, and treats the cumulative high-confidence memory as an
explicit post-blind product rule.  A local-engine parity gate against the
already locked, label-free STOPPUNKT D predictions must pass before full-Skane
outputs may be written.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from rapskartan_blind_prediction_core import (
    SAFE_GEOMETRY_COLUMNS, current_field_id, sha256_file,
    validate_safe_projection_columns,
)
from rapskartan_model_core import SPECTRAL_NAMES, stable_rank
from rapskartan_s2_pilot_core import artifact_records, stable_json, utc_now, write_json


CONTRACT_REL = Path("config/rapskartan_2025_map_product_v1.json")
ACCEPTED_STOPD_REL = Path("analysis/rapskartan_v1/accepted_stopD_manifest.json")
FEATURE_BRANCH = "feature/rapskartan-skane-v1a"
FORBIDDEN_PRODUCT_COLUMNS = {
    "is_winter_rapeseed", "crop_group", "official_crop_name", "crop_code_raw",
    "crop_subcategory_raw", "dominant_crop_name", "grdkod_mar", "grdkod_und",
}


def read_full_safe_2025_geometry(path: Path, contract: dict[str, Any]) -> Any:
    """Read identity/municipality/geometry only, retaining all 2025 fields."""
    import geopandas as gpd

    if not path.is_file() or sha256_file(path) != contract["geometry"]["expected_sha256"]:
        raise RuntimeError("Frozen 2025 geometry file/hash mismatch")
    frame = gpd.read_file(path, columns=list(SAFE_GEOMETRY_COLUMNS))
    validate_safe_projection_columns(frame.columns)
    if len(frame) != int(contract["geometry"]["expected_total_fields"]):
        raise RuntimeError(f"2025 geometry rows {len(frame)}, expected {contract['geometry']['expected_total_fields']}")
    if frame.crs is None or set(pd.to_numeric(frame["arslager"], errors="raise").astype(int)) != {2025}:
        raise RuntimeError("2025 safe geometry CRS/year is invalid")
    frame = frame.to_crs(int(contract["geometry"]["crs_epsg"])).copy()
    good = frame.geometry.notna() & ~frame.geometry.is_empty & frame.geometry.is_valid
    if not good.all():
        raise RuntimeError(f"2025 source contains {int((~good).sum())} invalid geometries")
    frame["area_ha"] = frame.geometry.area / 10_000.0
    frame["municipality_code"] = frame["region_kod"].astype(str).str[:4]
    frame["current_field_id"] = [current_field_id(a, b) for a, b in zip(frame["blockid"], frame["skiftesbeteckning"])]
    if frame["current_field_id"].duplicated().any():
        raise RuntimeError("2025 geometry contains duplicate field identities")
    frame["target_year"] = 2025
    frame["development_field_id"] = [
        f"2025-{code}-{identity.replace('|', '-')}"
        for code, identity in zip(frame["municipality_code"], frame["current_field_id"])
    ]
    frame["geographic_fold"] = [int(stable_rank("geo", code)[:8], 16) % 5 for code in frame["municipality_code"]]
    frame["model_scope_status"] = np.where(
        frame["area_ha"].between(
            float(contract["geometry"]["minimum_area_ha"]),
            float(contract["geometry"]["maximum_area_ha"]), inclusive="both",
        ),
        "MODEL_ELIGIBLE", "OUTSIDE_AREA_SCOPE",
    )
    return gpd.GeoDataFrame(
        frame.sort_values(["municipality_code", "current_field_id"], kind="mergesort").reset_index(drop=True),
        geometry="geometry", crs=frame.crs,
    )


def full_model_selection(fields: Any) -> pd.DataFrame:
    selected = fields[fields["model_scope_status"] == "MODEL_ELIGIBLE"].copy()
    selected["area_stratum"] = -1
    selected["population_weight"] = 1.0
    keep = [
        "development_field_id", "current_field_id", "target_year", "municipality_code",
        "area_ha", "area_stratum", "population_weight", "geographic_fold",
    ]
    return selected[keep].sort_values("development_field_id", kind="mergesort").reset_index(drop=True)


def add_outside_scope_rows(
    product: pd.DataFrame,
    all_fields: Any,
    contract: dict[str, Any],
) -> pd.DataFrame:
    """Add explicit NO_DATA rows so every source field appears at every cutoff."""
    outside = all_fields[all_fields["model_scope_status"] != "MODEL_ELIGIBLE"].copy()
    if outside.empty:
        result = product.copy()
        result["model_scope_status"] = "MODEL_ELIGIBLE"
        return result
    thresholds = product.groupby("cutoff_date")["frozen_p95_threshold"].first().to_dict()
    rows = []
    for cutoff in sorted(product["cutoff_date"].unique()):
        part = pd.DataFrame({
            "field_id": outside["current_field_id"].astype(str),
            "current_field_id": outside["current_field_id"].astype(str),
            "municipality_code": outside["municipality_code"].astype(str),
            "target_year": 2025,
            "area_ha": outside["area_ha"].astype(float),
            "cutoff_date": str(cutoff),
            "latest_used_acquisition": None,
            "days_since_last_obs": np.nan,
            "valid_obs_count": np.nan,
            "valid_pixel_fraction": np.nan,
            "data_quality_status": "OUTSIDE_MODEL_SCOPE",
            "p_raps": np.nan,
            "frozen_p95_threshold": float(thresholds[str(cutoff)]),
            "current_high_confidence": False,
            "remembered_high_confidence": False,
            "first_high_confidence_date": None,
            "confidence_status": "NO_DATA",
            "model_arm": contract["product_rule"]["primary_model_arm"],
            "model_version": contract["model_version"],
            "feature_contract_version": contract["frozen_feature_contract_version"],
            "source_manifest_id": contract["frozen_model_contract_id"],
            "product_rule_id": contract["product_rule"]["rule_id"],
            "product_rule_class": contract["product_rule"]["rule_class"],
            "ground_truth_present": False,
            "model_scope_status": "OUTSIDE_AREA_SCOPE",
        })
        rows.append(part)
    eligible = product.copy()
    eligible["model_scope_status"] = "MODEL_ELIGIBLE"
    result = pd.concat([eligible, *rows], ignore_index=True)
    return result.sort_values(["cutoff_date", "municipality_code", "field_id"], kind="mergesort").reset_index(drop=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_lf_normalized_text(path: Path) -> str:
    """Hash repository text identically after LF or CRLF checkout."""
    value = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return sha256_bytes(value)


def load_map_contract(root: Path) -> dict[str, Any]:
    contract = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    validate_map_contract(contract)
    return contract


def validate_map_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != "rapskartan-2025-map-product-contract-v1":
        raise RuntimeError("Unexpected map-product contract schema")
    if int(contract.get("target_year", 0)) != 2025:
        raise RuntimeError("Map product is not frozen to historical year 2025")
    if tuple(contract["geometry"]["safe_attribute_columns"]) != SAFE_GEOMETRY_COLUMNS:
        raise RuntimeError("Map product changed the safe geometry projection")
    scene = contract["scene_archive"]
    if scene.get("engine") != "LOCAL_STAC_S3_SENTINEL2_L2A_SCENE_ARCHIVE":
        raise RuntimeError("Map product must use the authorized local scene engine")
    if scene.get("collection") != "sentinel-2-l2a" or int(scene.get("resolution_m", 0)) != 10:
        raise RuntimeError("Map product changed the frozen Sentinel-2 collection/resolution")
    if scene.get("mosaicking") != "SIMPLE" or scene.get("mosaicking_order") != "leastCC":
        raise RuntimeError("Map product changed the frozen mosaicking contract")
    expected_bands = {"B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"}
    if set(scene.get("reflectance_assets", {})) != expected_bands:
        raise RuntimeError("Map product does not contain the ten frozen reflectance bands")
    if set(map(int, scene.get("valid_scl_codes", []))) != {2, 4, 5}:
        raise RuntimeError("Map product changed the frozen SCL mask")
    parity = contract["parity_gate"]
    if parity.get("primary_model_arm") != "SATELLITE_ONLY":
        raise RuntimeError("Parity gate must verify the satellite-only product arm")
    if float(parity.get("required_frozen_p95_decision_agreement", 0)) != 1.0:
        raise RuntimeError("Every frozen P95 decision must agree at the parity gate")
    rule = contract["product_rule"]
    if rule.get("rule_class") != "POST_BLIND_PRODUCT_RULE" or rule.get("entry_decision") != "predicted_at_frozen_p95":
        raise RuntimeError("Unexpected post-blind product memory rule")
    if rule.get("blind_benchmark_is_immutable") is not True or rule.get("model_retuning") is not False or rule.get("threshold_retuning") is not False:
        raise RuntimeError("Product rule would alter the accepted blind benchmark")
    scope = contract.get("scope", {})
    if scope.get("full_historical_2025_map_product") is not True or scope.get("ground_truth_in_product") is not False:
        raise RuntimeError("Map-product scope is invalid")
    for key in ("post_blind_model_retuning", "threshold_retuning", "sentinel1", "web", "deployment", "tag", "merge"):
        if scope.get(key) is not False:
            raise RuntimeError(f"Map-product contract authorizes forbidden scope: {key}")


def _verify_manifest_artifacts(root: Path, manifest: dict[str, Any]) -> None:
    for record in manifest.get("artifacts", []):
        path = root / record["path"]
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Accepted STOPPUNKT D artifact mismatch: {record['path']}")


def _git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if process.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {process.stderr.strip()}")
    return process.stdout.strip()


def verify_stop_d(root: Path, stop_d: Path, contract: dict[str, Any]) -> dict[str, Any]:
    accepted_path = root / ACCEPTED_STOPD_REL
    if sha256_lf_normalized_text(accepted_path) != contract["accepted_stopd_manifest_sha256"]:
        raise RuntimeError("Repository accepted STOPPUNKT D manifest changed")
    accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
    if accepted.get("status") != "PASS" or accepted.get("authorization", {}).get("go_map_product_received") is not True:
        raise RuntimeError("Repository does not contain accepted STOPPUNKT D + GO MAP PRODUCT")
    lock_path = stop_d / "prediction_lock_manifest.json"
    evaluation_path = stop_d / "blind_evaluation_manifest.json"
    if not lock_path.is_file() or not evaluation_path.is_file():
        raise RuntimeError("Accepted STOPPUNKT D manifests are missing")
    expected = contract["accepted_stopd"]
    if sha256_file(lock_path) != expected["prediction_lock_manifest_sha256"]:
        raise RuntimeError("STOPPUNKT D prediction lock differs from accepted return")
    if sha256_file(evaluation_path) != expected["blind_evaluation_manifest_sha256"]:
        raise RuntimeError("STOPPUNKT D evaluation manifest differs from accepted return")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    if lock.get("status") != "PREDICTIONS_HASH_LOCKED" or evaluation.get("status") != "PASS":
        raise RuntimeError("STOPPUNKT D manifests are not PASS/locked")
    if lock.get("critical_prediction_sha256") != expected["critical_prediction_sha256"]:
        raise RuntimeError("STOPPUNKT D critical prediction hash mismatch")
    if evaluation.get("critical_prediction_sha256") != expected["critical_prediction_sha256"]:
        raise RuntimeError("STOPPUNKT D evaluation is not bound to the prediction lock")
    _verify_manifest_artifacts(stop_d, lock)
    _verify_manifest_artifacts(stop_d, evaluation)
    source = accepted["source_archive"]
    if _git(root, "show", "-s", "--format=%T", source["verified_feature_head"]) != source["verified_feature_tree"]:
        raise RuntimeError("Accepted STOPPUNKT D verifier commit/tree is absent")
    if _git(root, "merge-base", "--is-ancestor", source["verified_feature_head"], "HEAD") != "":
        raise RuntimeError("Accepted STOPPUNKT D is not an ancestor of the map-product code")
    return {"accepted": accepted, "lock": lock, "evaluation": evaluation}


def apply_product_memory_rule(predictions: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    """Project the frozen satellite arm and latch every earlier P95 detection."""
    arm = contract["product_rule"]["primary_model_arm"]
    frame = predictions[predictions["model_arm"] == arm].copy()
    required = {
        "field_id", "current_field_id", "municipality_code", "target_year", "area_ha",
        "cutoff_date", "latest_used_acquisition", "data_quality_status", "valid_obs_count",
        "days_since_last_obs", "valid_pixel_fraction", "calibrated_probability",
        "frozen_p95_threshold", "predicted_at_frozen_p95", "model_arm", "model_version",
        "feature_contract_version", "source_manifest_id",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Frozen prediction output lacks product columns: {missing}")
    if frame.empty or frame["target_year"].astype(int).ne(2025).any():
        raise RuntimeError("Map-product predictions are not historical year 2025")
    if FORBIDDEN_PRODUCT_COLUMNS & set(frame.columns):
        raise RuntimeError("Ground-truth/crop columns entered the map-product projection")
    frame = frame.sort_values(["field_id", "cutoff_date"], kind="mergesort").reset_index(drop=True)
    frame["current_high_confidence"] = frame["predicted_at_frozen_p95"].astype(bool)
    frame["remembered_high_confidence"] = frame.groupby("field_id", sort=False)["current_high_confidence"].cummax()
    first = (
        frame.loc[frame["current_high_confidence"], ["field_id", "cutoff_date"]]
        .groupby("field_id", sort=False)["cutoff_date"].min()
    )
    frame["first_high_confidence_date"] = frame["field_id"].map(first)
    usable = frame["data_quality_status"].eq("USABLE") & frame["calibrated_probability"].notna()
    frame["confidence_status"] = np.select(
        [frame["remembered_high_confidence"], ~usable, frame["calibrated_probability"].ge(0.5)],
        ["HIGH_CONFIDENCE", "NO_DATA", "POSSIBLE"],
        default="LOW",
    )
    frame["p_raps"] = frame["calibrated_probability"]
    frame["product_rule_id"] = contract["product_rule"]["rule_id"]
    frame["product_rule_class"] = contract["product_rule"]["rule_class"]
    frame["ground_truth_present"] = False
    keep = [
        "field_id", "current_field_id", "municipality_code", "target_year", "area_ha",
        "cutoff_date", "latest_used_acquisition", "days_since_last_obs", "valid_obs_count",
        "valid_pixel_fraction", "data_quality_status", "p_raps", "frozen_p95_threshold",
        "current_high_confidence", "remembered_high_confidence", "first_high_confidence_date",
        "confidence_status", "model_arm", "model_version", "feature_contract_version",
        "source_manifest_id", "product_rule_id", "product_rule_class", "ground_truth_present",
    ]
    result = frame[keep].sort_values(["cutoff_date", "municipality_code", "field_id"], kind="mergesort").reset_index(drop=True)
    if result.groupby(["field_id", "cutoff_date"]).size().ne(1).any():
        raise RuntimeError("Map product does not contain exactly one primary-arm row per field/cutoff")
    for _, part in result.groupby("field_id", sort=False):
        values = part.sort_values("cutoff_date")["remembered_high_confidence"].astype(int).to_numpy()
        if np.any(np.diff(values) < 0):
            raise RuntimeError("Post-blind product memory was lost at a later cutoff")
    return result


def select_parity_field_ids(
    blind_selection: pd.DataFrame,
    blind_predictions: pd.DataFrame,
    contract: dict[str, Any],
) -> list[str]:
    gate = contract["parity_gate"]
    arm = gate["primary_model_arm"]
    predictions = blind_predictions[blind_predictions["model_arm"] == arm].copy()
    predictions["distance_to_p95"] = (
        pd.to_numeric(predictions["calibrated_probability"], errors="coerce")
        - pd.to_numeric(predictions["frozen_p95_threshold"], errors="coerce")
    ).abs()
    chosen: set[str] = set()
    background = int(gate["per_municipality_background_fields"])
    ordered_selection = blind_selection.sort_values(["municipality_code", "development_field_id"], kind="mergesort")
    for _, part in ordered_selection.groupby("municipality_code", sort=True):
        chosen.update(part.head(background)["development_field_id"].astype(str))
    high = predictions[predictions["predicted_at_frozen_p95"].astype(bool)].sort_values(
        ["cutoff_date", "development_field_id"], kind="mergesort"
    )
    chosen.update(high.head(int(gate["high_confidence_fields"]))["development_field_id"].astype(str))
    near = predictions[predictions["distance_to_p95"].notna()].sort_values(
        ["distance_to_p95", "development_field_id", "cutoff_date"], kind="mergesort"
    )
    chosen.update(near.head(int(gate["near_threshold_fields"]))["development_field_id"].astype(str))
    no_data = predictions[predictions["data_quality_status"] == "NO_DATA"].sort_values(
        ["cutoff_date", "development_field_id"], kind="mergesort"
    )
    chosen.update(no_data.head(int(gate["no_data_fields"]))["development_field_id"].astype(str))
    maximum = int(gate["maximum_fields"])
    values = sorted(chosen)[:maximum]
    if len(values) < int(gate["minimum_fields"]):
        remaining = [value for value in ordered_selection["development_field_id"].astype(str) if value not in chosen]
        values.extend(remaining[: int(gate["minimum_fields"]) - len(values)])
        values = sorted(set(values))
    if not int(gate["minimum_fields"]) <= len(values) <= maximum:
        raise RuntimeError(f"Parity selection count {len(values)} is outside the frozen guard")
    return values


def compare_parity_predictions(
    local_predictions: pd.DataFrame,
    locked_predictions: pd.DataFrame,
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    arm = contract["parity_gate"]["primary_model_arm"]
    keys = ["development_field_id", "cutoff_date", "model_arm"]
    left = local_predictions[local_predictions["model_arm"] == arm].copy()
    right = locked_predictions[locked_predictions["model_arm"] == arm].copy()
    columns = keys + ["data_quality_status", "calibrated_probability", "predicted_at_frozen_p95"]
    joined = left[columns].merge(right[columns], on=keys, how="outer", validate="one_to_one", suffixes=("_local", "_locked"), indicator=True)
    joined["decision_agrees"] = (
        joined["_merge"].eq("both")
        & joined["predicted_at_frozen_p95_local"].fillna(False).astype(bool).eq(joined["predicted_at_frozen_p95_locked"].fillna(False).astype(bool))
    )
    joined["quality_agrees"] = (
        joined["_merge"].eq("both")
        & joined["data_quality_status_local"].astype(str).eq(joined["data_quality_status_locked"].astype(str))
    )
    joined["probability_abs_delta"] = (
        pd.to_numeric(joined["calibrated_probability_local"], errors="coerce")
        - pd.to_numeric(joined["calibrated_probability_locked"], errors="coerce")
    ).abs()
    finite = joined["probability_abs_delta"].dropna()
    decision_agreement = float(joined["decision_agrees"].mean()) if len(joined) else 0.0
    quality_agreement = float(joined["quality_agrees"].mean()) if len(joined) else 0.0
    median_delta = float(finite.median()) if len(finite) else math.inf
    p95_delta = float(finite.quantile(0.95)) if len(finite) else math.inf
    gate = contract["parity_gate"]
    passed = (
        joined["_merge"].eq("both").all()
        and decision_agreement >= float(gate["required_frozen_p95_decision_agreement"])
        and quality_agreement >= float(gate["minimum_data_quality_agreement"])
        and median_delta <= float(gate["maximum_median_absolute_probability_delta"])
        and p95_delta <= float(gate["maximum_p95_absolute_probability_delta"])
    )
    summary = {
        "schema_version": "rapskartan-local-scene-parity-v1",
        "status": "PASS" if passed else "FAIL",
        "rows": int(len(joined)),
        "fields": int(joined["development_field_id"].nunique()),
        "decision_agreement": decision_agreement,
        "data_quality_agreement": quality_agreement,
        "median_absolute_probability_delta": median_delta,
        "p95_absolute_probability_delta": p95_delta,
        "thresholds": {
            "required_frozen_p95_decision_agreement": float(gate["required_frozen_p95_decision_agreement"]),
            "minimum_data_quality_agreement": float(gate["minimum_data_quality_agreement"]),
            "maximum_median_absolute_probability_delta": float(gate["maximum_median_absolute_probability_delta"]),
            "maximum_p95_absolute_probability_delta": float(gate["maximum_p95_absolute_probability_delta"]),
        },
    }
    return joined.sort_values(keys, kind="mergesort").reset_index(drop=True), summary


def _next_stac_link(document: dict[str, Any], current_url: str) -> str:
    links = [item for item in document.get("links", []) if item.get("rel") == "next"]
    return urllib.parse.urljoin(current_url, str(links[0]["href"])) if links else ""


def _normalize_asset(asset: dict[str, Any]) -> dict[str, Any]:
    href = str(asset.get("href") or "")
    if not href.startswith("s3://"):
        raise RuntimeError(f"Scene asset is not available over S3: {href}")
    return {
        "s3_uri": href,
        "bytes": int(asset.get("file:size") or 0),
        "checksum": asset.get("file:checksum"),
        "scale": float(asset.get("raster:scale", 0.0001)),
        "offset": float(asset.get("raster:offset", 0.0)),
        "nodata": asset.get("nodata", 0),
        "proj_code": asset.get("proj:code"),
        "proj_bbox": asset.get("proj:bbox"),
        "proj_transform": asset.get("proj:transform"),
        "proj_shape": asset.get("proj:shape"),
    }


def query_scene_inventory(
    bbox_wgs84: Iterable[float],
    contract: dict[str, Any],
    source_dir: Path,
    *,
    timeout: int = 120,
) -> list[dict[str, Any]]:
    scene = contract["scene_archive"]
    params = {
        "collections": scene["collection"],
        "bbox": ",".join(f"{float(value):.8f}" for value in bbox_wgs84),
        "datetime": f"{scene['time_from']}/{scene['time_to']}",
        "limit": "100",
    }
    current = scene["stac_search_url"] + "?" + urllib.parse.urlencode(params)
    seen: set[str] = set()
    features: dict[str, dict[str, Any]] = {}
    page = 0
    while current:
        if current in seen:
            raise RuntimeError("STAC pagination loop detected")
        if page >= int(contract["resource_guards"]["maximum_stac_pages"]):
            raise RuntimeError("RESOURCE_GUARD: STAC page limit exceeded")
        seen.add(current)
        request = urllib.request.Request(current, headers={"User-Agent": "AkerSync-Rapskartan/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
        page += 1
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / f"stac_page_{page:03d}.json").write_bytes(raw)
        document = json.loads(raw.decode("utf-8"))
        for feature in document.get("features", []):
            features[str(feature["id"])] = feature
        current = _next_stac_link(document, current)
    required = {**scene["reflectance_assets"], "SCL": scene["quality_asset"]}
    inventory = []
    for item_id, feature in sorted(features.items()):
        props = feature.get("properties") or {}
        assets = feature.get("assets") or {}
        missing = sorted(asset for asset in required.values() if asset not in assets)
        if missing:
            raise RuntimeError(f"STAC item {item_id} lacks required assets: {missing}")
        when = str(props.get("datetime") or "")
        inventory.append({
            "item_id": item_id,
            "datetime": when,
            "acquisition_date": when[:10],
            "cloud_cover": float(props.get("eo:cloud_cover") or 0.0),
            "geometry": feature.get("geometry"),
            "bbox": feature.get("bbox"),
            "assets": {name: _normalize_asset(assets[key]) for name, key in required.items()},
        })
    if not inventory:
        raise RuntimeError("STAC returned no Sentinel-2 L2A scenes for the product period")
    if len(inventory) > int(contract["resource_guards"]["maximum_scene_items"]):
        raise RuntimeError(f"RESOURCE_GUARD: {len(inventory)} scene items exceed the contract")
    return sorted(inventory, key=lambda item: (item["acquisition_date"], item["cloud_cover"], item["item_id"]))


def filter_scenes_to_fields(scenes: list[dict[str, Any]], fields: Any) -> list[dict[str, Any]]:
    """Discard rectangular-bbox STAC hits that intersect no 2025 field."""
    from shapely.geometry import shape

    wgs84 = fields.to_crs(4326)
    index = wgs84.sindex
    kept = []
    for scene in scenes:
        footprint = shape(scene["geometry"])
        if len(index.query(footprint, predicate="intersects")):
            kept.append(scene)
    if not kept:
        raise RuntimeError("No Sentinel-2 scenes intersect the exact 2025 field geometry")
    return kept


def _multihash_digest(path: Path, encoded: str | None) -> bool:
    if not encoded:
        return True
    raw = bytes.fromhex(str(encoded))
    if len(raw) < 3:
        return False
    code, length, expected = raw[0], raw[1], raw[2:]
    algorithms = {0x12: "sha256", 0x16: "sha3_256"}
    if code not in algorithms or length != len(expected):
        raise RuntimeError(f"Unsupported STAC multihash code/length: {code}/{length}")
    digest = hashlib.new(algorithms[code])
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.digest() == expected


def local_asset_path(archive_root: Path, scene: dict[str, Any], band: str) -> Path:
    uri = scene["assets"][band]["s3_uri"]
    name = Path(urllib.parse.urlparse(uri).path).name
    return archive_root / "items" / scene["item_id"] / f"{band}_{name}"


def download_scene_archive(
    scenes: list[dict[str, Any]],
    archive_root: Path,
    contract: dict[str, Any],
) -> pd.DataFrame:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("boto3/botocore are required for the local Sentinel-2 scene archive") from exc
    access = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if not access or not secret:
        raise RuntimeError("BLOCKED_S3_CREDENTIALS: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are not set")
    expected_assets = len(scenes) * 11
    if expected_assets > int(contract["resource_guards"]["maximum_scene_assets"]):
        raise RuntimeError("RESOURCE_GUARD: scene asset count exceeds the product contract")
    expected_bytes = sum(int(asset["bytes"]) for scene in scenes for asset in scene["assets"].values())
    if expected_bytes > int(contract["resource_guards"]["maximum_archive_bytes"]):
        raise RuntimeError(f"RESOURCE_GUARD: projected scene archive {expected_bytes} bytes exceeds the contract")
    archive_root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(archive_root).free
    if free < int(contract["resource_guards"]["minimum_free_disk_bytes_before_download"]):
        raise RuntimeError(f"BLOCKED_DISK_SPACE: {free} free bytes are below the frozen preflight guard")
    client = boto3.client(
        "s3", endpoint_url=contract["scene_archive"]["s3_endpoint_url"],
        aws_access_key_id=access, aws_secret_access_key=secret,
        region_name="default", config=Config(signature_version="s3v4", retries={"max_attempts": 8, "mode": "adaptive"}),
    )
    rows = []
    downloads = cache_hits = 0
    for scene_number, scene in enumerate(scenes, start=1):
        for band, asset in sorted(scene["assets"].items()):
            target = local_asset_path(archive_root, scene, band)
            good = target.is_file() and (not asset["bytes"] or target.stat().st_size == int(asset["bytes"]))
            if good:
                good = _multihash_digest(target, asset.get("checksum"))
            if good:
                cache_hits += 1
                downloaded = False
            else:
                if target.exists():
                    raise RuntimeError(f"Cached scene asset is corrupt; preserve for diagnosis: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".partial")
                temporary.unlink(missing_ok=True)
                parsed = urllib.parse.urlparse(asset["s3_uri"])
                client.download_file(parsed.netloc, parsed.path.lstrip("/"), str(temporary))
                if asset["bytes"] and temporary.stat().st_size != int(asset["bytes"]):
                    raise RuntimeError(f"Downloaded scene asset size mismatch: {scene['item_id']}/{band}")
                if not _multihash_digest(temporary, asset.get("checksum")):
                    raise RuntimeError(f"Downloaded scene asset checksum mismatch: {scene['item_id']}/{band}")
                temporary.replace(target)
                downloads += 1
                downloaded = True
            rows.append({
                "item_id": scene["item_id"], "acquisition_date": scene["acquisition_date"],
                "band": band, "path": str(target.resolve()), "bytes": target.stat().st_size,
                "stac_checksum": asset.get("checksum"), "downloaded": downloaded,
            })
        if scene_number % 10 == 0 or scene_number == len(scenes):
            print(f"[SCENE-ARCHIVE] items {scene_number}/{len(scenes)} · downloaded {downloads} · cache {cache_hits}", flush=True)
    return pd.DataFrame(rows).sort_values(["acquisition_date", "item_id", "band"], kind="mergesort").reset_index(drop=True)


def _safe_ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    denominator = a + b
    return np.divide(a - b, denominator, out=np.zeros_like(a, dtype=np.float32), where=np.abs(denominator) > 1e-12)


def _metric_arrays(bands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    ndvi = _safe_ratio(bands["B08"], bands["B04"])
    ndre = _safe_ratio(bands["B8A"], bands["B05"])
    evi2 = 2.5 * (bands["B08"] - bands["B04"]) / (bands["B08"] + 2.4 * bands["B04"] + 1.0)
    gndvi = _safe_ratio(bands["B08"], bands["B03"])
    lswi = _safe_ratio(bands["B08"], bands["B11"])
    nirv = bands["B08"] * ndvi
    yellow = _safe_ratio(bands["B03"], (bands["B02"] + bands["B04"]) / 2.0)
    return {**bands, "NDVI": ndvi, "NDRE": ndre, "EVI2": evi2, "GNDVI": gndvi, "LSWI": lswi, "NIRV": nirv, "YELLOWNESS": yellow}


def field_grid(bounds: Iterable[float], resolution: int) -> tuple[Any, int, int]:
    """Build the per-field bounds grid used by the frozen Statistics API."""
    from affine import Affine

    minx, miny, maxx, maxy = [float(value) for value in bounds]
    width = max(1, int(round((maxx - minx) / resolution)))
    height = max(1, int(round((maxy - miny) / resolution)))
    transform = Affine((maxx - minx) / width, 0, minx, 0, -(maxy - miny) / height, maxy)
    return transform, width, height


def _bounds_intersect(left: Iterable[float], right: Iterable[float]) -> bool:
    aminx, aminy, amaxx, amaxy = [float(value) for value in left]
    bminx, bminy, bmaxx, bmaxy = [float(value) for value in right]
    return not (amaxx <= bminx or bmaxx <= aminx or amaxy <= bminy or bmaxy <= aminy)


def aggregate_local_scene_timeseries(
    fields: Any,
    scenes: list[dict[str, Any]],
    archive_root: Path,
    contract: dict[str, Any],
    *,
    progress_prefix: str = "LOCAL-S2",
) -> pd.DataFrame:
    """Aggregate cached L2A scenes into the frozen daily field-statistics schema."""
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.features import rasterize
        from rasterio.warp import reproject, transform_bounds
    except ImportError as exc:
        raise RuntimeError("rasterio with JPEG2000 support is required for local scene aggregation") from exc
    if fields.empty:
        return pd.DataFrame()
    projected = fields.to_crs(int(contract["scene_archive"]["target_crs_epsg"])).sort_values("development_field_id", kind="mergesort").reset_index(drop=True)
    resolution = int(contract["scene_archive"]["resolution_m"])
    valid_scl = np.array(contract["scene_archive"]["valid_scl_codes"], dtype=np.int16)
    dates = sorted({scene["acquisition_date"] for scene in scenes})
    rows: list[dict[str, Any]] = []
    for date_number, acquisition in enumerate(dates, start=1):
        day_scenes = sorted(
            [scene for scene in scenes if scene["acquisition_date"] == acquisition],
            key=lambda item: (float(item["cloud_cover"]), str(item["item_id"])),
        )
        with ExitStack() as stack:
            sources: list[tuple[dict[str, Any], dict[str, Any], tuple[float, float, float, float]]] = []
            for scene in day_scenes:
                opened: dict[str, Any] = {}
                for band in scene["assets"]:
                    opened[band] = stack.enter_context(rasterio.open(local_asset_path(archive_root, scene, band)))
                reference = opened["SCL"]
                scene_bounds = transform_bounds(
                    reference.crs, f"EPSG:{contract['scene_archive']['target_crs_epsg']}",
                    *reference.bounds, densify_pts=21,
                )
                sources.append((scene, opened, scene_bounds))
            for _, field in projected.iterrows():
                transform, width, height = field_grid(field.geometry.bounds, resolution)
                shape = (height, width)
                polygon = rasterize(
                    [(field.geometry, 1)], out_shape=shape, transform=transform,
                    fill=0, dtype="uint8", all_touched=False,
                ).astype(bool)
                owner = np.full(shape, -1, dtype=np.int16)
                scl = np.zeros(shape, dtype=np.int16)
                field_bounds = field.geometry.bounds
                for scene_index, (scene, opened, scene_bounds) in enumerate(sources):
                    if not _bounds_intersect(field_bounds, scene_bounds):
                        continue
                    values = np.zeros(shape, dtype=np.int16)
                    source = opened["SCL"]
                    reproject(
                        rasterio.band(source, 1), values,
                        src_transform=source.transform, src_crs=source.crs,
                        src_nodata=scene["assets"]["SCL"].get("nodata", 0),
                        dst_transform=transform, dst_crs=f"EPSG:{contract['scene_archive']['target_crs_epsg']}",
                        dst_nodata=0, resampling=Resampling.nearest, init_dest_nodata=True,
                    )
                    use = (owner < 0) & (values != 0)
                    owner[use] = scene_index
                    scl[use] = values[use]
                if not np.any(owner >= 0):
                    continue
                sample_count = width * height
                valid = polygon & (owner >= 0) & np.isin(scl, valid_scl)
                valid_count = int(valid.sum())
                fraction = valid_count / sample_count
                if valid_count < int(contract["scene_archive"]["minimum_valid_pixels"]):
                    status = "NO_DATA_TOO_FEW_PIXELS"
                elif fraction < float(contract["scene_archive"]["minimum_valid_pixel_fraction"]):
                    status = "LOW_COVERAGE"
                else:
                    status = "VALID"
                bands: dict[str, np.ndarray] = {}
                for band in contract["scene_archive"]["reflectance_assets"]:
                    mosaic = np.full(shape, np.nan, dtype=np.float32)
                    for scene_index, (scene, opened, scene_bounds) in enumerate(sources):
                        use = valid & (owner == scene_index)
                        if not np.any(use):
                            continue
                        values = np.zeros(shape, dtype=np.float32)
                        source = opened[band]
                        reproject(
                            rasterio.band(source, 1), values,
                            src_transform=source.transform, src_crs=source.crs,
                            src_nodata=scene["assets"][band].get("nodata", 0),
                            dst_transform=transform, dst_crs=f"EPSG:{contract['scene_archive']['target_crs_epsg']}",
                            dst_nodata=0, resampling=Resampling.bilinear, init_dest_nodata=True,
                        )
                        asset = scene["assets"][band]
                        mosaic[use] = values[use] * float(asset["scale"]) + float(asset["offset"])
                    bands[band] = mosaic
                metrics = _metric_arrays(bands)
                next_day = (date.fromisoformat(acquisition) + timedelta(days=1)).isoformat()
                row: dict[str, Any] = {
                    "development_field_id": str(field["development_field_id"]),
                    "target_year": 2025, "municipality_code": str(field["municipality_code"]),
                    "area_ha": round(float(field["area_ha"]), 6), "edge_rule": "ORIGINAL",
                    "interval_from": f"{acquisition}T00:00:00Z", "interval_to": f"{next_day}T00:00:00Z",
                    "acquisition_date": acquisition, "sample_pixels": sample_count,
                    "valid_pixels": valid_count, "valid_pixel_fraction": round(fraction, 8),
                    "data_quality_status": status,
                }
                for name in SPECTRAL_NAMES:
                    values = metrics[name][valid]
                    if status == "NO_DATA_TOO_FEW_PIXELS" or not len(values):
                        row.update({f"{name}_p10": None, f"{name}_p50": None, f"{name}_p90": None})
                    else:
                        p10, p50, p90 = np.percentile(values, [10, 50, 90])
                        row.update({f"{name}_p10": float(p10), f"{name}_p50": float(p50), f"{name}_p90": float(p90)})
                rows.append(row)
        if date_number % 5 == 0 or date_number == len(dates):
            print(f"[{progress_prefix}] acquisition dates {date_number}/{len(dates)} · rows {len(rows):,}", flush=True)
    if not rows:
        raise RuntimeError("Local Sentinel-2 scene aggregation produced no field observations")
    return pd.DataFrame(rows).sort_values(["development_field_id", "acquisition_date", "interval_from"], kind="mergesort").reset_index(drop=True)


def write_product_manifest(
    root: Path,
    relatives: Iterable[str],
    *,
    repository_head: str,
    repository_tree: str,
    contract_sha256: str,
    accepted_stopd_sha256: str,
    counts: dict[str, Any],
) -> dict[str, Any]:
    manifest = {
        "schema_version": "rapskartan-2025-full-map-manifest-v1",
        "status": "PASS",
        "created_at_utc": utc_now(),
        "repository_head": repository_head,
        "repository_tree": repository_tree,
        "contract_sha256": contract_sha256,
        "accepted_stopd_manifest_sha256": accepted_stopd_sha256,
        "counts": counts,
        "artifacts": artifact_records(root, relatives),
        "scope": {
            "full_historical_2025_map_product": True, "ground_truth_in_product": False,
            "post_blind_model_retuning": False, "threshold_retuning": False,
            "sentinel1": False, "web": False, "deployment": False, "tag": False, "merge": False,
        },
    }
    write_json(root / "full_map_manifest.json", manifest)
    return manifest
