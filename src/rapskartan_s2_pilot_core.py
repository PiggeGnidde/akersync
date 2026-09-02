#!/usr/bin/env python3
"""Leakage-safe helpers for the bounded Rapskartan Sentinel-2 datapilot.

This module contains no classifier, model fitting, threshold selection, 2025
row-level access, Sentinel-1 integration or web code.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from rapskartan_v1_discovery_core import load_official_tables, official_lookup, raw_text


TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
STATS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/process/v1"
STAC_SEARCH_URL = "https://stac.dataspace.copernicus.eu/v1/search"
CRS_UTM33 = "http://www.opengis.net/def/crs/EPSG/0/32633"
CONTRACT_REL = Path("config/rapskartan_s2_pilot_v1.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.unlink(missing_ok=True)
    temporary.replace(path)


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_REL
    contract = json.loads(path.read_text(encoding="utf-8"))
    validate_contract(contract)
    return contract


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != "rapskartan-s2-datapilot-v1":
        raise RuntimeError("Unexpected Sentinel-2 pilot contract schema")
    guard = contract.get("blind_guard") or {}
    years = [int(x) for x in guard.get("allowed_target_years", [])]
    strata_years = [int(x["target_year"]) for x in contract.get("pilot_strata", [])]
    if not years or sorted(set(years)) != sorted(set(strata_years)):
        raise RuntimeError("Pilot years and blind-guard years differ")
    if any(year >= int(guard.get("forbidden_target_year", 2025)) for year in years):
        raise RuntimeError("Pilot contract exposes the blind year")
    if int(contract.get("expected_selected_fields", 0)) < 20:
        raise RuntimeError("STOPPUNKT B requires at least 20 selected fields")
    if int(contract["expected_selected_fields"]) > int(contract["resource_guards"]["maximum_selected_fields"]):
        raise RuntimeError("Pilot field count exceeds resource guard")
    total = 0
    for item in contract["pilot_strata"]:
        total += sum(int(item[key]) for key in (
            "winter_rapeseed_fields", "winter_crop_control_fields", "spring_crop_control_fields"
        ))
    if total != int(contract["expected_selected_fields"]):
        raise RuntimeError(f"Pilot stratum counts total {total}, expected {contract['expected_selected_fields']}")
    scl = contract["cloud_mask"]
    valid = {int(x) for x in scl["valid_scl_codes"]}
    excluded = {int(x) for x in scl["excluded_scl_codes"]}
    if valid & excluded or valid | excluded != set(range(12)):
        raise RuntimeError("SCL contract must partition codes 0-11")
    forbidden = contract.get("forbidden_scope") or {}
    if not forbidden or not all(bool(value) for value in forbidden.values()):
        raise RuntimeError("Every later-phase scope must remain forbidden in the datapilot")


def contract_sha256(root: Path) -> str:
    return sha256_file(root / CONTRACT_REL)


def period_for_year(year: int, contract: dict[str, Any]) -> tuple[str, str]:
    guard = contract["blind_guard"]
    if int(year) not in {int(x) for x in guard["allowed_target_years"]}:
        raise RuntimeError(f"Target year {year} is outside the pre-2025 datapilot contract")
    start = f"{year}-{contract['temporal']['start_month_day']}T00:00:00Z"
    end = f"{year}-{contract['temporal']['end_exclusive_month_day']}T00:00:00Z"
    return start, end


def safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if abs(denominator) > 1e-12 else 0.0


def stat_evalscript(contract: dict[str, Any]) -> str:
    bands = contract["sentinel2"]["bands"]
    outputs = bands + list(contract["sentinel2"]["indices"])
    valid = ",".join(str(int(x)) for x in contract["cloud_mask"]["valid_scl_codes"])
    input_bands = bands + ["SCL", "CLD", "dataMask"]
    band_defs = json.dumps(outputs + ["CLD"], separators=(",", ":"))
    return f'''//VERSION=3
function setup(){{
  return {{
    input: [{{bands: {json.dumps(input_bands)}}}],
    output: [
      {{id:"default", bands:{band_defs}, sampleType:"FLOAT32"}},
      {{id:"dataMask", bands:1}}
    ],
    mosaicking:"{contract['sentinel2']['mosaicking']}"
  }};
}}
function ratio(a,b){{return Math.abs(a+b)>1e-12?(a-b)/(a+b):0.0;}}
function evaluatePixel(s){{
  let ndvi=ratio(s.B08,s.B04);
  let ndre=ratio(s.B8A,s.B05);
  let evi2=2.5*(s.B08-s.B04)/(s.B08+2.4*s.B04+1.0);
  let gndvi=ratio(s.B08,s.B03);
  let lswi=ratio(s.B08,s.B11);
  let nirv=s.B08*ndvi;
  let yellow=ratio(s.B03,(s.B02+s.B04)/2.0);
  let sclOK=[{valid}].indexOf(s.SCL)>=0;
  return {{
    default:[s.B02,s.B03,s.B04,s.B05,s.B06,s.B07,s.B08,s.B8A,s.B11,s.B12,ndvi,ndre,evi2,gndvi,lswi,nirv,yellow,s.CLD],
    dataMask:[s.dataMask && sclOK ? 1 : 0]
  }};
}}'''


def scl_evalscript(contract: dict[str, Any]) -> str:
    scl_defs = json.dumps([f"SCL_{code}" for code in range(12)], separators=(",", ":"))
    values = ",".join(f"s.SCL=={code}?1:0" for code in range(12))
    return f'''//VERSION=3
function setup(){{
  return {{
    input:[{{bands:["SCL","dataMask"]}}],
    output:[
      {{id:"default",bands:{scl_defs},sampleType:"FLOAT32"}},
      {{id:"dataMask",bands:1}}
    ],
    mosaicking:"{contract['sentinel2']['mosaicking']}"
  }};
}}
function evaluatePixel(s){{
  return {{default:[{values}],dataMask:[s.dataMask?1:0]}};
}}'''


def qa_evalscript(contract: dict[str, Any]) -> str:
    valid = ",".join(str(int(x)) for x in contract["cloud_mask"]["valid_scl_codes"])
    return f'''//VERSION=3
function setup(){{
  return {{input:["B02","B03","B04","SCL","dataMask"],output:{{bands:4,sampleType:"UINT8"}}}};
}}
function clamp(v){{return Math.max(0,Math.min(1,v));}}
function evaluatePixel(s){{
  if(!s.dataMask) return [0,0,0,0];
  let clear=[{valid}].indexOf(s.SCL)>=0;
  if(!clear) return [255,38,80,235];
  return [255*clamp(2.8*s.B04),255*clamp(2.8*s.B03),255*clamp(2.8*s.B02),255];
}}'''


def _bounds_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    return {"geometry": geometry, "properties": {"crs": CRS_UTM33}}


def build_stat_request(
    geometry: dict[str, Any],
    year: int,
    contract: dict[str, Any],
    *,
    scl_distribution: bool = False,
) -> dict[str, Any]:
    start, end = period_for_year(year, contract)
    evalscript = scl_evalscript(contract) if scl_distribution else stat_evalscript(contract)
    percentile_block: dict[str, Any] = {}
    if not scl_distribution:
        percentile_block = {"percentiles": {"k": contract["statistics"]["percentiles"]}}
    return {
        "input": {
            "bounds": _bounds_geometry(geometry),
            "data": [{
                "type": contract["sentinel2"]["collection"],
                "dataFilter": {
                    "timeRange": {"from": start, "to": end},
                    "mosaickingOrder": contract["sentinel2"]["mosaicking_order"],
                    "maxCloudCoverage": int(contract["sentinel2"]["max_scene_cloud_coverage_percent"]),
                },
                "processing": {
                    "upsampling": "BILINEAR",
                    "downsampling": "BILINEAR",
                    "harmonizeValues": bool(contract["sentinel2"]["harmonize_values"]),
                },
            }],
        },
        "aggregation": {
            "timeRange": {"from": start, "to": end},
            "aggregationInterval": {
                "of": contract["temporal"]["daily_aggregation_interval"],
                "lastIntervalBehavior": "SKIP",
            },
            "resx": int(contract["sentinel2"]["resolution_m"]),
            "resy": int(contract["sentinel2"]["resolution_m"]),
            "evalscript": evalscript,
        },
        "calculations": {"default": {"statistics": {"default": percentile_block}}},
    }


def build_process_request(
    geometry: dict[str, Any],
    acquisition_date: str,
    width: int,
    height: int,
    contract: dict[str, Any],
) -> dict[str, Any]:
    day = date.fromisoformat(acquisition_date)
    next_day = day + timedelta(days=1)
    return {
        "input": {
            "bounds": _bounds_geometry(geometry),
            "data": [{
                "type": contract["sentinel2"]["collection"],
                "dataFilter": {
                    "timeRange": {
                        "from": f"{day.isoformat()}T00:00:00Z",
                        "to": f"{next_day.isoformat()}T00:00:00Z",
                    },
                    "mosaickingOrder": contract["sentinel2"]["mosaicking_order"],
                    "maxCloudCoverage": 100,
                },
                "processing": {"upsampling": "BILINEAR", "downsampling": "BILINEAR", "harmonizeValues": True},
            }],
        },
        "output": {
            "width": int(width),
            "height": int(height),
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": qa_evalscript(contract),
    }


def request_key(endpoint: str, payload: dict[str, Any]) -> str:
    return sha256_bytes(stable_json({"endpoint": endpoint, "payload": payload}).encode("utf-8"))


def oauth_token(timeout: int = 60) -> str:
    client_id = os.environ.get("CDSE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("CDSE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("BLOCKED_CREDENTIALS: CDSE_CLIENT_ID/CDSE_CLIENT_SECRET are not set")
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret,
    }).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OAuth HTTP {exc.code}; verify the local Copernicus client") from exc
    token = str(parsed.get("access_token") or "")
    if not token:
        raise RuntimeError("OAuth response did not contain access_token")
    return token


@dataclass
class CacheResult:
    body: bytes
    metadata: dict[str, Any]


class ApiCache:
    def __init__(self, root: Path, token: str | None, *, offline: bool = False, request_limit: int = 140):
        self.root = root
        self.token = token
        self.offline = offline
        self.request_limit = int(request_limit)
        self.authenticated_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def _paths(self, key: str, suffix: str) -> tuple[Path, Path, Path]:
        directory = self.root / key[:2] / key[2:4]
        return (
            directory / f"{key}.request.json",
            directory / f"{key}.response{suffix}",
            directory / f"{key}.meta.json",
        )

    def fetch(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        response_suffix: str,
        accept: str,
        tries: int = 3,
    ) -> CacheResult:
        key = request_key(endpoint, payload)
        req_path, response_path, meta_path = self._paths(key, response_suffix)
        request_bytes = (stable_json(payload) + "\n").encode("utf-8")
        if req_path.exists() and response_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = response_path.read_bytes()
            if sha256_bytes(request_bytes) != meta.get("request_sha256"):
                raise RuntimeError(f"Cache request hash mismatch: {key}")
            if sha256_bytes(body) != meta.get("response_sha256"):
                raise RuntimeError(f"Cache response hash mismatch: {key}")
            self.cache_hits += 1
            return CacheResult(body, {**meta, "cache_hit": True})
        if self.offline:
            raise RuntimeError(f"OFFLINE_CACHE_MISS: {key}")
        if not self.token:
            raise RuntimeError("BLOCKED_CREDENTIALS: no OAuth token available for cache miss")
        if self.authenticated_requests >= self.request_limit:
            raise RuntimeError(f"RESOURCE_GUARD: authenticated request limit {self.request_limit} exceeded")
        last_error: Exception | None = None
        headers: dict[str, str] = {}
        body = b""
        for attempt in range(1, tries + 1):
            if self.authenticated_requests >= self.request_limit:
                raise RuntimeError(f"RESOURCE_GUARD: authenticated request limit {self.request_limit} exceeded")
            self.authenticated_requests += 1
            request = urllib.request.Request(endpoint, data=request_bytes, method="POST")
            request.add_header("Authorization", f"Bearer {self.token}")
            request.add_header("Content-Type", "application/json")
            request.add_header("Accept", accept)
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    body = response.read()
                    headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                    if response.status < 200 or response.status >= 300:
                        raise RuntimeError(f"HTTP {response.status}")
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 401 and attempt < tries:
                    self.token = oauth_token()
                elif attempt == tries:
                    raise RuntimeError(f"Copernicus request failed after {tries} attempts: HTTP {exc.code}") from exc
                time.sleep(2 * attempt)
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == tries:
                    raise RuntimeError(f"Copernicus request failed after {tries} attempts: {type(exc).__name__}") from exc
                time.sleep(2 * attempt)
        if not body:
            raise RuntimeError(f"Copernicus returned an empty response: {last_error}")
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_bytes(request_bytes)
        response_path.write_bytes(body)
        meta = {
            "schema_version": "rapskartan-s2-api-cache-v1",
            "endpoint": endpoint,
            "cache_key": key,
            "request_sha256": sha256_bytes(request_bytes),
            "response_sha256": sha256_bytes(body),
            "response_bytes": len(body),
            "content_type": headers.get("content-type"),
            "processing_units_spent": headers.get("x-processingunits-spent"),
            "created_at_utc": utc_now(),
        }
        write_json(meta_path, meta)
        self.cache_misses += 1
        return CacheResult(body, {**meta, "cache_hit": False})


def _band_stats(output: dict[str, Any], band: str) -> dict[str, Any]:
    return (((output.get("bands") or {}).get(band) or {}).get("stats") or {})


def parse_stat_response(
    body: bytes,
    contract: dict[str, Any],
    *,
    field_meta: dict[str, Any],
    edge_rule: str,
) -> list[dict[str, Any]]:
    parsed = json.loads(body.decode("utf-8"))
    if parsed.get("status") not in (None, "OK"):
        raise RuntimeError(f"Statistics API status is not OK: {parsed.get('status')}")
    bands = contract["sentinel2"]["bands"] + list(contract["sentinel2"]["indices"]) + ["CLD"]
    rows: list[dict[str, Any]] = []
    for item in parsed.get("data", []):
        interval = item.get("interval") or {}
        output = (item.get("outputs") or {}).get("default") or {}
        anchor = _band_stats(output, "B02")
        sample_count = int(anchor.get("sampleCount") or 0)
        no_data_count = int(anchor.get("noDataCount") or 0)
        valid_pixels = max(0, sample_count - no_data_count)
        valid_fraction = valid_pixels / sample_count if sample_count else 0.0
        if valid_pixels < int(contract["cloud_mask"]["minimum_valid_pixels"]):
            status = "NO_DATA_TOO_FEW_PIXELS"
        elif valid_fraction < float(contract["cloud_mask"]["minimum_valid_pixel_fraction"]):
            status = "LOW_COVERAGE"
        else:
            status = "VALID"
        row: dict[str, Any] = {
            **field_meta,
            "edge_rule": edge_rule,
            "interval_from": interval.get("from"),
            "interval_to": interval.get("to"),
            "acquisition_date": str(interval.get("from") or "")[:10],
            "sample_pixels": sample_count,
            "valid_pixels": valid_pixels,
            "valid_pixel_fraction": round(valid_fraction, 8),
            "data_quality_status": status,
        }
        for band in bands:
            stats = _band_stats(output, band)
            percentiles = stats.get("percentiles") or {}
            row[f"{band}_p10"] = percentiles.get("10.0", percentiles.get("10"))
            row[f"{band}_p50"] = percentiles.get("50.0", percentiles.get("50"))
            row[f"{band}_p90"] = percentiles.get("90.0", percentiles.get("90"))
        rows.append(row)
    return rows


def parse_scl_response(body: bytes, *, field_meta: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = json.loads(body.decode("utf-8"))
    if parsed.get("status") not in (None, "OK"):
        raise RuntimeError(f"SCL Statistics API status is not OK: {parsed.get('status')}")
    rows: list[dict[str, Any]] = []
    for item in parsed.get("data", []):
        interval = item.get("interval") or {}
        output = (item.get("outputs") or {}).get("default") or {}
        anchor = _band_stats(output, "SCL_0")
        sample_count = int(anchor.get("sampleCount") or 0)
        no_data_count = int(anchor.get("noDataCount") or 0)
        row: dict[str, Any] = {
            **field_meta,
            "interval_from": interval.get("from"),
            "interval_to": interval.get("to"),
            "acquisition_date": str(interval.get("from") or "")[:10],
            "sample_pixels": sample_count,
            "source_valid_pixels": max(0, sample_count - no_data_count),
        }
        for code in range(12):
            stats = _band_stats(output, f"SCL_{code}")
            row[f"scl_{code}_fraction"] = stats.get("mean")
        rows.append(row)
    return rows


def deterministic_positions(total: int, wanted: int) -> list[int]:
    if wanted <= 0:
        return []
    if total < wanted:
        raise RuntimeError(f"Selection group has {total} eligible fields, needs {wanted}")
    if wanted == 1:
        return [total // 2]
    positions = [round(i * (total - 1) / (wanted - 1)) for i in range(wanted)]
    if len(set(positions)) != wanted:
        raise RuntimeError("Deterministic area-rank selection produced duplicate positions")
    return positions


def _stable_tiebreak(year: int, municipality_code: str, blockid: Any, field: Any) -> str:
    raw = f"{year}|{municipality_code}|{raw_text(blockid)}|{raw_text(field)}"
    return sha256_bytes(raw.encode("utf-8"))


def select_group(frame: pd.DataFrame, wanted: int) -> pd.DataFrame:
    ordered = frame.sort_values(["area_ha", "_stable"], kind="mergesort").reset_index(drop=True)
    return ordered.iloc[deterministic_positions(len(ordered), wanted)].copy()


def classify_control_group(name: str, contract: dict[str, Any]) -> str | None:
    selection = contract["selection"]
    if name == selection["positive_crop"]:
        return "WINTER_RAPESEED"
    if name in selection["winter_crop_controls"]:
        return "WINTER_CROP_CONTROL"
    if name in selection["spring_crop_controls"]:
        return "SPRING_CROP_CONTROL"
    return None


def geometry_mapping(geometry: Any) -> dict[str, Any]:
    return json.loads(json.dumps(geometry.__geo_interface__, ensure_ascii=False))


def load_and_select_fields(root: Path, raw_root: Path, contract: dict[str, Any]) -> tuple[Any, pd.DataFrame]:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise RuntimeError("geopandas is required for the Windows Sentinel-2 datapilot") from exc
    official, _ = load_official_tables(root)
    selected_frames = []
    selection_rows: list[dict[str, Any]] = []
    for stratum in contract["pilot_strata"]:
        year = int(stratum["target_year"])
        if year >= int(contract["blind_guard"]["forbidden_target_year"]):
            raise RuntimeError("BLIND_GUARD: attempted to read target-year 2025 geometry/labels")
        municipality = str(stratum["municipality_name"])
        municipality_code = str(stratum["municipality_code"])
        safe = municipality.lower().replace(" ", "_")
        path = raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_{safe}_{year}.gpkg"
        if not path.exists():
            raise FileNotFoundError(path)
        gdf = gpd.read_file(path)
        required = {"arslager", "blockid", "skiftesbeteckning", "grdkod_mar", "grdkod_und", "geometry"}
        missing = sorted(required - set(gdf.columns))
        if missing:
            raise RuntimeError(f"{path.name}: missing pilot columns {missing}")
        if gdf.crs is None:
            raise RuntimeError(f"{path.name}: CRS is missing")
        if set(pd.to_numeric(gdf["arslager"], errors="raise").astype(int)) != {year}:
            raise RuntimeError(f"{path.name}: contains another target year")
        gdf = gdf.to_crs(3006).copy()
        valid = gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid
        gdf = gdf.loc[valid].copy()
        gdf["area_ha"] = gdf.geometry.area / 10_000.0
        gdf = gdf[
            gdf["area_ha"].between(
                float(contract["selection"]["minimum_area_ha"]),
                float(contract["selection"]["maximum_area_ha"]),
                inclusive="both",
            )
        ].copy()
        names = []
        for row in gdf.itertuples(index=False):
            found = official_lookup(official, year, row.grdkod_mar, row.grdkod_und)
            names.append(found[0] if found else None)
        gdf["official_crop_name"] = names
        gdf["pilot_group"] = [
            classify_control_group(str(name), contract) if name is not None else None
            for name in gdf["official_crop_name"]
        ]
        gdf = gdf[gdf["pilot_group"].notna()].copy()
        gdf["_stable"] = [
            _stable_tiebreak(year, municipality_code, blockid, field)
            for blockid, field in zip(gdf["blockid"], gdf["skiftesbeteckning"])
        ]
        wants = {
            "WINTER_RAPESEED": int(stratum["winter_rapeseed_fields"]),
            "WINTER_CROP_CONTROL": int(stratum["winter_crop_control_fields"]),
            "SPRING_CROP_CONTROL": int(stratum["spring_crop_control_fields"]),
        }
        pieces = []
        for group, wanted in wants.items():
            pieces.append(select_group(gdf[gdf["pilot_group"] == group], wanted))
        chosen = gpd.GeoDataFrame(pd.concat(pieces, ignore_index=True), crs=gdf.crs)
        chosen["target_year"] = year
        chosen["municipality_code"] = municipality_code
        chosen["municipality_name"] = municipality
        chosen["geography_role"] = str(stratum["geography_role"])
        chosen["pilot_field_id"] = [
            f"{year}-{municipality_code}-{raw_text(blockid)}-{raw_text(field)}"
            for blockid, field in zip(chosen["blockid"], chosen["skiftesbeteckning"])
        ]
        for row in chosen.itertuples(index=False):
            selection_rows.append({
                "pilot_field_id": row.pilot_field_id,
                "target_year": year,
                "municipality_code": municipality_code,
                "municipality_name": municipality,
                "geography_role": stratum["geography_role"],
                "pilot_group": row.pilot_group,
                "official_crop_name": row.official_crop_name,
                "crop_code_raw": raw_text(row.grdkod_mar),
                "crop_subcategory_raw": raw_text(row.grdkod_und),
                "area_ha": round(float(row.area_ha), 6),
                "source_path": str(path.resolve()),
            })
        selected_frames.append(chosen)
    selected = gpd.GeoDataFrame(pd.concat(selected_frames, ignore_index=True), crs=3006)
    selection = pd.DataFrame(selection_rows).sort_values(
        ["target_year", "municipality_code", "pilot_group", "area_ha", "pilot_field_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    if len(selection) != int(contract["expected_selected_fields"]):
        raise RuntimeError(f"Selected {len(selection)} fields, expected {contract['expected_selected_fields']}")
    if selection["pilot_field_id"].duplicated().any():
        raise RuntimeError("Pilot selection contains duplicate field identities")
    return selected, selection


def edge_geometry(field_geometry: Any, negative_buffer_m: float) -> Any | None:
    result = field_geometry if float(negative_buffer_m) == 0 else field_geometry.buffer(-float(negative_buffer_m))
    if result is None or result.is_empty or not result.is_valid or result.area <= 0:
        return None
    return result


def image_dimensions(bounds: Iterable[float], max_pixels: int) -> tuple[int, int]:
    x0, y0, x1, y1 = [float(x) for x in bounds]
    width_m, height_m = max(1.0, x1 - x0), max(1.0, y1 - y0)
    if width_m >= height_m:
        width = int(max_pixels)
        height = max(32, int(round(max_pixels * height_m / width_m)))
    else:
        height = int(max_pixels)
        width = max(32, int(round(max_pixels * width_m / height_m)))
    return width, height


def cache_inventory(root: Path) -> dict[str, Any]:
    files = sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []
    records = [f"{path.relative_to(root).as_posix()}|{path.stat().st_size}|{sha256_file(path)}" for path in files]
    return {
        "root": str(root.resolve()),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "inventory_sha256": sha256_bytes("\n".join(records).encode("utf-8")),
    }


def artifact_records(root: Path, relative_paths: Iterable[str]) -> list[dict[str, Any]]:
    records = []
    for name in sorted(relative_paths):
        path = root / name
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"Missing manifest artifact: {name}")
        records.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def dataframe_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.10g",
        na_rep="",
    ).encode("utf-8")


def write_dataframe(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dataframe_csv_bytes(frame)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(body)
    path.unlink(missing_ok=True)
    temporary.replace(path)
    return sha256_bytes(body)


def public_stac_inventory(
    bbox_wgs84: Iterable[float],
    year: int,
    contract: dict[str, Any],
    *,
    timeout: int = 120,
) -> dict[str, Any]:
    start, end = period_for_year(year, contract)
    params = {
        "collections": contract["sentinel2"]["collection"],
        "bbox": ",".join(f"{float(value):.8f}" for value in bbox_wgs84),
        "datetime": f"{start}/{end}",
        "limit": "100",
    }
    url = STAC_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    current_url = url
    seen_urls: set[str] = set()
    raw_hashes: list[str] = []
    item_by_id: dict[str, dict[str, Any]] = {}
    pages = 0
    while current_url:
        if current_url in seen_urls:
            raise RuntimeError("Public STAC pagination loop detected")
        if pages >= 10:
            raise RuntimeError("Public STAC pagination exceeded the bounded 10-page guard")
        seen_urls.add(current_url)
        request = urllib.request.Request(current_url, headers={"User-Agent": "AkerSync-Rapskartan/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Public STAC request failed: {type(exc).__name__}") from exc
        pages += 1
        raw_hashes.append(sha256_bytes(raw))
        parsed = json.loads(raw.decode("utf-8"))
        for feature in parsed.get("features") or []:
            props = feature.get("properties") or {}
            item = {
                "id": feature.get("id"),
                "datetime": props.get("datetime"),
                "eo_cloud_cover": props.get("eo:cloud_cover"),
                "platform": props.get("platform"),
                "constellation": props.get("constellation"),
            }
            item_by_id[str(item["id"])] = item
        next_links = [link for link in parsed.get("links") or [] if link.get("rel") == "next"]
        current_url = urllib.parse.urljoin(current_url, str(next_links[0]["href"])) if next_links else ""
    items = sorted(item_by_id.values(), key=lambda item: (str(item.get("datetime")), str(item.get("id"))))
    if not items:
        raise RuntimeError(f"Public STAC returned no Sentinel-2 L2A items for {year}")
    return {
        "schema_version": "rapskartan-s2-stac-inventory-v1",
        "collection": contract["sentinel2"]["collection"],
        "target_year": int(year),
        "bbox_wgs84": [round(float(value), 8) for value in bbox_wgs84],
        "time_range": {"from": start, "to": end},
        "query_sha256": sha256_bytes(url.encode("utf-8")),
        "response_pages": pages,
        "raw_response_inventory_sha256": sha256_bytes("\n".join(raw_hashes).encode("utf-8")),
        "returned_items": len(items),
        "items": items,
        "pagination_note": "All advertised STAC next links followed, bounded by a 10-page guard.",
    }
