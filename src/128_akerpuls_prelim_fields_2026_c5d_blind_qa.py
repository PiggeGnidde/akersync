#!/usr/bin/env python3
"""STOPPUNKT C5d: blind visual QA of all high-confidence splits + near-threshold controls. Zero PU."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c5d.json"
C5ACFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c5a.json"
C5BCFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c5b.json"
B3SCRIPT = ROOT / "src" / "114_akerpuls_prelim_fields_2026_b3_qa.py"
SNAPS = ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def as_bool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def blind_hash(salt: str, fid: str) -> str:
    return hashlib.sha256(f"{salt}|{fid}".encode("utf-8")).hexdigest()


def render_blind(index, parent_geom, child_geoms, raster_dir, out_file, b3):
    import rasterio
    from PIL import Image, ImageDraw

    bounds = parent_geom.buffer(80).bounds
    panels = []
    for snap in SNAPS:
        path = raster_dir / f"{snap.lower()}.tif"
        with rasterio.open(path) as ds:
            win = b3.bounds_to_window(bounds, ds.transform, ds.width, ds.height, pad_px=3)
            band = {n: i + 1 for i, n in enumerate(ds.descriptions) if n}
            rgb = np.stack([
                ds.read(band["B04"], window=win),
                ds.read(band["B03"], window=win),
                ds.read(band["B02"], window=win),
            ])
            valid = ds.read(band["VALID"], window=win) > 0.5
            img = b3.stretch_rgb(rgb)
            if (~valid).any():
                tint = np.array([255, 40, 80], dtype=np.float32)
                p = img[~valid].astype(np.float32)
                img[~valid] = (0.35 * p + 0.65 * tint).astype(np.uint8)
            img = b3.overlay_geom(img, [parent_geom], win, ds.transform, [255, 255, 255])
            img = b3.overlay_geom(img, child_geoms, win, ds.transform, [0, 0, 0])
            panel = Image.fromarray(img).resize((280, 280))
            canvas = Image.new("RGB", (280, 305), "white")
            canvas.paste(panel, (0, 25))
            ImageDraw.Draw(canvas).text((5, 5), snap, fill="black")
            panels.append(canvas)

    sheet = Image.new("RGB", (1120, 340), "white")
    for i, panel in enumerate(panels):
        sheet.paste(panel, (280 * i, 35))
    ImageDraw.Draw(sheet).text((5, 8), f"C5D BLIND #{index:02d}", fill="black")
    sheet.save(out_file)


def main():
    import geopandas as gpd
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--c5c-dir")
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    a = json.loads(C5ACFG.read_text(encoding="utf-8"))
    b = json.loads(C5BCFG.read_text(encoding="utf-8"))
    if cfg["split_candidate_rule_frozen_for_test"] != a["split_candidate_rule_frozen_for_test"] or cfg["split_candidate_rule_frozen_for_test"] != b["split_candidate_rule_frozen_for_test"]:
        raise RuntimeError("C5d split-candidate rule mismatch")
    if cfg["high_confidence_rule_frozen_for_test"] != a["high_confidence_rule_frozen_for_test"] or cfg["high_confidence_rule_frozen_for_test"] != b["high_confidence_rule_frozen_for_test"]:
        raise RuntimeError("C5d high-confidence rule mismatch")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("C5d guards unexpectedly enable forbidden scope")

    pdir = Path(args.pilot_dir or cfg["pilot_dir"])
    rdir = Path(args.raster_dir or cfg["raster_dir"])
    cdir = Path(args.c5c_dir or cfg["c5c_dir"])
    out = Path(args.output_dir or cfg["output_dir"])
    imgdir = out / "blind_images"
    imgdir.mkdir(parents=True, exist_ok=True)

    fields = pd.read_csv(cdir / cfg["field_validation_filename"], dtype={"parent_field_id_2025": str})
    for col in ["split_candidate_pass", "high_confidence_split"]:
        if col not in fields.columns:
            raise RuntimeError(f"C5c validation missing {col}")
        fields[col] = as_bool(fields[col])
    if "separation_ratio" not in fields.columns:
        raise RuntimeError("C5c validation missing separation_ratio")

    high = fields[fields["high_confidence_split"]].copy()
    expected_high = int(cfg["blind_visual_set"]["all_high_confidence"])
    if len(high) != expected_high:
        raise RuntimeError(f"Expected {expected_high} high-confidence splits from frozen C5c run, got {len(high)}")

    threshold = float(cfg["high_confidence_rule_frozen_for_test"]["minimum_separation_ratio"])
    controls = fields[
        fields["split_candidate_pass"] & ~fields["high_confidence_split"]
    ].copy()
    controls = controls[pd.to_numeric(controls["separation_ratio"], errors="coerce") < threshold]
    controls = controls.sort_values("separation_ratio", ascending=False).head(int(cfg["blind_visual_set"]["near_threshold_candidate_controls"]))
    if len(controls) != int(cfg["blind_visual_set"]["near_threshold_candidate_controls"]):
        raise RuntimeError("Too few below-threshold split-candidate controls for C5d")

    selected = pd.concat([
        high.assign(_hidden_group="HIGH_CONFIDENCE_CENSUS"),
        controls.assign(_hidden_group="NEAR_THRESHOLD_CANDIDATE_CONTROL"),
    ], ignore_index=True)
    salt = cfg["blind_visual_set"]["shuffle_salt"]
    selected["_blind_hash"] = [blind_hash(salt, str(fid)) for fid in selected["parent_field_id_2025"]]
    selected = selected.sort_values("_blind_hash").reset_index(drop=True)
    selected["blind_index"] = np.arange(1, len(selected) + 1)

    pilot = gpd.read_file(pdir / cfg["pilot_filename"]).to_crs(32633)
    pilot["parent_field_id_2025"] = pilot["parent_field_id_2025"].astype(str)
    children = gpd.read_file(cdir / cfg["candidate_children_filename"]).to_crs(32633)
    children["parent_field_id_2025"] = children["parent_field_id_2025"].astype(str)
    b3 = load_module(B3SCRIPT, "akerpuls_c5d_b3")

    key_rows = []
    for rec in selected.itertuples(index=False):
        fid = str(rec.parent_field_id_2025)
        pg = pilot[pilot["parent_field_id_2025"] == fid]
        cg = children[children["parent_field_id_2025"] == fid]
        if len(pg) != 1:
            raise RuntimeError(f"Expected one parent geometry for {fid}, got {len(pg)}")
        if len(cg) != 2:
            raise RuntimeError(f"Expected two candidate child geometries for {fid}, got {len(cg)}")
        bi = int(rec.blind_index)
        render_blind(bi, pg.geometry.iloc[0], list(cg.geometry), rdir, imgdir / f"C5D_{bi:02d}.png", b3)
        key_rows.append({
            "blind_index": bi,
            "parent_field_id_2025": fid,
            "hidden_group": str(rec._hidden_group),
            "split_candidate_pass": bool(rec.split_candidate_pass),
            "high_confidence_split": bool(rec.high_confidence_split),
            "separation_ratio": float(rec.separation_ratio),
            "min_largest_component_fraction": None if pd.isna(rec.min_largest_component_fraction) else float(rec.min_largest_component_fraction),
            "edge_support_count": None if pd.isna(rec.edge_support_count) else int(rec.edge_support_count),
            "loo_all4": False if pd.isna(rec.loo_all4) else bool(rec.loo_all4),
        })

    key = pd.DataFrame(key_rows).sort_values("blind_index")
    key_path = out / "c5d_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
    key.to_csv(key_path, index=False)
    key_hash = hashlib.sha256(key_path.read_bytes()).hexdigest()

    summary = {
        "schema_version": "akerpuls-prelim-fields-2026-c5d-blind-qa-v1",
        "status": "PASS",
        "third_holdout_fields": int(len(fields)),
        "high_confidence_census_images": int((key["hidden_group"] == "HIGH_CONFIDENCE_CENSUS").sum()),
        "near_threshold_control_images": int((key["hidden_group"] == "NEAR_THRESHOLD_CANDIDATE_CONTROL").sum()),
        "blind_images": int(len(key)),
        "blind_key_sha256": key_hash,
        "split_candidate_rule_frozen_for_test": cfg["split_candidate_rule_frozen_for_test"],
        "high_confidence_rule_frozen_for_test": cfg["high_confidence_rule_frozen_for_test"],
        "sentinel_hub_pu_used": 0,
        "thresholds_tuned": False,
        "product_thresholds_frozen": False,
        "interpretation_guard": "All six HIGH_CONFIDENCE_SPLIT cases in this 1000-field holdout are included, so post-reveal visual precision can be reported for this holdout. The six controls are a deliberately difficult near-threshold challenge set and are not a random negative sample.",
        "next_step": "Visually label C5D_01..C5D_12 as TYDLIG/MOJLIG/TVEKSAM/FALSK without opening the blind key; freeze labels before reveal.",
    }
    (out / "c5d_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C5D BLIND THIRD-HOLDOUT QA")
    print(f"THIRD_HOLDOUT_FIELDS={len(fields)}")
    print(f"BLIND_IMAGES={len(key)} HIGH_CONFIDENCE_CENSUS=6 NEAR_THRESHOLD_CONTROLS=6")
    print(f"BLIND_KEY_SHA256={key_hash}")
    print("DO_NOT_OPEN_BLIND_KEY_BEFORE_VISUAL_REVIEW=TRUE")
    print("HIGH_CONFIDENCE_RULE_CHANGED=FALSE")
    print("THRESHOLDS_TUNED=FALSE")
    print("PRODUCT_THRESHOLDS_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C5D_STATUS=PASS")
    print("OUTPUT=" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
