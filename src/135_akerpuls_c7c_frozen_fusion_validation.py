#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C7C: fourth geographic holdout, frozen 3-signal fusion validation.

Zero Sentinel API calls. Reuses C7B rasters and applies:
1) B2 split discovery,
2) the previously locked candidate gate,
3) TRUE leave-one-date-out refits,
4) frozen AkerMinne prior + Sentinel + TRUE-LOO empirical-CDF fusion.

No C7 visual labels are used and no thresholds are tuned or refit.
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
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c7c.json"
B2CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_b2.json"
B2SCRIPT = ROOT / "src" / "113_akerpuls_prelim_fields_2026_b2_baseline.py"
B4SCRIPT = ROOT / "src" / "115_akerpuls_prelim_fields_2026_b4_diagnostic.py"
B3SCRIPT = ROOT / "src" / "114_akerpuls_prelim_fields_2026_b3_qa.py"
TRUELOO = ROOT / "src" / "132_akerpuls_true_loo_diagnostic.py"


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


def normalize_field_id(v: Any) -> str:
    s = str(v).strip()
    p = s.split("|")
    if len(p) >= 3 and p[0] == "2025":
        return "|".join(p[1:])
    return s


def empirical_midrank(ref_sorted: np.ndarray, values: np.ndarray) -> np.ndarray:
    ref = np.asarray(ref_sorted, dtype=float)
    x = np.asarray(values, dtype=float)
    left = np.searchsorted(ref, x, side="left")
    right = np.searchsorted(ref, x, side="right")
    return (left + right) / (2.0 * len(ref))


def build_split_validation(cfg: dict[str, Any], out: Path) -> pd.DataFrame:
    import geopandas as gpd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize

    b2cfg = read_json(B2CFG)
    b2 = load_module(B2SCRIPT, "c7c_b2")
    b4 = load_module(B4SCRIPT, "c7c_b4")
    b3 = load_module(B3SCRIPT, "c7c_b3")

    pdir = Path(cfg["pilot_dir"])
    rdir = Path(cfg["raster_dir"])
    g = gpd.read_file(pdir / cfg["pilot_filename"]).to_crs(32633).reset_index(drop=True)
    if len(g) != int(cfg["expected_pilot_fields"]):
        raise RuntimeError(f"Expected {cfg['expected_pilot_fields']} C7 fields, got {len(g)}")

    manifest = read_json(rdir / "c7b_manifest.json")
    if manifest.get("status") != "PASS":
        raise RuntimeError("C7B manifest is not PASS")
    if manifest.get("preprocessing_contract") != "IDENTICAL_TO_B1_C1_C5B":
        raise RuntimeError("C7B preprocessing contract mismatch")
    if manifest.get("fusion_freeze_sha256") != cfg["expected_fusion_freeze_sha256"]:
        raise RuntimeError("C7B fusion-freeze hash mismatch")
    if manifest.get("thresholds_tuned") is not False or manifest.get("fusion_refit") is not False:
        raise RuntimeError("C7B is not a clean frozen holdout")

    if cfg["candidate_discovery_contract"] != "IDENTICAL_TO_B2":
        raise RuntimeError("C7C discovery must remain IDENTICAL_TO_B2")

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
        raise RuntimeError("No all-valid C7 pixels")
    center = np.nanmedian(sample, axis=0)
    mad = np.nanmedian(np.abs(sample - center), axis=0) * 1.4826
    std = np.nanstd(sample, axis=0)
    scale = np.where(mad > 1e-6, mad, np.where(std > 1e-6, std, 1.0))
    z = (raw - center) / scale
    dims_per = len(features)

    sp = b2cfg["split"]
    locked = cfg["locked_split_rule"]
    rows: list[dict[str, Any]] = []

    for pos, row in g.iterrows():
        fid = str(row["parent_field_id_2025"])
        fm = labels == (pos + 1)
        interior = ndi.binary_erosion(
            fm, structure=np.ones((3, 3), dtype=bool),
            iterations=int(sp["interior_erosion_pixels"]), border_value=0,
        )
        if interior.sum() < int(sp["minimum_valid_pixels"]):
            interior = fm.copy()
        m = interior & all_valid
        n = int(m.sum()); total = int(fm.sum())
        if n < int(sp["minimum_valid_pixels"]):
            rows.append({
                "parent_field_id_2025": fid, "discovery_type": "UNCERTAIN",
                "locked_split_pass": False, "reason": "TOO_FEW_ALL_VALID_INTERIOR_PIXELS",
                "pixels": total, "analysis_pixels": n,
            })
            continue

        x = z[m]
        fit = b2.deterministic_k2(x)
        if fit is None:
            rows.append({
                "parent_field_id_2025": fid, "discovery_type": "UNCHANGED",
                "locked_split_pass": False, "reason": "NO_STABLE_K2",
                "pixels": total, "analysis_pixels": n,
            })
            continue
        lab, c, between, win = fit
        sep_ratio = float(between / max(win, 0.15))
        cluster_img = np.full((h, w), -1, dtype=np.int8); cluster_img[m] = lab
        comps = []; counts = []
        for k in (0, 1):
            cm, count = b2.largest_component(cluster_img == k, ndi)
            comps.append(cm); counts.append(count)
        coherence = sum(counts) / max(1, n)
        fractions = [cc / max(1, n) for cc in counts]
        minfrac = min(fractions); minpix = min(counts)

        support = 0; snap_ratios = []
        for sidx in range(4):
            sl = slice(sidx * dims_per, (sidx + 1) * dims_per)
            d = b2.rms(c[0, sl] - c[1, sl])
            xx = x[:, sl]
            rr = np.sqrt(np.mean((xx - c[lab][:, sl]) ** 2, axis=1))
            ww = float(np.sqrt(np.mean(rr ** 2)))
            ratio = float(d / max(ww, 0.15))
            snap_ratios.append(ratio)
            support += int(ratio >= float(sp["snapshot_support_ratio"]))

        baseline = (
            minpix >= int(sp["minimum_child_pixels"])
            and minfrac >= float(sp["minimum_child_fraction"])
            and coherence >= float(sp["minimum_spatial_coherence"])
            and sep_ratio >= float(sp["minimum_total_separation_ratio"])
            and support >= int(sp["minimum_supporting_snapshots"])
        )
        common = {
            "parent_field_id_2025": fid, "pixels": total, "analysis_pixels": n,
            "separation_ratio": round(sep_ratio, 4), "spatial_coherence": round(coherence, 4),
            "min_child_fraction": round(minfrac, 4), "supporting_snapshots": support,
            "sep_april": round(snap_ratios[0], 4), "sep_may": round(snap_ratios[1], 4),
            "sep_june": round(snap_ratios[2], 4), "sep_july": round(snap_ratios[3], 4),
        }
        if not baseline:
            rows.append({**common, "discovery_type": "UNCHANGED", "locked_split_pass": False,
                         "reason": "B2_DISCOVERY_FAIL"})
            continue

        c0 = cluster_img == 0; c1 = cluster_img == 1
        morph, iface = b4.morphology_metrics(c0, c1, interior, fm, ndi, abs(transform.a))
        edge = b4.split_edge_metrics(c0, c1, iface, z, valids, dims_per, ndi, 2)
        edge_ratios = [r[2] for r in edge]
        edge_count = sum(v is not None and v >= float(locked["edge_ratio_threshold"]) for v in edge_ratios)
        loo_row = {"sep_april": snap_ratios[0], "sep_may": snap_ratios[1],
                   "sep_june": snap_ratios[2], "sep_july": snap_ratios[3]}
        loo_all4 = all(b3.split_loo_pass(loo_row, {
            "snapshot_support_ratio": 1.25,
            "minimum_supporting_remaining_snapshots": 2,
            "minimum_remaining_median_ratio": 1.25,
        }))
        lcf = min(float(morph["child0_largest_component_fraction"]),
                  float(morph["child1_largest_component_fraction"]))
        locked_pass = (
            lcf >= float(locked["minimum_largest_component_fraction_each_child"])
            and edge_count >= int(locked["minimum_supporting_edge_snapshots"])
            and ((not bool(locked["require_loo_all4"])) or loo_all4)
        )
        rows.append({
            **common, "discovery_type": "SPLIT_CANDIDATE", "locked_split_pass": bool(locked_pass),
            "reason": "LOCKED_RULE_PASS" if locked_pass else "LOCKED_RULE_REJECT",
            "min_largest_component_fraction": round(lcf, 4), "edge_support_count": int(edge_count),
            "loo_all4": bool(loo_all4),
            "edge_ratio_april": None if edge_ratios[0] is None else round(edge_ratios[0], 4),
            "edge_ratio_may": None if edge_ratios[1] is None else round(edge_ratios[1], 4),
            "edge_ratio_june": None if edge_ratios[2] is None else round(edge_ratios[2], 4),
            "edge_ratio_july": None if edge_ratios[3] is None else round(edge_ratios[3], 4),
        })

    fdf = pd.DataFrame(rows)
    fdf.to_csv(out / "c7c_field_validation.csv", index=False)
    return fdf


def score_fusion(cfg: dict[str, Any], fdf: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    # TRUE LOO on C7 baseline candidates using the frozen implementation.
    tloo = load_module(TRUELOO, "c7c_true_loo")
    b2cfg = read_json(B2CFG)
    b2 = load_module(B2SCRIPT, "c7c_b2_for_loo")
    tlcfg = read_json(ROOT / cfg["true_loo_config"])
    dcfg = {
        "pilot_dir": cfg["pilot_dir"],
        "raster_dir": cfg["raster_dir"],
        "validation_csv": str(out / "c7c_field_validation.csv"),
        "pilot_filename": cfg["pilot_filename"],
    }
    loo = tloo.process_dataset("C7", dcfg, tlcfg, b2, b2cfg)
    loo.to_csv(out / "c7c_true_loo_candidates.csv", index=False)

    freeze_path = Path(cfg["fusion_freeze"])
    got_hash = sha256_file(freeze_path)
    if got_hash != cfg["expected_fusion_freeze_sha256"]:
        raise RuntimeError(f"Frozen fusion hash changed: {got_hash}")
    freeze = read_json(freeze_path)
    if freeze.get("uses_visual_labels") is not False or freeze.get("product_rule") is not False:
        raise RuntimeError("Fusion freeze contract changed")
    p90 = float(freeze["development_fusion_p90"])
    p95 = float(freeze["development_fusion_p95"])
    if abs(p90 - float(cfg["fusion_tiers"]["development_p90"])) > 1e-6 or abs(p95 - float(cfg["fusion_tiers"]["development_p95"])) > 1e-6:
        raise RuntimeError("Configured frozen fusion tiers mismatch freeze artifact")

    cand = fdf[fdf["discovery_type"].astype(str) == "SPLIT_CANDIDATE"].copy()
    cand["field_id_normalized"] = cand["parent_field_id_2025"].map(normalize_field_id)
    loo2 = loo[["field_id_normalized", "true_loo_min_child_dice", "true_loo_mean_child_dice",
                "true_loo_stable"]].copy()
    cand = cand.merge(loo2, on="field_id_normalized", how="left", validate="one_to_one")

    prior = pd.read_csv(Path(cfg["rolling_prior"]), dtype={"field_id": str})
    prior["field_id_normalized"] = prior["field_id"].map(normalize_field_id)
    cand = cand.merge(
        prior[["field_id_normalized", "prototype_p_splitmerge_2026", "prototype_p_strict_same_2026"]],
        on="field_id_normalized", how="left", validate="many_to_one",
    )

    validity = pd.read_csv(Path(cfg["raster_dir"]) / "field_snapshot_validity.csv",
                           dtype={"parent_field_id_2025": str})
    cand = cand.merge(validity[["parent_field_id_2025", "valid_s2_2026_june"]],
                      on="parent_field_id_2025", how="left", validate="one_to_one")

    signals = list(freeze["signals"])
    weights = np.asarray(freeze["weights"], dtype=float)
    parts = []
    for sig in signals:
        cand[sig] = pd.to_numeric(cand[sig], errors="coerce")
        if cand[sig].isna().any():
            raise RuntimeError(f"C7 candidate signal missing: {sig}")
        ref = np.asarray(freeze["reference_sorted_values"][sig], dtype=float)
        cdf = empirical_midrank(ref, cand[sig].to_numpy(dtype=float))
        cand[f"cdf_{sig}"] = cdf
        parts.append(cdf)
    cand["fusion_score"] = np.vstack(parts).T @ weights
    cand["fusion_ge_dev_p90"] = cand["fusion_score"] >= p90
    cand["fusion_ge_dev_p95"] = cand["fusion_score"] >= p95

    high = float(cfg["june_validity_strata"]["high"])
    med = float(cfg["june_validity_strata"]["medium"])
    jv = pd.to_numeric(cand["valid_s2_2026_june"], errors="coerce")
    cand["june_validity_stratum"] = np.where(jv >= high, "GE80", np.where(jv >= med, "50_80", "LT50"))
    cand = cand.sort_values(["fusion_score", "parent_field_id_2025"], ascending=[False, True]).reset_index(drop=True)
    cand.to_csv(out / "c7c_fusion_candidates.csv", index=False, encoding="utf-8-sig")

    summary = {
        "schema_version": cfg["schema_version"], "status": "PASS",
        "fields": int(len(fdf)),
        "uncertain": int((fdf["discovery_type"] == "UNCERTAIN").sum()),
        "baseline_split_candidates": int(len(cand)),
        "locked_split_candidates": int(cand["locked_split_pass"].fillna(False).astype(bool).sum()),
        "fusion_ge_dev_p90": int(cand["fusion_ge_dev_p90"].sum()),
        "fusion_ge_dev_p95": int(cand["fusion_ge_dev_p95"].sum()),
        "fusion_dev_p90": p90, "fusion_dev_p95": p95,
        "fusion_freeze_sha256": got_hash,
        "june_strata": {
            s: {
                "candidates": int((cand["june_validity_stratum"] == s).sum()),
                "p90": int(((cand["june_validity_stratum"] == s) & cand["fusion_ge_dev_p90"]).sum()),
                "p95": int(((cand["june_validity_stratum"] == s) & cand["fusion_ge_dev_p95"]).sum()),
            } for s in ("GE80", "50_80", "LT50")
        },
        "fusion_refit": False, "visual_labels_used": False,
        "thresholds_tuned": False, "product_rule_frozen": False,
        "sentinel_hub_pu_used": 0,
    }
    (out / "c7c_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cand, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("C7C guards unexpectedly enable forbidden scope")
    out = Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True, exist_ok=True)

    fdf = build_split_validation(cfg, out)
    cand, s = score_fusion(cfg, fdf, out)

    print("AKERPULS C7C - FOURTH HOLDOUT FROZEN FUSION VALIDATION - ZERO PU")
    print(f"FIELDS={s['fields']} UNCERTAIN={s['uncertain']}")
    print(f"BASELINE_SPLIT_CANDIDATES={s['baseline_split_candidates']}")
    print(f"LOCKED_SPLIT_CANDIDATES={s['locked_split_candidates']}")
    print(f"FUSION_GE_DEV_P90={s['fusion_ge_dev_p90']} THRESHOLD={s['fusion_dev_p90']:.6f}")
    print(f"FUSION_GE_DEV_P95={s['fusion_ge_dev_p95']} THRESHOLD={s['fusion_dev_p95']:.6f}")
    for st in ("GE80", "50_80", "LT50"):
        x = s["june_strata"][st]
        print(f"JUNE_{st}_CANDIDATES={x['candidates']} P90={x['p90']} P95={x['p95']}")
    if len(cand):
        print(f"FUSION_SCORE_C7_P50={float(cand.fusion_score.quantile(.5)):.6f} P90={float(cand.fusion_score.quantile(.9)):.6f} MAX={float(cand.fusion_score.max()):.6f}")
    print(f"FUSION_FREEZE_SHA256={s['fusion_freeze_sha256']}")
    print("FUSION_REFIT=FALSE")
    print("VISUAL_LABELS_USED=FALSE")
    print("THRESHOLDS_TUNED=FALSE")
    print("PRODUCT_RULE_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C7C_STATUS=PASS")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
