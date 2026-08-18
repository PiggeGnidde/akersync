#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerScore soil v0b: spatial-CV diagnosis + transparent 10-point calibration.

This script reuses the paired training_sample.csv.gz created by v0a.  It does
NOT rescan the rasters.

Goals
-----
1) Preserve the raw v0a soil signal as a diagnostic.
2) Test it out-of-sample by 10x10 km spatial folds.
3) Calibrate the display scale so historic class centres correspond to roughly
   45,55,65,75,85,95 without injecting a field's own class at scoring time.
4) Re-score the German Triesdorf references with the final frozen mapping.

The calibration is a scale mapping, not extra predictive information.  Model
quality must therefore be judged from the held-out raw ordering as well as the
calibrated display score.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd


N_FOLDS = 5
TARGET_CENTRES = {5: 45.0, 6: 55.0, 7: 65.0, 8: 75.0, 9: 85.0, 10: 95.0}


def load_v0a_module(root: Path):
    p = root / "src" / "31_akerscore_soil_v0a.py"
    spec = importlib.util.spec_from_file_location("akerscore_soil_v0a", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stable_fold(cell: str, n_folds: int = N_FOLDS) -> int:
    return int(zlib.crc32(str(cell).encode("utf-8")) % n_folds)


def fit_calibration(raw: pd.DataFrame, score_col: str):
    """Map classwise raw medians to fixed class centres by monotone piecewise linear interpolation."""
    rows = []
    for klass in sorted(TARGET_CENTRES):
        q = raw.loc[raw["historic_class"].eq(klass), score_col].dropna().to_numpy(float)
        if len(q) == 0:
            raise RuntimeError(f"No calibration data for class {klass}")
        rows.append((klass, float(np.median(q)), TARGET_CENTRES[klass]))
    x = np.array([r[1] for r in rows], float)
    y = np.array([r[2] for r in rows], float)
    # Raw class medians should already be increasing. If tiny reversals occur,
    # enforce monotonicity conservatively to keep the scale well-defined.
    x = np.maximum.accumulate(x)
    for i in range(1, len(x)):
        if x[i] <= x[i-1] + 1e-9:
            x[i] = x[i-1] + 1e-6
    return x, y, rows


def apply_calibration(values, x, y):
    """Piecewise linear interpolation with linear end extrapolation, clipped 0..100."""
    v = np.asarray(values, float)
    out = np.interp(v, x, y)
    lo = v < x[0]
    hi = v > x[-1]
    if len(x) >= 2:
        slo = (y[1]-y[0])/(x[1]-x[0])
        shi = (y[-1]-y[-2])/(x[-1]-x[-2])
        out[lo] = y[0] + slo*(v[lo]-x[0])
        out[hi] = y[-1] + shi*(v[hi]-x[-1])
    return np.clip(out, 0.0, 100.0)


def class_summary(df: pd.DataFrame, score_col: str):
    rows=[]
    for klass,q in df.groupby("historic_class"):
        s=q[score_col].dropna().to_numpy(float)
        rows.append({
            "historic_class": int(klass),
            "n": int(len(s)),
            "mean": float(np.mean(s)),
            "p10": float(np.percentile(s,10)),
            "p50": float(np.percentile(s,50)),
            "p90": float(np.percentile(s,90)),
            "nominal_low": 10*(int(klass)-1),
            "nominal_high": 10*int(klass),
            "share_in_nominal_band_pct": float(100*np.mean((s>=10*(int(klass)-1)) & (s<=10*int(klass)))),
        })
    return pd.DataFrame(rows).sort_values("historic_class")


def rank_check(g: pd.DataFrame, score_col: str):
    rows=[]
    for depth,q in g.groupby("depth_cm", sort=False):
        q=q.copy()
        q["yield_rank"] = q["yield_t_ha"].rank(method="average")
        q["score_rank"] = q[score_col].rank(method="average")
        exact = list(q.sort_values("yield_t_ha")["cluster"]) == list(q.sort_values(score_col)["cluster"])
        rows.append({
            "depth_cm": depth,
            "exact_order": bool(exact),
            "yield_order": " < ".join(q.sort_values("yield_t_ha")["cluster"].tolist()),
            "score_order": " < ".join(q.sort_values(score_col)["cluster"].tolist()),
        })
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--folds", type=int, default=N_FOLDS)
    args=ap.parse_args()

    root=Path(__file__).resolve().parents[1]
    v0a=load_v0a_module(root)
    cfg=v0a.load_config(root/args.config)
    base=root/cfg.get("build_dir","data/derived")
    indir=base/"akerscore_soil_v0a"
    outdir=base/"akerscore_soil_v0b"
    outdir.mkdir(parents=True, exist_ok=True)
    sample_path=indir/"training_sample.csv.gz"
    if not sample_path.exists():
        raise FileNotFoundError(f"Missing {sample_path}. Run RUN_AKERSCORE_SOIL_V0A.bat first.")

    print("="*92)
    print("ÅkerScore Soil v0b · spatial CV + 10-point calibration")
    print("="*92)
    print("Loading", sample_path)
    sample=pd.read_csv(sample_path)
    if "spatial_cell_10km" not in sample.columns:
        sample["spatial_cell_10km"]=(np.floor(sample.x_3006/10000).astype(int).astype(str)+"_"+
                                      np.floor(sample.y_3006/10000).astype(int).astype(str))
    sample["cv_fold"]=[stable_fold(c,args.folds) for c in sample.spatial_cell_10km.astype(str)]

    oof=[]
    fold_knots=[]
    for fold in range(args.folds):
        tr=sample[sample.cv_fold.ne(fold)].copy()
        te=sample[sample.cv_fold.eq(fold)].copy()
        print(f"Fold {fold+1}/{args.folds}: train={len(tr):,} test={len(te):,} cells={te.spatial_cell_10km.nunique():,}")
        if te.empty:
            continue
        model=v0a.fit_cloud_model(tr, use_mull=True)
        tr_sc=v0a.score_df(tr, model, "raw")
        te_sc=v0a.score_df(te, model, "raw")
        x,y,rows=fit_calibration(tr_sc,"raw_score")
        te_sc["display_score"] = apply_calibration(te_sc["raw_score"].to_numpy(float),x,y)
        te_sc["cv_fold"]=fold
        oof.append(te_sc[["historic_class","spatial_cell_10km","cv_fold","raw_score","display_score"]])
        for klass,rawmed,target in rows:
            fold_knots.append({"fold":fold,"historic_class":klass,"train_raw_median":rawmed,"target_score":target})

    if not oof:
        raise RuntimeError("No CV folds produced output")
    oof=pd.concat(oof, ignore_index=True)
    oof.to_csv(outdir/"spatial_cv_scores.csv.gz", index=False, compression="gzip")
    rawsum=class_summary(oof,"raw_score")
    calsum=class_summary(oof,"display_score")
    rawsum.to_csv(outdir/"spatial_cv_class_summary_raw.csv",index=False,encoding="utf-8-sig")
    calsum.to_csv(outdir/"spatial_cv_class_summary_calibrated.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(fold_knots).to_csv(outdir/"spatial_cv_calibration_knots.csv",index=False,encoding="utf-8-sig")

    # Final frozen model and mapping on all Swedish samples.
    final_model=v0a.fit_cloud_model(sample, use_mull=True)
    final_sc=v0a.score_df(sample, final_model, "raw")
    x,y,rows=fit_calibration(final_sc,"raw_score")
    final_knots=pd.DataFrame([{"historic_class":k,"raw_median":m,"target_score":t} for k,m,t in rows])
    final_knots.to_csv(outdir/"final_calibration_knots.csv",index=False,encoding="utf-8-sig")

    german=v0a.german_reference_frame()
    german=v0a.score_df(german, final_model, "raw")
    german["akerscore_soil_v0b"] = apply_calibration(german["raw_score"].to_numpy(float),x,y)
    german.to_csv(outdir/"german_triesdorf_reference_scores_v0b.csv",index=False,encoding="utf-8-sig")
    ranks=rank_check(german,"akerscore_soil_v0b")
    ranks.to_csv(outdir/"german_rank_check_v0b.csv",index=False,encoding="utf-8-sig")

    # Descriptive class signatures already show an important mull gradient.
    sig=sample.groupby("historic_class").agg(
        n=("historic_class","size"),
        clay_mean_pct=("clay_pct","mean"),
        silt_mean_pct=("silt_pct","mean"),
        sand_mean_pct=("sand_pct","mean"),
        mull_proxy_mean_pct=("mull_proxy_pct","mean"),
    ).reset_index()
    low=sample.assign(lt35=sample.mull_proxy_pct<3.5).groupby("historic_class")["lt35"].mean().mul(100)
    sig["share_mull_proxy_lt3_5_pct"]=sig.historic_class.map(low)
    sig.to_csv(outdir/"class_soil4_signature_v0b.csv",index=False,encoding="utf-8-sig")

    lines=[
        "ÅkerScore Soil v0b · spatial CV + calibrated display scale",
        "="*82,
        f"Rows: {len(sample):,}; spatial cells: {sample.spatial_cell_10km.nunique():,}; folds: {args.folds}",
        "Raw model: same Swedish ILR(texture)+mull-proxy cloud model as v0a.",
        "Display calibration: training-class raw medians -> 45/55/65/75/85/95, piecewise linear.",
        "Historic class is not supplied when held-out rows or German references are scored.",
        "",
        "SPATIAL OOF RAW SCORE",
    ]
    for _,r in rawsum.iterrows():
        lines.append(f"  class {int(r.historic_class)}: p10/p50/p90={r.p10:.1f}/{r.p50:.1f}/{r.p90:.1f}; mean={r['mean']:.1f}")
    lines += ["","SPATIAL OOF CALIBRATED DISPLAY SCORE"]
    for _,r in calsum.iterrows():
        lines.append(f"  class {int(r.historic_class)}: p10/p50/p90={r.p10:.1f}/{r.p50:.1f}/{r.p90:.1f}; band share={r.share_in_nominal_band_pct:.1f}%")
    lines += ["","GERMAN EXTERNAL CONSISTENCY CHECK"]
    for _,r in ranks.iterrows():
        lines.append(f"  {r.depth_cm} cm: yield {r.yield_order}; score {r.score_order}; exact={r.exact_order}")
    lines += [
        "",
        "Interpretation:",
        "- Calibration only stretches the display scale; it cannot create missing soil information.",
        "- Judge real signal from spatial held-out ordering/overlap in the raw score.",
        "- Strong class overlap is expected because the 1971 productivity class also contains climate/water/profile/management information.",
        "- Mull proxy is an empirical fingerprint here, not evidence that reducing SOM improves soil.",
    ]
    report="\n".join(lines)+"\n"
    (outdir/"report.txt").write_text(report,encoding="utf-8")
    metadata={
        "version":"akerscore_soil_v0b",
        "n_folds":args.folds,
        "fold_unit":"10x10 km spatial_cell_10km, CRC32 deterministic assignment",
        "target_centres":TARGET_CENTRES,
        "final_calibration_raw_knots":x.tolist(),
        "final_calibration_score_knots":y.tolist(),
        "note":"Display calibration is scale-setting, not new predictive information.",
    }
    (outdir/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    print("\n"+report)
    print("Output:",outdir)
    print("Send report.txt, spatial_cv_class_summary_raw.csv, spatial_cv_class_summary_calibrated.csv, german_triesdorf_reference_scores_v0b.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
