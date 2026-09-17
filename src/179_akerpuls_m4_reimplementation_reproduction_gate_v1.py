#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent M4-hard reimplementation compatibility gate.

Rebuilds the surviving M4 feature contract from the three frozen CSV inputs,
runs year-blind folds 2021-2025, compares against the frozen STOPPUNKT C
benchmark, and saves every fold model plus a SHA manifest.

2026 is deliberately NOT predicted here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
DEFAULT_CONFIG = ROOT / "config" / "akerpuls_m4_reimplementation_v1.json"
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1")
PASS_STATUS = "PASS_M4_REIMPLEMENTATION_REPRODUCTION_COMPATIBILITY_GATE"
FAIL_STATUS = "FAIL_M4_REIMPLEMENTATION_REPRODUCTION_COMPATIBILITY_GATE"
UNKNOWN = "__UNKNOWN__"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def truthy(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    s = series.astype("string").str.strip().str.lower()
    return s.isin({"1", "true", "t", "yes", "y"})


def compile_rules(cfg: dict):
    rules = []
    for item in cfg["crop_name_mapping_rules"]:
        rules.append((item["class"], [re.compile(p, flags=re.IGNORECASE) for p in item["patterns"]]))
    return rules


def map_crop_name(name, known: bool, rules) -> str:
    if not known or pd.isna(name):
        return UNKNOWN
    s = str(name).strip()
    for cls, pats in rules:
        if any(p.search(s) for p in pats):
            return cls
    return "annan gröda"


def package_version(name: str):
    try:
        import importlib.metadata
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def ece_equal_width(y_true: np.ndarray, proba: np.ndarray, bins: int = 15) -> float:
    conf = proba.max(axis=1)
    pred = proba.argmax(axis=1)
    corr = (pred == y_true).astype(np.float64)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y_true)
    out = 0.0
    for i in range(bins):
        if i == bins - 1:
            mask = (conf >= edges[i]) & (conf <= edges[i + 1])
        else:
            mask = (conf >= edges[i]) & (conf < edges[i + 1])
        n = int(mask.sum())
        if n:
            out += (n / total) * abs(float(corr[mask].mean()) - float(conf[mask].mean()))
    return float(out)


def metrics(y_true: np.ndarray, proba: np.ndarray) -> dict:
    nclass = proba.shape[1]
    eps = 1e-15
    p = np.clip(proba, eps, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    onehot = np.eye(nclass, dtype=np.float64)[y_true]
    top3 = np.argpartition(-p, kth=2, axis=1)[:, :3]
    return {
        "n": int(len(y_true)),
        "log_loss": float(log_loss(y_true, p, labels=list(range(nclass)))),
        "brier_multiclass": float(np.mean(np.sum((p - onehot) ** 2, axis=1))),
        "top1_accuracy": float(np.mean(np.argmax(p, axis=1) == y_true)),
        "top3_accuracy": float(np.mean(np.any(top3 == y_true[:, None], axis=1))),
        "ece": ece_equal_width(y_true, p, bins=15),
        "mean_entropy": float(np.mean(-np.sum(p * np.log(p), axis=1))),
    }


def build_feature_schema(cfg: dict) -> tuple[list[str], list[str], list[str]]:
    classes = cfg["target_classes"]
    cats = [f"lag_{d}" for d in cfg["history_features"]["calendar_lags"]]
    cats += list(cfg["static_features"]["categorical"])
    nums = ["valid_history_years", "history_coverage_mean", "history_dominant_share_mean"]
    for cls in classes:
        key = cls.replace(" ", "_").replace("/", "_")
        nums.append(f"recency__{key}")
        for w in cfg["history_features"]["count_windows_years"]:
            nums.append(f"count{w}__{key}")
        nums.append(f"share_long__{key}")
    nums += list(cfg["static_features"]["numeric"])
    return cats + nums, cats, nums


def prepare_base(cfg: dict):
    inp = Path(cfg["inputs"]["directory"])
    files = {}
    for key in ("history", "static_context", "soil_score"):
        meta = cfg["inputs"][key]
        p = inp / meta["file"]
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha256_file(p)
        if got != meta["sha256"]:
            raise RuntimeError(f"Frozen input SHA mismatch {p.name}: {got}")
        files[key] = p

    hist_cols = [
        "current_field_id", "reference_year", "history_year", "dominant_crop_name",
        "dominant_crop_known", "coverage_raw", "dominant_crop_share", "status", "reason_flags",
    ]
    hist = pd.read_csv(files["history"], usecols=hist_cols, compression="gzip", low_memory=False)
    static = pd.read_csv(files["static_context"], compression="gzip", low_memory=False)
    soil = pd.read_csv(files["soil_score"], compression="gzip", low_memory=False)

    if len(hist) != cfg["inputs"]["history"]["rows"] or hist["current_field_id"].nunique() != cfg["inputs"]["history"]["fields"]:
        raise RuntimeError("History census mismatch")
    if len(static) != cfg["inputs"]["static_context"]["rows"] or static["current_field_id"].nunique() != cfg["inputs"]["static_context"]["fields"]:
        raise RuntimeError("Static census mismatch")
    if len(soil) != cfg["inputs"]["soil_score"]["rows"] or soil["current_field_id"].nunique() != cfg["inputs"]["soil_score"]["fields"]:
        raise RuntimeError("Soil-score census mismatch")

    hist["current_field_id"] = hist["current_field_id"].astype("string")
    static["current_field_id"] = static["current_field_id"].astype("string")
    soil["current_field_id"] = soil["current_field_id"].astype("string")
    hist["history_year"] = pd.to_numeric(hist["history_year"], errors="raise").astype(int)
    known = truthy(hist["dominant_crop_known"])
    rules = compile_rules(cfg)
    hist["crop_class"] = [map_crop_name(n, bool(k), rules) for n, k in zip(hist["dominant_crop_name"], known)]
    hist["known_bool"] = known.to_numpy(dtype=bool)
    hist["coverage_raw"] = pd.to_numeric(hist["coverage_raw"], errors="coerce")
    hist["dominant_crop_share"] = pd.to_numeric(hist["dominant_crop_share"], errors="coerce")

    ids = pd.Index(sorted(static["current_field_id"].unique().tolist()), name="current_field_id")
    if len(ids) != cfg["inputs"]["history"]["fields"]:
        raise RuntimeError("Field-id population mismatch")

    cls_wide = hist.pivot(index="current_field_id", columns="history_year", values="crop_class").reindex(ids)
    known_wide = hist.pivot(index="current_field_id", columns="history_year", values="known_bool").reindex(ids).fillna(False)
    cov_wide = hist.pivot(index="current_field_id", columns="history_year", values="coverage_raw").reindex(ids)
    share_wide = hist.pivot(index="current_field_id", columns="history_year", values="dominant_crop_share").reindex(ids)

    static_i = static.set_index("current_field_id").reindex(ids)
    soil_i = soil.set_index("current_field_id").reindex(ids)
    return ids, cls_wide, known_wide, cov_wide, share_wide, static_i, soil_i


def build_year_features(t: int, cfg: dict, base, cat_domains: dict[str, list[str]]):
    ids, cls_wide, known_wide, cov_wide, share_wide, static_i, soil_i = base
    classes = cfg["target_classes"]
    hcfg = cfg["history_features"]
    years = [y for y in cls_wide.columns if int(y) < t]
    years = sorted(map(int, years))
    if not years:
        raise RuntimeError(f"No history years before {t}")

    out = pd.DataFrame(index=ids)
    unknown = hcfg["unknown_history_category"]
    for d in hcfg["calendar_lags"]:
        y = t - int(d)
        if y in cls_wide.columns:
            s = cls_wide[y].fillna(unknown).astype("string")
        else:
            s = pd.Series(unknown, index=ids, dtype="string")
        out[f"lag_{d}"] = pd.Categorical(s, categories=cat_domains[f"lag_{d}"])

    k = known_wide[years].to_numpy(dtype=bool)
    out["valid_history_years"] = k.sum(axis=1).astype(np.float32)
    out["history_coverage_mean"] = cov_wide[years].mean(axis=1, skipna=True).astype(np.float32)
    out["history_dominant_share_mean"] = share_wide[years].mean(axis=1, skipna=True).astype(np.float32)

    hist_arr = cls_wide[years].fillna(unknown).astype("string").to_numpy()
    for cls in classes:
        key = cls.replace(" ", "_").replace("/", "_")
        cap = int(hcfg["recency_cap_years"])
        rec = np.full(len(ids), cap, dtype=np.uint8)
        for y in reversed(years):
            d = t - y
            if d >= cap:
                continue
            mask = cls_wide[y].fillna(unknown).astype("string").to_numpy() == cls
            rec[(rec == cap) & mask] = d
        out[f"recency__{key}"] = rec
        for w in hcfg["count_windows_years"]:
            use = [y for y in years if y >= t - int(w)]
            if use:
                arr = cls_wide[use].fillna(unknown).astype("string").to_numpy()
                cnt = (arr == cls).sum(axis=1).astype(np.uint8)
            else:
                cnt = np.zeros(len(ids), dtype=np.uint8)
            out[f"count{w}__{key}"] = cnt
        cnt_long = (hist_arr == cls).sum(axis=1).astype(np.float32)
        denom = np.maximum(out["valid_history_years"].to_numpy(dtype=np.float32), 1.0)
        out[f"share_long__{key}"] = (cnt_long / denom).astype(np.float32)

    # Static categories: stable 2025 context, no target-year crop information.
    s = static_i
    q = soil_i
    static_cat_sources = {
        "municipality": s["municipality"],
        "dominant_sko_id": s["dominant_sko_id"],
        "dominant_soil_class": s["dominant_soil_class"],
        "context_status": s["context_status"],
        "context_reason_flags": s["reason_flags"],
        "historic_class_qa": q["historic_class_qa"],
    }
    for col, src in static_cat_sources.items():
        ss = src.astype("string").fillna(unknown)
        out[col] = pd.Categorical(ss, categories=cat_domains[col])

    area_ha = pd.to_numeric(s["field_area_m2"], errors="coerce").to_numpy(dtype=np.float64) / 10000.0
    out["field_area_log1p_ha"] = np.log1p(np.maximum(area_ha, 0.0)).astype(np.float32)
    out["akerscore_soil_p50"] = pd.to_numeric(q["akerscore_soil_p50"], errors="coerce").astype(np.float32)
    out["soil_coverage_pct"] = pd.to_numeric(q["soil_coverage_pct"], errors="coerce").astype(np.float32)

    target = cls_wide[t].fillna(unknown).astype("string") if t in cls_wide.columns else pd.Series(unknown, index=ids, dtype="string")
    target_valid = known_wide[t].to_numpy(dtype=bool) if t in known_wide.columns else np.zeros(len(ids), dtype=bool)
    return out, target, target_valid


def categorical_domains(cfg: dict, base) -> dict[str, list[str]]:
    _, _, _, _, _, static_i, soil_i = base
    classes = list(cfg["target_classes"])
    unknown = cfg["history_features"]["unknown_history_category"]
    domains = {f"lag_{d}": classes + [unknown] for d in cfg["history_features"]["calendar_lags"]}
    sources = {
        "municipality": static_i["municipality"],
        "dominant_sko_id": static_i["dominant_sko_id"],
        "dominant_soil_class": static_i["dominant_soil_class"],
        "context_status": static_i["context_status"],
        "context_reason_flags": static_i["reason_flags"],
        "historic_class_qa": soil_i["historic_class_qa"],
    }
    for col, src in sources.items():
        vals = sorted(set(src.astype("string").fillna(unknown).tolist()))
        if unknown not in vals:
            vals.append(unknown)
        domains[col] = vals
    return domains


def compare_to_benchmark(actual_rows: list[dict], cfg: dict) -> tuple[bool, dict]:
    tol = cfg["reproduction_gate_tolerances_frozen_before_run"]
    benchmark = cfg["frozen_benchmark_m4"]
    metrics_gate = ["log_loss", "brier_multiclass", "top1_accuracy", "top3_accuracy", "mean_entropy"]
    per_year = []
    exact_n = True
    for row in actual_rows:
        year = str(row["year"])
        ref = benchmark[year]
        exact_n = exact_n and int(row["n"]) == int(ref["n"])
        rr = {"year": int(year), "n_match": int(row["n"]) == int(ref["n"])}
        for m in metrics_gate + ["ece"]:
            rr[f"delta_{m}"] = float(row[m] - ref[m])
            rr[f"abs_delta_{m}"] = abs(rr[f"delta_{m}"])
        per_year.append(rr)

    summary = {"n_exact_all_years": exact_n, "per_year": per_year, "gate_metrics": {}}
    passed = bool(exact_n)
    for m in metrics_gate:
        vals = [x[f"abs_delta_{m}"] for x in per_year]
        mean_abs = float(np.mean(vals))
        max_abs = float(np.max(vals))
        mpass = mean_abs <= float(tol["mean_abs_delta"][m]) and max_abs <= float(tol["max_abs_delta"][m])
        summary["gate_metrics"][m] = {
            "mean_abs_delta": mean_abs,
            "max_abs_delta": max_abs,
            "mean_tolerance": float(tol["mean_abs_delta"][m]),
            "max_tolerance": float(tol["max_abs_delta"][m]),
            "pass": bool(mpass),
        }
        passed = passed and mpass
    return bool(passed), summary


def write_sha_manifest(out: Path) -> Path:
    rows = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "SHA256_MANIFEST.txt":
            rows.append(f"{sha256_file(p)}  {p.relative_to(out).as_posix()}")
    path = out / "SHA256_MANIFEST.txt"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    git_head = git_guard()
    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    expected_lgb = cfg["lightgbm"]["package_version"]
    installed_lgb = package_version("lightgbm")
    if installed_lgb != expected_lgb:
        raise RuntimeError(f"lightgbm=={expected_lgb} required; installed={installed_lgb or 'MISSING'}")
    import lightgbm as lgb

    out.mkdir(parents=True, exist_ok=False)
    model_dir = out / "models"
    model_dir.mkdir()

    base = prepare_base(cfg)
    domains = categorical_domains(cfg, base)
    feature_order, cat_cols, num_cols = build_feature_schema(cfg)

    feature_contract = {
        "schema_version": "akerpuls-m4-reimplementation-feature-contract-v1",
        "git_head": git_head,
        "config_sha256": sha256_file(cfg_path),
        "feature_order": feature_order,
        "categorical_features": cat_cols,
        "numeric_features": num_cols,
        "categorical_domains": domains,
        "target_classes_order": cfg["target_classes"],
        "history_policy": cfg["history_features"],
        "crop_name_mapping_rules": cfg["crop_name_mapping_rules"],
        "static_features": cfg["static_features"],
        "note": "Reimplementation from surviving frozen contract; original transient feature-builder was not preserved."
    }
    (out / "FEATURE_CONTRACT.json").write_text(json.dumps(feature_contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    environment = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            "numpy": package_version("numpy"),
            "pandas": package_version("pandas"),
            "scikit-learn": package_version("scikit-learn"),
            "lightgbm": package_version("lightgbm"),
        },
        "lightgbm_params": cfg["lightgbm"],
    }
    (out / "ENVIRONMENT.json").write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validation_years = list(map(int, cfg["history_features"]["validation_years"]))
    min_target = int(cfg["history_features"]["minimum_target_year"])
    all_years = list(range(min_target, max(validation_years) + 1))
    cache = {}
    class_to_int = {c: i for i, c in enumerate(cfg["target_classes"])}

    print("AKERPULS M4 REIMPLEMENTATION REPRODUCTION GATE")
    print(f"GIT_HEAD={git_head}")
    print(f"LIGHTGBM_VERSION={installed_lgb}")
    print("PROGRESS=BUILD_YEAR_FEATURES_AND_TARGET_CENSUS")
    census = []
    for y in all_years:
        X, target, valid = build_year_features(y, cfg, base, domains)
        X = X[feature_order]
        y_int = target.map(class_to_int)
        # A valid public target must map to one of the 16 agronomic classes.
        good = valid & y_int.notna().to_numpy()
        cache[y] = (X, y_int, good)
        rec = {"year": y, "n_valid_target": int(good.sum())}
        if str(y) in cfg["frozen_benchmark_m4"]:
            rec["frozen_n"] = int(cfg["frozen_benchmark_m4"][str(y)]["n"])
            rec["n_match"] = rec["n_valid_target"] == rec["frozen_n"]
        census.append(rec)
        print(f"TARGET_CENSUS_YEAR={y} N={rec['n_valid_target']}" + (f" FROZEN={rec['frozen_n']} MATCH={str(rec['n_match']).upper()}" if 'frozen_n' in rec else ""))

    if not all(r.get("n_match", True) for r in census):
        status = "FAIL_M4_REIMPLEMENTATION_TARGET_CENSUS_GATE"
        summary = {
            "status": status,
            "git_head": git_head,
            "target_census": census,
            "model_fit_executed": False,
            "prediction_2026_executed": False,
            "next": "REVIEW_TARGET_VALIDITY_ORIGINAL_MAPPING_BEFORE_ANY_MODEL_FIT",
        }
        (out / "REPRODUCTION_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_sha_manifest(out)
        print(f"STATUS={status}")
        print("MODEL_FIT_EXECUTED=FALSE PREDICTION_2026_EXECUTED=FALSE")
        print("NEXT=REVIEW_TARGET_VALIDITY_ORIGINAL_MAPPING_BEFORE_ANY_MODEL_FIT")
        print(f"OUTPUT={out}")
        return 0

    rows = []
    params = dict(cfg["lightgbm"])
    params.pop("package_version", None)
    objective = params.pop("objective")
    params["objective"] = objective
    params["num_class"] = len(cfg["target_classes"])

    print("PROGRESS=YEAR_BLIND_M4_FOLDS")
    for val_year in validation_years:
        train_years = list(range(min_target, val_year))
        train_frames = []
        train_targets = []
        for y in train_years:
            Xy, yy, good = cache[y]
            train_frames.append(Xy.loc[good])
            train_targets.append(yy.loc[good].astype(int))
        X_train = pd.concat(train_frames, axis=0, ignore_index=True)
        y_train = pd.concat(train_targets, axis=0, ignore_index=True).to_numpy(dtype=np.int32)
        Xv, yv, goodv = cache[val_year]
        X_val = Xv.loc[goodv].copy()
        y_val = yv.loc[goodv].astype(int).to_numpy(dtype=np.int32)

        print(f"FOLD={val_year} TRAIN_YEARS={train_years[0]}-{train_years[-1]} TRAIN_N={len(y_train)} VAL_N={len(y_val)}")
        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train, categorical_feature=cat_cols)
        proba = model.predict_proba(X_val)
        m = metrics(y_val, proba)
        m.update({
            "year": val_year,
            "model": "M4_reimplementation_v1",
            "train_target_year_min": train_years[0],
            "train_target_year_max": train_years[-1],
            "train_n": int(len(y_train)),
        })
        rows.append(m)
        model_path = model_dir / f"M4_REIMPL_FOLD_{val_year}.txt"
        model.booster_.save_model(str(model_path))
        print(
            f"FOLD_RESULT={val_year} LOGLOSS={m['log_loss']:.9f} BRIER={m['brier_multiclass']:.9f} "
            f"TOP1={m['top1_accuracy']:.9f} TOP3={m['top3_accuracy']:.9f} ENTROPY={m['mean_entropy']:.9f} ECE={m['ece']:.9f}"
        )
        del X_train, y_train, X_val, y_val, proba, model

    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(out / "M4_REIMPLEMENTATION_FOLD_METRICS.csv", index=False)
    passed, comparison = compare_to_benchmark(rows, cfg)
    status = PASS_STATUS if passed else FAIL_STATUS

    summary = {
        "schema_version": "akerpuls-m4-reimplementation-reproduction-gate-v1",
        "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "config_sha256": sha256_file(cfg_path),
        "target_census": census,
        "actual_metrics": rows,
        "frozen_benchmark": cfg["frozen_benchmark_m4"],
        "comparison": comparison,
        "tolerances": cfg["reproduction_gate_tolerances_frozen_before_run"],
        "models_saved": [str((model_dir / f"M4_REIMPL_FOLD_{y}.txt").relative_to(out)) for y in validation_years],
        "prediction_2026_executed": False,
        "fusion_executed": False,
        "geometry_mutated": False,
        "next": "FREEZE_REIMPLEMENTATION_THEN_TRAIN_FINAL_2026_PRIOR" if passed else "REVIEW_REIMPLEMENTATION_DELTAS_WITHOUT_OPENING_2026",
    }
    (out / "REPRODUCTION_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = write_sha_manifest(out)

    print(f"STATUS={status}")
    print(f"TARGET_CENSUS_ALL_MATCH={str(comparison['n_exact_all_years']).upper()}")
    for metric_name, info in comparison["gate_metrics"].items():
        print(
            f"GATE_{metric_name.upper()}=PASS:{str(info['pass']).upper()} "
            f"MEAN_ABS_DELTA:{info['mean_abs_delta']:.9f}/{info['mean_tolerance']:.9f} "
            f"MAX_ABS_DELTA:{info['max_abs_delta']:.9f}/{info['max_tolerance']:.9f}"
        )
    print("PREDICTION_2026_EXECUTED=FALSE FUSION_EXECUTED=FALSE GEOMETRY_MUTATED=FALSE")
    print(f"SHA256_MANIFEST={manifest}")
    print(f"NEXT={summary['next']}")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
