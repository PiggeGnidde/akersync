#!/usr/bin/env python3
"""Discovery-only helpers for Rapskartan Skåne V1.

This module deliberately contains no feature engineering, classifier, threshold,
calibration or 2025 row-level export.  The 2025 crop label is only aggregated for
the STOPPUNKT A inventory required by the implementation contract.
"""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SCHEMA_VERSION = "rapskartan-skane-v1-discovery-v1"
FEATURE_BRANCH = "feature/rapskartan-skane-v1a"
UPSTREAM_TAG = "akernorm-v1.0"
UPSTREAM_TAG_OBJECT = "c7f8022f13ef1fdc4560ce906e9a10c467f15c0f"
UPSTREAM_COMMIT = "c859a69de51a104d10f87906d4d050a34222bbb4"
UPSTREAM_TREE = "81667aa78205a186a1fca6bd3d6386bc504c0002"
EXPECTED_CURRENT_FIELDS = 128_636
EXPECTED_HISTORY_ROWS = 1_414_996
EXPECTED_HISTORY_SHA256 = "05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf"
EXPECTED_CURRENT_GEOMETRY_SHA256 = "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706"

DICT_REL = Path("data/reference/akerminne_crop_codes_official")
HISTORY_NAME = "akerminne_2015_2025_selected.csv.gz"
MUNICIPALITIES_REL = Path("config/akerminne_skane_municipalities.json")

STAC_COLLECTION_URL = "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a"
STAC_SEARCH_URL = "https://stac.dataspace.copernicus.eu/v1/search"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/process/v1"
SMOKE_BBOX = [13.17, 55.69, 13.18, 55.70]
SMOKE_FROM = "2024-04-01T00:00:00Z"
SMOKE_TO = "2024-04-30T23:59:59Z"

CUTOFF_MONTH_DAYS = [
    (3, 15), (3, 31), (4, 10), (4, 20), (4, 30),
    (5, 10), (5, 20), (5, 31), (6, 10),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def raw_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def repository_snapshot(root: Path) -> dict[str, Any]:
    tag_type = _git(root, "cat-file", "-t", UPSTREAM_TAG)
    tag_object = _git(root, "rev-parse", UPSTREAM_TAG)
    peeled = _git(root, "rev-parse", f"{UPSTREAM_TAG}^{{}}")
    return {
        "schema_version": SCHEMA_VERSION,
        "branch": _git(root, "branch", "--show-current"),
        "head": _git(root, "rev-parse", "HEAD"),
        "head_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "working_tree_clean": not bool(_git(root, "status", "--short")),
        "upstream_tag": UPSTREAM_TAG,
        "upstream_tag_type": tag_type,
        "upstream_tag_object": tag_object,
        "upstream_dereferenced_commit": peeled,
        "upstream_is_ancestor": subprocess.run(
            ["git", "merge-base", "--is-ancestor", peeled, "HEAD"], cwd=root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0,
        "satellite_path_hits": satellite_code_inventory(root),
    }


def verify_repository_snapshot(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    checks = {
        "branch": FEATURE_BRANCH,
        "upstream_tag_type": "tag",
        "upstream_tag_object": UPSTREAM_TAG_OBJECT,
        "upstream_dereferenced_commit": UPSTREAM_COMMIT,
    }
    for key, expected in checks.items():
        if snapshot.get(key) != expected:
            errors.append(f"{key}: expected {expected}, got {snapshot.get(key)}")
    if not snapshot.get("working_tree_clean"):
        errors.append("working tree is not clean")
    if not snapshot.get("upstream_is_ancestor"):
        errors.append("akernorm-v1.0 is not an ancestor of feature HEAD")
    return errors


def satellite_code_inventory(root: Path) -> list[str]:
    """Return real satellite implementation paths, excluding guardrail prose."""
    # Plain "Sentinel-2" occurs in older negative guardrails.  These tokens point
    # to executable integrations, provider URLs or implementation identifiers.
    needles = ("sentinelhub", "sh.dataspace", "stac.dataspace", "copernicusdataspace")
    hits: list[str] = []
    allowed_suffixes = {".py", ".js", ".ts", ".bat", ".ps1", ".json", ".yaml", ".yml"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
            continue
        if any(part in {".git", "dist", "data"} for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix().lower()
        if "rapskartan_v1" in relative or path.name.startswith(("RUN_RAPSKARTAN", "VERIFY_RAPSKARTAN")):
            continue
        if "sentinel" in path.name.lower() or "satellite" in path.name.lower():
            hits.append(path.relative_to(root).as_posix())
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if any(needle in text for needle in needles):
            hits.append(path.relative_to(root).as_posix())
    return hits


def load_official_tables(root: Path) -> tuple[dict[int, dict[tuple[str | None, str | None], tuple[str, str | None]]], dict[str, Any]]:
    directory = root / DICT_REL
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    years = list(range(2015, 2026))
    if sorted(map(int, manifest.get("years", {}))) != years:
        raise RuntimeError("Official crop dictionary must contain exactly 2015-2025")
    tables: dict[int, dict[tuple[str | None, str | None], tuple[str, str | None]]] = {}
    verified: dict[str, Any] = {}
    for year in years:
        meta = manifest["years"][str(year)]
        path = directory / meta["payload_file"]
        raw = gzip.decompress(base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True))
        digest = sha256_bytes(raw)
        if digest != meta["normalized_sha256"]:
            raise RuntimeError(f"{year}: official crop dictionary SHA256 mismatch")
        frame = pd.read_csv(pd.io.common.BytesIO(raw), dtype=str, encoding="utf-8-sig")
        if len(frame) != int(meta["normalized_rows"]):
            raise RuntimeError(f"{year}: official crop dictionary row mismatch")
        table: dict[tuple[str | None, str | None], tuple[str, str | None]] = {}
        for row in frame.itertuples(index=False):
            code, sub = raw_text(row.crop_code_raw), raw_text(row.crop_subcategory_raw)
            name, group = raw_text(row.crop_name), raw_text(row.crop_group)
            if code is None or name is None:
                continue
            old = table.get((code, sub))
            if old is not None and old[0] != name:
                raise RuntimeError(f"{year}: conflicting official crop mapping {(code, sub)}")
            table[(code, sub)] = (name, group)
        tables[year] = table
        verified[str(year)] = {
            "normalized_rows": len(frame), "keys": len(table), "normalized_sha256": digest,
            "source_filename": meta["source_filename"], "source_sha256": meta["source_sha256"],
        }
    return tables, {"manifest": manifest, "verified": verified}


def official_lookup(tables: dict, year: int, code: Any, subcategory: Any) -> tuple[str, str | None] | None:
    c, s = raw_text(code), raw_text(subcategory)
    table = tables.get(int(year), {})
    if (c, s) in table:
        return table[(c, s)]
    if s is not None and (c, None) in table:
        return table[(c, None)]
    return None


def crop_code_contract(root: Path) -> dict[str, Any]:
    tables, meta = load_official_tables(root)
    mappings: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for year in sorted(tables):
        for (code, sub), (name, group) in sorted(tables[year].items(), key=lambda x: ((x[0][0] or ""), (x[0][1] or ""))):
            rec = {"year": year, "crop_code_raw": code, "crop_subcategory_raw": sub, "official_name": name, "official_group": group}
            if name == "Raps (höst)":
                mappings.append(rec)
            elif name in {"Raps (vår)", "Högerukaraps"}:
                exclusions.append(rec)
    by_year = {year: [(x["crop_code_raw"], x["crop_subcategory_raw"]) for x in mappings if x["year"] == year] for year in range(2015, 2026)}
    errors = []
    for year, pairs in by_year.items():
        if not pairs:
            errors.append(f"{year}: no official mapping for Raps (höst)")
    if official_lookup(tables, 2025, "20", None) != ("Raps (höst)", None):
        errors.append("2025 anchor 20 -> Raps (höst) failed")
    if official_lookup(tables, 2025, "80", "20") != ("Raps (höst)", None):
        errors.append("2025 anchor 80/20 -> Raps (höst) failed")
    return {
        "schema_version": "rapskartan-crop-code-contract-v1",
        "status": "PASS" if not errors else "BLOCKED",
        "target": {"binary_positive": "Raps (höst)", "binary_negative": "all other official annual crop mappings"},
        "canonical_product_code": 20,
        "lookup_contract": "Exact same-year (crop_code_raw, crop_subcategory_raw), then same-year main-code fallback only; cross-year fallback forbidden.",
        "positive_mappings": mappings,
        "explicit_non_positive_rapeseed_mappings": exclusions,
        "dictionary": {
            "schema_version": meta["manifest"]["schema_version"],
            "source": meta["manifest"]["source"],
            "received_date": meta["manifest"]["received_date"],
            "total_normalized_rows": meta["manifest"]["total_normalized_rows"],
            "years": meta["verified"],
        },
        "ground_truth_rules": {
            "2025_use": "aggregate discovery inventory and later locked blind evaluation only",
            "row_level_2025_export_at_stop_a": False,
            "eligible_status_for_harmonized_inventory": "SINGLE_CROP",
            "historical_training_geometry": "year-specific official field geometry; final eligibility pending complete Windows inventory",
        },
        "errors": errors,
    }


def summarize_ground_truth_frame(root: Path, history: pd.DataFrame, *, enforce_frozen_dimensions: bool = True) -> pd.DataFrame:
    required = {"current_field_id", "history_year", "current_area_m2", "dominant_crop_code_raw", "dominant_crop_name", "status"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise RuntimeError(f"Frozen history lacks required columns: {missing}")
    history = history.copy()
    if enforce_frozen_dimensions and len(history) != EXPECTED_HISTORY_ROWS:
        raise RuntimeError(f"Frozen history rows: expected {EXPECTED_HISTORY_ROWS}, got {len(history)}")
    if "dominant_crop_subcategory_raw" not in history.columns:
        history["dominant_crop_subcategory_raw"] = None
    history["history_year"] = pd.to_numeric(history["history_year"], errors="raise").astype(int)
    history["current_area_m2"] = pd.to_numeric(history["current_area_m2"], errors="coerce")
    tables, _ = load_official_tables(root)
    official_names: list[str | None] = []
    for row in history.itertuples(index=False):
        found = official_lookup(tables, int(row.history_year), row.dominant_crop_code_raw, row.dominant_crop_subcategory_raw)
        official_names.append(found[0] if found else None)
    history["_official_name"] = official_names
    history["_is_positive"] = history["status"].eq("SINGLE_CROP") & history["_official_name"].eq("Raps (höst)")
    history["_raw_pair"] = [
        f"{raw_text(c) or '<NULL>'}/{raw_text(s) or '<NULL>'}"
        for c, s in zip(history["dominant_crop_code_raw"], history["dominant_crop_subcategory_raw"])
    ]
    rows: list[dict[str, Any]] = []
    for year, group in history.groupby("history_year", sort=True):
        positive = group[group["_is_positive"]]
        pairs = sorted(positive["_raw_pair"].dropna().astype(str).unique().tolist())
        crosscheck = group["_official_name"].fillna("<UNKNOWN>").eq(group["dominant_crop_name"].fillna("<UNKNOWN>"))
        rows.append({
            "target_year": int(year),
            "field_rows": int(len(group)),
            "unique_current_reference_fields": int(group["current_field_id"].nunique()),
            "single_crop_rows": int(group["status"].eq("SINGLE_CROP").sum()),
            "winter_rapeseed_fields": int(len(positive)),
            "winter_rapeseed_area_ha": round(float(positive["current_area_m2"].sum()) / 10_000.0, 6),
            "positive_raw_code_pairs": ";".join(pairs),
            "official_name_crosscheck": "PASS" if bool(crosscheck.all()) else "MISMATCH",
            "geometry_basis": "2025_REFERENCE_HARMONIZED" if int(year) < 2025 else "2025_EXACT_REFERENCE",
            "label_access_scope": "AGGREGATE_DISCOVERY_ONLY" if int(year) == 2025 else "DEVELOPMENT_INVENTORY",
        })
    inventory = pd.DataFrame(rows)
    if enforce_frozen_dimensions and inventory["target_year"].tolist() != list(range(2015, 2026)):
        raise RuntimeError("Frozen history must contain exactly 2015-2025")
    if enforce_frozen_dimensions and int(inventory.loc[inventory.target_year == 2025, "unique_current_reference_fields"].iloc[0]) != EXPECTED_CURRENT_FIELDS:
        raise RuntimeError("2025 current-field count mismatch")
    if (inventory["official_name_crosscheck"] != "PASS").any():
        raise RuntimeError("Frozen crop names differ from verified annual dictionaries")
    return inventory


def inventory_ground_truth(root: Path, input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    history_path = input_dir / HISTORY_NAME
    if not history_path.exists():
        raise FileNotFoundError(history_path)
    history_sha = sha256_file(history_path)
    if history_sha != EXPECTED_HISTORY_SHA256:
        raise RuntimeError(f"Frozen history SHA256 mismatch: {history_sha}")
    columns = pd.read_csv(history_path, nrows=0).columns.tolist()
    required = {"current_field_id", "history_year", "current_area_m2", "dominant_crop_code_raw", "dominant_crop_name", "status"}
    missing = sorted(required - set(columns))
    if missing:
        raise RuntimeError(f"Frozen history lacks required columns: {missing}")
    usecols = sorted(required | ({"dominant_crop_subcategory_raw"} & set(columns)))
    history = pd.read_csv(history_path, usecols=usecols, low_memory=False, dtype={"current_field_id": str})
    inventory = summarize_ground_truth_frame(root, history, enforce_frozen_dimensions=True)
    return inventory, {
        "path": str(history_path.resolve()), "sha256": history_sha, "rows": len(history),
        "columns_read": usecols, "contains_row_level_2025_output": False,
    }


def inventory_geometry(root: Path, raw_root: Path, local_paths: Path) -> dict[str, Any]:
    cfg = json.loads(local_paths.read_text(encoding="utf-8-sig"))
    current = Path(str(cfg.get("skiften") or ""))
    if not current.exists():
        raise FileNotFoundError(f"2025 field geometry from local_paths.json: {current}")
    current_sha = sha256_file(current)
    municipalities_doc = json.loads((root / MUNICIPALITIES_REL).read_text(encoding="utf-8"))
    municipalities = municipalities_doc["municipalities"]
    year_rows = []
    for year in range(2015, 2025):
        expected: list[Path] = []
        for item in municipalities:
            safe = str(item["name"]).lower().replace(" ", "_")
            expected.append(raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_{safe}_{year}.gpkg")
        existing = [path for path in expected if path.exists()]
        missing = [path.name for path in expected if not path.exists()]
        records = [f"{path.name}|{path.stat().st_size}" for path in existing]
        year_rows.append({
            "year": year, "expected_municipality_files": len(expected), "existing_municipality_files": len(existing),
            "total_bytes": sum(path.stat().st_size for path in existing), "complete": len(existing) == len(expected),
            "missing_files": missing,
            "path_size_inventory_sha256": sha256_bytes("\n".join(sorted(records)).encode("utf-8")),
        })
    complete_years = [row["year"] for row in year_rows if row["complete"]]
    return {
        "schema_version": "rapskartan-geometry-lineage-v1",
        "current_2025": {
            "path": str(current.resolve()), "sha256": current_sha,
            "expected_sha256": EXPECTED_CURRENT_GEOMETRY_SHA256,
            "hash_status": "PASS" if current_sha == EXPECTED_CURRENT_GEOMETRY_SHA256 else "MISMATCH",
            "field_identity_count": EXPECTED_CURRENT_FIELDS,
            "lineage": "Exact 2025 Jordbruksverket field layer used by frozen ÅkerMinne/ÅkerNorm.",
            "blind_guard": "Only geometry/identity columns may be projected for 2025 model input; crop attributes remain behind the blind-label gate.",
        },
        "historical_year_specific": year_rows,
        "complete_years": complete_years,
        "development_geometry_candidate_years": complete_years,
        "akerminne_harmonization": "ÅkerMinne 2015-2024 maps historical polygons to fixed 2025 reference fields; those harmonized shapes are not accepted as year-specific satellite training geometry.",
        "classification_basis_proposal": "Use each development year's official field geometry and same-year crop label; use exact 2025 field geometry for blind predictions with crop columns projected out.",
        "split_merge_rule": "Train/evaluate on the field definition of each target year. ÅkerMinne split/merge mapping is prior-only metadata, never a replacement geometry for satellite labels.",
    }


def cutoff_contract() -> dict[str, Any]:
    return {
        "schema_version": "rapskartan-temporal-cutoff-contract-v1",
        "status": "DISCOVERY_FROZEN_BEFORE_2025_ROW_LEVEL_LABEL_ACCESS",
        "calendar_rule": "The same month/day grid is applied independently to every target year.",
        "cutoff_month_days": [{"month": m, "day": d, "label_sv": f"{d:02d}-{m:02d}"} for m, d in CUTOFF_MONTH_DAYS],
        "blind_year_dates": [f"2025-{m:02d}-{d:02d}" for m, d in CUTOFF_MONTH_DAYS],
        "causal_rule": "Every acquisition used by a prediction must have acquisition_time <= prediction_cutoff_date 23:59:59Z.",
        "reporting_fields_required_later": [
            "prediction_cutoff_date", "latest_usable_acquisition", "usable_observation_count",
            "days_since_latest_observation", "cloud_free_pixel_coverage", "sensor_passes",
        ],
        "not_frozen_at_stop_a": ["feature set", "cloud mask details", "edge buffer", "model", "threshold", "calibration"],
        "change_control": "Any grid change after this commit creates a new version and cannot use 2025 labels as evidence.",
    }


def _http_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 45) -> tuple[Any, bytes, dict[str, str]]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")), raw, {k.lower(): v for k, v in response.headers.items()}


def sentinel_stac_smoke(source_dir: Path) -> dict[str, Any]:
    source_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "status": "BLOCKED", "collection_url": STAC_COLLECTION_URL, "search_url": STAC_SEARCH_URL,
        "bbox": SMOKE_BBOX, "datetime": f"{SMOKE_FROM}/{SMOKE_TO}", "ground_truth_selected_aoi": False,
    }
    try:
        collection, collection_raw, _ = _http_json(STAC_COLLECTION_URL)
        query = urllib.parse.urlencode({
            "collections": "sentinel-2-l2a", "bbox": ",".join(map(str, SMOKE_BBOX)),
            "datetime": f"{SMOKE_FROM}/{SMOKE_TO}", "limit": "1",
        })
        search, search_raw, _ = _http_json(f"{STAC_SEARCH_URL}?{query}")
        features = search.get("features") or []
        if collection.get("id") != "sentinel-2-l2a" or not features:
            raise RuntimeError("STAC did not return sentinel-2-l2a metadata and at least one item")
        item = features[0]
        safe = {
            "type": search.get("type"), "features": [{
                "id": item.get("id"), "collection": item.get("collection"),
                "bbox": item.get("bbox"), "properties": {
                    "datetime": (item.get("properties") or {}).get("datetime"),
                    "eo:cloud_cover": (item.get("properties") or {}).get("eo:cloud_cover"),
                },
            }], "context": search.get("context"), "numberMatched": search.get("numberMatched"),
        }
        write_json(source_dir / "sentinel2_stac_search_smoke.json", safe)
        result.update({
            "status": "PASS", "collection_id": collection.get("id"), "collection_title": collection.get("title"),
            "collection_raw_sha256": sha256_bytes(collection_raw), "search_raw_sha256": sha256_bytes(search_raw),
            "returned_items": len(features), "first_item_id": item.get("id"),
            "first_item_datetime": (item.get("properties") or {}).get("datetime"),
            "matched": (search.get("context") or {}).get("matched", search.get("numberMatched")),
            "stored_response": "source/sentinel2_stac_search_smoke.json",
        })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _process_payload() -> dict[str, Any]:
    evalscript = """//VERSION=3
function setup(){return{input:[\"B04\",\"B08\",\"SCL\",\"dataMask\"],output:{bands:4,sampleType:\"FLOAT32\"}}}
function evaluatePixel(s){return[s.B04,s.B08,s.SCL,s.dataMask]}
"""
    return {
        "input": {"bounds": {"bbox": SMOKE_BBOX, "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
                  "data": [{"type": "sentinel-2-l2a", "dataFilter": {"timeRange": {"from": SMOKE_FROM, "to": SMOKE_TO}, "mosaickingOrder": "leastCC", "maxCloudCoverage": 80}}]},
        "output": {"width": 32, "height": 32, "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": evalscript,
    }


def sentinel_process_smoke() -> dict[str, Any]:
    client_id = os.environ.get("CDSE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("CDSE_CLIENT_SECRET", "").strip()
    payload = _process_payload()
    result: dict[str, Any] = {
        "status": "BLOCKED_CREDENTIALS", "token_url": TOKEN_URL, "process_url": PROCESS_URL,
        "credential_environment_variables": ["CDSE_CLIENT_ID", "CDSE_CLIENT_SECRET"],
        "credentials_logged": False, "request_sha256": sha256_bytes(stable_json(payload).encode("utf-8")),
        "bbox": SMOKE_BBOX, "datetime": f"{SMOKE_FROM}/{SMOKE_TO}", "width": 32, "height": 32,
        "bands": ["B04", "B08", "SCL", "dataMask"], "ground_truth_selected_aoi": False,
    }
    if not client_id or not client_secret:
        result["error"] = "Set both CDSE_CLIENT_ID and CDSE_CLIENT_SECRET locally; never return their values in logs or chat."
        return result
    try:
        token_body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}).encode("utf-8")
        token_doc, _, _ = _http_json(TOKEN_URL, data=token_body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        token = str(token_doc.get("access_token") or "")
        if not token:
            raise RuntimeError("OAuth response lacks access_token")
        request = urllib.request.Request(
            PROCESS_URL, data=stable_json(payload).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "image/tiff"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
            headers = {k.lower(): v for k, v in response.headers.items()}
        if len(raw) < 64 or not (raw.startswith(b"II*\x00") or raw.startswith(b"MM\x00*")):
            raise RuntimeError("Process API response is not a non-empty TIFF")
        result.update({
            "status": "PASS", "response_bytes": len(raw), "response_sha256": sha256_bytes(raw),
            "content_type": headers.get("content-type"), "processing_units_spent": headers.get("x-processingunits-spent"),
            "pixel_payload_persisted": False,
        })
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        result.update({"status": "BLOCKED_API", "error": f"HTTP {exc.code}: {body}"})
    except Exception as exc:
        result.update({"status": "BLOCKED_API", "error": f"{type(exc).__name__}: {exc}"})
    return result


def storage_estimate() -> dict[str, Any]:
    area_km2 = 11_027
    pixels_10m = int(area_km2 * 1_000_000 / 100)
    bytes_per_pixel = 22  # ten uint16 reflectance bands + SCL + dataMask
    bytes_per_observation = pixels_10m * bytes_per_pixel
    observations_per_spring = 24
    years = 7
    raw = bytes_per_observation * observations_per_spring * years
    return {
        "status": "PLANNING_ESTIMATE_NOT_ALLOCATION",
        "assumptions": {
            "skane_area_km2": area_km2, "common_grid_m": 10, "reflectance_bands": 10,
            "quality_layers": ["SCL", "dataMask"], "bytes_per_common_grid_pixel": bytes_per_pixel,
            "candidate_spring_observations_per_year": observations_per_spring, "candidate_development_years": years,
        },
        "uncompressed_full_scene_equivalent_gib_per_observation": round(bytes_per_observation / 2**30, 2),
        "uncompressed_seven_year_upper_planning_gib": round(raw / 2**30, 1),
        "recommended_source_cache_envelope_gib": [200, 800],
        "recommended_field_aggregate_envelope_gib": [1, 5],
        "pilot_budget": {"area": "two small municipalities or <=500 fields", "source_cache_gib": [2, 10], "api_requests": "bounded and logged"},
        "cache_contract": {
            "root": r"C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a",
            "layout": "provider/collection/target_year/acquisition_date/request_sha256",
            "immutable_keys": ["provider", "collection", "bbox_or_geometry_hash", "time_range", "bands", "processing_parameters", "evalscript_sha256"],
            "required_provenance": ["request.json", "response_headers.json", "response_sha256", "acquisition timestamps", "API endpoint", "retrieved_at_utc"],
            "secret_storage": "Environment variables only; never manifest, cache, log or Git.",
        },
        "official_general_user_quota_snapshot": {
            "sentinel_hub_requests_per_month": 10_000, "sentinel_hub_requests_per_minute": 300,
            "processing_units_per_month": 10_000, "processing_units_per_minute": 300,
            "source": "https://documentation.dataspace.copernicus.eu/Quotas.html",
            "note": "Verify again before the data pilot because quotas can change.",
        },
    }


def artifact_records(root: Path, names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for name in names:
        path = root / name
        rows.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def write_inventory_csv(path: Path, frame: pd.DataFrame) -> None:
    forbidden = {"current_field_id", "field_id", "geometry", "wkt", "geom"}
    if forbidden & set(frame.columns):
        raise RuntimeError("Aggregate ground-truth inventory contains forbidden row-level columns")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
