#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""True rolling out-of-time geometry-persistence backtest for AkerPuls.

For every adjacent year pair 2015->2016 ... 2024->2025, the frozen AkerMinne
geometry matcher is applied directly to those two annual geometries. Historical
features for a field in year t are recursively inherited through the maximum-
overlap predecessor and contain only transitions observed at or before t.
The label is the actual t->t+1 geometry transition.

No Sentinel calls, no downloads and no modification of frozen AkerMinne data.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from akerminne_mapping_core import MatchingConfig, map_fields, prepare_fields

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerpuls_geometry_rolling_backtest_v0.json"
STRICT = {"direct_id", "one_to_one_strict"}
PRACTICAL = STRICT | {"one_to_one_relaxed"}
SPLIT_MERGE = {"split", "merge"}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else base / p


def slug_municipality(name: str) -> str:
    return str(name).lower().replace(" ", "_")


def locate_workspace_inputs(workspace: Path) -> tuple[Path, dict[str, Any], Path, dict[str, Any], Path]:
    local_cfg_path = workspace / "config" / "akerminne_local.json"
    project_cfg_path = workspace / "config" / "local_paths.json"
    if not local_cfg_path.exists():
        fallback = Path(r"C:\AkerSyncRepo\config\akerminne_local.json")
        if fallback.exists():
            local_cfg_path = fallback
    if not project_cfg_path.exists():
        fallback = Path(r"C:\AkerSyncRepo\config\local_paths.json")
        if fallback.exists():
            project_cfg_path = fallback
    local_cfg = read_json(local_cfg_path)
    project_cfg = read_json(project_cfg_path)

    raw_base = resolve_path(local_cfg_path.parent.parent, str(local_cfg["raw_root"]))
    if (raw_base / "2015").is_dir():
        raw_root = raw_base
    elif (raw_base / "akerminne_v1a" / "2015").is_dir():
        raw_root = raw_base / "akerminne_v1a"
    else:
        raise FileNotFoundError(
            f"Cannot locate frozen AkerMinne annual raw root below {raw_base}; "
            "expected either <raw_root>/2015 or <raw_root>/akerminne_v1a/2015"
        )

    skane_root = workspace / "data" / "derived" / "akerminne_v1a" / "skane"
    plan_path = skane_root / "skane_plan.json"
    plan = read_json(plan_path)
    return raw_root, local_cfg, project_cfg_path, project_cfg, plan_path


def _read_region(path: Path, code: str) -> gpd.GeoDataFrame:
    try:
        g = gpd.read_file(path, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'")
        if len(g):
            return g
    except Exception:
        pass
    g = gpd.read_file(path)
    if "region_kod" not in g.columns:
        raise RuntimeError(f"region_kod missing in {path}")
    return g[g["region_kod"].astype(str).str.startswith(code)].copy()


def read_2025(project_cfg_path: Path, project_cfg: dict[str, Any], code: str) -> gpd.GeoDataFrame:
    base = project_cfg_path.parent.parent
    spath = resolve_path(base, str(project_cfg["skiften"]))
    try:
        return _read_region(spath, code)
    except RuntimeError:
        bpath = resolve_path(base, str(project_cfg["blocks"]))
        blocks = _read_region(bpath, code)
        allowed = set(blocks["blockid"].astype(str))
        bbox = tuple(float(v) for v in blocks.total_bounds)
        g = gpd.read_file(spath, bbox=bbox)
        return g[g["blockid"].astype(str).isin(allowed)].copy()


def historical_path(raw_root: Path, municipality: str, year: int) -> Path:
    return raw_root / str(year) / f"arslager_skifte_{slug_municipality(municipality)}_{year}.gpkg"


def field_ids(gdf: gpd.GeoDataFrame) -> pd.Series:
    return gdf["blockid"].astype(str) + "|" + gdf["skiftesbeteckning"].astype(str)


def classify_source_fields(source: gpd.GeoDataFrame, edges: pd.DataFrame, cfg: MatchingConfig) -> pd.DataFrame:
    """Mirror the frozen bipartite topology onto the historical/source side.

    map_fields(current=future, historical=source) classifies future fields. This
    function classifies the source fields using the exact same qualifying graph,
    yielding the actual forward source->future transition label.
    """
    src, _ = prepare_fields(source, "rolling_source")
    relaxed = edges[edges["qualifies_relaxed"]].copy() if len(edges) else edges.copy()
    c_neighbors = (
        relaxed.groupby("current_field_key")["historical_field_key"].apply(lambda x: sorted(set(x))).to_dict()
        if len(relaxed) else {}
    )
    h_neighbors = (
        relaxed.groupby("historical_field_key")["current_field_key"].apply(lambda x: sorted(set(x))).to_dict()
        if len(relaxed) else {}
    )

    component_by_historical: dict[str, tuple[set[str], set[str]]] = {}
    seen_h: set[str] = set()
    for start in sorted(h_neighbors):
        if start in seen_h:
            continue
        cs: set[str] = set()
        hs: set[str] = set()
        q: list[tuple[str, str]] = [("h", start)]
        while q:
            kind, key = q.pop()
            if kind == "h":
                if key in hs:
                    continue
                hs.add(key); seen_h.add(key)
                for c in h_neighbors.get(key, []):
                    if c not in cs:
                        q.append(("c", c))
            else:
                if key in cs:
                    continue
                cs.add(key)
                for h in c_neighbors.get(key, []):
                    if h not in hs:
                        q.append(("h", h))
        for h in hs:
            component_by_historical[h] = (cs, hs)

    by_h = edges.groupby("historical_field_key") if len(edges) else None
    rows: list[dict[str, Any]] = []
    for _, srow in src.iterrows():
        hk = str(srow["field_key"])
        raw = by_h.get_group(hk).copy() if by_h is not None and hk in by_h.groups else pd.DataFrame(columns=edges.columns)
        status = "unmatched"
        reason = "NO_POSITIVE_OVERLAP" if not len(raw) else "BELOW_RELAXED_THRESHOLD"
        nc = nh = 0
        if hk in component_by_historical:
            cs, hs = component_by_historical[hk]
            nc, nh = len(cs), len(hs)
            qraw = raw[raw["qualifies_relaxed"]]
            if nc == 1 and nh == 1:
                edge = qraw.iloc[0]
                if bool(edge["current_primary_tie"]) or bool(edge["historical_primary_tie"]):
                    status, reason = "ambiguous", "PRIMARY_OVERLAP_TIE"
                elif not bool(edge["is_mutual_primary"]):
                    status, reason = "ambiguous", "NOT_MUTUAL_PRIMARY"
                elif bool(edge["qualifies_strict"]):
                    if bool(edge["same_admin_key"]):
                        status, reason = "direct_id", "STRICT_GEOMETRY_AND_SAME_ADMIN_KEY"
                    else:
                        status, reason = "one_to_one_strict", "STRICT_GEOMETRY"
                else:
                    status, reason = "one_to_one_relaxed", "RELAXED_GEOMETRY"
            elif nc > 1 and nh == 1:
                status, reason = "split", "ONE_SOURCE_TO_MULTIPLE_FUTURE"
            elif nc == 1 and nh > 1:
                status, reason = "merge", "MULTIPLE_SOURCE_TO_ONE_FUTURE"
            else:
                status, reason = "ambiguous", "MANY_TO_MANY_COMPONENT"
        rows.append({
            "field_id": hk,
            "forward_status": status,
            "forward_reason": reason,
            "component_future_count": int(nc),
            "component_source_count": int(nh),
        })
    return pd.DataFrame(rows).sort_values("field_id", kind="mergesort").reset_index(drop=True)


def cache_paths(cache_root: Path, code: str, source_year: int, future_year: int) -> tuple[Path, Path, Path]:
    d = cache_root / code / f"{source_year}_{future_year}"
    return d / "backward.parquet", d / "forward.parquet", d / "manifest.json"


def transition_pair(
    source: gpd.GeoDataFrame,
    future: gpd.GeoDataFrame,
    code: str,
    municipality: str,
    source_year: int,
    future_year: int,
    cfg: MatchingConfig,
    cache_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    bpath, fpath, mpath = cache_paths(cache_root, code, source_year, future_year)
    contract = {
        "schema_version": "akerpuls-rolling-transition-cache-v0",
        "municipality_code": code,
        "source_year": source_year,
        "future_year": future_year,
        "source_rows": int(len(source)),
        "future_rows": int(len(future)),
        "strict_min_fraction": cfg.strict_min_fraction,
        "relaxed_max_fraction": cfg.relaxed_max_fraction,
        "tie_relative_fraction": cfg.tie_relative_fraction,
    }
    if bpath.exists() and fpath.exists() and mpath.exists():
        try:
            old = read_json(mpath)
            if all(old.get(k) == v for k, v in contract.items()):
                return pd.read_parquet(bpath), pd.read_parquet(fpath), True
        except Exception:
            pass

    matches, edges, qa = map_fields(future, source, cfg)
    backward = matches.rename(columns={
        "current_field_id": "field_id",
        "match_confidence": "backward_status",
        "match_reason": "backward_reason",
        "primary_historical_field_id": "predecessor_id",
    })[[
        "field_id", "backward_status", "backward_reason", "predecessor_id",
        "primary_f_current", "primary_f_historical", "current_area_m2",
    ]].copy()
    forward = classify_source_fields(source, edges, cfg)
    bpath.parent.mkdir(parents=True, exist_ok=True)
    backward.to_parquet(bpath, index=False)
    forward.to_parquet(fpath, index=False)
    manifest = {
        **contract,
        "municipality": municipality,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "positive_area_pairs": int(qa.get("positive_area_pairs", len(edges))),
        "future_match_counts": qa.get("match_counts", {}),
        "source_forward_counts": {str(k): int(v) for k, v in forward["forward_status"].value_counts().sort_index().items()},
    }
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return backward, forward, False


def bool_status(s: pd.Series, allowed: set[str]) -> pd.Series:
    return s.astype(str).isin(allowed)


def build_lineage_features(transitions: dict[int, tuple[pd.DataFrame, pd.DataFrame]], first_year: int, last_year: int) -> dict[int, pd.DataFrame]:
    first_forward = transitions[first_year][1]
    base = pd.DataFrame({"field_id": first_forward["field_id"].astype(str)})
    base["history_n"] = 0
    base["strict_count"] = 0
    base["practical_count"] = 0
    base["splitmerge_count"] = 0
    base["strict_streak"] = 0
    base["years_since_splitmerge"] = np.nan
    base["prev_transition_status"] = "NONE"
    base["lineage_predecessor_found"] = False
    by_year: dict[int, pd.DataFrame] = {first_year: base}

    for year in range(first_year + 1, last_year + 1):
        backward = transitions[year - 1][0].copy()
        prev = by_year[year - 1].copy()
        prev_cols = {
            "field_id": "predecessor_id",
            "history_n": "p_history_n",
            "strict_count": "p_strict_count",
            "practical_count": "p_practical_count",
            "splitmerge_count": "p_splitmerge_count",
            "strict_streak": "p_strict_streak",
            "years_since_splitmerge": "p_years_since_splitmerge",
        }
        prev = prev[list(prev_cols)].rename(columns=prev_cols)
        x = backward.merge(prev, on="predecessor_id", how="left")
        found = x["p_history_n"].notna()
        for col in ("p_history_n", "p_strict_count", "p_practical_count", "p_splitmerge_count", "p_strict_streak"):
            x[col] = x[col].fillna(0).astype(int)
        ev_strict = bool_status(x["backward_status"], STRICT)
        ev_practical = bool_status(x["backward_status"], PRACTICAL)
        ev_sm = bool_status(x["backward_status"], SPLIT_MERGE)
        out = pd.DataFrame({
            "field_id": x["field_id"].astype(str),
            "history_n": x["p_history_n"] + 1,
            "strict_count": x["p_strict_count"] + ev_strict.astype(int),
            "practical_count": x["p_practical_count"] + ev_practical.astype(int),
            "splitmerge_count": x["p_splitmerge_count"] + ev_sm.astype(int),
            "strict_streak": np.where(ev_strict, x["p_strict_streak"] + 1, 0).astype(int),
            "prev_transition_status": x["backward_status"].astype(str),
            "lineage_predecessor_found": found.astype(bool),
        })
        prev_since = pd.to_numeric(x["p_years_since_splitmerge"], errors="coerce")
        out["years_since_splitmerge"] = np.where(
            ev_sm,
            0.0,
            np.where(prev_since.notna(), prev_since + 1.0, np.nan),
        )
        by_year[year] = out
    return by_year


def add_history_categories(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    n = x["history_n"].astype(float).replace(0, np.nan)
    x["strict_fraction"] = (x["strict_count"].astype(float) / n).fillna(0.0)
    f = x["strict_fraction"]
    x["strict_fraction_bin"] = np.select(
        [f < .50, f < .75, f < .90, f < 1.0, f >= 1.0],
        ["LT50", "50_75", "75_90", "90_LT100", "ALL_STRICT"],
        default="UNKNOWN",
    )
    s = x["strict_streak"].astype(int)
    x["streak_bin"] = np.select(
        [s == 0, s == 1, s == 2, s <= 4, s >= 5],
        ["0", "1", "2", "3_4", "5PLUS"],
        default="UNKNOWN",
    )
    x["prior_splitmerge_any"] = x["splitmerge_count"].astype(int) > 0
    x["history_category"] = (
        x["strict_fraction_bin"].astype(str) + "|STREAK_" + x["streak_bin"].astype(str)
        + "|SM_" + x["prior_splitmerge_any"].astype(int).astype(str)
    )
    return x


def safe_rate(mask: pd.Series, outcome: pd.Series) -> tuple[float, int]:
    m = mask.fillna(False).astype(bool)
    n = int(m.sum())
    return (float(outcome[m].mean()) if n else float("nan"), n)


def odds(p: float) -> float:
    if not np.isfinite(p):
        return float("nan")
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    return p / (1 - p)


def rolling_category_predictions(eval_df: pd.DataFrame, target_col: str, start_year: int, smoothing: float) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    pred_base: list[float] = []
    pred_hist: list[float] = []
    actual: list[float] = []
    details: list[pd.DataFrame] = []
    for year in sorted(int(y) for y in eval_df["source_year"].unique() if int(y) >= start_year):
        train = eval_df[eval_df["source_year"] < year]
        test = eval_df[eval_df["source_year"] == year].copy()
        if train.empty or test.empty:
            continue
        p0 = float(train[target_col].mean())
        agg = train.groupby("history_category")[target_col].agg(["sum", "count"])
        lookup = {
            str(k): (float(v["sum"]) + smoothing * p0) / (float(v["count"]) + smoothing)
            for k, v in agg.iterrows()
        }
        ph = test["history_category"].astype(str).map(lookup).fillna(p0).astype(float).to_numpy()
        pb = np.full(len(test), p0, dtype=float)
        yy = test[target_col].astype(float).to_numpy()
        pred_base.extend(pb.tolist()); pred_hist.extend(ph.tolist()); actual.extend(yy.tolist())
        test["rolling_baseline_p"] = pb
        test["rolling_history_p"] = ph
        details.append(test[["municipality_code", "field_id", "source_year", "future_year", "history_category", target_col, "rolling_baseline_p", "rolling_history_p"]])
    detail = pd.concat(details, ignore_index=True) if details else pd.DataFrame()
    return np.asarray(pred_base), np.asarray(pred_hist), np.asarray(actual), detail


def brier(pred: np.ndarray, actual: np.ndarray) -> float:
    return float(np.mean((pred - actual) ** 2)) if len(actual) else float("nan")


def calibrate_2026(eval_df: pd.DataFrame, features_2025: pd.DataFrame, target_col: str, smoothing: float) -> pd.Series:
    p0 = float(eval_df[target_col].mean())
    agg = eval_df.groupby("history_category")[target_col].agg(["sum", "count"])
    lookup = {
        str(k): (float(v["sum"]) + smoothing * p0) / (float(v["count"]) + smoothing)
        for k, v in agg.iterrows()
    }
    return features_2025["history_category"].astype(str).map(lookup).fillna(p0).astype(float)


def write_summary_tables(eval_df: pd.DataFrame, out_dir: Path, min_long: int) -> None:
    long = eval_df[eval_df["history_n"] >= min_long].copy()
    cal = (
        long.groupby("strict_fraction_bin")
        .agg(n=("field_id", "size"), p_next_strict=("target_strict", "mean"), p_next_practical=("target_practical", "mean"), p_next_splitmerge=("target_splitmerge", "mean"))
        .reset_index()
    )
    cal.to_csv(out_dir / "calibration_by_strict_fraction.csv", index=False)
    streak = (
        eval_df.groupby("streak_bin")
        .agg(n=("field_id", "size"), p_next_strict=("target_strict", "mean"), p_next_splitmerge=("target_splitmerge", "mean"))
        .reset_index()
    )
    streak.to_csv(out_dir / "calibration_by_recent_streak.csv", index=False)
    sm = (
        eval_df.groupby("prior_splitmerge_any")
        .agg(n=("field_id", "size"), p_next_strict=("target_strict", "mean"), p_next_splitmerge=("target_splitmerge", "mean"))
        .reset_index()
    )
    sm.to_csv(out_dir / "calibration_by_prior_splitmerge.csv", index=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--workspace")
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg_doc = read_json(Path(args.config))
    workspace = Path(args.workspace or cfg_doc["workspace_default"])
    out_dir = Path(args.output_dir or cfg_doc["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_root = out_dir / "transition_cache"

    raw_root, _local_cfg, project_cfg_path, project_cfg, plan_path = locate_workspace_inputs(workspace)
    plan = read_json(plan_path)
    if int(plan.get("municipality_count", -1)) != int(cfg_doc["expected_municipalities"]):
        raise RuntimeError("Unexpected municipality count in frozen AkerMinne plan")
    municipalities = sorted(plan["municipalities"], key=lambda z: str(z["code"]))

    mc = cfg_doc["matching"]
    match_cfg = MatchingConfig(float(mc["strict_min_fraction"]), float(mc["relaxed_max_fraction"]), float(mc["tie_relative_fraction"]))
    match_cfg.validate()
    years = [int(y) for y in cfg_doc["years"]]
    if years != list(range(2015, 2026)):
        raise RuntimeError("Rolling study contract requires 2015-2025")

    print("AKERPULS TRUE ROLLING GEOMETRY PRIOR BACKTEST")
    print(f"WORKSPACE={workspace}")
    print(f"RAW_ROOT={raw_root}")
    print(f"MUNICIPALITIES={len(municipalities)} YEARS={years[0]}-{years[-1]}")

    all_eval: list[pd.DataFrame] = []
    all_2025: list[pd.DataFrame] = []
    annual_forward: list[pd.DataFrame] = []
    cache_hits = cache_builds = 0
    t0 = time.perf_counter()

    for mi, item in enumerate(municipalities, 1):
        code, name = str(item["code"]), str(item["name"])
        print(f"[{mi:02d}/33] {name} ({code})", flush=True)
        layers: dict[int, gpd.GeoDataFrame] = {}
        for year in years[:-1]:
            p = historical_path(raw_root, name, year)
            if not p.exists():
                raise FileNotFoundError(f"Missing frozen raw annual geometry: {p}")
            layers[year] = gpd.read_file(p)
        layers[2025] = read_2025(project_cfg_path, project_cfg, code)
        if len(layers[2025]) != int(item["current_fields"]):
            raise RuntimeError(f"{name}: 2025 field count {len(layers[2025])} != frozen plan {item['current_fields']}")

        transitions: dict[int, tuple[pd.DataFrame, pd.DataFrame]] = {}
        for source_year in years[:-1]:
            future_year = source_year + 1
            backward, forward, cached = transition_pair(
                layers[source_year], layers[future_year], code, name,
                source_year, future_year, match_cfg, cache_root,
            )
            transitions[source_year] = (backward, forward)
            cache_hits += int(cached); cache_builds += int(not cached)
            y = forward.copy()
            y["municipality_code"] = code
            y["source_year"] = source_year
            y["future_year"] = future_year
            annual_forward.append(y)

        feats = build_lineage_features(transitions, 2015, 2025)
        for source_year in range(2016, 2025):
            f = feats[source_year].copy()
            target = transitions[source_year][1][["field_id", "forward_status"]].copy()
            e = f.merge(target, on="field_id", how="inner", validate="one_to_one")
            e["municipality_code"] = code
            e["source_year"] = source_year
            e["future_year"] = source_year + 1
            e["target_strict"] = bool_status(e["forward_status"], STRICT)
            e["target_practical"] = bool_status(e["forward_status"], PRACTICAL)
            e["target_splitmerge"] = bool_status(e["forward_status"], SPLIT_MERGE)
            all_eval.append(e)
        f25 = feats[2025].copy()
        f25["municipality_code"] = code
        all_2025.append(f25)

        del layers

    eval_df = add_history_categories(pd.concat(all_eval, ignore_index=True))
    f2025 = add_history_categories(pd.concat(all_2025, ignore_index=True))
    annual = pd.concat(annual_forward, ignore_index=True)
    expected_2025 = int(cfg_doc["expected_2025_fields"])
    if len(f2025) != expected_2025:
        raise RuntimeError(f"Expected {expected_2025} 2025 prior-feature rows, got {len(f2025)}")

    annual["target_strict"] = bool_status(annual["forward_status"], STRICT)
    annual["target_practical"] = bool_status(annual["forward_status"], PRACTICAL)
    annual["target_splitmerge"] = bool_status(annual["forward_status"], SPLIT_MERGE)
    annual_rates = (
        annual.groupby(["source_year", "future_year"])
        .agg(n=("field_id", "size"), strict=("target_strict", "mean"), practical=("target_practical", "mean"), splitmerge=("target_splitmerge", "mean"))
        .reset_index()
    )
    annual_rates.to_csv(out_dir / "annual_transition_rates.csv", index=False)

    min_long = int(cfg_doc["rolling_evaluation"]["minimum_history_for_long_history_metrics"])
    start_year = int(cfg_doc["rolling_evaluation"]["probability_model_start_source_year"])
    smoothing = float(cfg_doc["rolling_evaluation"]["category_smoothing_strength"])
    write_summary_tables(eval_df, out_dir, min_long)

    prev_strict = bool_status(eval_df["prev_transition_status"], STRICT)
    prev_sm = bool_status(eval_df["prev_transition_status"], SPLIT_MERGE)
    p_strict_prev, n_strict_prev = safe_rate(prev_strict, eval_df["target_strict"])
    p_strict_nonprev, n_strict_nonprev = safe_rate(~prev_strict, eval_df["target_strict"])
    p_sm_prev, n_sm_prev = safe_rate(prev_sm, eval_df["target_splitmerge"])
    p_sm_nonprev, n_sm_nonprev = safe_rate(~prev_sm, eval_df["target_splitmerge"])

    long = eval_df[eval_df["history_n"] >= min_long]
    all_strict_mask = long["strict_count"] == long["history_n"]
    low_mask = (long["strict_count"] / long["history_n"]) <= .60
    p_all, n_all = safe_rate(all_strict_mask, long["target_strict"])
    p_low, n_low = safe_rate(low_mask, long["target_strict"])
    prior_sm = long["splitmerge_count"] > 0
    p_next_sm_prior, n_next_sm_prior = safe_rate(prior_sm, long["target_splitmerge"])
    p_next_sm_none, n_next_sm_none = safe_rate(~prior_sm, long["target_splitmerge"])

    pb_s, ph_s, yy_s, detail_s = rolling_category_predictions(eval_df, "target_strict", start_year, smoothing)
    pb_m, ph_m, yy_m, detail_m = rolling_category_predictions(eval_df, "target_splitmerge", start_year, smoothing)
    bs0, bsh = brier(pb_s, yy_s), brier(ph_s, yy_s)
    bm0, bmh = brier(pb_m, yy_m), brier(ph_m, yy_m)
    if len(detail_s):
        detail_s.to_parquet(out_dir / "rolling_predictions_strict.parquet", index=False)
    if len(detail_m):
        detail_m.to_parquet(out_dir / "rolling_predictions_splitmerge.parquet", index=False)

    f2025["prototype_p_strict_same_2026"] = calibrate_2026(eval_df, f2025, "target_strict", smoothing)
    f2025["prototype_p_splitmerge_2026"] = calibrate_2026(eval_df, f2025, "target_splitmerge", smoothing)
    f2025["prototype_prior_status"] = "EXPLORATORY_NOT_FROZEN"
    f2025.to_parquet(out_dir / "field_prior_features_2025_for_2026.parquet", index=False)

    eval_df.to_parquet(out_dir / "rolling_evaluation_rows.parquet", index=False)
    f2025[["municipality_code", "field_id", "history_n", "strict_count", "strict_streak", "splitmerge_count", "strict_fraction", "history_category", "prototype_p_strict_same_2026", "prototype_p_splitmerge_2026", "prototype_prior_status"]].to_csv(
        out_dir / "field_prior_2026_preview.csv", index=False
    )

    q_strict = f2025["prototype_p_strict_same_2026"].quantile([.1, .5, .9]).to_dict()
    q_sm = f2025["prototype_p_splitmerge_2026"].quantile([.1, .5, .9]).to_dict()
    result = {
        "schema_version": "akerpuls-geometry-rolling-backtest-result-v0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "raw_root": str(raw_root),
        "municipalities": len(municipalities),
        "rolling_evaluation_rows": int(len(eval_df)),
        "fields_2025": int(len(f2025)),
        "cache_hits": cache_hits,
        "cache_builds": cache_builds,
        "p_next_strict_given_prev_strict": p_strict_prev,
        "p_next_strict_given_prev_nonstrict": p_strict_nonprev,
        "odds_ratio_next_strict_prev_strict_vs_not": odds(p_strict_prev) / odds(p_strict_nonprev),
        "p_next_splitmerge_given_prev_splitmerge": p_sm_prev,
        "p_next_splitmerge_given_prev_not_splitmerge": p_sm_nonprev,
        "odds_ratio_next_splitmerge_prev_splitmerge_vs_not": odds(p_sm_prev) / odds(p_sm_nonprev),
        "p_next_strict_given_all_prior_strict_history_n_ge_min": p_all,
        "n_all_prior_strict": n_all,
        "p_next_strict_given_strict_fraction_le_0_60_history_n_ge_min": p_low,
        "n_low_history": n_low,
        "p_next_splitmerge_given_any_prior_splitmerge_history_n_ge_min": p_next_sm_prior,
        "n_prior_splitmerge": n_next_sm_prior,
        "p_next_splitmerge_given_no_prior_splitmerge_history_n_ge_min": p_next_sm_none,
        "n_no_prior_splitmerge": n_next_sm_none,
        "rolling_brier_strict_baseline": bs0,
        "rolling_brier_strict_history": bsh,
        "rolling_brier_strict_relative_improvement": (1.0 - bsh / bs0) if bs0 > 0 else None,
        "rolling_brier_splitmerge_baseline": bm0,
        "rolling_brier_splitmerge_history": bmh,
        "rolling_brier_splitmerge_relative_improvement": (1.0 - bmh / bm0) if bm0 > 0 else None,
        "prototype_2026_strict_quantiles": {str(k): float(v) for k, v in q_strict.items()},
        "prototype_2026_splitmerge_quantiles": {str(k): float(v) for k, v in q_sm.items()},
        "guards": cfg_doc["guards"],
        "elapsed_seconds": round(time.perf_counter() - t0, 3),
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    for r in annual_rates.itertuples(index=False):
        print(f"TRANSITION_{int(r.source_year)}_{int(r.future_year)} STRICT={r.strict:.4f} PRACTICAL={r.practical:.4f} SPLIT_MERGE={r.splitmerge:.4f} N={int(r.n)}")
    print(f"ROLLING_EVALUATION_ROWS={len(eval_df)} FIELDS_2025={len(f2025)} CACHE_HITS={cache_hits} CACHE_BUILDS={cache_builds}")
    print(f"P_NEXT_STRICT_GIVEN_PREV_STRICT={p_strict_prev:.4f} N={n_strict_prev}")
    print(f"P_NEXT_STRICT_GIVEN_PREV_NONSTRICT={p_strict_nonprev:.4f} N={n_strict_nonprev}")
    print(f"ODDS_RATIO_STRICT_PREV_STRICT_VS_NOT={odds(p_strict_prev)/odds(p_strict_nonprev):.3f}")
    print(f"P_NEXT_STRICT_GIVEN_ALL_PRIOR_STRICT_NGE{min_long}={p_all:.4f} N={n_all}")
    print(f"P_NEXT_STRICT_GIVEN_HIST_FRAC_LE60_NGE{min_long}={p_low:.4f} N={n_low}")
    print(f"P_NEXT_SPLITMERGE_GIVEN_PREV_SPLITMERGE={p_sm_prev:.4f} N={n_sm_prev}")
    print(f"P_NEXT_SPLITMERGE_GIVEN_PREV_NOT_SPLITMERGE={p_sm_nonprev:.4f} N={n_sm_nonprev}")
    print(f"ODDS_RATIO_SPLITMERGE_PREV_VS_NOT={odds(p_sm_prev)/odds(p_sm_nonprev):.3f}")
    print(f"P_NEXT_SPLITMERGE_GIVEN_ANY_PRIOR_SM_NGE{min_long}={p_next_sm_prior:.4f} N={n_next_sm_prior}")
    print(f"P_NEXT_SPLITMERGE_GIVEN_NO_PRIOR_SM_NGE{min_long}={p_next_sm_none:.4f} N={n_next_sm_none}")
    print(f"ROLLING_BRIER_STRICT_BASELINE={bs0:.6f} HISTORY={bsh:.6f} REL_IMPROVEMENT={(1-bsh/bs0):.4f}")
    print(f"ROLLING_BRIER_SPLITMERGE_BASELINE={bm0:.6f} HISTORY={bmh:.6f} REL_IMPROVEMENT={(1-bmh/bm0):.4f}")
    print(f"PROTOTYPE_2026_P_STRICT_P10={q_strict[.1]:.4f} P50={q_strict[.5]:.4f} P90={q_strict[.9]:.4f}")
    print(f"PROTOTYPE_2026_P_SPLITMERGE_P10={q_sm[.1]:.4f} P50={q_sm[.5]:.4f} P90={q_sm[.9]:.4f}")
    print("FEATURES_USE_FUTURE_GEOMETRY=FALSE")
    print("SOURCE_TRANSITIONS_ARE_TRUE_ADJACENT_YEAR_GEOMETRY=TRUE")
    print("PRODUCT_PRIOR_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("ROLLING_BACKTEST_STATUS=PASS")
    print(f"OUTPUT={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
