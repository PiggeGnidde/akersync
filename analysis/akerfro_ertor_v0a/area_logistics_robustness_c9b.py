#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C9b area/logistics robustness.

Robustness checks downstream of C9:
  1) area enrichment within distance bands,
  2) distance enrichment within area bands,
  3) municipality composition / concentration,
  4) post-hoc 5-12 ha & <60 km sweet-zone stability by municipality,
  5) leave-one-municipality-out logistic model using continuous area/distance.

No C8 class or frozen ÄrtMatch artifact is modified.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
except Exception as exc:
    raise RuntimeError("C9b requires scikit-learn") from exc

DEFAULT_CONFIG = ROOT / "config" / "akerfro_ertor_c9b.json"
DEFAULT_C9 = ROOT / "work" / "akerfro_ertor_v0a" / "area_logistics_c9" / "artkandidat_c9_area_logistics_fields.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "area_logistics_c9b"

CANDIDATE_CLASSES = {"A_STRONG_CANDIDATE", "B_PHYSICAL_CANDIDATE"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    q = frame[frame["artkandidat_class"].isin(CANDIDATE_CLASSES)].copy()
    needed = ["field_area_ha", "distance_bjuv_km", "municipality", "is_positive"]
    q = q.dropna(subset=needed)
    q["field_area_ha"] = pd.to_numeric(q["field_area_ha"], errors="coerce")
    q["distance_bjuv_km"] = pd.to_numeric(q["distance_bjuv_km"], errors="coerce")
    q = q[
        q["field_area_ha"].gt(0)
        & q["distance_bjuv_km"].ge(0)
    ].copy()
    q["is_positive"] = q["is_positive"].astype(bool)
    return q


def conditional_enrichment(
    frame: pd.DataFrame,
    condition_col: str,
    target_col: str,
    condition_name: str,
    target_name: str,
) -> pd.DataFrame:
    rows = []
    q = frame[frame[condition_col].notna() & frame[target_col].notna()].copy()
    for cond, g0 in q.groupby(condition_col, observed=False, sort=False):
        if len(g0) == 0:
            continue
        base_rate = float(g0["is_positive"].mean())
        for target, g in g0.groupby(target_col, observed=False, sort=False):
            if len(g) == 0:
                continue
            rate = float(g["is_positive"].mean())
            rows.append({
                condition_name: str(cond),
                target_name: str(target),
                "n_fields": int(len(g)),
                "n_historical_positive": int(g["is_positive"].sum()),
                "historical_positive_rate_pct": 100.0 * rate,
                "conditional_baseline_rate_pct": 100.0 * base_rate,
                "conditional_enrichment": rate / base_rate if base_rate > 0 else np.nan,
                "n_A_2026": int(g["artkandidat_class"].eq("A_STRONG_CANDIDATE").sum()),
                "n_B_2026": int(g["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE").sum()),
            })
    return pd.DataFrame(rows)


def municipality_distance_composition(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    q = frame[frame["distance_band"].notna()].copy()
    for band, gb in q.groupby("distance_band", observed=False, sort=False):
        n_pos_band = int(gb["is_positive"].sum())
        n_band = len(gb)
        for muni, g in gb.groupby("municipality", sort=True):
            npos = int(g["is_positive"].sum())
            rows.append({
                "distance_band": str(band),
                "municipality": str(muni),
                "n_fields": int(len(g)),
                "field_share_of_band_pct": 100.0 * len(g) / n_band if n_band else np.nan,
                "n_historical_positive": npos,
                "positive_share_of_band_pct": (
                    100.0 * npos / n_pos_band if n_pos_band else np.nan
                ),
                "historical_positive_rate_pct": 100.0 * float(g["is_positive"].mean()),
            })
    return pd.DataFrame(rows)


def corrected_odds_ratio(k1: int, n1: int, k0: int, n0: int) -> float:
    a = k1 + 0.5
    b = n1 - k1 + 0.5
    c = k0 + 0.5
    d = n0 - k0 + 0.5
    if b <= 0 or c <= 0:
        return np.nan
    return float((a * d) / (b * c))


def sweet_zone_summary(frame: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    zcfg = cfg["sweet_zone_posthoc"]
    amin = float(zcfg["area_min_ha"])
    amax = float(zcfg["area_max_ha"])
    dmax = float(zcfg["distance_max_km"])

    q = frame.copy()
    q["sweet_zone"] = (
        q["field_area_ha"].ge(amin)
        & q["field_area_ha"].lt(amax)
        & q["distance_bjuv_km"].lt(dmax)
    )

    min_all = int(cfg["municipality_min_candidate_fields"])
    min_zone = int(cfg["municipality_min_sweet_zone_fields"])

    rows = []
    groups = [("__ALL__", q)] + [(str(k), g) for k, g in q.groupby("municipality", sort=True)]
    for muni, g in groups:
        zone = g[g["sweet_zone"]]
        other = g[~g["sweet_zone"]]
        nz, no = len(zone), len(other)
        kz, ko = int(zone["is_positive"].sum()), int(other["is_positive"].sum())
        rz = kz / nz if nz else np.nan
        ro = ko / no if no else np.nan
        evaluable = (
            muni == "__ALL__"
            or (len(g) >= min_all and nz >= min_zone and no > 0)
        )
        rows.append({
            "municipality": muni,
            "n_candidate_fields": int(len(g)),
            "n_sweet_zone_fields": int(nz),
            "n_other_fields": int(no),
            "sweet_zone_positive": kz,
            "other_positive": ko,
            "sweet_zone_positive_rate_pct": 100.0 * rz if nz else np.nan,
            "other_positive_rate_pct": 100.0 * ro if no else np.nan,
            "risk_ratio_sweet_vs_other": rz / ro if ro and ro > 0 else np.nan,
            "odds_ratio_corrected": corrected_odds_ratio(kz, nz, ko, no) if nz and no else np.nan,
            "evaluable_municipality": bool(evaluable),
        })
    return pd.DataFrame(rows)


def make_model_matrix(
    area_ha: pd.Series,
    distance_km: pd.Series,
    mean_log_area: float,
    sd_log_area: float,
    mean_distance: float,
    sd_distance: float,
) -> np.ndarray:
    la = np.log1p(pd.to_numeric(area_ha, errors="coerce").to_numpy(float))
    d = pd.to_numeric(distance_km, errors="coerce").to_numpy(float)
    za = (la - mean_log_area) / sd_log_area
    zd = (d - mean_distance) / sd_distance
    return np.column_stack([za, za ** 2, zd, zd ** 2])


def fit_one_model(train: pd.DataFrame, cfg: dict[str, Any]):
    lcfg = cfg["lomo_model"]
    la = np.log1p(train["field_area_ha"].to_numpy(float))
    d = train["distance_bjuv_km"].to_numpy(float)
    mla = float(np.mean(la))
    sla = float(np.std(la, ddof=0))
    md = float(np.mean(d))
    sd = float(np.std(d, ddof=0))
    if sla <= 0 or sd <= 0:
        raise RuntimeError("C9b standardization failed: zero variance")

    x = make_model_matrix(
        train["field_area_ha"], train["distance_bjuv_km"],
        mla, sla, md, sd
    )
    y = train["is_positive"].astype(int).to_numpy()
    clf = LogisticRegression(
        C=float(lcfg["C"]),
        solver=str(lcfg["solver"]),
        max_iter=int(lcfg["max_iter"]),
        class_weight=lcfg["class_weight"],
        random_state=int(lcfg["random_state"]),
    )
    clf.fit(x, y)
    scale = {
        "mean_log_area": mla,
        "sd_log_area": sla,
        "mean_distance": md,
        "sd_distance": sd,
    }
    return clf, scale


def quadratic_optimum(
    b1: float,
    b2: float,
    mean_raw: float,
    sd_raw: float,
    inverse: str,
) -> float:
    if not np.isfinite(b1) or not np.isfinite(b2) or b2 >= 0 or abs(b2) < 1e-12:
        return np.nan
    z = -b1 / (2.0 * b2)
    raw = mean_raw + z * sd_raw
    if inverse == "log1p":
        return float(np.expm1(raw))
    return float(raw)


def lomo_logistic(frame: pd.DataFrame, cfg: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    feature_names = ["z_log_area", "z_log_area_sq", "z_distance", "z_distance_sq"]
    rows = []
    oof = pd.Series(np.nan, index=frame.index, dtype=float)

    for muni in sorted(frame["municipality"].astype(str).unique()):
        test_mask = frame["municipality"].astype(str).eq(muni)
        train = frame[~test_mask].copy()
        test = frame[test_mask].copy()
        if train["is_positive"].nunique() < 2 or len(test) == 0:
            continue

        clf, scale = fit_one_model(train, cfg)
        xt = make_model_matrix(
            test["field_area_ha"], test["distance_bjuv_km"],
            scale["mean_log_area"], scale["sd_log_area"],
            scale["mean_distance"], scale["sd_distance"],
        )
        p = clf.predict_proba(xt)[:, 1]
        oof.loc[test.index] = p

        auc = np.nan
        if test["is_positive"].nunique() == 2:
            auc = float(roc_auc_score(test["is_positive"].astype(int), p))

        coef = dict(zip(feature_names, clf.coef_[0]))
        rows.append({
            "heldout_municipality": muni,
            "n_test": int(len(test)),
            "n_test_positive": int(test["is_positive"].sum()),
            "test_auc": auc,
            **{f"coef_{k}": float(v) for k, v in coef.items()},
            "area_optimum_ha_if_concave": quadratic_optimum(
                coef["z_log_area"], coef["z_log_area_sq"],
                scale["mean_log_area"], scale["sd_log_area"], "log1p"
            ),
            "distance_optimum_km_if_concave": quadratic_optimum(
                coef["z_distance"], coef["z_distance_sq"],
                scale["mean_distance"], scale["sd_distance"], "identity"
            ),
        })

    folds = pd.DataFrame(rows)
    valid_oof = oof.notna()
    pooled_auc = np.nan
    if valid_oof.any() and frame.loc[valid_oof, "is_positive"].nunique() == 2:
        pooled_auc = float(
            roc_auc_score(
                frame.loc[valid_oof, "is_positive"].astype(int),
                oof.loc[valid_oof],
            )
        )

    full_clf, full_scale = fit_one_model(frame, cfg)
    full_coef = dict(zip(feature_names, full_clf.coef_[0]))
    full = {
        "n_fields": int(len(frame)),
        "n_positive": int(frame["is_positive"].sum()),
        "pooled_lomo_auc": pooled_auc,
        "fold_auc_mean": float(folds["test_auc"].mean()) if len(folds) else np.nan,
        "fold_auc_median": float(folds["test_auc"].median()) if len(folds) else np.nan,
        "fold_auc_min": float(folds["test_auc"].min()) if len(folds) else np.nan,
        "fold_auc_max": float(folds["test_auc"].max()) if len(folds) else np.nan,
        "full_coefficients": {k: float(v) for k, v in full_coef.items()},
        "full_area_optimum_ha_if_concave": quadratic_optimum(
            full_coef["z_log_area"], full_coef["z_log_area_sq"],
            full_scale["mean_log_area"], full_scale["sd_log_area"], "log1p"
        ),
        "full_distance_optimum_km_if_concave": quadratic_optimum(
            full_coef["z_distance"], full_coef["z_distance_sq"],
            full_scale["mean_distance"], full_scale["sd_distance"], "identity"
        ),
        "fold_pct_area_quadratic_negative": (
            100.0 * float(folds["coef_z_log_area_sq"].lt(0).mean()) if len(folds) else np.nan
        ),
        "fold_pct_distance_linear_negative": (
            100.0 * float(folds["coef_z_distance"].lt(0).mean()) if len(folds) else np.nan
        ),
        "fold_pct_distance_quadratic_negative": (
            100.0 * float(folds["coef_z_distance_sq"].lt(0).mean()) if len(folds) else np.nan
        ),
    }
    return folds, full


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--c9", default=str(DEFAULT_C9))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    c9_path = Path(args.c9)
    if not c9_path.exists():
        raise FileNotFoundError(f"Run C9 first: {c9_path}")

    raw = pd.read_parquet(c9_path)
    if len(raw) != 128636:
        raise RuntimeError(f"C9b expected 128,636 C9 rows; got {len(raw):,}")
    frame = candidate_frame(raw)
    if len(frame) < 1000:
        raise RuntimeError("C9b candidate universe unexpectedly small")

    area_within_dist = conditional_enrichment(
        frame, "distance_band", "area_band", "distance_band", "area_band"
    )
    dist_within_area = conditional_enrichment(
        frame, "area_band", "distance_band", "area_band", "distance_band"
    )
    muni_dist = municipality_distance_composition(frame)
    sweet = sweet_zone_summary(frame, cfg)
    folds, model_summary = lomo_logistic(frame, cfg)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    p_area = out / "area_within_distance_enrichment.csv"
    p_dist = out / "distance_within_area_enrichment.csv"
    p_muni = out / "municipality_distance_composition.csv"
    p_sweet = out / "sweet_zone_by_municipality.csv"
    p_folds = out / "lomo_logistic_by_municipality.csv"

    area_within_dist.to_csv(p_area, index=False, encoding="utf-8-sig")
    dist_within_area.to_csv(p_dist, index=False, encoding="utf-8-sig")
    muni_dist.to_csv(p_muni, index=False, encoding="utf-8-sig")
    sweet.to_csv(p_sweet, index=False, encoding="utf-8-sig")
    folds.to_csv(p_folds, index=False, encoding="utf-8-sig")

    eval_sweet = sweet[
        sweet["evaluable_municipality"]
        & sweet["municipality"].ne("__ALL__")
        & sweet["risk_ratio_sweet_vs_other"].notna()
    ]
    global_sweet = sweet[sweet["municipality"].eq("__ALL__")].iloc[0].to_dict()

    report = {
        "schema_version": "akerfro-ertor-area-logistics-c9b-robustness-v0a",
        "candidate_fields": int(len(frame)),
        "historical_positive_fields": int(frame["is_positive"].sum()),
        "candidate_definition": cfg["candidate_universe"],
        "sweet_zone_posthoc": cfg["sweet_zone_posthoc"],
        "global_sweet_zone": {
            k: (bool(v) if isinstance(v, (np.bool_, bool)) else
                int(v) if isinstance(v, (np.integer,)) else
                float(v) if isinstance(v, (np.floating,)) and np.isfinite(v) else
                None if isinstance(v, (np.floating, float)) and not np.isfinite(v) else
                v)
            for k, v in global_sweet.items()
        },
        "sweet_zone_municipality_robustness": {
            "evaluable_municipalities": int(len(eval_sweet)),
            "municipalities_rr_gt_1": int(eval_sweet["risk_ratio_sweet_vs_other"].gt(1).sum()),
            "fraction_rr_gt_1": (
                float(eval_sweet["risk_ratio_sweet_vs_other"].gt(1).mean())
                if len(eval_sweet) else np.nan
            ),
            "median_risk_ratio": (
                float(eval_sweet["risk_ratio_sweet_vs_other"].median())
                if len(eval_sweet) else np.nan
            ),
        },
        "lomo_logistic": model_summary,
        "guardrails": cfg["guardrails"],
        "policy_status": "DIAGNOSTIC_ONLY_NO_C10_POLICY",
        "outputs": {
            "area_within_distance": str(p_area),
            "distance_within_area": str(p_dist),
            "municipality_distance_composition": str(p_muni),
            "sweet_zone_by_municipality": str(p_sweet),
            "lomo_logistic_by_municipality": str(p_folds),
        },
    }
    p_summary = out / "c9b_summary.json"
    p_summary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 128)
    print("ÅkerFrö – Ärter MVP v0a · C9b AREA / LOGISTICS ROBUSTNESS")
    print("=" * 128)
    print(
        f"Candidate universe: {len(frame):,} A/B fields · historical positives: "
        f"{int(frame['is_positive'].sum()):,}"
    )
    print("C8 classes unchanged · ÄrtMatch frozen/read-only · diagnostic only")

    print("\nAREA WITHIN DISTANCE BANDS")
    print(area_within_dist.to_string(index=False, formatters={
        "historical_positive_rate_pct": lambda v: f"{v:.3f}%",
        "conditional_baseline_rate_pct": lambda v: f"{v:.3f}%",
        "conditional_enrichment": lambda v: f"{v:.2f}x",
    }))

    print("\nDISTANCE WITHIN AREA BANDS")
    print(dist_within_area.to_string(index=False, formatters={
        "historical_positive_rate_pct": lambda v: f"{v:.3f}%",
        "conditional_baseline_rate_pct": lambda v: f"{v:.3f}%",
        "conditional_enrichment": lambda v: f"{v:.2f}x",
    }))

    print("\nPOST-HOC SWEET ZONE: 5-12 ha AND <60 km")
    print(
        f"Global: n={int(global_sweet['n_sweet_zone_fields']):,} sweet-zone fields · "
        f"positive rate={float(global_sweet['sweet_zone_positive_rate_pct']):.3f}% vs "
        f"{float(global_sweet['other_positive_rate_pct']):.3f}% outside · "
        f"RR={float(global_sweet['risk_ratio_sweet_vs_other']):.2f}x · "
        f"corrected OR={float(global_sweet['odds_ratio_corrected']):.2f}"
    )
    print(
        f"Municipality robustness: {len(eval_sweet)} evaluable · "
        f"RR>1 in {int(eval_sweet['risk_ratio_sweet_vs_other'].gt(1).sum())} "
        f"({100*float(eval_sweet['risk_ratio_sweet_vs_other'].gt(1).mean()) if len(eval_sweet) else float('nan'):.1f}%) · "
        f"median RR={float(eval_sweet['risk_ratio_sweet_vs_other'].median()) if len(eval_sweet) else float('nan'):.2f}x"
    )

    print("\nTOP MUNICIPALITY CONTRIBUTORS WITHIN EACH DISTANCE BAND")
    top_muni = (
        muni_dist.sort_values(
            ["distance_band", "n_historical_positive", "n_fields"],
            ascending=[True, False, False],
            kind="mergesort",
        )
        .groupby("distance_band", sort=False)
        .head(5)
    )
    print(top_muni.to_string(index=False, formatters={
        "field_share_of_band_pct": lambda v: f"{v:.1f}%",
        "positive_share_of_band_pct": lambda v: f"{v:.1f}%",
        "historical_positive_rate_pct": lambda v: f"{v:.3f}%",
    }))

    print("\nLEAVE-ONE-MUNICIPALITY-OUT CONTINUOUS LOGISTIC MODEL")
    print(
        f"Pooled LOMO AUC={model_summary['pooled_lomo_auc']:.3f} · "
        f"fold mean={model_summary['fold_auc_mean']:.3f} · "
        f"median={model_summary['fold_auc_median']:.3f} · "
        f"range {model_summary['fold_auc_min']:.3f}-{model_summary['fold_auc_max']:.3f}"
    )
    fc = model_summary["full_coefficients"]
    print(
        "Full standardized coefficients: "
        f"log(area)={fc['z_log_area']:+.3f}, "
        f"log(area)^2={fc['z_log_area_sq']:+.3f}, "
        f"distance={fc['z_distance']:+.3f}, "
        f"distance^2={fc['z_distance_sq']:+.3f}"
    )
    print(
        f"Area quadratic negative in {model_summary['fold_pct_area_quadratic_negative']:.1f}% of folds · "
        f"distance linear negative in {model_summary['fold_pct_distance_linear_negative']:.1f}% · "
        f"distance quadratic negative in {model_summary['fold_pct_distance_quadratic_negative']:.1f}%"
    )
    print(
        f"Full-model area optimum if concave: "
        f"{model_summary['full_area_optimum_ha_if_concave']:.2f} ha · "
        f"distance optimum if concave: "
        f"{model_summary['full_distance_optimum_km_if_concave']:.2f} km"
    )

    print("\nGUARDRAILS")
    for g in cfg["guardrails"]:
        print("  - " + g)

    print(f"\nArea within distance: {p_area}")
    print(f"Distance within area: {p_dist}")
    print(f"Sweet-zone stability: {p_sweet}")
    print(f"LOMO folds: {p_folds}")
    print(f"Summary: {p_summary}")
    print("=" * 128)
    print("C9b AREA / LOGISTICS ROBUSTNESS: PASS")
    print("=" * 128)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
