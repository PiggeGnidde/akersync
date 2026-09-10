#!/usr/bin/env python3
"""STOPPUNKT C4: post-reveal high-confidence split diagnostic. Zero API calls.

Uses C3 as DEVELOPMENT data only. The existing SPLIT_CANDIDATE rule remains untouched.
Reconstructs richer topology/morphology for all C baseline split candidates, marks the
43 locked-pass candidates plus near-rejects, and evaluates a simple post-hoc
HIGH_CONFIDENCE_SPLIT candidate family that must be validated on a new geography.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c4.json"
C2CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c2.json"
B2CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_b2.json"
B2SCRIPT = ROOT / "src" / "113_akerpuls_prelim_fields_2026_b2_baseline.py"
B4SCRIPT = ROOT / "src" / "115_akerpuls_prelim_fields_2026_b4_diagnostic.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def largest_component(mask, ndi):
    labs, n = ndi.label(mask, structure=np.ones((3, 3), dtype=np.uint8))
    if n <= 0:
        return np.zeros_like(mask, dtype=bool), 0, 0, 0.0
    counts = np.bincount(labs.ravel())
    counts[0] = 0
    lab = int(np.argmax(counts))
    largest = labs == lab
    total = int(mask.sum())
    return largest, int(n), int(largest.sum()), float(largest.sum() / max(1, total))


def boundary_pixels(mask, ndi):
    return mask & ~ndi.binary_erosion(
        mask, structure=np.ones((3, 3), dtype=bool), border_value=0
    )


def count_holes(component, support, ndi):
    filled = ndi.binary_fill_holes(component)
    holes = filled & ~component & support
    labs, n = ndi.label(holes, structure=np.ones((3, 3), dtype=np.uint8))
    if n <= 0:
        return 0, 0
    counts = np.bincount(labs.ravel())
    counts[0] = 0
    return int(n), int(counts.sum())


def interface_linearity(iface):
    yy, xx = np.nonzero(iface)
    if len(xx) < 3:
        return None, None
    pts = np.column_stack([xx.astype(float), yy.astype(float)])
    pts -= pts.mean(axis=0, keepdims=True)
    cov = (pts.T @ pts) / max(1, len(pts) - 1)
    vals = np.sort(np.maximum(np.linalg.eigvalsh(cov), 0.0))
    major = float(vals[-1])
    minor = float(vals[0])
    if major <= 1e-12:
        return 0.0, 1.0
    width_to_length = math.sqrt(minor / major)
    return float(1.0 - width_to_length), float(width_to_length)


def topology_metrics(c0, c1, interior, iface, ndi):
    perimeter = boundary_pixels(interior, ndi)
    perimeter_dil = ndi.binary_dilation(perimeter, structure=np.ones((3, 3), dtype=bool))
    ppx = int(perimeter.sum())

    l0, n0, _l0px, lcf0 = largest_component(c0, ndi)
    l1, n1, _l1px, lcf1 = largest_component(c1, ndi)

    contact0 = int((l0 & perimeter_dil).sum())
    contact1 = int((l1 & perimeter_dil).sum())
    largest_touch0 = contact0 > 0
    largest_touch1 = contact1 > 0
    any_touch0 = bool((c0 & perimeter_dil).any())
    any_touch1 = bool((c1 & perimeter_dil).any())

    _iface_labs, iface_n = ndi.label(iface, structure=np.ones((3, 3), dtype=np.uint8))
    iface_px = int(iface.sum())
    endmask = iface & perimeter_dil
    _, endpoint_components = ndi.label(endmask, structure=np.ones((3, 3), dtype=np.uint8))
    anis, width_ratio = interface_linearity(iface)

    h0n, h0px = count_holes(l0, interior, ndi)
    h1n, h1px = count_holes(l1, interior, ndi)

    c0px = int(c0.sum())
    c1px = int(c1.sum())
    total = max(1, c0px + c1px)
    min_child_share = min(c0px, c1px) / total

    return {
        "child0_components": n0,
        "child1_components": n1,
        "component_count_total": n0 + n1,
        "child0_lcf": lcf0,
        "child1_lcf": lcf1,
        "min_lcf": min(lcf0, lcf1),
        "largest_child0_touches_outer": largest_touch0,
        "largest_child1_touches_outer": largest_touch1,
        "both_largest_children_touch_outer": bool(largest_touch0 and largest_touch1),
        "child0_any_component_touches_outer": any_touch0,
        "child1_any_component_touches_outer": any_touch1,
        "both_children_any_component_touch_outer": bool(any_touch0 and any_touch1),
        "largest_child0_outer_contact_pixels": contact0,
        "largest_child1_outer_contact_pixels": contact1,
        "min_largest_child_outer_contact_pixels": min(contact0, contact1),
        "largest_child0_outer_contact_parent_fraction": contact0 / max(1, ppx),
        "largest_child1_outer_contact_parent_fraction": contact1 / max(1, ppx),
        "min_largest_child_outer_contact_parent_fraction": min(contact0, contact1) / max(1, ppx),
        "parent_perimeter_pixels": ppx,
        "interface_pixels": iface_px,
        "interface_components": int(iface_n),
        "interface_outer_endpoint_components": int(endpoint_components),
        "interface_norm_sqrt_area": iface_px / math.sqrt(total),
        "interface_anisotropy": anis,
        "interface_width_to_length": width_ratio,
        "child0_holes": h0n,
        "child1_holes": h1n,
        "child_holes_total": h0n + h1n,
        "child0_hole_pixels": h0px,
        "child1_hole_pixels": h1px,
        "min_child_share": min_child_share,
    }


def c3_label_map(cfg):
    out = {}
    for item in cfg["c3_development_labels"]:
        out[str(item["parent_field_id_2025"])] = {
            "blind_index": int(item["blind_index"]),
            "visual_label": str(item["visual_label"]),
        }
    return out


def as_bool_series(s):
    if s.dtype == bool:
        return s.fillna(False)
    return s.map(lambda v: str(v).strip().lower() in {"true", "1", "yes"} if v is not None else False)


def eval_rule(df, sep_thr, require_largest_touch, max_components, max_holes,
              max_iface_components, min_outer_contact, min_edge_median):
    ok = as_bool_series(df["locked_split_pass"])
    ok &= df["separation_ratio"].astype(float) >= float(sep_thr)
    if require_largest_touch:
        ok &= as_bool_series(df["both_largest_children_touch_outer"])
    ok &= df["component_count_total"].astype(float) <= float(max_components)
    ok &= df["child_holes_total"].astype(float) <= float(max_holes)
    ok &= df["interface_components"].astype(float) <= float(max_iface_components)
    ok &= df["min_largest_child_outer_contact_parent_fraction"].astype(float) >= float(min_outer_contact)
    ok &= df["edge_ratio_median"].astype(float) >= float(min_edge_median)
    return ok


def main():
    import geopandas as gpd
    import pandas as pd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize

    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--c2-dir")
    ap.add_argument("--c3-dir")
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    c2cfg = json.loads(C2CFG.read_text(encoding="utf-8"))
    b2cfg = json.loads(B2CFG.read_text(encoding="utf-8"))

    if cfg["split_candidate_rule_unchanged"] != c2cfg["locked_split_rule"]:
        raise RuntimeError("C4 candidate rule differs from C2 locked rule")
    if cfg["high_confidence_candidate"]["minimum_separation_ratio"] != 4.0:
        raise RuntimeError("C4 documented post-hoc separation candidate must remain 4.0")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("C4 guards unexpectedly enable forbidden scope")

    pdir = Path(args.pilot_dir or cfg["pilot_dir"])
    rdir = Path(args.raster_dir or cfg["raster_dir"])
    c2dir = Path(args.c2_dir or cfg["c2_dir"])
    c3dir = Path(args.c3_dir or cfg["c3_dir"])
    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    key_path = c3dir / "c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
    key_hash = hashlib.sha256(key_path.read_bytes()).hexdigest()
    if key_hash != cfg["c3_blind_key_sha256"]:
        raise RuntimeError(f"C3 blind-key hash mismatch: {key_hash}")

    c2sum = json.loads((c2dir / "c2_summary.json").read_text(encoding="utf-8"))
    if c2sum.get("status") != "PASS" or c2sum.get("thresholds_tuned") is not False:
        raise RuntimeError("C2 is not an untuned PASS")

    fdf = pd.read_csv(c2dir / "c2_field_validation.csv", dtype={"parent_field_id_2025": str})
    fdf["locked_split_pass"] = as_bool_series(fdf["locked_split_pass"])
    baseline = fdf[fdf["discovery_type"].eq("SPLIT_CANDIDATE")].copy()
    if len(baseline) != int(c2sum["baseline_split_candidates"]):
        raise RuntimeError("C2 baseline split count mismatch")
    locked_n = int(as_bool_series(baseline["locked_split_pass"]).sum())
    if locked_n != int(c2sum["locked_split_candidates"]):
        raise RuntimeError("C2 locked split count mismatch")

    g = gpd.read_file(pdir / "c0_pilot_fields_2025.gpkg").to_crs(32633).reset_index(drop=True)
    if len(g) != int(c2sum["pilot_fields"]):
        raise RuntimeError("C4 pilot geometry count mismatch")

    b2 = load_module(B2SCRIPT, "akerpuls_c4_b2")
    b4 = load_module(B4SCRIPT, "akerpuls_c4_b4")
    feats = list(b2cfg["feature_bands_per_snapshot"])
    cubes, valids, _rgbs, transform, crs, (h, w) = b2.load_snapshots(rdir, feats)
    labels = rasterize(
        [(geom, i + 1) for i, geom in enumerate(g.geometry)],
        out_shape=(h, w), transform=transform, fill=0, dtype="int32", all_touched=False
    )
    all_valid = np.logical_and.reduce(valids)
    raw = np.concatenate(cubes, axis=0).transpose(1, 2, 0)
    sample = raw[(labels > 0) & all_valid]
    center = np.nanmedian(sample, axis=0)
    mad = np.nanmedian(np.abs(sample - center), axis=0) * 1.4826
    std = np.nanstd(sample, axis=0)
    scale = np.where(mad > 1e-6, mad, np.where(std > 1e-6, std, 1.0))
    z = (raw - center) / scale
    dims_per = len(feats)

    id_to_pos = {str(fid): i for i, fid in enumerate(g["parent_field_id_2025"].astype(str))}
    sp = b2cfg["split"]
    rows = []

    for rec in baseline.itertuples(index=False):
        fid = str(rec.parent_field_id_2025)
        pos = id_to_pos[fid]
        fm = labels == (pos + 1)
        interior = ndi.binary_erosion(
            fm, structure=np.ones((3, 3), dtype=bool),
            iterations=int(sp["interior_erosion_pixels"]), border_value=0
        )
        if interior.sum() < int(sp["minimum_valid_pixels"]):
            interior = fm.copy()
        m = interior & all_valid
        if int(m.sum()) < int(sp["minimum_valid_pixels"]):
            raise RuntimeError(f"Baseline split has too few C4 analysis pixels: {fid}")

        x = z[m]
        fit = b2.deterministic_k2(x)
        if fit is None:
            raise RuntimeError(f"Cannot reconstruct C2 split candidate {fid}")
        lab, centroids, between, within = fit
        sep_ratio = float(between / max(within, 0.15))

        cluster_img = np.full((h, w), -1, dtype=np.int8)
        cluster_img[m] = lab
        c0 = cluster_img == 0
        c1 = cluster_img == 1
        iface = b4.interface_mask(c0, c1, ndi)
        topo = topology_metrics(c0, c1, interior, iface, ndi)

        edge = b4.split_edge_metrics(c0, c1, iface, z, valids, dims_per, ndi, 2)
        edge_ratios = [r[2] for r in edge if r[2] is not None]
        edge_med = None if not edge_ratios else float(np.median(edge_ratios))
        edge_min = None if not edge_ratios else float(np.min(edge_ratios))
        edge_max = None if not edge_ratios else float(np.max(edge_ratios))

        snap_sep = []
        for sidx in range(4):
            sl = slice(sidx * dims_per, (sidx + 1) * dims_per)
            d = b2.rms(centroids[0, sl] - centroids[1, sl])
            xx = x[:, sl]
            rr = np.sqrt(np.mean((xx - centroids[lab][:, sl]) ** 2, axis=1))
            ww = float(np.sqrt(np.mean(rr ** 2)))
            snap_sep.append(float(d / max(ww, 0.15)))

        rows.append({
            "parent_field_id_2025": fid,
            "locked_split_pass": bool(rec.locked_split_pass),
            "c2_separation_ratio": float(rec.separation_ratio),
            "separation_ratio": sep_ratio,
            "separation_reconstruction_absdiff": abs(sep_ratio - float(rec.separation_ratio)),
            "spatial_coherence": float(rec.spatial_coherence),
            "min_child_fraction": float(rec.min_child_fraction),
            "edge_support_count": int(rec.edge_support_count),
            "loo_all4": bool(rec.loo_all4),
            "edge_ratio_median": edge_med,
            "edge_ratio_min": edge_min,
            "edge_ratio_max": edge_max,
            "sep_april": snap_sep[0],
            "sep_may": snap_sep[1],
            "sep_june": snap_sep[2],
            "sep_july": snap_sep[3],
            "sep_median": float(np.median(snap_sep)),
            "sep_min": float(np.min(snap_sep)),
            "sep_max": float(np.max(snap_sep)),
            "sep_std": float(np.std(snap_sep)),
            **topo,
        })

    diag = pd.DataFrame(rows)
    if float(diag["separation_reconstruction_absdiff"].max()) > 5e-3:
        raise RuntimeError("C4 reconstructed separation differs materially from C2")

    dev = c3_label_map(cfg)
    diag["c3_blind_index"] = diag["parent_field_id_2025"].map(
        lambda x: dev.get(str(x), {}).get("blind_index")
    )
    diag["c3_visual_label"] = diag["parent_field_id_2025"].map(
        lambda x: dev.get(str(x), {}).get("visual_label")
    )

    locked_rule = cfg["split_candidate_rule_unchanged"]
    diag["near_reject_eligible"] = (
        ~as_bool_series(diag["locked_split_pass"])
        & as_bool_series(diag["loo_all4"])
        & (diag["edge_support_count"] >= int(locked_rule["minimum_supporting_edge_snapshots"]))
        & (diag["min_lcf"] >= float(cfg["near_rejects"]["minimum_lcf"]))
    )
    diag["near_reject_distance_to_lcf_gate"] = (
        float(locked_rule["minimum_largest_component_fraction_each_child"]) - diag["min_lcf"]
    ).clip(lower=0)
    near = diag[diag["near_reject_eligible"]].sort_values(
        ["near_reject_distance_to_lcf_gate", "separation_ratio"], ascending=[True, False]
    ).head(int(cfg["near_rejects"]["maximum_count"]))
    diag["c4_analysis_set"] = as_bool_series(diag["locked_split_pass"]) | diag["parent_field_id_2025"].isin(
        set(near["parent_field_id_2025"])
    )

    hc = cfg["high_confidence_candidate"]
    diag["high_confidence_core_candidate"] = (
        as_bool_series(diag["locked_split_pass"])
        & (diag["separation_ratio"] >= float(hc["minimum_separation_ratio"]))
    )

    analysis = diag[diag["c4_analysis_set"]].copy()
    decisive = analysis[analysis["c3_visual_label"].isin(["TYDLIG", "FALSK"])].copy()
    pos_total = int((decisive["c3_visual_label"] == "TYDLIG").sum())
    neg_total = int((decisive["c3_visual_label"] == "FALSK").sum())

    grid_rows = []
    grid = cfg["diagnostic_grid"]
    for sep_thr, touch, max_comp, max_holes, max_iface, min_contact, edge_med in itertools.product(
        grid["minimum_separation_ratio"],
        grid["require_both_largest_children_touch_outer"],
        grid["maximum_component_count_total"],
        grid["maximum_child_holes_total"],
        grid["maximum_interface_components"],
        grid["minimum_outer_contact_parent_fraction"],
        grid["minimum_edge_ratio_median"],
    ):
        passed = eval_rule(
            analysis, sep_thr, touch, max_comp, max_holes, max_iface, min_contact, edge_med
        )
        pass_map = dict(zip(analysis["parent_field_id_2025"], passed.astype(bool)))
        dpass = decisive["parent_field_id_2025"].map(pass_map).fillna(False).astype(bool)
        tp = int(((decisive["c3_visual_label"] == "TYDLIG") & dpass).sum())
        fp = int(((decisive["c3_visual_label"] == "FALSK") & dpass).sum())
        fn = pos_total - tp
        tn = neg_total - fp
        grid_rows.append({
            "minimum_separation_ratio": sep_thr,
            "require_both_largest_children_touch_outer": touch,
            "maximum_component_count_total": max_comp,
            "maximum_child_holes_total": max_holes,
            "maximum_interface_components": max_iface,
            "minimum_outer_contact_parent_fraction": min_contact,
            "minimum_edge_ratio_median": edge_med,
            "analysis_retained": int(passed.sum()),
            "locked_pass_retained": int((passed & as_bool_series(analysis["locked_split_pass"])).sum()),
            "c3_decisive_tp": tp,
            "c3_decisive_fp": fp,
            "c3_decisive_fn": fn,
            "c3_decisive_tn": tn,
            "c3_clear_retention": None if pos_total == 0 else tp / pos_total,
            "c3_false_rejection": None if neg_total == 0 else tn / neg_total,
        })

    grid_df = pd.DataFrame(grid_rows)
    grid_df["zero_c3_false_pass"] = grid_df["c3_decisive_fp"].eq(0)
    grid_df = grid_df.sort_values(
        ["zero_c3_false_pass", "c3_decisive_tp", "analysis_retained",
         "minimum_separation_ratio", "maximum_component_count_total"],
        ascending=[False, False, False, True, False]
    ).reset_index(drop=True)

    diag.to_csv(out / "c4_rich_split_diagnostics_all_baseline.csv", index=False)
    analysis.to_csv(out / "c4_locked_pass_plus_near_rejects.csv", index=False)
    grid_df.to_csv(out / "c4_high_confidence_sensitivity_grid.csv", index=False)
    diag[diag["c3_visual_label"].notna()].sort_values("c3_blind_index").to_csv(
        out / "c4_c3_development_examples.csv", index=False
    )

    core_dec = diag[diag["c3_visual_label"].isin(["TYDLIG", "FALSK"])].copy()
    core_pass = as_bool_series(core_dec["high_confidence_core_candidate"])
    core_tp = int(((core_dec["c3_visual_label"] == "TYDLIG") & core_pass).sum())
    core_fp = int(((core_dec["c3_visual_label"] == "FALSK") & core_pass).sum())
    core_pos = int((core_dec["c3_visual_label"] == "TYDLIG").sum())
    core_neg = int((core_dec["c3_visual_label"] == "FALSK").sum())
    best = grid_df.iloc[0].to_dict() if len(grid_df) else {}

    summary = {
        "schema_version": "akerpuls-prelim-fields-2026-c4-high-confidence-diagnostic-v1",
        "status": "PASS",
        "baseline_split_candidates": int(len(diag)),
        "locked_split_candidates": int(as_bool_series(diag["locked_split_pass"]).sum()),
        "near_reject_eligible": int(diag["near_reject_eligible"].sum()),
        "near_rejects_in_analysis_set": int(analysis["near_reject_eligible"].sum()),
        "analysis_set_candidates": int(len(analysis)),
        "core_high_confidence_rule": {
            "requires_existing_locked_split_candidate": True,
            "minimum_separation_ratio": float(hc["minimum_separation_ratio"]),
            "status": "POST_HOC_DEVELOPMENT_CANDIDATE_NOT_VALIDATED"
        },
        "core_high_confidence_candidates_on_c": int(diag["high_confidence_core_candidate"].sum()),
        "core_c3_decisive": {
            "clear_total": core_pos,
            "false_total": core_neg,
            "clear_retained": core_tp,
            "false_retained": core_fp
        },
        "best_diagnostic_grid_row": best,
        "c3_labels_role": "DEVELOPMENT_ONLY_POST_REVEAL",
        "c3_blind_key_sha256_verified": key_hash,
        "split_candidate_rule_changed": False,
        "thresholds_frozen": False,
        "sentinel_hub_pu_used": 0,
        "merge_policy": "MERGE_CANDIDATE_ONLY",
        "next_step": "Select one simple HIGH_CONFIDENCE_SPLIT development candidate from C4, freeze it for testing only, then validate unchanged on a third independent geographic patch."
    }
    (out / "c4_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C4 HIGH-CONFIDENCE SPLIT DIAGNOSTIC")
    print(
        f'BASELINE_SPLITS={len(diag)} LOCKED_SPLITS={int(as_bool_series(diag["locked_split_pass"]).sum())} '
        f'NEAR_REJECT_ELIGIBLE={int(diag["near_reject_eligible"].sum())} ANALYSIS_SET={len(analysis)}'
    )
    print(
        f'CORE_HIGH_CONF_SEP_GE_{float(hc["minimum_separation_ratio"]):.1f}='
        f'{int(diag["high_confidence_core_candidate"].sum())}/{int(as_bool_series(diag["locked_split_pass"]).sum())}'
    )
    print(f'CORE_C3_DECISIVE CLEAR_RETAIN={core_tp}/{core_pos} FALSE_RETAIN={core_fp}/{core_neg}')
    if best:
        print(
            "BEST_DIAGNOSTIC_GRID="
            f'RETAIN={int(best["analysis_retained"])} '
            f'CLEAR={int(best["c3_decisive_tp"])}/{pos_total} '
            f'FALSE_PASS={int(best["c3_decisive_fp"])}/{neg_total} '
            f'SEP={best["minimum_separation_ratio"]} '
            f'TOUCH={best["require_both_largest_children_touch_outer"]} '
            f'COMP={best["maximum_component_count_total"]} '
            f'HOLES={best["maximum_child_holes_total"]} '
            f'IFACECOMP={best["maximum_interface_components"]} '
            f'CONTACT={best["minimum_outer_contact_parent_fraction"]} '
            f'EDGEMED={best["minimum_edge_ratio_median"]}'
        )
    print("C3_LABELS_ROLE=DEVELOPMENT_ONLY_POST_REVEAL")
    print("SPLIT_CANDIDATE_RULE_CHANGED=FALSE")
    print("THRESHOLDS_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C4_STATUS=PASS")
    print("OUTPUT=" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
