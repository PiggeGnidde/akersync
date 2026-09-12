#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls full-Skåne D1 Sentinel-2 acquisition and frozen snapshot mosaic build.

Expensive stage: may spend ~5.5k Sentinel Hub PU. The exact D0b execution
contract and D0 request plan are hash-pinned before the first Process API call.
No model fitting, threshold tuning, crop classification, split/merge mutation,
or geometry replacement occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_full_skane_d1_acquisition_v1.json"
SNAPSHOT_BANDS = ["B02","B03","B04","B08","B11","SCL","CLD","VALID","NDVI","LSWI","SOURCE_DATE_INDEX"]
SOURCE_BANDS = ["B02","B03","B04","B08","B11","SCL","CLD","dataMask"]
CRS_URI = "http://www.opengis.net/def/crs/EPSG/0/32633"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def log(msg: str) -> None:
    print(msg, flush=True)


def oauth(cfg: dict[str, Any]) -> str:
    cid = os.getenv("CDSE_CLIENT_ID", "").strip()
    sec = os.getenv("CDSE_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        raise RuntimeError("BLOCKED_CREDENTIALS: CDSE_CLIENT_ID/CDSE_CLIENT_SECRET are not set")
    body = urllib.parse.urlencode({"grant_type":"client_credentials","client_id":cid,"client_secret":sec}).encode()
    req = urllib.request.Request(cfg["token_url"], data=body, method="POST", headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def evalscript() -> str:
    return """//VERSION=3
function setup(){
  return {
    input:[{bands:[\"B02\",\"B03\",\"B04\",\"B08\",\"B11\",\"SCL\",\"CLD\",\"dataMask\"]}],
    output:{bands:8,sampleType:\"FLOAT32\"}
  };
}
function evaluatePixel(s){
  return [s.B02,s.B03,s.B04,s.B08,s.B11,s.SCL,s.CLD,s.dataMask];
}"""


def process_payload(day: str, bbox: list[float], width: int, height: int, source_cfg: dict[str, Any]) -> dict[str, Any]:
    d = date.fromisoformat(day)
    e = d + timedelta(days=1)
    return {
        "input": {
            "bounds": {"bbox": [float(x) for x in bbox], "properties": {"crs": CRS_URI}},
            "data": [{
                "type": source_cfg["collection"],
                "dataFilter": {"timeRange":{"from":f"{d}T00:00:00Z","to":f"{e}T00:00:00Z"}, "maxCloudCoverage":100},
                "processing": {
                    "upsampling": source_cfg["processing_upsampling"],
                    "downsampling": source_cfg["processing_downsampling"],
                    "harmonizeValues": bool(source_cfg["harmonize_values"]),
                },
            }],
        },
        "output": {"width": int(width), "height": int(height), "responses":[{"identifier":"default","format":{"type":"image/tiff"}}]},
        "evalscript": evalscript(),
    }


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def fetch_tiff(token: str, process_url: str, payload: dict[str, Any], out: Path, max_retries: int) -> tuple[dict[str, Any], bool]:
    raw = stable_json_bytes(payload)
    reqhash = sha256_bytes(raw)
    meta = out.with_suffix(out.suffix + ".json")
    if out.exists() and meta.exists():
        m = read_json(meta)
        if m.get("request_sha256") != reqhash:
            raise RuntimeError(f"Cached request hash mismatch: {out}")
        if sha256_file(out) != m.get("response_sha256"):
            raise RuntimeError(f"Cached response hash mismatch: {out}")
        return m, True

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(process_url, data=raw, method="POST", headers={
            "Authorization":"Bearer " + token,
            "Content-Type":"application/json",
            "Accept":"image/tiff",
        })
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
                pu = r.headers.get("x-processingunits-spent")
            atomic_write(out, body)
            m = {
                "request_sha256": reqhash,
                "response_sha256": sha256_bytes(body),
                "bytes": len(body),
                "reported_pu": float(pu) if pu not in (None, "") else None,
                "created_utc": datetime.now(timezone.utc).isoformat(),
            }
            meta.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
            return m, False
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    detail = exc.read().decode("utf-8", "replace")[:800]
                except Exception:
                    detail = ""
                log(f"D1_HTTP_RETRY attempt={attempt}/{max_retries} code={exc.code} detail={detail}")
            else:
                log(f"D1_NETWORK_RETRY attempt={attempt}/{max_retries} error={exc}")
            if attempt < max_retries:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Process API request failed after {max_retries} attempts: {last_exc}")


def read_source(path: Path, width: int, height: int):
    import rasterio
    with rasterio.open(path) as ds:
        arr = ds.read().astype("float32")
        if arr.shape != (8, height, width):
            raise RuntimeError(f"{path}: unexpected shape {arr.shape}, expected (8,{height},{width})")
        return arr, ds.transform, ds.crs


def combine_snapshot(indexed_arrays: list[tuple[int, np.ndarray]], width: int, height: int, clear_codes: set[int]) -> np.ndarray:
    if not indexed_arrays:
        out = np.zeros((11, height, width), dtype="float32")
        out[10].fill(-1.0)
        return out
    indexed_arrays = sorted(indexed_arrays, key=lambda x: x[0])
    if len(indexed_arrays) == 1:
        idx, a = indexed_arrays[0]
        choice = np.full((height, width), float(idx), dtype="float32")
    elif len(indexed_arrays) == 2:
        idx1, a = indexed_arrays[0]
        idx2, b = indexed_arrays[1]
        d1 = a[7] > 0.5
        d2 = b[7] > 0.5
        c1 = d1 & np.isin(np.rint(a[5]).astype(np.int16), list(clear_codes))
        c2 = d2 & np.isin(np.rint(b[5]).astype(np.int16), list(clear_codes))
        choose2 = (c2 & ~c1) | ((c1 == c2) & d2 & (~d1 | (b[6] < a[6])))
        choice = np.where(choose2, float(idx2), float(idx1)).astype("float32")
        a = np.where(choose2[None, :, :], b, a)
    else:
        raise RuntimeError("Frozen snapshots support at most two dates")
    scl = np.rint(a[5]).astype(np.int16)
    dat = a[7] > 0.5
    valid = dat & np.isin(scl, list(clear_codes))
    den = a[3] + a[2]
    ndvi = np.divide(a[3] - a[2], den, out=np.zeros_like(den), where=np.abs(den) > 1e-8)
    den2 = a[3] + a[4]
    lswi = np.divide(a[3] - a[4], den2, out=np.zeros_like(den2), where=np.abs(den2) > 1e-8)
    return np.stack([
        a[0], a[1], a[2], a[3], a[4], a[5], a[6], valid.astype("float32"),
        ndvi.astype("float32"), lswi.astype("float32"), choice,
    ]).astype("float32")


def write_snapshot(path: Path, arr: np.ndarray, transform, crs) -> None:
    import rasterio
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    profile = {
        "driver":"GTiff", "width":arr.shape[2], "height":arr.shape[1], "count":arr.shape[0],
        "dtype":"float32", "crs":crs, "transform":transform, "compress":"DEFLATE", "predictor":3,
        "tiled":True, "blockxsize":256, "blockysize":256,
    }
    with rasterio.open(tmp, "w", **profile) as ds:
        ds.write(arr)
        for i, name in enumerate(SNAPSHOT_BANDS, 1):
            ds.set_band_description(i, name)
    os.replace(tmp, path)


def build_vrt(vrt_path: Path, tile_paths: list[Path]) -> None:
    import rasterio
    if not tile_paths:
        raise RuntimeError(f"No tile paths for {vrt_path}")
    infos = []
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    xres = yres = None
    crs = None
    for p in tile_paths:
        with rasterio.open(p) as ds:
            if ds.count != 11:
                raise RuntimeError(f"{p}: expected 11 bands")
            b = ds.bounds
            minx, miny, maxx, maxy = min(minx,b.left), min(miny,b.bottom), max(maxx,b.right), max(maxy,b.top)
            rx, ry = float(ds.transform.a), abs(float(ds.transform.e))
            if xres is None:
                xres, yres, crs = rx, ry, ds.crs
            elif abs(rx-xres)>1e-9 or abs(ry-yres)>1e-9 or ds.crs != crs:
                raise RuntimeError("Snapshot tile grid/CRS mismatch while building VRT")
            infos.append((p, ds.width, ds.height, b.left, b.top))
    width = int(round((maxx-minx)/xres))
    height = int(round((maxy-miny)/yres))
    lines = [
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">',
        f'  <SRS>{crs.to_string()}</SRS>',
        f'  <GeoTransform>{minx}, {xres}, 0.0, {maxy}, 0.0, {-yres}</GeoTransform>',
    ]
    for band_idx, band_name in enumerate(SNAPSHOT_BANDS, 1):
        lines.append(f'  <VRTRasterBand dataType="Float32" band="{band_idx}">')
        lines.append(f'    <Description>{band_name}</Description>')
        for p, w, h, left, top in infos:
            xoff = int(round((left-minx)/xres))
            yoff = int(round((maxy-top)/yres))
            rel = os.path.relpath(p, vrt_path.parent).replace("\\", "/")
            lines += [
                '    <SimpleSource>',
                f'      <SourceFilename relativeToVRT="1">{rel}</SourceFilename>',
                f'      <SourceBand>{band_idx}</SourceBand>',
                f'      <SourceProperties RasterXSize="{w}" RasterYSize="{h}" DataType="Float32" BlockXSize="256" BlockYSize="256"/>',
                f'      <SrcRect xOff="0" yOff="0" xSize="{w}" ySize="{h}"/>',
                f'      <DstRect xOff="{xoff}" yOff="{yoff}" xSize="{w}" ySize="{h}"/>',
                '    </SimpleSource>',
            ]
        lines.append('  </VRTRasterBand>')
    lines.append('</VRTDataset>')
    vrt_path.parent.mkdir(parents=True, exist_ok=True)
    vrt_path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    with rasterio.open(vrt_path) as ds:
        if ds.count != 11:
            raise RuntimeError(f"VRT verification failed for {vrt_path}")


def main() -> int:
    import pandas as pd
    import rasterio
    from rasterio.transform import from_bounds

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    ap.add_argument("--raw-root")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    if cfg["schema_version"] != "akerpuls-full-skane-d1-acquisition-v1":
        raise RuntimeError("D1 config schema changed")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1 forbidden-scope guard unexpectedly enabled")

    contract_path = Path(cfg["final_execution_contract"])
    if not contract_path.is_file():
        raise FileNotFoundError(contract_path)
    contract_sha = sha256_file(contract_path)
    if contract_sha != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError(f"Final D1 execution contract SHA mismatch: {contract_sha}")
    contract = read_json(contract_path)
    if contract.get("automatic_split") or contract.get("automatic_merge") or contract.get("automatic_geometry_replacement"):
        raise RuntimeError("Execution contract unexpectedly enables automatic geometry mutation")
    if int(contract["request_plan"]["rows"]) != int(cfg["expected_process_requests"]):
        raise RuntimeError("Execution contract request count changed")

    d0dir = Path(cfg["d0_output_dir"])
    req_path = d0dir / "d0_process_request_plan.csv"
    snapshot_plan_path = d0dir / "d0_snapshot_tile_plan.csv"
    tiles_path = d0dir / "d0_raster_tiles.csv"
    if sha256_file(req_path) != contract["request_plan"]["sha256"]:
        raise RuntimeError("D0 request-plan SHA does not match final execution contract")
    requests = pd.read_csv(req_path, encoding="utf-8-sig")
    snapshot_plan = pd.read_csv(snapshot_plan_path, encoding="utf-8-sig")
    tiles = pd.read_csv(tiles_path, encoding="utf-8-sig")
    if len(requests) != int(cfg["expected_process_requests"]):
        raise RuntimeError("D0 request-plan row count changed")
    if len(snapshot_plan) != int(cfg["expected_snapshot_tiles"]):
        raise RuntimeError("D0 snapshot-tile row count changed")
    if len(tiles) != int(cfg["expected_raster_tiles"]):
        raise RuntimeError("D0 raster-tile row count changed")

    raw_root = Path(args.raw_root or cfg["raw_root"])
    out = Path(args.output_dir or cfg["output_dir"])
    raw_root.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    free_gib = shutil.disk_usage(raw_root).free / (1024**3)
    log(f"D1_FREE_DISK_GIB={free_gib:.2f}")
    if free_gib < float(cfg["minimum_free_gib_before_new_download"]):
        raise RuntimeError(f"Insufficient free disk before D1: {free_gib:.2f} GiB")

    source_cfg = contract["sentinel_source"]
    if source_cfg["source_bands"] != SOURCE_BANDS:
        raise RuntimeError("Source-band contract changed")
    if source_cfg["processing_upsampling"] != "NEAREST" or source_cfg["processing_downsampling"] != "NEAREST":
        raise RuntimeError("Preprocessing contract changed")

    log("D1_PROGRESS=OAUTH")
    token = oauth(cfg)
    process_url = source_cfg["process_url"]
    new_pu = 0.0
    new_requests = 0
    cache_hits = 0
    api_rows = []
    total = len(requests)
    log(f"D1_PROGRESS=DOWNLOAD_DAILY_SOURCE_TILES TOTAL={total}")
    for i, r in requests.iterrows():
        bbox = [float(r.minx), float(r.miny), float(r.maxx), float(r.maxy)]
        width, height = int(r.width), int(r.height)
        rel = Path(str(r.daily_output_relative).replace("/", os.sep))
        target = raw_root / rel
        payload = process_payload(str(r.date), bbox, width, height, source_cfg)
        m, hit = fetch_tiff(token, process_url, payload, target, int(cfg["max_request_retries"]))
        cache_hits += int(hit)
        if not hit:
            new_requests += 1
            if m.get("reported_pu") is not None:
                new_pu += float(m["reported_pu"])
            if new_pu > float(cfg["maximum_new_reported_pu"]):
                raise RuntimeError(f"Actual new reported PU guard exceeded: {new_pu}")
        api_rows.append({
            "n": i+1, "snapshot":r.snapshot, "date":r.date, "tile_id":r.tile_id,
            "cache_hit":bool(hit), "reported_pu":m.get("reported_pu"), "bytes":m.get("bytes"),
            "response_sha256":m.get("response_sha256"), "path":str(target),
        })
        if (i+1) % 10 == 0 or (i+1) == total:
            log(f"D1_DOWNLOAD_PROGRESS={i+1}/{total} NEW_REQUESTS={new_requests} CACHE_HITS={cache_hits} NEW_REPORTED_PU={new_pu:.3f}")
    pd.DataFrame(api_rows).to_csv(out / "d1_api_requests.csv", index=False, encoding="utf-8-sig")

    clear_codes = set(int(x) for x in source_cfg["clear_scl_codes"])
    frozen_snapshots = contract["frozen_snapshots"]
    req_lookup = {(str(r.date), str(r.tile_id)): Path(str(r.daily_output_relative).replace("/", os.sep)) for _, r in requests.iterrows()}
    tile_lookup = {str(r.tile_id): r for _, r in tiles.iterrows()}
    snapshot_outputs = []
    total_snap = len(snapshot_plan)
    log(f"D1_PROGRESS=BUILD_SNAPSHOT_TILES TOTAL={total_snap}")
    for j, r in snapshot_plan.iterrows():
        snap = str(r.snapshot)
        tile_id = str(r.tile_id)
        dates = list(frozen_snapshots[snap])
        rr = tile_lookup[tile_id]
        bbox = [float(rr.minx), float(rr.miny), float(rr.maxx), float(rr.maxy)]
        width, height = int(rr.width), int(rr.height)
        transform = from_bounds(*bbox, width=width, height=height)
        crs = rasterio.crs.CRS.from_epsg(32633)
        indexed = []
        for date_idx, day in enumerate(dates):
            rel = req_lookup.get((day, tile_id))
            if rel is None:
                continue
            p = raw_root / rel
            if not p.is_file():
                raise FileNotFoundError(p)
            arr, tr, cc = read_source(p, width, height)
            if tr != transform or cc != crs:
                raise RuntimeError(f"Daily source grid mismatch for {p}")
            indexed.append((date_idx, arr))
        arr = combine_snapshot(indexed, width, height, clear_codes)
        relout = Path(str(r.snapshot_output_relative).replace("/", os.sep))
        dst = raw_root / relout
        if dst.exists():
            with rasterio.open(dst) as ds:
                if ds.count != 11 or ds.width != width or ds.height != height or ds.transform != transform or ds.crs != crs:
                    raise RuntimeError(f"Cached snapshot tile structure mismatch: {dst}")
        else:
            write_snapshot(dst, arr, transform, crs)
        snapshot_outputs.append({"snapshot":snap,"tile_id":tile_id,"path":str(dst),"sha256":sha256_file(dst)})
        if (j+1) % 20 == 0 or (j+1) == total_snap:
            log(f"D1_SNAPSHOT_PROGRESS={j+1}/{total_snap}")
    pd.DataFrame(snapshot_outputs).to_csv(out / "d1_snapshot_tiles.csv", index=False, encoding="utf-8-sig")

    log("D1_PROGRESS=BUILD_4_SNAPSHOT_VRTS")
    vrt_rows = []
    for snap in frozen_snapshots:
        sub = [Path(x["path"]) for x in snapshot_outputs if x["snapshot"] == snap]
        vrt = raw_root / "snapshots" / f"{snap.lower()}.vrt"
        build_vrt(vrt, sub)
        vrt_rows.append({"snapshot":snap,"path":str(vrt),"sha256":sha256_file(vrt)})
        log(f"D1_VRT={snap} PATH={vrt}")
    pd.DataFrame(vrt_rows).to_csv(out / "d1_vrts.csv", index=False, encoding="utf-8-sig")

    manifest = {
        "schema_version":"akerpuls-full-skane-d1-acquisition-result-v1",
        "status":"PASS",
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "final_execution_contract_sha256":contract_sha,
        "request_plan_sha256":contract["request_plan"]["sha256"],
        "planned_process_requests":len(requests),
        "new_process_requests":new_requests,
        "cache_hits":cache_hits,
        "new_reported_pu_total":round(new_pu,6),
        "snapshot_tiles":len(snapshot_outputs),
        "snapshot_vrts":len(vrt_rows),
        "raw_root":str(raw_root),
        "automatic_split":False,
        "automatic_merge":False,
        "automatic_geometry_replacement":False,
        "next_step":"D2 frozen split-fusion QA model application over all 2025 fields; no geometry mutation.",
    }
    (out / "d1_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    log("AKERPULS FULL SKANE D1 SENTINEL ACQUISITION")
    log("STATUS=PASS")
    log(f"FINAL_EXECUTION_CONTRACT_SHA256={contract_sha}")
    log(f"PLANNED_PROCESS_REQUESTS={len(requests)}")
    log(f"NEW_PROCESS_REQUESTS={new_requests}")
    log(f"CACHE_HITS={cache_hits}")
    log(f"NEW_REPORTED_PU_TOTAL={new_pu:.6f}")
    log(f"SNAPSHOT_TILES={len(snapshot_outputs)}")
    log(f"SNAPSHOT_VRTS={len(vrt_rows)}")
    log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    log("D1_STATUS=PASS")
    log("OUTPUT="+str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
