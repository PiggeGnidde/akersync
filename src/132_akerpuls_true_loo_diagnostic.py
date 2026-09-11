#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C6 TRUE leave-one-date-out segmentation diagnostic for AkerPuls 2026.

Zero Sentinel API calls. Re-fits deterministic B2 k=2 segmentation after omitting
one complete snapshot at a time and compares the resulting child masks with the
four-date reference segmentation under optimal binary label permutation.

The diagnostic stability criterion is frozen in config before outcomes are seen.
It is NOT a product split rule.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerpuls_true_loo_diagnostic_v0.json"
SNAP_NAMES = ["APRIL", "MAY", "JUNE", "JULY"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize_field_id(value: Any) -> str:
    s = str(value).strip()
    parts = s.split("|")
    if len(parts) >= 3 and parts[0] == "2025":
        return "|".join(parts[1:])
    return s


def extract_features(cubes: list[np.ndarray], snap_indices: list[int], mask: np.ndarray) -> np.ndarray:
    parts = [cubes[i][:, mask].T.astype(np.float64, copy=False) for i in snap_indices]
    return np.concatenate(parts, axis=1)


def robust_scale_for_variant(
    cubes: list[np.ndarray],
    valids: list[np.ndarray],
    field_labels: np.ndarray,
    snap_indices: list[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    valid = np.logical_and.reduce([valids[i] for i in snap_indices])
    pilotmask = (field_labels > 0) & valid
    if not pilotmask.any():
        raise RuntimeError(f"No valid pilot pixels for snapshots {snap_indices}")
    sample = extract_features(cubes, snap_indices, pilotmask)
    center = np.nanmedian(sample, axis=0)
    mad = np.nanmedian(np.abs(sample - center), axis=0) * 1.4826
    std = np.nanstd(sample, axis=0)
    scale = np.where(mad > 1e-6, mad, np.where(std > 1e-6, std, 1.0))
    return valid, center, scale


def fit_mask(
    b2,
    cubes: list[np.ndarray],
    mask: np.ndarray,
    snap_indices: list[int],
    center: np.ndarray,
    scale: np.ndarray,
):
    if not mask.any():
        return None
    raw = extract_features(cubes, snap_indices, mask)
    z = (raw - center) / scale
    return b2.deterministic_k2(z)


def dice_binary(a: np.ndarray, b: np.ndarray) -> float:
    aa = np.asarray(a, dtype=bool)
    bb = np.asarray(b, dtype=bool)
    den = int(aa.sum()) + int(bb.sum())
    if den == 0:
        return 1.0
    return float(2 * np.logical_and(aa, bb).sum() / den)


def optimal_binary_dice(reference: np.ndarray, predicted: np.ndarray) -> tuple[float, float, bool]:
    ref = np.asarray(reference, dtype=np.int8)
    pred = np.asarray(predicted, dtype=np.int8)
    if len(ref) != len(pred):
        raise ValueError("Reference and predicted labels differ in length")
    d_id = (dice_binary(ref == 0, pred == 0), dice_binary(ref == 1, pred == 1))
    d_sw = (dice_binary(ref == 0, pred == 1), dice_binary(ref == 1, pred == 0))
    if np.mean(d_sw) > np.mean(d_id):
        return float(d_sw[0]), float(d_sw[1]), True
    return float(d_id[0]), float(d_id[1]), False


def auc_rank(score: pd.Series, positive: pd.Series) -> tuple[float, int, int, float]:
    x = pd.to_numeric(score, errors="coerce")
    y = positive.astype(bool)
    ok = x.notna()
    pos = x[ok & y].to_numpy(dtype=float)
    neg = x[ok & ~y].to_numpy(dtype=float)
    if len(pos) == 0 or len(neg) == 0:
        return float("nan"), len(pos), len(neg), float("nan")
    u = mannwhitneyu(pos, neg, alternative="two-sided")
    return float(u.statistic) / float(len(pos) * len(neg)), len(pos), len(neg), float(u.pvalue)


def build_blind_cases(cfg: dict[str, Any]) -> pd.DataFrame:
    br = cfg["blind_review"]
    frames = []
    specs = [
        ("C", Path(br["c3_key"]), list(br["c3_labels"]), "C3"),
        ("C5", Path(br["c5d_key"]), list(br["c5d_labels"]), "C5D"),
    ]
    for dataset, path, labels, source in specs:
        if not path.exists():
            raise FileNotFoundError(path)
        x = pd.read_csv(path, dtype=str).sort_values("blind_index").reset_index(drop=True)
        if len(x) != len(labels):
            raise RuntimeError(f"{source}: blind key rows {len(x)} != labels {len(labels)}")
        x["blind_index"] = pd.to_numeric(x["blind_index"], errors="raise").astype(int)
        if x["blind_index"].tolist() != list(range(1, len(x) + 1)):
            raise RuntimeError(f"{source}: blind indices not consecutive")
        x["visual_label"] = labels
        x["blind_source"] = source
        x["dataset"] = dataset
        x["field_id_normalized"] = x["parent_field_id_2025"].map(normalize_field_id)
        frames.append(x)
    return pd.concat(frames, ignore_index=True, sort=False)


def process_dataset(name: str, dcfg: dict[str, Any], cfg: dict[str, Any], b2, b2cfg: dict[str, Any]) -> pd.DataFrame:
    import geopandas as gpd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize

    pdir = Path(dcfg["pilot_dir"])
    rdir = Path(dcfg["raster_dir"])
    vpath = Path(dcfg["validation_csv"])
    gpath = pdir / dcfg["pilot_filename"]
    for p in (gpath, vpath):
        if not p.exists():
            raise FileNotFoundError(p)

    g = gpd.read_file(gpath).to_crs(32633).reset_index(drop=True)
    vdf = pd.read_csv(vpath, dtype={"parent_field_id_2025": str})
    candidates = vdf[vdf["discovery_type"].astype(str) == "SPLIT_CANDIDATE"].copy()
    features = list(b2cfg["feature_bands_per_snapshot"])
    cubes, valids, _rgbs, transform, _crs, (h, w) = b2.load_snapshots(rdir, features)
    field_labels = rasterize(
        [(geom, i + 1) for i, geom in enumerate(g.geometry)],
        out_shape=(h, w), transform=transform, fill=0, dtype="int32", all_touched=False,
    )
    ids = g["parent_field_id_2025"].astype(str).tolist()
    id_to_pos = {fid: i for i, fid in enumerate(ids)}

    variants: dict[str, dict[str, Any]] = {}
    all_idx = [0, 1, 2, 3]
    valid, center, scale = robust_scale_for_variant(cubes, valids, field_labels, all_idx)
    variants["FULL4"] = {"snaps": all_idx, "valid": valid, "center": center, "scale": scale}
    for omit in range(4):
        keep = [i for i in all_idx if i != omit]
        valid, center, scale = robust_scale_for_variant(cubes, valids, field_labels, keep)
        variants[f"OMIT_{SNAP_NAMES[omit]}"] = {"snaps": keep, "valid": valid, "center": center, "scale": scale}

    contract = cfg["true_loo_contract"]
    minpix = int(contract["minimum_reference_comparison_pixels"])
    minfrac_req = float(contract["minimum_child_fraction_each_omission_on_comparison_domain"])
    mindice_req = float(contract["minimum_each_child_dice_each_omission"])
    mean_req = float(contract["minimum_mean_matched_child_dice_across_all_omissions"])
    sp = b2cfg["split"]

    rows: list[dict[str, Any]] = []
    for rec in candidates.itertuples(index=False):
        fid = str(rec.parent_field_id_2025)
        if fid not in id_to_pos:
            raise RuntimeError(f"{name}: candidate {fid} missing from pilot geometry")
        pos = id_to_pos[fid]
        fm = field_labels == (pos + 1)
        interior = ndi.binary_erosion(
            fm, structure=np.ones((3, 3), dtype=bool),
            iterations=int(sp["interior_erosion_pixels"]), border_value=0,
        )
        if interior.sum() < int(sp["minimum_valid_pixels"]):
            interior = fm.copy()

        ref_state = variants["FULL4"]
        ref_mask = interior & ref_state["valid"]
        nref = int(ref_mask.sum())
        base = {
            "dataset": name,
            "parent_field_id_2025": fid,
            "field_id_normalized": normalize_field_id(fid),
            "reference_pixels": nref,
            "existing_separation_ratio": pd.to_numeric(getattr(rec, "separation_ratio", np.nan), errors="coerce"),
            "existing_locked_split_pass": bool(getattr(rec, "locked_split_pass", False)),
        }
        if "high_confidence_split" in candidates.columns:
            base["existing_high_confidence_split"] = bool(getattr(rec, "high_confidence_split", False))
        else:
            base["existing_high_confidence_split"] = False

        if nref < minpix:
            base.update({"reference_fit_ok": False, "reference_separation_ratio": np.nan, "true_loo_refits_ok": 0,
                         "true_loo_min_child_dice": 0.0, "true_loo_mean_child_dice": 0.0,
                         "true_loo_min_child_fraction": 0.0, "true_loo_stable": False,
                         "true_loo_failure_reason": "TOO_FEW_REFERENCE_PIXELS"})
            rows.append(base)
            continue

        fit_ref = fit_mask(b2, cubes, ref_mask, ref_state["snaps"], ref_state["center"], ref_state["scale"])
        if fit_ref is None:
            base.update({"reference_fit_ok": False, "reference_separation_ratio": np.nan, "true_loo_refits_ok": 0,
                         "true_loo_min_child_dice": 0.0, "true_loo_mean_child_dice": 0.0,
                         "true_loo_min_child_fraction": 0.0, "true_loo_stable": False,
                         "true_loo_failure_reason": "REFERENCE_K2_FAILED"})
            rows.append(base)
            continue

        ref_lab, ref_centers, ref_between, ref_within = fit_ref
        ref_sep = float(ref_between / max(ref_within, 0.15))
        existing_sep = base["existing_separation_ratio"]
        if pd.notna(existing_sep) and abs(float(existing_sep) - ref_sep) > 0.03:
            raise RuntimeError(f"{name} {fid}: reconstructed full4 separation {ref_sep:.4f} != existing {float(existing_sep):.4f}")

        ref_flat = np.flatnonzero(ref_mask.ravel())
        all_child_dice: list[float] = []
        all_minfrac: list[float] = []
        omission_ok = 0
        per: dict[str, Any] = {}
        failures: list[str] = []

        for omit_idx, snap_name in enumerate(SNAP_NAMES):
            key = f"OMIT_{snap_name}"
            state = variants[key]
            m3 = interior & state["valid"]
            n3 = int(m3.sum())
            per[f"omit_{snap_name.lower()}_pixels"] = n3
            if n3 < minpix:
                per[f"omit_{snap_name.lower()}_fit_ok"] = False
                per[f"omit_{snap_name.lower()}_dice0"] = 0.0
                per[f"omit_{snap_name.lower()}_dice1"] = 0.0
                per[f"omit_{snap_name.lower()}_min_dice"] = 0.0
                per[f"omit_{snap_name.lower()}_mean_dice"] = 0.0
                per[f"omit_{snap_name.lower()}_min_child_fraction"] = 0.0
                failures.append(f"{snap_name}:TOO_FEW_PIXELS")
                all_child_dice.extend([0.0, 0.0]); all_minfrac.append(0.0)
                continue

            fit3 = fit_mask(b2, cubes, m3, state["snaps"], state["center"], state["scale"])
            if fit3 is None:
                per[f"omit_{snap_name.lower()}_fit_ok"] = False
                per[f"omit_{snap_name.lower()}_dice0"] = 0.0
                per[f"omit_{snap_name.lower()}_dice1"] = 0.0
                per[f"omit_{snap_name.lower()}_min_dice"] = 0.0
                per[f"omit_{snap_name.lower()}_mean_dice"] = 0.0
                per[f"omit_{snap_name.lower()}_min_child_fraction"] = 0.0
                failures.append(f"{snap_name}:K2_FAILED")
                all_child_dice.extend([0.0, 0.0]); all_minfrac.append(0.0)
                continue

            lab3 = fit3[0]
            m3_flat = np.flatnonzero(m3.ravel())
            loc = np.searchsorted(m3_flat, ref_flat)
            if np.any(loc >= len(m3_flat)) or not np.array_equal(m3_flat[loc], ref_flat):
                raise RuntimeError(f"{name} {fid} {key}: reference domain is not subset of three-date domain")
            pred_ref = lab3[loc]
            frac0 = float(np.mean(pred_ref == 0)); frac1 = float(np.mean(pred_ref == 1))
            minfrac = min(frac0, frac1)
            d0, d1, swapped = optimal_binary_dice(ref_lab, pred_ref)
            md = min(d0, d1); av = 0.5 * (d0 + d1)
            per[f"omit_{snap_name.lower()}_fit_ok"] = True
            per[f"omit_{snap_name.lower()}_labels_swapped"] = bool(swapped)
            per[f"omit_{snap_name.lower()}_dice0"] = d0
            per[f"omit_{snap_name.lower()}_dice1"] = d1
            per[f"omit_{snap_name.lower()}_min_dice"] = md
            per[f"omit_{snap_name.lower()}_mean_dice"] = av
            per[f"omit_{snap_name.lower()}_min_child_fraction"] = minfrac
            omission_ok += 1
            all_child_dice.extend([d0, d1]); all_minfrac.append(minfrac)
            if minfrac < minfrac_req:
                failures.append(f"{snap_name}:CHILD_FRACTION")
            if md < mindice_req:
                failures.append(f"{snap_name}:DICE")

        mean_dice = float(np.mean(all_child_dice)) if all_child_dice else 0.0
        min_dice = float(np.min(all_child_dice)) if all_child_dice else 0.0
        min_child_fraction = float(np.min(all_minfrac)) if all_minfrac else 0.0
        stable = (
            omission_ok == 4
            and min_child_fraction >= minfrac_req
            and min_dice >= mindice_req
            and mean_dice >= mean_req
        )
        if mean_dice < mean_req:
            failures.append("MEAN_DICE")
        base.update({
            "reference_fit_ok": True,
            "reference_separation_ratio": ref_sep,
            "true_loo_refits_ok": omission_ok,
            "true_loo_min_child_dice": min_dice,
            "true_loo_mean_child_dice": mean_dice,
            "true_loo_min_child_fraction": min_child_fraction,
            "true_loo_stable": bool(stable),
            "true_loo_failure_reason": "PASS" if stable else ";".join(sorted(set(failures))) if failures else "CRITERION_FAIL",
        })
        base.update(per)
        rows.append(base)

    out = pd.DataFrame(rows)
    if len(out) != len(candidates):
        raise RuntimeError(f"{name}: output rows {len(out)} != candidate rows {len(candidates)}")
    return out


def report_auc(frame: pd.DataFrame, positives: list[str], score: str, label: str) -> None:
    positive = frame["visual_label"].isin(positives)
    auc, npos, nneg, p = auc_rank(frame[score], positive)
    pos_med = float(pd.to_numeric(frame.loc[positive, score], errors="coerce").median())
    neg_med = float(pd.to_numeric(frame.loc[~positive, score], errors="coerce").median())
    print(f"{label} AUC={auc:.3f} MED_POS={pos_med:.4f} MED_NEG={neg_med:.4f} GAP={pos_med-neg_med:+.4f} N_POS={npos} N_NEG={nneg} P={p:.4f}")


def report_stable(frame: pd.DataFrame, positives: list[str], label: str) -> None:
    pos = frame["visual_label"].isin(positives)
    s = frame["true_loo_stable"].astype(bool)
    np_ = int(pos.sum()); nn = int((~pos).sum())
    sp = int((s & pos).sum()); sn = int((s & ~pos).sum())
    print(f"{label} STABLE_POS={sp}/{np_} RATE_POS={sp/max(1,np_):.3f} STABLE_NEG={sn}/{nn} RATE_NEG={sn/max(1,nn):.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("TRUE-LOO guards unexpectedly enable forbidden scope")
    b2cfg_path = ROOT / cfg["b2_config"]
    b2script_path = ROOT / cfg["b2_script"]
    b2cfg = read_json(b2cfg_path)
    b2 = load_module(b2script_path, "akerpuls_b2_true_loo")
    outdir = Path(args.output_dir or cfg["output_dir"])
    outdir.mkdir(parents=True, exist_ok=True)

    frames = []
    for name in ("C", "C5"):
        print(f"TRUE_LOO_DATASET={name}", flush=True)
        x = process_dataset(name, cfg["datasets"][name], cfg, b2, b2cfg)
        x.to_csv(outdir / f"true_loo_candidates_{name.lower()}.csv", index=False)
        frames.append(x)
    cand = pd.concat(frames, ignore_index=True)
    cand.to_csv(outdir / "true_loo_candidates_all.csv", index=False)

    blind = build_blind_cases(cfg)
    joined = blind.merge(
        cand,
        on=["dataset", "field_id_normalized"],
        how="left",
        validate="one_to_one",
        suffixes=("_blind", ""),
    )
    if joined["true_loo_mean_child_dice"].isna().any():
        bad = joined.loc[joined["true_loo_mean_child_dice"].isna(), ["blind_source", "blind_index", "parent_field_id_2025_blind"]]
        raise RuntimeError("Blind cases missing TRUE-LOO rows:\n" + bad.to_string(index=False))
    joined.to_csv(outdir / "true_loo_blind_cases_32.csv", index=False, encoding="utf-8-sig")

    summary = {
        "schema_version": cfg["schema_version"],
        "status": "PASS",
        "candidate_rows": int(len(cand)),
        "candidate_rows_c": int((cand["dataset"] == "C").sum()),
        "candidate_rows_c5": int((cand["dataset"] == "C5").sum()),
        "true_loo_stable": int(cand["true_loo_stable"].sum()),
        "blind_cases": int(len(joined)),
        "thresholds_tuned": False,
        "new_product_split_rule": False,
        "product_thresholds_frozen": False,
        "sentinel_hub_pu_used": 0,
        "true_loo_contract": cfg["true_loo_contract"],
    }
    (outdir / "true_loo_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS TRUE LEAVE-ONE-DATE-OUT SEGMENTATION DIAGNOSTIC")
    for name in ("C", "C5"):
        x = cand[cand["dataset"] == name]
        print(f"{name}_CANDIDATES={len(x)} TRUE_LOO_STABLE={int(x.true_loo_stable.sum())} RATE={float(x.true_loo_stable.mean()):.4f} MED_MIN_DICE={float(x.true_loo_min_child_dice.median()):.4f} MED_MEAN_DICE={float(x.true_loo_mean_child_dice.median()):.4f}")
    print(f"ALL_CANDIDATES={len(cand)} TRUE_LOO_STABLE={int(cand.true_loo_stable.sum())} RATE={float(cand.true_loo_stable.mean()):.4f}")

    report_auc(joined, ["TYDLIG"], "true_loo_min_child_dice", "ALL32_STRICT_TRUE_LOO_MIN_DICE")
    report_auc(joined, ["TYDLIG", "MÖJLIG"], "true_loo_min_child_dice", "ALL32_LIBERAL_TRUE_LOO_MIN_DICE")
    report_auc(joined, ["TYDLIG"], "true_loo_mean_child_dice", "ALL32_STRICT_TRUE_LOO_MEAN_DICE")
    report_auc(joined, ["TYDLIG", "MÖJLIG"], "true_loo_mean_child_dice", "ALL32_LIBERAL_TRUE_LOO_MEAN_DICE")
    report_stable(joined, ["TYDLIG"], "ALL32_STRICT_TRUE_LOO_STABLE")
    report_stable(joined, ["TYDLIG", "MÖJLIG"], "ALL32_LIBERAL_TRUE_LOO_STABLE")

    c3pass = joined[(joined["blind_source"] == "C3") & (joined["hidden_group"] == "LOCKED_PASS_REPRESENTATIVE")]
    c5hc = joined[(joined["blind_source"] == "C5D") & (joined["hidden_group"] == "HIGH_CONFIDENCE_CENSUS")]
    report_auc(c3pass, ["TYDLIG", "MÖJLIG"], "true_loo_min_child_dice", "C3_LOCKED_PASS_LIBERAL_TRUE_LOO_MIN_DICE")
    report_stable(c3pass, ["TYDLIG", "MÖJLIG"], "C3_LOCKED_PASS_LIBERAL_TRUE_LOO_STABLE")
    report_auc(c5hc, ["TYDLIG"], "true_loo_min_child_dice", "C5D_HC_STRICT_TRUE_LOO_MIN_DICE")
    report_stable(c5hc, ["TYDLIG"], "C5D_HC_STRICT_TRUE_LOO_STABLE")

    print("HISTORICAL_LOO_ALL4_REDEFINED=FALSE")
    print("THRESHOLDS_TUNED=FALSE")
    print("NEW_PRODUCT_SPLIT_RULE=FALSE")
    print("PRODUCT_THRESHOLDS_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("TRUE_LOO_DIAGNOSTIC_STATUS=PASS")
    print(f"OUTPUT={outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
