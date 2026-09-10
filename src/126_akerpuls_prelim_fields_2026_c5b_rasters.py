#!/usr/bin/env python3
"""STOPPUNKT C5b: bounded 10 m Sentinel-2 rasters for third independent holdout."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c5b.json"
C5ACFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c5a.json"
B1SCRIPT = ROOT / "src" / "112_akerpuls_prelim_fields_2026_b1_rasters.py"


def load_b1():
    spec = importlib.util.spec_from_file_location("akerpuls_b1_reference", B1SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    import geopandas as gpd
    import pandas as pd
    from rasterio.features import rasterize

    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    master = json.loads(MASTER.read_text(encoding="utf-8"))
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    c5a_cfg = json.loads(C5ACFG.read_text(encoding="utf-8"))
    b1 = load_b1()

    if cfg["split_candidate_rule_frozen_for_test"] != c5a_cfg["split_candidate_rule_frozen_for_test"]:
        raise RuntimeError("C5b split-candidate test rule differs from C5a")
    if cfg["high_confidence_rule_frozen_for_test"] != c5a_cfg["high_confidence_rule_frozen_for_test"]:
        raise RuntimeError("C5b high-confidence test rule differs from C5a")
    if cfg["preprocessing_contract"] != "IDENTICAL_TO_B1":
        raise RuntimeError("C5b preprocessing contract must remain IDENTICAL_TO_B1")
    if cfg["source_bands"] != b1.SOURCE_BANDS:
        raise RuntimeError("C5b source bands differ from B1")
    if cfg["snapshot_bands"] != b1.SNAPSHOT_BANDS:
        raise RuntimeError("C5b snapshot bands differ from B1")
    if cfg["guards"].get("threshold_tuning") is not False:
        raise RuntimeError("Threshold tuning must remain disabled in C5 holdout")

    pdir = Path(args.pilot_dir or cfg["c5a_selection_dir"])
    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    c5a_summary_path = pdir / "c5a_summary.json"
    if not c5a_summary_path.exists():
        raise FileNotFoundError(c5a_summary_path)
    c5a_summary = json.loads(c5a_summary_path.read_text(encoding="utf-8"))
    if c5a_summary.get("status") != "PASS":
        raise RuntimeError("C5a summary is not PASS")
    if c5a_summary.get("thresholds_tuned") is not False:
        raise RuntimeError("C5a unexpectedly reports threshold tuning")

    pilot_path = pdir / cfg["pilot_filename"]
    if not pilot_path.exists():
        raise FileNotFoundError(pilot_path)
    g = gpd.read_file(pilot_path).to_crs(32633)
    expected = int(cfg["expected_pilot_fields"])
    if len(g) != expected:
        raise RuntimeError(f"Expected C5a pilot of {expected} fields, got {len(g)}")
    if "parent_field_id_2025" not in g.columns:
        raise RuntimeError("C5a pilot lacks parent_field_id_2025")

    bbox = b1.aligned_bounds(g.total_bounds, cfg["resolution_m"], cfg["buffer_m"])
    width = int(round((bbox[2] - bbox[0]) / cfg["resolution_m"]))
    height = int(round((bbox[3] - bbox[1]) / cfg["resolution_m"]))
    if width > int(cfg["maximum_width_pixels"]) or height > int(cfg["maximum_height_pixels"]):
        raise RuntimeError(f"Raster guard exceeded: {width}x{height}")
    print(f"GRID={width}x{height} BBOX_32633={[round(float(x), 1) for x in bbox]}")

    ref_manifest = Path(cfg["b1_reference_dir"]) / "b1_manifest.json"
    est_pu = None
    if ref_manifest.exists():
        ref = json.loads(ref_manifest.read_text(encoding="utf-8"))
        rw = int(ref["grid"]["width"])
        rh = int(ref["grid"]["height"])
        rpu = float(ref.get("new_reported_pu_total") or 0.0)
        if rw > 0 and rh > 0 and rpu > 0:
            est_pu = rpu * (width * height) / (rw * rh)
            print(f"ESTIMATED_PU_FROM_B1_SCALE={est_pu:.3f}")
            if est_pu > float(cfg["maximum_total_reported_pu"]):
                raise RuntimeError(f"Pre-download PU estimate exceeds guard: {est_pu:.3f}")

    token = b1.oauth(master)
    reported = 0.0
    request_rows = []
    source_arrays = {}
    transform = None
    crs = None

    for snap, days in master["snapshots"].items():
        source_arrays[snap] = []
        for day in days:
            f = out / "source_daily" / f"s2_{day}.tif"
            meta, hit = b1.fetch_tiff(token, b1.payload(day, bbox, width, height), f)
            if meta.get("reported_pu") is not None and not hit:
                reported += float(meta["reported_pu"])
                if reported > float(cfg["maximum_total_reported_pu"]):
                    raise RuntimeError(f"PU guard exceeded during download: {reported:.3f}")
            request_rows.append(
                {
                    "snapshot": snap,
                    "date": day,
                    "cache_hit": hit,
                    "reported_pu": meta.get("reported_pu"),
                    "bytes": meta["bytes"],
                }
            )
            arr, tr, cc = b1.read_source(f, width, height)
            source_arrays[snap].append(arr)
            if transform is None:
                transform, crs = tr, cc
            elif tr != transform or cc != crs:
                raise RuntimeError("C5b source raster grid mismatch")

    snapshots = {}
    for snap, arrays in source_arrays.items():
        arr = b1.choose_pair(arrays, set(cfg["clear_scl_codes"]))
        snapshots[snap] = arr
        b1.write_snapshot(out / f"{snap.lower()}.tif", arr, transform, crs)
        b1.qa_png(out / f"{snap.lower()}_qa.png", arr)

    labels = rasterize(
        [(geom, i + 1) for i, geom in enumerate(g.geometry)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    totals = np.bincount(labels.ravel(), minlength=len(g) + 1).astype(float)
    good_counts = {
        snap: np.bincount(labels.ravel(), weights=arr[7].ravel(), minlength=len(g) + 1)
        for snap, arr in snapshots.items()
    }

    rows = []
    ids = g["parent_field_id_2025"].astype(str).tolist()
    for i, fid in enumerate(ids, 1):
        rec = {"parent_field_id_2025": fid, "pixels": int(totals[i])}
        for snap in snapshots:
            good = good_counts[snap]
            rec[f"valid_{snap.lower()}"] = None if totals[i] == 0 else round(float(good[i] / totals[i]), 6)
        rows.append(rec)
    pd.DataFrame(rows).to_csv(out / "field_snapshot_validity.csv", index=False)
    pd.DataFrame(request_rows).to_csv(out / "api_requests.csv", index=False)

    validity = []
    for snap, arr in snapshots.items():
        mask = labels > 0
        vf = float(arr[7][mask].mean()) if mask.any() else 0.0
        vals = [rec[f"valid_{snap.lower()}"] for rec in rows if rec[f"valid_{snap.lower()}"] is not None]
        validity.append(
            {
                "snapshot": snap,
                "pilot_pixel_valid_fraction": round(vf, 6),
                "fields_ge_0p8_valid": sum(v >= 0.8 for v in vals),
                "fields_ge_0p5_valid": sum(v >= 0.5 for v in vals),
                "fields_total": len(vals),
            }
        )

    manifest = {
        "schema_version": "akerpuls-prelim-fields-2026-c5b-third-holdout-raster-v1",
        "status": "PASS",
        "grid": {
            "bbox_32633": [float(x) for x in bbox],
            "width": width,
            "height": height,
            "resolution_m": cfg["resolution_m"],
        },
        "pilot_fields": len(g),
        "snapshot_dates": master["snapshots"],
        "preprocessing_contract": "IDENTICAL_TO_B1",
        "pair_rule": cfg["pair_rule"],
        "estimated_pu_from_b1_scale": None if est_pu is None else round(float(est_pu), 6),
        "new_reported_pu_total": round(reported, 6),
        "snapshot_validity": validity,
        "split_candidate_rule_frozen_for_test": cfg["split_candidate_rule_frozen_for_test"],
        "high_confidence_rule_frozen_for_test": cfg["high_confidence_rule_frozen_for_test"],
        "merge_policy": cfg["merge_policy"],
        "thresholds_tuned": False,
        "product_thresholds_frozen": False,
        "outputs": [
            "s2_2026_april.tif",
            "s2_2026_may.tif",
            "s2_2026_june.tif",
            "s2_2026_july.tif",
            "field_snapshot_validity.csv",
        ],
        "next_step": "C5c run identical B2 discovery plus frozen split-candidate and HIGH_CONFIDENCE_SPLIT rules without tuning.",
    }
    (out / "c5b_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"NEW_REPORTED_PU_TOTAL={reported:.6f}")
    for s in validity:
        print(
            f'{s["snapshot"]}: VALID_PIXELS={s["pilot_pixel_valid_fraction"]:.4f} '
            f'FIELDS_GE80={s["fields_ge_0p8_valid"]}/{s["fields_total"]} '
            f'FIELDS_GE50={s["fields_ge_0p5_valid"]}/{s["fields_total"]}'
        )
    print("PREPROCESSING_CONTRACT=IDENTICAL_TO_B1")
    print("SPLIT_CANDIDATE_RULE_CHANGED=FALSE")
    print("HIGH_CONFIDENCE_RULE_CHANGED=FALSE")
    print("THRESHOLDS_TUNED=FALSE")
    print("PRODUCT_THRESHOLDS_FROZEN=FALSE")
    print("C5B_STATUS=PASS")
    print("OUTPUT=" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
