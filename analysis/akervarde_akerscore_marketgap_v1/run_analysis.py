#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen retrospective ÅkerVärde × ÅkerScore market-gap analysis v1.0.

This script is standalone and read-only with respect to source project data.
It verifies exact input SHA256 hashes, reconstructs the frozen ÅkerVärde v1.0-rc1
sample, links each sale to the already locked v0h reconstructed agricultural
blocks, aggregates current ÅkerScore over those blocks, forms historic-class and
local class×SKO×municipality score-surprise variables, and reruns same-row
spatial CV comparisons.

Interpretation guardrail:
This is a retrospective diagnostic information-gap study developed after the
ÅkerScore × ÅkerMinne behavioural-validation result was known. It is NOT a
prospective/blind validation and does not prove causal mispricing or arbitrage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import spearmanr


HERE = Path(__file__).resolve().parent
DEFAULT_EXPECTED = HERE / "expected_results.json"
DEFAULT_MANIFEST = HERE / "manifests" / "input_manifest.json"

ARABLE_BASE = ["year_centered", "log_area_20", "lat_centered", "lon_centered"]
COMPONENT_SEEDS = {
    "house": 15_000.0,
    "econ": 1_500.0,
    "pasture": 80_000.0,
    "forest": 100_000.0,
    "imped": 10_000.0,
    "other": 30_000.0,
}
ARABLE_SEED = 300_000.0
MIN_COMPONENT_ACTIVE = 20
MIN_GEO_COMPONENT_ACTIVE = 80


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def materialize_input(path: Path, temp_root: Path, label: str) -> Path:
    if path.is_dir():
        return path
    if path.is_file() and path.suffix.lower() == ".zip":
        dst = temp_root / label
        dst.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(dst)
        return dst
    raise FileNotFoundError(f"Input must be a directory or ZIP: {path}")


def verify_inputs(av_dir: Path, score_dir: Path, manifest: dict) -> None:
    errors = []
    for item in manifest["files"]:
        base = av_dir if item["source_group"] == "akervarde" else score_dir
        p = base / item["relative_path"]
        if not p.exists():
            errors.append(f"missing: {p}")
            continue
        got = sha256_file(p)
        if got.lower() != item["sha256"].lower():
            errors.append(f"sha mismatch: {p}\n expected {item['sha256']}\n got      {got}")
            continue
        if item.get("rows") is not None:
            if p.name.endswith(".csv.gz"):
                n = len(pd.read_csv(p, compression="gzip"))
            elif p.suffix.lower() == ".csv":
                n = len(pd.read_csv(p, encoding="utf-8-sig"))
            else:
                n = None
            if n is not None and int(n) != int(item["rows"]):
                errors.append(f"row mismatch: {p}: expected {item['rows']}, got {n}")
    if errors:
        raise RuntimeError("INPUT VERIFICATION FAILED:\n" + "\n".join(errors))
    print("INPUT VERIFICATION: PASS")


def num(s):
    return pd.to_numeric(s, errors="coerce")


def safe_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype("string").str.strip().str.casefold().isin({"1", "true", "yes", "ja"})


def stable_fold(value, k=10):
    h = hashlib.sha1(str(value).encode("utf-8")).hexdigest()
    return int(h[:8], 16) % k


def prepare_value_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    qty = [
        "smahus_kvm_total_n", "ekonomibyggnad_kvm_total_n",
        "betesmark_ha_n", "skogsmark_ha_n", "skogsimpediment_ha_n",
        "smahusmark_kvm_total_n",
    ]
    for c in qty:
        if c not in d.columns:
            d[c] = 0.0
        d[c] = num(d[c]).fillna(0.0).clip(lower=0.0)

    for c in [
        "kopeskilling_kr_n", "akermark_ha_n", "total_areal_ha_n",
        "lat_n", "lon_n", "year", "aker_share_frac",
    ]:
        d[c] = num(d[c])

    d["year_centered"] = d["year"] - 2024.0
    d["lat_centered"] = d["lat_n"] - 55.5
    d["lon_centered"] = d["lon_n"] - 13.0
    d["log_area_20"] = np.log(d["akermark_ha_n"] / 20.0)

    d["aker_beskaffenhet_score0"] = num(d["aker_beskaffenhet_score"]).fillna(0.0)
    d["aker_beskaffenhet_mixed0"] = num(d["aker_beskaffenhet_mixed"]).fillna(0.0)

    state = d["drainage_state"].fillna("missing").astype(str)
    d["drain_unsatisfactory"] = state.eq("unsatisfactory").astype(float)
    d["drain_legacy_system_tiled"] = state.eq("legacy_system_tiled").astype(float)
    d["drain_missing_other"] = (~state.isin([
        "satisfactory_other", "unsatisfactory", "legacy_system_tiled"
    ])).astype(float)

    component_area = (
        d["akermark_ha_n"].fillna(0)
        + d["betesmark_ha_n"]
        + d["skogsmark_ha_n"]
        + d["skogsimpediment_ha_n"]
    )
    d["other_ha"] = (d["total_areal_ha_n"].fillna(0) - component_area).clip(lower=0.0)

    if "sale_spatial_cell" not in d.columns:
        d["sale_spatial_cell"] = d["sale_id"].astype(str)
    groupkey = d["sale_spatial_cell"].fillna(d["sale_id"]).astype(str)
    d["spatial_fold10"] = groupkey.map(lambda x: stable_fold(x, 10)).astype(int)

    d["anchor_strict"] = (
        d["smahus_kvm_total_n"].eq(0)
        & d["ekonomibyggnad_kvm_total_n"].eq(0)
        & d["skogsmark_ha_n"].eq(0)
        & d["betesmark_ha_n"].eq(0)
        & d["skogsimpediment_ha_n"].eq(0)
        & d["other_ha"].le(0.5)
    )

    if "expanded_main_eligible" in d.columns:
        eligible = safe_bool(d["expanded_main_eligible"])
    else:
        eligible = pd.Series(True, index=d.index)

    d["v0j_eligible"] = (
        eligible
        & d["kopeskilling_kr_n"].gt(0)
        & d["akermark_ha_n"].gt(0)
        & d["total_areal_ha_n"].gt(0)
        & d["lat_n"].notna()
        & d["lon_n"].notna()
        & d["year"].notna()
    )
    return d


def nuisance_specs(df: pd.DataFrame):
    specs = []

    def add(name, qty, terms):
        active = int(num(df[qty]).fillna(0).gt(0).sum())
        if active >= MIN_COMPONENT_ACTIVE:
            specs.append((name, qty, terms, COMPONENT_SEEDS[name], active))

    n_house = int(df["smahus_kvm_total_n"].gt(0).sum())
    add(
        "house", "smahus_kvm_total_n",
        ["year_centered", "lat_centered", "lon_centered"]
        if n_house >= MIN_GEO_COMPONENT_ACTIVE else [],
    )

    n_econ = int(df["ekonomibyggnad_kvm_total_n"].gt(0).sum())
    add("econ", "ekonomibyggnad_kvm_total_n", ["year_centered"] if n_econ >= 50 else [])

    n_past = int(df["betesmark_ha_n"].gt(0).sum())
    add("pasture", "betesmark_ha_n", ["year_centered"] if n_past >= 50 else [])

    n_for = int(df["skogsmark_ha_n"].gt(0).sum())
    if n_for >= MIN_COMPONENT_ACTIVE:
        terms = ["year_centered", "lat_centered", "lon_centered"] if n_for >= MIN_GEO_COMPONENT_ACTIVE else []
        add("forest", "skogsmark_ha_n", terms)

    add("imped", "skogsimpediment_ha_n", [])
    add("other", "other_ha", [])
    return specs


def param_names(arable_terms, nuis):
    names = ["arable_log_rate0"] + [f"arable_{t}" for t in arable_terms]
    for name, qty, terms, seed, active in nuis:
        names += [f"{name}_log_rate0"] + [f"{name}_{t}" for t in terms]
    return names


def initial_params(arable_terms, nuis):
    p = [math.log(ARABLE_SEED)] + [0.0] * len(arable_terms)
    for name, qty, terms, seed, active in nuis:
        p += [math.log(seed)] + [0.0] * len(terms)
    return np.asarray(p, float)


def parameter_bounds(arable_terms, nuis):
    names = param_names(arable_terms, nuis)
    lo = np.full(len(names), -3.0, float)
    hi = np.full(len(names), +3.0, float)
    for i, n in enumerate(names):
        if n.endswith("log_rate0"):
            lo[i] = math.log(10.0)
            hi[i] = math.log(50_000_000.0)
    return lo, hi


def predict_components(df, p, arable_terms, nuis):
    n = len(df)
    i = 0
    eta = np.full(n, p[i], float)
    i += 1
    for t in arable_terms:
        eta += p[i] * num(df[t]).to_numpy(float)
        i += 1
    arable_rate = np.exp(np.clip(eta, -20.0, 25.0))
    total = num(df["akermark_ha_n"]).to_numpy(float) * arable_rate

    for name, qty, terms, seed, active in nuis:
        eta = np.full(n, p[i], float)
        i += 1
        for t in terms:
            eta += p[i] * num(df[t]).to_numpy(float)
            i += 1
        rate = np.exp(np.clip(eta, -20.0, 25.0))
        total += num(df[qty]).fillna(0).to_numpy(float) * rate
    return total


def complete(df, arable_terms, nuis):
    cols = ["kopeskilling_kr_n", "akermark_ha_n", *arable_terms]
    for name, qty, terms, seed, active in nuis:
        cols += [qty, *terms]
    cols = list(dict.fromkeys(cols))
    mask = pd.Series(True, index=df.index)
    for c in cols:
        if c not in df.columns:
            return df.iloc[0:0].copy()
        mask &= num(df[c]).notna()
    mask &= num(df["kopeskilling_kr_n"]).gt(0)
    mask &= num(df["akermark_ha_n"]).gt(0)
    return df.loc[mask].copy()


def fit_model(df, arable_terms, nuis=None, p0=None, max_nfev=800):
    if nuis is None:
        nuis = nuisance_specs(df)
    x = complete(df, arable_terms, nuis).reset_index(drop=True)
    if len(x) < max(30, len(param_names(arable_terms, nuis)) + 10):
        return None
    y = num(x["kopeskilling_kr_n"]).to_numpy(float)
    if p0 is None or len(p0) != len(param_names(arable_terms, nuis)):
        p0 = initial_params(arable_terms, nuis)
    lo, hi = parameter_bounds(arable_terms, nuis)

    def residual(p):
        pred = predict_components(x, p, arable_terms, nuis)
        return np.log(np.maximum(pred, 1.0)) - np.log(y)

    res = least_squares(
        residual, p0, bounds=(lo, hi), loss="soft_l1", f_scale=0.20,
        max_nfev=max_nfev, xtol=1e-8, ftol=1e-8, gtol=1e-8,
    )
    pred = predict_components(x, res.x, arable_terms, nuis)
    return {
        "data": x, "params": res.x, "names": param_names(arable_terms, nuis),
        "nuis": nuis, "pred": pred,
    }


def r2_log(y, pred):
    y = np.asarray(y, float)
    pred = np.asarray(pred, float)
    ok = np.isfinite(y) & np.isfinite(pred) & (y > 0) & (pred > 0)
    yy = np.log(y[ok])
    pp = np.log(pred[ok])
    den = np.sum((yy - yy.mean()) ** 2)
    return float(1.0 - np.sum((yy - pp) ** 2) / den)


def spatial_cv10(df, arable_terms):
    nuis = nuisance_specs(df)
    full = fit_model(df, arable_terms, nuis=nuis)
    if full is None:
        raise RuntimeError("fit failed")
    x = full["data"].copy().reset_index(drop=True)
    y = num(x["kopeskilling_kr_n"]).to_numpy(float)
    pred = np.full(len(x), np.nan, float)
    for f in sorted(x["spatial_fold10"].dropna().astype(int).unique().tolist()):
        train = x.loc[x["spatial_fold10"].ne(f)].copy()
        test_idx = x.index[x["spatial_fold10"].eq(f)].to_numpy()
        fit = fit_model(train, arable_terms, nuis=nuis, p0=full["params"], max_nfev=250)
        if fit is None:
            raise RuntimeError(f"fold {f} fit failed")
        pred[test_idx] = predict_components(x.loc[test_idx], fit["params"], arable_terms, nuis)

    ape = 100.0 * np.abs(pred / y - 1.0)
    return {
        "full": full,
        "data": x,
        "cv_pred": pred,
        "n": int(len(x)),
        "cv_r2_log": r2_log(y, pred),
        "median_ape_pct": float(np.median(ape)),
        "p75_ape_pct": float(np.percentile(ape, 75)),
        "p90_ape_pct": float(np.percentile(ape, 90)),
        "median_observed_pred_ratio": float(np.median(y / pred)),
    }


def weighted_mean(g: pd.DataFrame, col: str) -> float:
    ok = g[col].notna() & g["area_ha"].notna() & g["area_ha"].gt(0)
    if not ok.any():
        return np.nan
    return float(np.average(g.loc[ok, col], weights=g.loc[ok, "area_ha"]))


def build_transaction_score_features(
    frozen: pd.DataFrame,
    members: pd.DataFrame,
    score: pd.DataFrame,
    context: pd.DataFrame,
):
    frozen_ids = set(frozen["sale_id"].astype(str))
    m = members[members["sale_id"].astype(str).isin(frozen_ids)].copy()
    m["sale_id"] = m["sale_id"].astype(str)
    m["blockid_s"] = num(m["blockid"]).astype("Int64").astype(str)

    score = score.copy()
    score["blockid_s"] = num(score["blockid"]).astype("Int64").astype(str)

    context = context.copy()
    context["current_block_id_s"] = num(context["current_block_id"]).astype("Int64").astype(str)

    fields = score.merge(
        context[[
            "current_field_id", "municipality", "dominant_soil_class",
            "dominant_soil_class_share", "soil_class_coverage_unique",
            "mixed_soil_class", "dominant_sko_id",
        ]],
        on="current_field_id", how="left", validate="one_to_one",
    )

    # Raw transaction ÅkerScore over all valid scored current fields in locked sale blocks.
    raw_join = m.merge(
        fields[["current_field_id", "blockid_s", "area_ha", "akerscore_soil_p50"]],
        on="blockid_s", how="left",
    )
    raw_join["valid_score_area"] = np.where(
        raw_join["akerscore_soil_p50"].notna(), raw_join["area_ha"], 0.0
    )
    denom = m.groupby("sale_id")["block_area_ha"].sum().rename("selected_block_area_ha")
    raw_area = raw_join.groupby("sale_id")["valid_score_area"].sum().rename("score_area_ha")
    raw_count = raw_join.groupby("sale_id")["akerscore_soil_p50"].apply(lambda x: int(x.notna().sum())).rename("score_field_n")
    raw = pd.concat([denom, raw_area, raw_count], axis=1).reset_index()
    raw["score_coverage"] = raw["score_area_ha"] / raw["selected_block_area_ha"]

    raw_score_rows = []
    for sid, g in raw_join.groupby("sale_id", sort=False):
        raw_score_rows.append({"sale_id": sid, "tx_akerscore": weighted_mean(g, "akerscore_soil_p50")})
    raw_score = pd.DataFrame(raw_score_rows)
    raw = raw.merge(raw_score, on="sale_id", how="left")

    # Strict historical-class context used for surprise variables.
    fields["strict_context"] = (
        num(fields["dominant_soil_class"]).between(5, 10)
        & fields["akerscore_soil_p50"].notna()
        & num(fields["soil_class_coverage_unique"]).ge(0.95)
        & num(fields["dominant_soil_class_share"]).ge(0.95)
        & ~fields["mixed_soil_class"].fillna(False).astype(bool)
    )
    strict = fields.loc[fields["strict_context"]].copy()

    class_median = strict.groupby("dominant_soil_class")["akerscore_soil_p50"].median()
    strict["class_expected_score"] = strict["dominant_soil_class"].map(class_median)
    strict["class_surprise"] = strict["akerscore_soil_p50"] - strict["class_expected_score"]

    local_stats = strict.groupby(
        ["dominant_soil_class", "dominant_sko_id", "municipality"]
    )["akerscore_soil_p50"].agg(["median", "size"])
    local_median = local_stats.loc[local_stats["size"].ge(25), "median"]
    idx = pd.MultiIndex.from_frame(
        strict[["dominant_soil_class", "dominant_sko_id", "municipality"]]
    )
    strict["local_expected_score"] = local_median.reindex(idx).to_numpy()
    strict["local_surprise"] = strict["akerscore_soil_p50"] - strict["local_expected_score"]

    strict_join = m.merge(
        strict[[
            "current_field_id", "blockid_s", "area_ha", "akerscore_soil_p50",
            "class_surprise", "local_surprise",
        ]],
        on="blockid_s", how="left",
    )
    strict_join["strict_area"] = np.where(
        strict_join["akerscore_soil_p50"].notna(), strict_join["area_ha"], 0.0
    )
    strict_area = strict_join.groupby("sale_id")["strict_area"].sum().rename("strict_context_area_ha")
    strict_cov = pd.concat([denom, strict_area], axis=1).reset_index()
    strict_cov["strict_context_coverage"] = (
        strict_cov["strict_context_area_ha"] / strict_cov["selected_block_area_ha"]
    )

    surprise_rows = []
    for sid, g in strict_join.groupby("sale_id", sort=False):
        surprise_rows.append({
            "sale_id": sid,
            "tx_akerscore_strict": weighted_mean(g, "akerscore_soil_p50"),
            "class_surprise": weighted_mean(g, "class_surprise"),
            "local_surprise": weighted_mean(g, "local_surprise"),
        })
    surprise = pd.DataFrame(surprise_rows)

    tx = (
        frozen[["sale_id"]].copy()
        .assign(sale_id=lambda x: x["sale_id"].astype(str))
        .merge(raw, on="sale_id", how="left")
        .merge(strict_cov[["sale_id", "strict_context_coverage"]], on="sale_id", how="left")
        .merge(surprise, on="sale_id", how="left")
    )

    aux = {
        "strict_field_n": int(len(strict)),
        "local_benchmark_groups_total": int(len(local_stats)),
        "local_benchmark_groups_n_ge25": int(local_stats["size"].ge(25).sum()),
    }
    return tx, aux


def same_row_comparison(df: pd.DataFrame, feature: str):
    base = spatial_cv10(df, ARABLE_BASE)
    aug = spatial_cv10(df, ARABLE_BASE + [feature])
    name = f"arable_{feature}"
    idx = aug["full"]["names"].index(name)
    coef = float(aug["full"]["params"][idx])
    effect10 = float(100.0 * (math.exp(coef * 10.0) - 1.0))
    return {
        "n": int(len(df)),
        "feature": feature,
        "base_cv_r2": base["cv_r2_log"],
        "aug_cv_r2": aug["cv_r2_log"],
        "delta_cv_r2": aug["cv_r2_log"] - base["cv_r2_log"],
        "base_median_ape_pct": base["median_ape_pct"],
        "aug_median_ape_pct": aug["median_ape_pct"],
        "base_p75_ape_pct": base["p75_ape_pct"],
        "aug_p75_ape_pct": aug["p75_ape_pct"],
        "base_p90_ape_pct": base["p90_ape_pct"],
        "aug_p90_ape_pct": aug["p90_ape_pct"],
        "feature_coefficient_per_score_point": coef,
        "multiplicative_effect_pct_per_10_score": effect10,
    }


def approx_equal(a, b, tol):
    return np.isfinite(a) and np.isfinite(b) and abs(float(a) - float(b)) <= float(tol)


def verify_results(results: dict, expected: dict):
    errors = []

    for key, exp in expected["exact"].items():
        got = results
        for part in key.split("."):
            got = got[part]
        if int(got) != int(exp):
            errors.append(f"{key}: expected {exp}, got {got}")

    for key, spec in expected["approx"].items():
        got = results
        for part in key.split("."):
            got = got[part]
        if not approx_equal(got, spec["value"], spec["tol"]):
            errors.append(
                f"{key}: expected {spec['value']} ± {spec['tol']}, got {got}"
            )

    if errors:
        raise RuntimeError("RESULT VERIFICATION FAILED:\n" + "\n".join(errors))
    print("RESULT VERIFICATION: PASS")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--akervarde-input", required=True, help="Directory or ZIP from akervarde_residual_inputs packager")
    ap.add_argument("--akerscore-input", required=True, help="Directory or ZIP containing field_static_context_selected.csv.gz and akerscore_soil_skiften_selected.csv.gz")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--expected", default=str(DEFAULT_EXPECTED))
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="marketgap_v1_") as td:
        tmp = Path(td)
        av_dir = materialize_input(Path(args.akervarde_input), tmp, "akervarde")
        score_dir = materialize_input(Path(args.akerscore_input), tmp, "akerscore")
        verify_inputs(av_dir, score_dir, manifest)

        frozen = pd.read_csv(
            av_dir / "akervarde_v1_0_rc1_freeze" / "cv10_predictions.csv",
            encoding="utf-8-sig",
        )
        value_raw = pd.read_csv(
            av_dir / "frozen_feature_source" / "kt_regime_features.csv",
            encoding="utf-8-sig",
        )
        members = pd.read_csv(
            av_dir / "value_regression_v0h_kt_expanded" / "multiblock_members.csv",
            encoding="utf-8-sig",
        )
        score = pd.read_csv(
            score_dir / "akerscore_soil_skiften_selected.csv.gz",
            compression="gzip",
        )
        context = pd.read_csv(
            score_dir / "field_static_context_selected.csv.gz",
            compression="gzip",
            dtype={"dominant_sko_id": "string"},
        )

        frozen["sale_id"] = frozen["sale_id"].astype(str)
        value_raw["sale_id"] = value_raw["sale_id"].astype(str)
        members["sale_id"] = members["sale_id"].astype(str)

        print(
            f"Loaded frozen={len(frozen):,}, value_features={len(value_raw):,}, "
            f"members={len(members):,}, score={len(score):,}, context={len(context):,}"
        )

        d = prepare_value_features(value_raw)
        sample = d.loc[
            d["v0j_eligible"].fillna(False).astype(bool)
            & num(d["aker_share_frac"]).ge(0.70)
            & num(d["skogsmark_ha_n"]).eq(0)
        ].copy().reset_index(drop=True)

        if set(sample["sale_id"].astype(str)) != set(frozen["sale_id"].astype(str)):
            raise RuntimeError("Reconstructed S70_NOFOREST sample does not match frozen 233 sale IDs.")

        baseline = spatial_cv10(sample, ARABLE_BASE)

        tx, aux = build_transaction_score_features(frozen, members, score, context)
        data = sample.merge(tx, on="sale_id", how="left", validate="one_to_one")
        data = data.merge(
            frozen[[
                "sale_id", "akervarde_cv10_pred_total_kr",
                "akervarde_cv10_observed_to_pred_ratio",
            ]],
            on="sale_id", how="left", validate="one_to_one",
        )
        data["frozen_log_price_residual"] = np.log(
            num(data["kopeskilling_kr_n"]) / num(data["akervarde_cv10_pred_total_kr"])
        )

        inventory = {
            "frozen_sales": int(len(frozen)),
            "sales_with_locked_reconstruction": int(tx["selected_block_area_ha"].notna().sum()),
            "sales_with_any_score": int(tx["tx_akerscore"].notna().sum()),
            "score_coverage_ge80": int(num(tx["score_coverage"]).ge(0.80).sum()),
            "score_coverage_ge90": int(num(tx["score_coverage"]).ge(0.90).sum()),
            "score_coverage_ge95": int(num(tx["score_coverage"]).ge(0.95).sum()),
            "strict_context_coverage_ge80": int(num(tx["strict_context_coverage"]).ge(0.80).sum()),
            "strict_context_coverage_ge90": int(num(tx["strict_context_coverage"]).ge(0.90).sum()),
            "strict_context_coverage_ge95": int(num(tx["strict_context_coverage"]).ge(0.95).sum()),
            "local_surprise_n_at_strict90": int(
                (num(tx["strict_context_coverage"]).ge(0.90) & tx["local_surprise"].notna()).sum()
            ),
            **aux,
        }

        # Frozen core incremental tests. Other thresholds were explored during
        # development but are deliberately not part of the v1.0 verifier.
        raw_cv = []
        for th in [0.90, 0.95]:
            q = data.loc[
                num(data["score_coverage"]).ge(th) & data["tx_akerscore"].notna()
            ].copy()
            row = same_row_comparison(q, "tx_akerscore")
            row["coverage_threshold"] = th
            raw_cv.append(row)

        class_cv = []
        th = 0.80
        q = data.loc[
            num(data["strict_context_coverage"]).ge(th)
            & data["class_surprise"].notna()
        ].copy()
        row = same_row_comparison(q, "class_surprise")
        row["coverage_threshold"] = th
        class_cv.append(row)

        local_cv = []
        th = 0.90
        q = data.loc[
            num(data["strict_context_coverage"]).ge(th)
            & data["local_surprise"].notna()
        ].copy()
        row = same_row_comparison(q, "local_surprise")
        row["coverage_threshold"] = th
        local_cv.append(row)

        def corr_row(label, feature, mask):
            q = data.loc[mask, [feature, "frozen_log_price_residual"]].dropna()
            r = spearmanr(q[feature], q["frozen_log_price_residual"])
            return {
                "signal": label,
                "feature": feature,
                "n": int(len(q)),
                "spearman_rho": float(r.statistic),
                "p_value": float(r.pvalue),
            }

        correlations = [
            corr_row(
                "raw_akerscore",
                "tx_akerscore",
                num(data["score_coverage"]).ge(0.90) & data["tx_akerscore"].notna(),
            ),
            corr_row(
                "class_surprise",
                "class_surprise",
                num(data["strict_context_coverage"]).ge(0.90) & data["class_surprise"].notna(),
            ),
            corr_row(
                "local_class_sko_municipality_surprise",
                "local_surprise",
                num(data["strict_context_coverage"]).ge(0.90) & data["local_surprise"].notna(),
            ),
        ]

        local90 = data.loc[
            num(data["strict_context_coverage"]).ge(0.90) & data["local_surprise"].notna()
        ].copy()
        p75_surprise = float(local90["local_surprise"].quantile(0.75))
        p25_ratio = float(local90["akervarde_cv10_observed_to_pred_ratio"].quantile(0.25))
        local90["retrospective_candidate"] = (
            local90["local_surprise"].ge(p75_surprise)
            & local90["akervarde_cv10_observed_to_pred_ratio"].le(p25_ratio)
        )
        candidates = local90.loc[local90["retrospective_candidate"]].copy()

        # Descriptive strict-anchor examples. Humlarp is intentionally NOT asserted
        # to belong to the strict quartile candidate screen.
        example_names = ["Borrby 43:34", "Humlarp 4:12"]
        examples = data.loc[
            data["fastighetsbeteckningar"].astype(str).isin(example_names),
            [
                "sale_id", "fastighetsbeteckningar", "year", "anchor_strict",
                "tx_akerscore", "local_surprise",
                "akervarde_cv10_observed_to_pred_ratio",
            ],
        ].copy()

        results = {
            "study_id": "akervarde-akerscore-marketgap-v1.0",
            "interpretation": "retrospective diagnostic information-gap study; not prospective/blind validation and not proof of causal mispricing",
            "baseline_reproduction": {
                "n": baseline["n"],
                "cv_r2_log": baseline["cv_r2_log"],
                "median_ape_pct": baseline["median_ape_pct"],
                "p90_ape_pct": baseline["p90_ape_pct"],
            },
            "inventory": inventory,
            "raw_score_cv": {f"ge{int(round(r['coverage_threshold'] * 100))}": r for r in raw_cv},
            "class_surprise_cv": {f"ge{int(round(r['coverage_threshold'] * 100))}": r for r in class_cv},
            "local_surprise_cv": {f"ge{int(round(r['coverage_threshold'] * 100))}": r for r in local_cv},
            "residual_correlations": {r["signal"]: r for r in correlations},
            "retrospective_candidate_screen": {
                "sample_n": int(len(local90)),
                "local_surprise_p75": p75_surprise,
                "observed_pred_ratio_p25": p25_ratio,
                "candidate_n": int(len(candidates)),
            },
        }

        verify_results(results, expected)

        outdir = Path(args.out_dir)
        outdir.mkdir(parents=True, exist_ok=True)

        pd.DataFrame([inventory]).to_csv(outdir / "coverage_inventory.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(raw_cv).to_csv(outdir / "cv_incremental_raw_score.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(class_cv).to_csv(outdir / "cv_incremental_class_surprise.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(local_cv).to_csv(outdir / "cv_incremental_local_surprise.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(correlations).to_csv(outdir / "residual_correlations.csv", index=False, encoding="utf-8-sig")

        candidate_cols = [
            c for c in [
                "sale_id", "datum", "fastighetsbeteckningar", "municipality_county",
                "year", "anchor_strict", "akermark_ha_n", "tx_akerscore",
                "local_surprise", "akervarde_cv10_observed_to_pred_ratio",
                "kopeskilling_kr_n", "akervarde_cv10_pred_total_kr",
            ] if c in candidates.columns
        ]
        candidates[candidate_cols].sort_values(
            "akervarde_cv10_observed_to_pred_ratio"
        ).to_csv(outdir / "retrospective_candidates.csv", index=False, encoding="utf-8-sig")

        examples.to_csv(outdir / "strict_anchor_examples.csv", index=False, encoding="utf-8-sig")

        tx_cols = [
            "sale_id", "selected_block_area_ha", "score_area_ha", "score_coverage",
            "tx_akerscore", "strict_context_coverage", "tx_akerscore_strict",
            "class_surprise", "local_surprise",
        ]
        tx[tx_cols].to_csv(outdir / "transaction_score_features.csv", index=False, encoding="utf-8-sig")

        (outdir / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        verification = {
            "input_verification": "PASS",
            "result_verification": "PASS",
            "study_id": results["study_id"],
        }
        (outdir / "verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print()
        print("=" * 92)
        print("ÅkerVärde × ÅkerScore market-gap v1.0")
        print("=" * 92)
        print(f"Frozen ÅkerVärde sales: {inventory['frozen_sales']:,}")
        print(f"Locked reconstruction:   {inventory['sales_with_locked_reconstruction']:,}")
        print(f"Any ÅkerScore:           {inventory['sales_with_any_score']:,}")
        print(f"Score coverage >=80/90/95%: "
              f"{inventory['score_coverage_ge80']:,}/"
              f"{inventory['score_coverage_ge90']:,}/"
              f"{inventory['score_coverage_ge95']:,}")
        print(f"Strict-context >=90%:    {inventory['strict_context_coverage_ge90']:,}")
        print(f"Local surprise n:        {inventory['local_surprise_n_at_strict90']:,}")
        print()
        r90 = results["raw_score_cv"]["ge90"]
        print(f"Raw score >=90%: BASE R2 {r90['base_cv_r2']:.4f} -> "
              f"{r90['aug_cv_r2']:.4f}; median APE "
              f"{r90['base_median_ape_pct']:.2f}% -> {r90['aug_median_ape_pct']:.2f}%")
        r95 = results["raw_score_cv"]["ge95"]
        print(f"Raw score >=95%: BASE R2 {r95['base_cv_r2']:.4f} -> "
              f"{r95['aug_cv_r2']:.4f}; median APE "
              f"{r95['base_median_ape_pct']:.2f}% -> {r95['aug_median_ape_pct']:.2f}%")
        print()
        for r in correlations:
            print(f"{r['signal']}: n={r['n']}, Spearman={r['spearman_rho']:.4f}, p={r['p_value']:.4f}")
        print()
        print(f"Retrospective candidate screen: {len(candidates)} / {len(local90)}")
        print("RESULT VERIFICATION: PASS")
        print("Output:", outdir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
