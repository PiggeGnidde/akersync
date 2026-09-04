"""Bounded reference-pixel requests. No changes to production processing."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import rasterio
from shapely.geometry import shape

from rapskartan_map_product_core import field_grid, sha256_file
from rapskartan_s2_pilot_core import (
    CRS_UTM33, PROCESS_URL, TOKEN_URL, sha256_bytes, stable_json, stat_evalscript,
)

LIMIT = 10
MAX_TILES = 8
MAX_PIXELS = 100_000
MAX_RESPONSE_BYTES = 64 * 2**20
RAW_BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12", "SCL", "CLD", "dataMask"]
PRIMARY_BANDS = RAW_BANDS[:10] + ["NDVI", "NDRE", "EVI2", "GNDVI", "LSWI", "NIRV", "YELLOWNESS", "CLD", "SCL", "input_dataMask", "valid_mask"]


def scripts(frozen):
    # Reuse the actual frozen formulas, including cloud mask and CLD input.
    original = stat_evalscript(frozen)
    primary = original.replace("function setup()", "function frozenSetup()").replace("function evaluatePixel(s)", "function frozenPixel(s)")
    primary += '\nfunction setup(){return {input:[{bands:' + json.dumps(RAW_BANDS) + '}],output:{id:"default",bands:21,sampleType:"FLOAT32"},mosaicking:"SIMPLE"};}\n'
    primary += 'function evaluatePixel(s){let r=frozenPixel(s);return r.default.concat([s.SCL,s.dataMask,r.dataMask[0]]);}\n'
    primary += 'function updateOutputMetadata(scenes,inputMetadata,outputMetadata){outputMetadata.userData={mode:"SIMPLE",serviceVersion:inputMetadata.serviceVersion};}\n'
    tiles = '//VERSION=3\n'
    tiles += 'const N=' + str(MAX_TILES) + '; const bands=' + json.dumps(RAW_BANDS) + ';\n'
    tiles += 'function setup(){return {input:[{bands:bands}],output:{id:"default",bands:N*bands.length,sampleType:"FLOAT32"},mosaicking:"TILE"};}\n'
    tiles += 'function preProcessScenes(c){if(c.scenes.tiles.length>N)throw new Error("PIXEL_REFERENCE_TILE_LIMIT");return c;}\n'
    tiles += 'function evaluatePixel(samples){if(samples.length>N)throw new Error("PIXEL_REFERENCE_TILE_LIMIT");let v=[];for(let i=0;i<N;i++){for(let b of bands){v.push(i<samples.length?samples[i][b]:0);}}return v;}\n'
    tiles += 'function updateOutputMetadata(scenes,inputMetadata,outputMetadata){outputMetadata.userData={mode:"TILE",serviceVersion:inputMetadata.serviceVersion,tiles:scenes.tiles.map((s,i)=>({slot:i,date:s.date,cloudCoverage:s.cloudCoverage,dataPath:s.dataPath,shId:s.shId,dataGeometry:s.dataGeometry,dataEnvelope:s.dataEnvelope}))};}\n'
    return primary, tiles


def build_plan(cases, geometries, frozen):
    if not 1 <= len(cases) <= 5:
        raise RuntimeError("Reference requests require one to five pixel cases")
    primary, tiles = scripts(frozen)
    plan = []
    for case in cases:
        case_id = case["case_id"]
        if case_id not in {f"case_{i:02d}" for i in range(1, 6)}:
            raise RuntimeError("Unexpected case identifier")
        geometry = geometries[case_id]
        if geometry["crs"] != "EPSG:32633":
            raise RuntimeError("Reference geometry CRS must be EPSG:32633")
        polygon = shape(geometry["geometry"])
        if polygon.is_empty or not polygon.is_valid:
            raise RuntimeError("Invalid reference polygon")
        transform, width, height = field_grid(polygon.bounds, int(frozen["sentinel2"]["resolution_m"]))
        if width*height > MAX_PIXELS:
            raise RuntimeError("Reference image exceeds the 100000-pixel guard")
        day = date.fromisoformat(case["acquisition_date"])
        if not date(2025, 3, 1) <= day < date(2025, 6, 11):
            raise RuntimeError("Reference date is outside the frozen period")
        for mode, script in (("simple", primary), ("tiles", tiles)):
            payload = {
                "input": {"bounds": {"geometry": geometry["geometry"], "properties": {"crs": CRS_UTM33}},
                          "data": [{"type": frozen["sentinel2"]["collection"],
                                    "dataFilter": {"timeRange": {"from": day.isoformat()+"T00:00:00Z", "to": (day+timedelta(days=1)).isoformat()+"T00:00:00Z"},
                                                   "mosaickingOrder": frozen["sentinel2"]["mosaicking_order"],
                                                   "maxCloudCoverage": int(frozen["sentinel2"]["max_scene_cloud_coverage_percent"])},
                                    "processing": {"upsampling": "BILINEAR", "downsampling": "BILINEAR", "harmonizeValues": bool(frozen["sentinel2"]["harmonize_values"])}}]},
                "output": {"width": width, "height": height,
                           "responses": [{"identifier": "default", "format": {"type": "image/tiff"}},
                                         {"identifier": "userdata", "format": {"type": "application/json"}}]},
                "evalscript": script,
            }
            plan.append({"id": f"{case_id}_{mode}", "case_id": case_id, "mode": mode, "endpoint": PROCESS_URL,
                         "payload": payload, "expected_transform": list(transform)[:6],
                         "bands": PRIMARY_BANDS if mode == "simple" else [f"tile_{i}_{b}" for i in range(MAX_TILES) for b in RAW_BANDS]})
    if len({r["id"] for r in plan}) != len(plan):
        raise RuntimeError("Duplicate reference requests")
    return plan


def atomic_json(path: Path, value):
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(stable_json(value)+"\n", encoding="utf-8")
    temporary.replace(path)


@contextlib.contextmanager
def run_lock(folder: Path):
    path = folder / "reference_run.lock"
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError:
        raise RuntimeError("Reference run lock exists; do not launch parallel runs. Inspect before removing a stale lock.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


class BudgetCache:
    """Persist attempts BEFORE transport; no retries, even across restarts."""
    def __init__(self, root: Path, plan: list[dict]):
        self.root = root
        self.plan = {record["id"]: record for record in plan}
        if len(self.plan) != len(plan) or not 1 <= len(plan) <= LIMIT:
            raise RuntimeError("Invalid reference request plan")
        if any(not re.fullmatch(r"case_0[1-5]_(simple|tiles)", name) for name in self.plan):
            raise RuntimeError("Invalid reference request identifier")
        if any(record["endpoint"] != PROCESS_URL for record in plan):
            raise RuntimeError("Unapproved reference endpoint")
        root.mkdir(parents=True, exist_ok=True)
        self.state_path = root / "request_budget.json"
        identity = sha256_bytes(stable_json(plan).encode("utf-8"))
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state.get("plan_sha256") != identity or self.state.get("limit") != LIMIT:
                raise RuntimeError("Reference plan changed; existing authorization/budget cannot be reset automatically")
        else:
            if any(root.iterdir()):
                raise RuntimeError("Cache exists without budget ledger; refusing to reset request count")
            self.state = {"plan_sha256": identity, "limit": LIMIT, "attempts": []}
            atomic_json(self.state_path, self.state)
        attempts = self.state.get("attempts", [])
        ids = [a.get("id") for a in attempts]
        if len(ids) > LIMIT or len(set(ids)) != len(ids) or not set(ids) <= set(self.plan):
            raise RuntimeError("Invalid reference attempt ledger")
        self.hits = 0

    def cached(self, record):
        name = record["id"]
        if self.plan.get(name) != record:
            raise RuntimeError("Request is outside the authorized plan")
        folder = self.root / name
        meta_path, response = folder / "meta.json", folder / "response.tar"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if name not in {a["id"] for a in self.state["attempts"]}:
            raise RuntimeError("Cached response has no recorded attempt")
        if not response.is_file() or sha256_file(response) != meta.get("response_sha256"):
            raise RuntimeError("Reference response checksum mismatch; left untouched")
        payload = folder / "request.json"
        if not payload.is_file() or sha256_file(payload) != meta.get("request_sha256") or stable_json(json.loads(payload.read_text(encoding="utf-8"))) != stable_json(record["payload"]):
            raise RuntimeError("Reference request cache mismatch")
        return response.read_bytes(), meta

    def pending(self):
        pending = []
        attempted = {a["id"] for a in self.state["attempts"]}
        for record in self.plan.values():
            if self.cached(record) is None:
                if record["id"] in attempted:
                    raise RuntimeError("An earlier attempt lacks a verified response. No automatic retry or budget reset; return logs for review.")
                pending.append(record)
        if len(pending)+len(attempted) > LIMIT:
            raise RuntimeError("Persistent ten-request budget would be exceeded")
        return pending

    def fetch(self, record, transport):
        cached = self.cached(record)
        if cached is not None:
            self.hits += 1
            return cached
        self.pending()
        if len(self.state["attempts"]) >= LIMIT:
            raise RuntimeError("Persistent ten-request budget exhausted")
        self.state["attempts"].append({"id": record["id"], "status": "RESERVED_BEFORE_NETWORK"})
        atomic_json(self.state_path, self.state)
        folder = self.root / record["id"]
        folder.mkdir(exist_ok=True)
        atomic_json(folder / "request.json", record["payload"])
        # No credentials or headers are written into the ledger or request file.
        body, headers = transport(record["endpoint"], record["payload"])
        if not body or len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Reference response is empty or exceeds size guard")
        temporary = folder / "response.tar.tmp"
        temporary.write_bytes(body)
        temporary.replace(folder / "response.tar")
        meta = {"request_sha256": sha256_file(folder / "request.json"), "response_sha256": sha256_bytes(body),
                "response_bytes": len(body), "content_type": headers.get("content-type"),
                "processing_units_spent": headers.get("x-processingunits-spent")}
        atomic_json(folder / "meta.json", meta)
        self.state["attempts"][-1]["status"] = "RESPONSE_SAVED"
        atomic_json(self.state_path, self.state)
        return body, meta


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("HTTP redirect blocked; no credentials forwarded")


class Transport:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())
        self.token = None

    def _post(self, endpoint, body, headers, limit):
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=180) as response:
                result = response.read(limit+1)
                if len(result) > limit:
                    raise RuntimeError("HTTP response exceeds size guard")
                return result, {str(k).lower(): str(v) for k,v in response.headers.items()}
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Copernicus HTTP {exc.code}; no automatic retry. Credentials and response body are not logged.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("Copernicus connection failed; no automatic retry. Return the diagnostic log.") from None

    def authenticate(self):
        client_id = os.environ.get("CDSE_CLIENT_ID", "").strip()
        secret = os.environ.get("CDSE_CLIENT_SECRET", "").strip()
        if not client_id or not secret:
            raise RuntimeError("Set CDSE_CLIENT_ID and CDSE_CLIENT_SECRET locally; do not upload credentials")
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret}).encode()
        result, _ = self._post(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"}, 1024*1024)
        self.token = str(json.loads(result).get("access_token") or "")
        if not self.token:
            raise RuntimeError("OAuth did not return an access token")

    def __call__(self, endpoint, payload):
        if endpoint != PROCESS_URL or not self.token:
            raise RuntimeError("Unapproved endpoint or missing login")
        return self._post(endpoint, stable_json(payload).encode("utf-8"),
                          {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/tar"}, MAX_RESPONSE_BYTES)


def unpack_response(body: bytes, out: Path, record: dict) -> dict:
    expected = {"default.tif", "userdata.json"}
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:*") as archive:
        members = archive.getmembers()
        if len(members) != 2 or {m.name for m in members} != expected or sum(m.size for m in members) > MAX_RESPONSE_BYTES or any(not m.isfile() or m.size > MAX_RESPONSE_BYTES for m in members):
            raise RuntimeError("Unexpected reference archive members; no extraction performed")
        contents = {m.name: archive.extractfile(m).read() for m in members}
    metadata = json.loads(contents["userdata.json"])
    if record["mode"] == "tiles" and len(metadata.get("tiles", [])) > MAX_TILES:
        raise RuntimeError("Returned scene count exceeds guard")
    with rasterio.MemoryFile(contents["default.tif"]) as memory:
        with memory.open() as source:
            target = record["payload"]["output"]
            if (source.width, source.height, source.count) != (target["width"], target["height"], len(record["bands"])) or source.crs is None or source.crs.to_epsg() != 32633 or any(t != "float32" for t in source.dtypes):
                raise RuntimeError("Reference TIFF shape/bands/CRS/type differs from request")
            actual = list(source.transform)[:6]
            report = {"crs": source.crs.to_string(), "width": source.width, "height": source.height,
                      "bands": record["bands"], "actual_transform": actual, "expected_transform": record["expected_transform"],
                      "grid_matches_local": bool(np.allclose(actual, record["expected_transform"], atol=1e-7, rtol=0))}
    out.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        (out / name).write_bytes(data)
    atomic_json(out / "image_schema.json", report)
    return report
