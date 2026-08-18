#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze ÅkerVärde v1.0-rc1 before the 2018/2019 blind backtest.

This script deliberately does NOT change the model. It reruns the already selected
v0j S70_NOFOREST / BASE specification, stores the exact full-fit coefficients,
spatial-CV predictions, strict-anchor calibration ratios, metrics and SHA256 hashes.

The resulting local directory is the auditable model artifact used for the blind
backtest. Do not overwrite it after looking at blind-test prices; create a new
version instead.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_ID = "akervarde-v1.0-rc1"
MODEL_SAMPLE = "S70_NOFOREST"
MODEL_SPEC = "BASE"
BLIND_MIN_ARABLE_HA = 5.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "UNKNOWN"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    v0j_path = root / "src" / "20j_value_additive_property_v0j.py"
    v0j = load_module(v0j_path, "value_v0j_freeze")

    source = v0j.find_input(root, None)
    raw = pd.read_csv(source, encoding="utf-8-sig")
    d = v0j.prepare(raw)
    masks = v0j.sample_masks(d)
    sample = d.loc[masks[MODEL_SAMPLE]].copy().reset_index(drop=True)

    # EXACT already-selected production candidate: S70_NOFOREST / BASE.
    result = v0j.spatial_cv10(sample, v0j.ARABLE_BASE)
    if result is None:
        raise RuntimeError("BASE freeze fit failed")

    full = result["full"]
    x = result["data"].copy().reset_index(drop=True)
    x["akervarde_cv10_pred_total_kr"] = result["cv_pred"]
    x["akervarde_cv10_observed_to_pred_ratio"] = (
        pd.to_numeric(x["kopeskilling_kr_n"], errors="coerce")
        / pd.to_numeric(x["akervarde_cv10_pred_total_kr"], errors="coerce")
    )

    outdir = root / "data" / "derived" / "akervarde_v1_0_rc1_freeze"
    outdir.mkdir(parents=True, exist_ok=True)

    coef = pd.DataFrame({
        "term": full["names"],
        "coefficient": full["params"],
    })
    coef.to_csv(outdir / "model_coefficients.csv", index=False, encoding="utf-8-sig")

    pred_cols = [
        c for c in [
            "sale_id", "datum", "fastighetsbeteckningar", "year",
            "akermark_ha_n", "lat_n", "lon_n", "sale_spatial_cell",
            "spatial_fold10", "anchor_strict", "kopeskilling_kr_n",
            "akervarde_cv10_pred_total_kr", "akervarde_cv10_observed_to_pred_ratio",
        ] if c in x.columns
    ]
    x[pred_cols].to_csv(outdir / "cv10_predictions.csv", index=False, encoding="utf-8-sig")

    anchor = x.loc[
        x["anchor_strict"].fillna(False).astype(bool)
        & pd.to_numeric(x["akervarde_cv10_observed_to_pred_ratio"], errors="coerce").notna()
    ].copy()
    ratio = pd.to_numeric(anchor["akervarde_cv10_observed_to_pred_ratio"], errors="coerce").dropna()
    if len(ratio) < 10:
        raise RuntimeError(f"För få strict-anchor CV residualer för kalibrering: {len(ratio)}")

    calibration = {
        "model_id": MODEL_ID,
        "calibration_source": "strict-anchor held-out spatial-CV observed/predicted ratios",
        "anchor_n": int(len(ratio)),
        "ratio_p10": float(ratio.quantile(0.10)),
        "ratio_p50": float(ratio.quantile(0.50)),
        "ratio_p90": float(ratio.quantile(0.90)),
        "use_for_prediction_interval": "multiply point prediction by ratio_p10 and ratio_p90",
        "important": "This is an empirical calibration interval, not a parametric confidence interval.",
    }
    (outdir / "prediction_interval_calibration.json").write_text(
        json.dumps(calibration, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    metrics = {
        "model_id": MODEL_ID,
        "sample": MODEL_SAMPLE,
        "spec": MODEL_SPEC,
        "n": int(len(full["data"])),
        "n_params": int(len(full["params"])),
        "train_r2_log_total": float(full["train_r2_log_total"]),
        "train_median_ape_total_pct": float(full["train_median_ape_total"]),
        "cv10_r2_log_total": float(result["cv10_r2_log_total"]),
        "cv10_median_ape_total_pct": float(result["cv10_median_ape_total"]),
        "anchor_n": int(result["anchor_n"]),
        "anchor_cv10_r2_log_total": float(result["anchor_cv10_r2_log_total"]),
        "anchor_cv10_median_ape_total_pct": float(result["anchor_cv10_median_ape_total"]),
    }
    (outdir / "validation_metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    protocol = {
        "blind_test_years": [2018, 2019],
        "selection_frozen_before_prices_are_used": True,
        "minimum_arable_ha": BLIND_MIN_ARABLE_HA,
        "required": [
            "market transaction",
            "unbuilt: no small house and no economic building",
            "no forest",
            "no pasture",
            "no forest impediment",
            "other_ha <= 0.5",
            "valid coordinates",
        ],
        "primary_metrics": [
            "median absolute percentage error",
            "median observed/predicted ratio (bias)",
            "log-price R2",
            "coverage of frozen empirical P10-P90 interval",
        ],
        "mvp_green_light_guideline": {
            "combined_n_preferred": ">=20",
            "median_ape_pct": "<=25",
            "median_observed_pred_ratio": "0.85-1.15",
            "p10_p90_coverage_pct": ">=70 (small-n tolerance; nominal target 80)",
            "note": "Guideline, not a regulatory appraisal criterion.",
        },
        "post_blind_rule": "If model is changed after inspecting blind results, 2018/2019 cease to be blind validation for the changed model.",
    }
    (outdir / "blind_backtest_protocol.json").write_text(
        json.dumps(protocol, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Hash after all core artifacts exist. Training/source data itself stays local.
    artifacts = [
        source,
        v0j_path,
        outdir / "model_coefficients.csv",
        outdir / "cv10_predictions.csv",
        outdir / "prediction_interval_calibration.json",
        outdir / "validation_metrics.json",
        outdir / "blind_backtest_protocol.json",
    ]
    manifest = {
        "model_id": MODEL_ID,
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_head(root),
        "model_source": str(v0j_path),
        "feature_source": str(source),
        "hashes_sha256": {str(p): sha256_file(p) for p in artifacts},
        "production_candidate": {
            "sample": MODEL_SAMPLE,
            "model": MODEL_SPEC,
            "arable_terms": list(v0j.ARABLE_BASE),
            "tax_assessed_value_used": False,
        },
    }
    (outdir / "freeze_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("=" * 88)
    print("ÅkerVärde v1.0-rc1 — MODEL FREEZE")
    print("=" * 88)
    print("Git commit:", manifest["git_commit"])
    print("Feature SHA256:", manifest["hashes_sha256"][str(source)])
    print(f"S70 BASE: n={metrics['n']}, spatial CV R2={metrics['cv10_r2_log_total']:.4f}, medianAPE={metrics['cv10_median_ape_total_pct']:.1f}%")
    print(f"Strict anchors: n={calibration['anchor_n']}, R2={metrics['anchor_cv10_r2_log_total']:.4f}, medianAPE={metrics['anchor_cv10_median_ape_total_pct']:.1f}%")
    print(f"Frozen empirical ratio P10/P50/P90: {calibration['ratio_p10']:.4f} / {calibration['ratio_p50']:.4f} / {calibration['ratio_p90']:.4f}")
    print("Output:", outdir)
    print("\nDo NOT overwrite this freeze after inspecting blind-test results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
