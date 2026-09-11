#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C7D: blind visual QA of the frozen C7 fusion tiers. Zero PU.

Selection is frozen before visual labels:
- census of all C7 baseline candidates >= frozen DEV-P90,
- five highest-scoring June-GE80 candidates just below DEV-P90.

The script never reads visual labels. Hidden fusion/group metadata is written to a
blind key that must not be opened before the human labels are frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c7d.json"
B2CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_b2.json"
B2SCRIPT = ROOT / "src" / "113_akerpuls_prelim_fields_2026_b2_baseline.py"
B3SCRIPT = ROOT / "src" / "114_akerpuls_prelim_fields_2026_b3_qa.py"
SNAPS = ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def as_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def blind_hash(salt: str, fid: str) -> str:
    return hashlib.sha256(f"{salt}|{fid}".encode("utf-8")).hexdigest()


def select_blind_cases(cand: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    x = cand.copy()
    for col in ("fusion_ge_dev_p90", "fusion_ge_dev_p95"):
        if col not in x.columns:
            raise RuntimeError(f"C7C candidates missing {col}")
        x[col] = as_bool(x[col])
    for col in ("fusion_score", "valid_s2_2026_june"):
        if col not in x.columns:
            raise RuntimeError(f"C7C candidates missing {col}")
        x[col] = pd.to_numeric(x[col], errors="coerce")
        if x[col].isna().any():
            raise RuntimeError(f"C7C candidates contain missing {col}")

    expected_n = int(cfg["expected_baseline_candidates"])
    if len(x) != expected_n:
        raise RuntimeError(f"Expected {expected_n} C7 baseline candidates, got {len(x)}")
    ep90 = int(cfg["expected_fusion_ge_dev_p90"])
    ep95 = int(cfg["expected_fusion_ge_dev_p95"])
    if int(x["fusion_ge_dev_p90"].sum()) != ep90:
        raise RuntimeError(f"Expected {ep90} DEV-P90 candidates, got {int(x['fusion_ge_dev_p90'].sum())}")
    if int(x["fusion_ge_dev_p95"].sum()) != ep95:
        raise RuntimeError(f"Expected {ep95} DEV-P95 candidates, got {int(x['fusion_ge_dev_p95'].sum())}")
    if (x["fusion_ge_dev_p95"] & ~x["fusion_ge_dev_p90"]).any():
        raise RuntimeError("DEV-P95 is not a subset of DEV-P90")

    b = cfg["blind_visual_set"]
    p90 = x[x["fusion_ge_dev_p90"]].copy()
    if len(p90) != int(b["p90_census"]):
        raise RuntimeError("Frozen P90 census size mismatch")
    if not (p90["june_validity_stratum"].astype(str) == "GE80").all():
        raise RuntimeError("Expected every C7 P90 case to be in June GE80 stratum")

    controls = x[(~x["fusion_ge_dev_p90"]) & (x["june_validity_stratum"].astype(str) == "GE80")].copy()
    controls = controls.sort_values(["fusion_score", "parent_field_id_2025"], ascending=[False, True])
    controls = controls.head(int(b["near_p90_controls"]))
    if len(controls) != int(b["near_p90_controls"]):
        raise RuntimeError("Too few frozen near-P90 June-GE80 controls")

    p90["hidden_group_internal"] = np.where(
        p90["fusion_ge_dev_p95"], "FUSION_GE_DEV_P95_CENSUS", "FUSION_P90_TO_P95_CENSUS"
    )
    controls["hidden_group_internal"] = "NEAR_P90_JUNE_GE80_CONTROL"
    selected = pd.concat([p90, controls], ignore_index=True, sort=False)
    salt = str(b["shuffle_salt"])
    selected["blind_hash_internal"] = [blind_hash(salt, str(fid)) for fid in selected["parent_field_id_2025"]]
    selected = selected.sort_values("blind_hash_internal").reset_index(drop=True)
    selected["blind_index"] = np.arange(1, len(selected) + 1)
    return selected


def reconstruct_child_geometries(selected: pd.DataFrame, cfg: dict[str, Any]):
    import geopandas as gpd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize

    b2cfg = read_json(B2CFG)
    b2 = load_module(B2SCRIPT, "c7d_b2")
    pdir = Path(cfg["pilot_dir"])
    rdir = Path(cfg["raster_dir"])
    g = gpd.read_file(pdir / cfg["pilot_filename"]).to_crs(32633).reset_index(drop=True)
    if len(g) != int(cfg["expected_fields"]):
        raise RuntimeError(f"Expected {cfg['expected_fields']} pilot fields, got {len(g)}")
    g["parent_field_id_2025"] = g["parent_field_id_2025"].astype(str)

    features = list(b2cfg["feature_bands_per_snapshot"])
    cubes, valids, _rgbs, transform, _crs, (h, w) = b2.load_snapshots(rdir, features)
    labels = rasterize(
        [(geom, i + 1) for i, geom in enumerate(g.geometry)],
        out_shape=(h, w), transform=transform, fill=0, dtype="int32", all_touched=False,
    )
    all_valid = np.logical_and.reduce(valids)
    raw = np.concatenate(cubes, axis=0).transpose(1, 2, 0)
    sample = raw[(labels > 0) & all_valid]
    if len(sample) == 0:
        raise RuntimeError("No all-valid C7 pixels for reconstruction")
    center = np.nanmedian(sample, axis=0)
    mad = np.nanmedian(np.abs(sample - center), axis=0) * 1.4826
    std = np.nanstd(sample, axis=0)
    scale = np.where(mad > 1e-6, mad, np.where(std > 1e-6, std, 1.0))
    z = (raw - center) / scale
    sp = b2cfg["split"]
    id_to_pos = {str(fid): i for i, fid in enumerate(g["parent_field_id_2025"])}

    child_map: dict[str, list[Any]] = {}
    parent_map: dict[str, Any] = {}
    for rec in selected.itertuples(index=False):
        fid = str(rec.parent_field_id_2025)
        if fid not in id_to_pos:
            raise RuntimeError(f"Selected field missing from pilot: {fid}")
        pos = id_to_pos[fid]
        parent_geom = g.geometry.iloc[pos]
        fm = labels == (pos + 1)
        interior = ndi.binary_erosion(
            fm, structure=np.ones((3, 3), dtype=bool),
            iterations=int(sp["interior_erosion_pixels"]), border_value=0,
        )
        if interior.sum() < int(sp["minimum_valid_pixels"]):
            interior = fm.copy()
        m = interior & all_valid
        if int(m.sum()) < int(sp["minimum_valid_pixels"]):
            raise RuntimeError(f"Selected candidate became invalid during reconstruction: {fid}")
        fit = b2.deterministic_k2(z[m])
        if fit is None:
            raise RuntimeError(f"Selected candidate k2 reconstruction failed: {fid}")
        lab, _c, between, win = fit
        sep = float(between / max(win, 0.15))
        if abs(sep - float(rec.separation_ratio)) > 0.03:
            raise RuntimeError(f"{fid}: reconstructed separation {sep:.4f} != C7C {float(rec.separation_ratio):.4f}")
        cluster_img = np.full((h, w), -1, dtype=np.int8)
        cluster_img[m] = lab
        geoms = []
        for k in (0, 1):
            cm, _count = b2.largest_component(cluster_img == k, ndi)
            geom = b2.mask_geom(cm, transform, parent_geom)
            if geom is None:
                raise RuntimeError(f"Selected candidate child geometry missing: {fid} child {k}")
            geoms.append(geom)
        child_map[fid] = geoms
        parent_map[fid] = parent_geom
    return parent_map, child_map


def render_blind(index: int, parent_geom, child_geoms, raster_dir: Path, out_file: Path, b3, cfg: dict[str, Any]) -> None:
    import rasterio
    from PIL import Image, ImageDraw

    rcfg = cfg["rendering"]
    px = int(rcfg["panel_px"])
    bounds = parent_geom.buffer(float(rcfg["buffer_m"])).bounds
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
                tint = np.array(rcfg["invalid_tint_rgb"], dtype=np.float32)
                q = img[~valid].astype(np.float32)
                img[~valid] = (0.35 * q + 0.65 * tint).astype(np.uint8)
            img = b3.overlay_geom(img, [parent_geom], win, ds.transform, list(rcfg["parent_outline_rgb"]))
            img = b3.overlay_geom(img, child_geoms, win, ds.transform, list(rcfg["child_outline_rgb"]))
            panel = Image.fromarray(img).resize((px, px))
            canvas = Image.new("RGB", (px, px + 25), "white")
            canvas.paste(panel, (0, 25))
            ImageDraw.Draw(canvas).text((5, 5), snap, fill="black")
            panels.append(canvas)

    sheet = Image.new("RGB", (px * 4, px + 60), "white")
    for i, panel in enumerate(panels):
        sheet.paste(panel, (px * i, 35))
    ImageDraw.Draw(sheet).text((5, 8), f"C7D BLIND #{index:02d}", fill="black")
    sheet.save(out_file)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("C7D guards unexpectedly enable forbidden scope")

    freeze_path = Path(cfg["fusion_freeze"])
    if sha256_file(freeze_path) != cfg["expected_fusion_freeze_sha256"]:
        raise RuntimeError("Frozen fusion artifact hash mismatch")
    freeze = read_json(freeze_path)
    if freeze.get("uses_visual_labels") is not False or freeze.get("product_rule") is not False:
        raise RuntimeError("Fusion freeze is no longer label-free/non-product")
    if abs(float(freeze["development_fusion_p90"]) - float(cfg["fusion_tiers"]["development_p90"])) > 1e-6:
        raise RuntimeError("DEV-P90 threshold mismatch")
    if abs(float(freeze["development_fusion_p95"]) - float(cfg["fusion_tiers"]["development_p95"])) > 1e-6:
        raise RuntimeError("DEV-P95 threshold mismatch")

    cdir = Path(cfg["c7c_dir"])
    summary = read_json(cdir / "c7c_summary.json")
    if summary.get("status") != "PASS" or summary.get("fusion_refit") is not False or summary.get("visual_labels_used") is not False:
        raise RuntimeError("C7C is not a clean frozen PASS")
    if summary.get("fusion_freeze_sha256") != cfg["expected_fusion_freeze_sha256"]:
        raise RuntimeError("C7C freeze hash mismatch")

    cand = pd.read_csv(cdir / cfg["candidate_filename"], dtype={"parent_field_id_2025": str})
    selected = select_blind_cases(cand, cfg)

    out = Path(args.output_dir or cfg["output_dir"])
    imgdir = out / "blind_images"
    imgdir.mkdir(parents=True, exist_ok=True)

    parent_map, child_map = reconstruct_child_geometries(selected, cfg)
    b3 = load_module(B3SCRIPT, "c7d_b3")
    rdir = Path(cfg["raster_dir"])

    key_rows = []
    hidden_cols = [
        "fusion_score", "fusion_ge_dev_p90", "fusion_ge_dev_p95", "june_validity_stratum",
        "valid_s2_2026_june", "locked_split_pass", "separation_ratio",
        "prototype_p_splitmerge_2026", "prototype_p_strict_same_2026",
        "true_loo_min_child_dice", "true_loo_mean_child_dice", "true_loo_stable",
        "cdf_prototype_p_splitmerge_2026", "cdf_separation_ratio", "cdf_true_loo_min_child_dice",
    ]
    for rec in selected.itertuples(index=False):
        fid = str(rec.parent_field_id_2025)
        bi = int(rec.blind_index)
        render_blind(bi, parent_map[fid], child_map[fid], rdir, imgdir / f"C7D_{bi:02d}.png", b3, cfg)
        row = {
            "blind_index": bi,
            "parent_field_id_2025": fid,
            "hidden_group": str(rec.hidden_group_internal),
        }
        rd = rec._asdict()
        for col in hidden_cols:
            if col in rd:
                v = rd[col]
                if isinstance(v, (np.bool_, bool)):
                    row[col] = bool(v)
                elif pd.isna(v):
                    row[col] = None
                elif isinstance(v, (np.integer, int)):
                    row[col] = int(v)
                elif isinstance(v, (np.floating, float)):
                    row[col] = float(v)
                else:
                    row[col] = v
        key_rows.append(row)

    key = pd.DataFrame(key_rows).sort_values("blind_index")
    key_path = out / "c7d_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
    key.to_csv(key_path, index=False, encoding="utf-8-sig")
    key_hash = hashlib.sha256(key_path.read_bytes()).hexdigest()

    public_order = pd.DataFrame({"blind_index": key["blind_index"], "image": [f"C7D_{i:02d}.png" for i in key["blind_index"]]})
    public_order.to_csv(out / "c7d_blind_review_order.csv", index=False)

    out_summary = {
        "schema_version": cfg["schema_version"],
        "status": "PASS",
        "fourth_holdout_fields": int(cfg["expected_fields"]),
        "baseline_candidates": int(len(cand)),
        "blind_images": int(len(key)),
        "p90_census_images": int(cfg["blind_visual_set"]["p90_census"]),
        "p95_within_p90_census": int(cfg["expected_fusion_ge_dev_p95"]),
        "near_p90_control_images": int(cfg["blind_visual_set"]["near_p90_controls"]),
        "blind_key_sha256": key_hash,
        "fusion_freeze_sha256": cfg["expected_fusion_freeze_sha256"],
        "fusion_refit": False,
        "visual_labels_used_for_selection": False,
        "thresholds_tuned": False,
        "product_rule_frozen": False,
        "sentinel_hub_pu_used": 0,
        "interpretation_guard": "All 15 C7 DEV-P90 cases are included, including all 9 DEV-P95 cases, so post-reveal visual precision can be reported exactly for those C7 census tiers. The five controls are deliberately difficult near-threshold June-GE80 cases and are not a random negative sample.",
        "next_step": "Label C7D_01..C7D_20 as TYDLIG/MÖJLIG/TVEKSAM/FALSK without opening the blind key; freeze labels before reveal.",
    }
    (out / "c7d_summary.json").write_text(json.dumps(out_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS C7D - FOURTH HOLDOUT BLIND FUSION QA - ZERO PU")
    print(f"BASELINE_CANDIDATES={len(cand)}")
    print(f"BLIND_IMAGES={len(key)} P90_CENSUS=15 P95_WITHIN_P90=9 NEAR_P90_CONTROLS=5")
    print(f"BLIND_KEY_SHA256={key_hash}")
    print(f"FUSION_FREEZE_SHA256={cfg['expected_fusion_freeze_sha256']}")
    print("DO_NOT_OPEN_BLIND_KEY_BEFORE_VISUAL_REVIEW=TRUE")
    print("FUSION_REFIT=FALSE")
    print("VISUAL_LABELS_USED_FOR_SELECTION=FALSE")
    print("THRESHOLDS_TUNED=FALSE")
    print("PRODUCT_RULE_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C7D_STATUS=PASS")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
