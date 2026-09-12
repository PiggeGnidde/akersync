#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safe/resumable driver for ÅkerPuls full-Skåne D1 acquisition v1.

Uses the frozen helper semantics in src/140_... while adding two operational
safety guards before the first production run: remaining-data disk budgeting
and periodic OAuth refresh. No scientific/model contract is changed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_full_skane_d1_acquisition_v1.json"
BASE = ROOT / "src" / "140_akerpuls_full_skane_d1_acquisition_v1.py"


def load_base():
    spec = importlib.util.spec_from_file_location("akerpuls_d1_base", BASE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    import pandas as pd
    import rasterio
    from rasterio.transform import from_bounds

    b = load_base()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    ap.add_argument("--raw-root")
    args = ap.parse_args()

    cfg = b.read_json(Path(args.config))
    if cfg["schema_version"] != "akerpuls-full-skane-d1-acquisition-v1":
        raise RuntimeError("D1 config schema changed")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1 forbidden-scope guard unexpectedly enabled")

    contract_path = Path(cfg["final_execution_contract"])
    if not contract_path.is_file():
        raise FileNotFoundError(contract_path)
    contract_sha = b.sha256_file(contract_path)
    if contract_sha != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError(f"Final D1 execution contract SHA mismatch: {contract_sha}")
    contract = b.read_json(contract_path)
    if contract.get("automatic_split") or contract.get("automatic_merge") or contract.get("automatic_geometry_replacement"):
        raise RuntimeError("Execution contract unexpectedly enables automatic geometry mutation")

    d0dir = Path(cfg["d0_output_dir"])
    req_path = d0dir / "d0_process_request_plan.csv"
    snapshot_plan_path = d0dir / "d0_snapshot_tile_plan.csv"
    tiles_path = d0dir / "d0_raster_tiles.csv"
    if b.sha256_file(req_path) != contract["request_plan"]["sha256"]:
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

    # Resume-aware disk guard. Use theoretical uncompressed remaining bytes,
    # which is deliberately conservative because actual GeoTIFFs are DEFLATE compressed.
    source_missing = 0
    source_remaining_bytes = 0
    for _, r in requests.iterrows():
        p = raw_root / Path(str(r.daily_output_relative).replace("/", os.sep))
        if not p.exists():
            source_missing += 1
            source_remaining_bytes += int(r.width) * int(r.height) * len(b.SOURCE_BANDS) * 4
    snapshot_missing = 0
    snapshot_remaining_bytes = 0
    tile_lookup = {str(r.tile_id): r for _, r in tiles.iterrows()}
    for _, r in snapshot_plan.iterrows():
        p = raw_root / Path(str(r.snapshot_output_relative).replace("/", os.sep))
        if not p.exists():
            rr = tile_lookup[str(r.tile_id)]
            snapshot_missing += 1
            snapshot_remaining_bytes += int(rr.width) * int(rr.height) * len(b.SNAPSHOT_BANDS) * 4
    remaining_gib = (source_remaining_bytes + snapshot_remaining_bytes) / (1024 ** 3)
    reserve_gib = float(cfg["disk_reserve_gib"])
    required_gib = remaining_gib + reserve_gib
    free_gib = shutil.disk_usage(raw_root).free / (1024 ** 3)
    b.log(f"D1_SOURCE_TILES_MISSING={source_missing}/{len(requests)}")
    b.log(f"D1_SNAPSHOT_TILES_MISSING={snapshot_missing}/{len(snapshot_plan)}")
    b.log(f"D1_REMAINING_UNCOMPRESSED_GIB={remaining_gib:.2f}")
    b.log(f"D1_DISK_RESERVE_GIB={reserve_gib:.2f}")
    b.log(f"D1_REQUIRED_FREE_GIB={required_gib:.2f}")
    b.log(f"D1_FREE_DISK_GIB={free_gib:.2f}")
    if free_gib < required_gib:
        raise RuntimeError(f"Insufficient free disk for remaining D1 work: need {required_gib:.2f} GiB, have {free_gib:.2f} GiB")

    source_cfg = contract["sentinel_source"]
    if source_cfg["source_bands"] != b.SOURCE_BANDS:
        raise RuntimeError("Source-band contract changed")
    if source_cfg["processing_upsampling"] != "NEAREST" or source_cfg["processing_downsampling"] != "NEAREST":
        raise RuntimeError("Preprocessing contract changed")

    b.log("D1_PROGRESS=OAUTH")
    token = b.oauth(cfg)
    refresh_every = int(cfg["token_refresh_every_rows"])
    process_url = source_cfg["process_url"]
    new_pu = 0.0
    total_reported_pu = 0.0
    new_requests = 0
    cache_hits = 0
    api_rows = []
    total = len(requests)
    b.log(f"D1_PROGRESS=DOWNLOAD_DAILY_SOURCE_TILES TOTAL={total}")
    for i, r in requests.iterrows():
        if i and i % refresh_every == 0:
            b.log(f"D1_OAUTH_REFRESH_AT_ROW={i}")
            token = b.oauth(cfg)
        bbox = [float(r.minx), float(r.miny), float(r.maxx), float(r.maxy)]
        width, height = int(r.width), int(r.height)
        rel = Path(str(r.daily_output_relative).replace("/", os.sep))
        target = raw_root / rel
        payload = b.process_payload(str(r.date), bbox, width, height, source_cfg)
        m, hit = b.fetch_tiff(token, process_url, payload, target, int(cfg["max_request_retries"]))
        cache_hits += int(hit)
        pu = m.get("reported_pu")
        if pu is not None:
            total_reported_pu += float(pu)
        if not hit:
            new_requests += 1
            if pu is not None:
                new_pu += float(pu)
        if total_reported_pu > float(cfg["maximum_total_reported_pu"]):
            raise RuntimeError(f"Total reported PU guard exceeded: {total_reported_pu}")
        api_rows.append({
            "n": i + 1,
            "snapshot": r.snapshot,
            "date": r.date,
            "tile_id": r.tile_id,
            "cache_hit": bool(hit),
            "reported_pu": pu,
            "bytes": m.get("bytes"),
            "response_sha256": m.get("response_sha256"),
            "path": str(target),
        })
        if (i + 1) % 10 == 0 or (i + 1) == total:
            b.log(
                f"D1_DOWNLOAD_PROGRESS={i+1}/{total} NEW_REQUESTS={new_requests} "
                f"CACHE_HITS={cache_hits} NEW_REPORTED_PU={new_pu:.3f} TOTAL_REPORTED_PU={total_reported_pu:.3f}"
            )
    pd.DataFrame(api_rows).to_csv(out / "d1_api_requests.csv", index=False, encoding="utf-8-sig")

    clear_codes = set(int(x) for x in source_cfg["clear_scl_codes"])
    frozen_snapshots = contract["frozen_snapshots"]
    req_lookup = {
        (str(r.date), str(r.tile_id)): Path(str(r.daily_output_relative).replace("/", os.sep))
        for _, r in requests.iterrows()
    }
    snapshot_outputs = []
    total_snap = len(snapshot_plan)
    b.log(f"D1_PROGRESS=BUILD_SNAPSHOT_TILES TOTAL={total_snap}")
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
            arr, tr, cc = b.read_source(p, width, height)
            if tr != transform or cc != crs:
                raise RuntimeError(f"Daily source grid mismatch for {p}")
            indexed.append((date_idx, arr))
        arr = b.combine_snapshot(indexed, width, height, clear_codes)
        relout = Path(str(r.snapshot_output_relative).replace("/", os.sep))
        dst = raw_root / relout
        if dst.exists():
            with rasterio.open(dst) as ds:
                if ds.count != 11 or ds.width != width or ds.height != height or ds.transform != transform or ds.crs != crs:
                    raise RuntimeError(f"Cached snapshot tile structure mismatch: {dst}")
        else:
            b.write_snapshot(dst, arr, transform, crs)
        snapshot_outputs.append({"snapshot": snap, "tile_id": tile_id, "path": str(dst), "sha256": b.sha256_file(dst)})
        if (j + 1) % 20 == 0 or (j + 1) == total_snap:
            b.log(f"D1_SNAPSHOT_PROGRESS={j+1}/{total_snap}")
    pd.DataFrame(snapshot_outputs).to_csv(out / "d1_snapshot_tiles.csv", index=False, encoding="utf-8-sig")

    b.log("D1_PROGRESS=BUILD_4_SNAPSHOT_VRTS")
    vrt_rows = []
    for snap in frozen_snapshots:
        sub = [Path(x["path"]) for x in snapshot_outputs if x["snapshot"] == snap]
        vrt = raw_root / "snapshots" / f"{snap.lower()}.vrt"
        b.build_vrt(vrt, sub)
        vrt_rows.append({"snapshot": snap, "path": str(vrt), "sha256": b.sha256_file(vrt)})
        b.log(f"D1_VRT={snap} PATH={vrt}")
    pd.DataFrame(vrt_rows).to_csv(out / "d1_vrts.csv", index=False, encoding="utf-8-sig")

    manifest = {
        "schema_version": "akerpuls-full-skane-d1-acquisition-result-v1",
        "status": "PASS",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "final_execution_contract_sha256": contract_sha,
        "request_plan_sha256": contract["request_plan"]["sha256"],
        "planned_process_requests": len(requests),
        "new_process_requests": new_requests,
        "cache_hits": cache_hits,
        "new_reported_pu_total": round(new_pu, 6),
        "total_reported_pu_from_all_verified_tiles": round(total_reported_pu, 6),
        "snapshot_tiles": len(snapshot_outputs),
        "snapshot_vrts": len(vrt_rows),
        "raw_root": str(raw_root),
        "automatic_split": False,
        "automatic_merge": False,
        "automatic_geometry_replacement": False,
        "next_step": "D2 frozen split-fusion QA model application over all 2025 fields; no geometry mutation.",
    }
    (out / "d1_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    b.log("AKERPULS FULL SKANE D1 SENTINEL ACQUISITION")
    b.log("STATUS=PASS")
    b.log(f"FINAL_EXECUTION_CONTRACT_SHA256={contract_sha}")
    b.log(f"PLANNED_PROCESS_REQUESTS={len(requests)}")
    b.log(f"NEW_PROCESS_REQUESTS={new_requests}")
    b.log(f"CACHE_HITS={cache_hits}")
    b.log(f"NEW_REPORTED_PU_TOTAL={new_pu:.6f}")
    b.log(f"TOTAL_REPORTED_PU={total_reported_pu:.6f}")
    b.log(f"SNAPSHOT_TILES={len(snapshot_outputs)}")
    b.log(f"SNAPSHOT_VRTS={len(vrt_rows)}")
    b.log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    b.log("D1_STATUS=PASS")
    b.log("OUTPUT=" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
