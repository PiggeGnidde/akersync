#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö C7c – broken sugar-beet ring / contract-shock study.

Hypothesis:
    A field in the established rotation state
        t-2 winter rapeseed -> t-1 winter wheat -> [expected sugar beet at t]
    may switch to CONSERVART in shock year 2025 when sugar-beet contracting
    tightens and processing-pea grower demand changes.

The primary test is temporal:
    compare 2025 with placebo years 2019-2024.

Three nested exposure definitions are reported:
  RING_STATE:
      t-2 == winter rapeseed AND t-1 == winter wheat
  RING_STATE + PRIOR_BEET_FIELD:
      above + field had any clean sugar beet before t
  RING_STATE + SAME_SLOT_REPEAT:
      above + field previously completed
              winter rapeseed -> winter wheat -> sugar beet

Optional reuse:
  If a frozen prior_2025.parquet from vaxfoljd-prior-m4-v1.0-rc1 can be found
  under a sibling C:\\AkerSync* tree, C7c inspects and, where schema permits,
  reports M4 expected-beet -> actual CONSERVART cases as an additional 2025
  diagnostic. The ring/placebo study does not depend on this optional file.

No frozen ÄrtMatch artifact is modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.build_history import (
    load_config as load_base_config,
    load_frozen_summary,
    municipality_dirs,
)
from analysis.akerfro_ertor_v0a.crop_groups import CONSERVART, normalize_crop_name

DEFAULT_BASE_CONFIG = ROOT / "config" / "akerfro_ertor_v0a.json"
DEFAULT_C7C_CONFIG = ROOT / "config" / "akerfro_ertor_c7c.json"
DEFAULT_AKERMINNE_ROOT = ROOT.parent / "AkerSync-Minne"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "contract_shock_c7c"

RAPS = "raps (höst)"
WINTER_WHEAT = "vete (höst)"
SUGAR_BEET = "sockerbetor"
SPRING_BARLEY = "korn (vår)"

EXPOSURES = {
    "ring_state": "exposure_ring_state",
    "ring_state_prior_beet_field": "exposure_prior_beet",
    "ring_state_same_slot_repeat": "exposure_same_slot",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_crop_panel(summary: pd.DataFrame) -> pd.DataFrame:
    x = summary[summary["is_clean"]].copy()
    x["crop_key"] = x["dominant_crop_name"].map(normalize_crop_name).astype("string")
    x["is_conservart"] = x["akerfro_group"].eq(CONSERVART)
    x["is_sugar_beet"] = x["crop_key"].eq(SUGAR_BEET)
    x["is_winter_rapeseed"] = x["crop_key"].eq(RAPS)
    x["is_winter_wheat"] = x["crop_key"].eq(WINTER_WHEAT)
    x["is_spring_barley"] = x["crop_key"].eq(SPRING_BARLEY)
    return x


def wide_crop(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.pivot(
        index="current_field_id",
        columns="history_year",
        values="crop_key",
    )


def prior_any_crop(wide: pd.DataFrame, field_ids: pd.Index, year: int, crop: str) -> pd.Series:
    prior_cols = [c for c in wide.columns if int(c) < year]
    if not prior_cols:
        return pd.Series(False, index=field_ids)
    q = wide.reindex(field_ids)[prior_cols]
    return q.eq(crop).any(axis=1)


def prior_same_slot(wide: pd.DataFrame, field_ids: pd.Index, year: int) -> pd.Series:
    """Earlier completed RAPS -> WINTER_WHEAT -> SUGAR_BEET before target year."""
    ids = pd.Index(field_ids)
    out = pd.Series(False, index=ids)
    w = wide.reindex(ids)
    for y in sorted(int(c) for c in wide.columns):
        if y >= year:
            break
        if (y - 1) not in wide.columns or (y - 2) not in wide.columns:
            continue
        hit = (
            w[y - 2].eq(RAPS)
            & w[y - 1].eq(WINTER_WHEAT)
            & w[y].eq(SUGAR_BEET)
        )
        out = out | hit.fillna(False)
    return out


def event_table(panel: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    wide = wide_crop(panel)
    municipality = (
        panel.sort_values(["current_field_id", "history_year"], kind="mergesort")
        .groupby("current_field_id", sort=True)
        .tail(1)
        .set_index("current_field_id")["municipality"]
    )

    rows = []
    for year in years:
        needed = [year - 2, year - 1, year]
        if not all(y in wide.columns for y in needed):
            continue
        ids = wide.index[
            wide[year - 2].notna() & wide[year - 1].notna() & wide[year].notna()
        ]
        q = pd.DataFrame(index=ids)
        q["target_year"] = year
        q["municipality"] = municipality.reindex(ids)
        q["crop_tminus2"] = wide.loc[ids, year - 2]
        q["crop_tminus1"] = wide.loc[ids, year - 1]
        q["actual_crop"] = wide.loc[ids, year]
        q["ring_state"] = q["crop_tminus2"].eq(RAPS) & q["crop_tminus1"].eq(WINTER_WHEAT)
        q["prior_beet_field"] = prior_any_crop(wide, ids, year, SUGAR_BEET).to_numpy()
        q["same_slot_repeat"] = prior_same_slot(wide, ids, year).to_numpy()
        q["actual_sugar_beet"] = q["actual_crop"].eq(SUGAR_BEET)

        actual_lookup = panel[panel["history_year"].eq(year)].set_index("current_field_id")["is_conservart"]
        q["actual_conservart"] = actual_lookup.reindex(ids).fillna(False).astype(bool).to_numpy()
        q["actual_spring_barley"] = q["actual_crop"].eq(SPRING_BARLEY)

        q["exposure_ring_state"] = q["ring_state"]
        q["exposure_prior_beet"] = q["ring_state"] & q["prior_beet_field"]
        q["exposure_same_slot"] = q["ring_state"] & q["same_slot_repeat"]
        rows.append(q.reset_index())

    if not rows:
        raise RuntimeError("C7c found no evaluable years")
    return pd.concat(rows, ignore_index=True)


def year_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in sorted(events["target_year"].unique()):
        y = events[events["target_year"].eq(year)]
        for label, col in EXPOSURES.items():
            g = y[y[col]].copy()
            n = len(g)
            cons = int(g["actual_conservart"].sum())
            beet = int(g["actual_sugar_beet"].sum())
            barley = int(g["actual_spring_barley"].sum())
            rows.append({
                "target_year": int(year),
                "exposure": label,
                "n_exposed_fields": int(n),
                "actual_conservart": cons,
                "conservart_pct": 100.0 * cons / n if n else np.nan,
                "actual_sugar_beet": beet,
                "sugar_beet_pct": 100.0 * beet / n if n else np.nan,
                "actual_spring_barley": barley,
                "spring_barley_pct": 100.0 * barley / n if n else np.nan,
                "other_crop": int(n - cons - beet - barley),
            })
    return pd.DataFrame(rows)


def pooled_placebo_comparison(
    events: pd.DataFrame,
    shock_year: int,
    placebo_years: list[int],
) -> pd.DataFrame:
    rows = []
    for label, col in EXPOSURES.items():
        shock = events[events["target_year"].eq(shock_year) & events[col]].copy()
        placebo = events[events["target_year"].isin(placebo_years) & events[col]].copy()
        for outcome, outcol in [
            ("CONSERVART", "actual_conservart"),
            ("SUGAR_BEET", "actual_sugar_beet"),
        ]:
            ns, np_ = len(shock), len(placebo)
            ks = int(shock[outcol].sum())
            kp = int(placebo[outcol].sum())
            rs = ks / ns if ns else np.nan
            rp = kp / np_ if np_ else np.nan
            rr = rs / rp if rp and rp > 0 else np.nan
            a, b = ks + 0.5, ns - ks + 0.5
            c, d = kp + 0.5, np_ - kp + 0.5
            odds_ratio = (a * d) / (b * c) if b > 0 and c > 0 else np.nan
            rows.append({
                "exposure": label,
                "outcome": outcome,
                "shock_year": shock_year,
                "shock_n": ns,
                "shock_events": ks,
                "shock_pct": 100.0 * rs if ns else np.nan,
                "placebo_years": ",".join(map(str, placebo_years)),
                "placebo_n": np_,
                "placebo_events": kp,
                "placebo_pct": 100.0 * rp if np_ else np.nan,
                "difference_pp": 100.0 * (rs - rp) if ns and np_ else np.nan,
                "risk_ratio": rr,
                "odds_ratio_corrected": odds_ratio,
            })
    return pd.DataFrame(rows)


def actual_outcomes(events: pd.DataFrame, exposure_col: str, year: int, n: int = 20) -> pd.DataFrame:
    g = events[events["target_year"].eq(year) & events[exposure_col]]
    return (
        g.groupby("actual_crop", dropna=False)
        .agg(n_fields=("current_field_id", "size"))
        .reset_index()
        .sort_values("n_fields", ascending=False, kind="mergesort")
        .head(n)
    )


def discover_prior_2025() -> list[Path]:
    candidates: list[Path] = []
    known = [
        Path("C:/AkerSyncRepo/work/vaxtfoljd_prior_v1_freeze/prior_2025.parquet"),
        ROOT / "work" / "vaxtfoljd_prior_v1_freeze" / "prior_2025.parquet",
    ]
    for p in known:
        if p.exists():
            candidates.append(p)

    croot = Path("C:/")
    if croot.exists():
        for repo_root in sorted(croot.glob("AkerSync*")):
            work = repo_root / "work"
            if not work.exists():
                continue
            try:
                for p in work.glob("**/prior_2025.parquet"):
                    if p not in candidates:
                        candidates.append(p)
            except OSError:
                pass
    return candidates


def find_field_id_col(columns: list[str]) -> str | None:
    for c in ["current_field_id", "field_id", "skifte_id", "field_key"]:
        if c in columns:
            return c
    return None


def inspect_m4_prior(
    prior_path: Path,
    panel: pd.DataFrame,
    shock_year: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    p = pd.read_parquet(prior_path)
    cols = [str(c) for c in p.columns]
    result: dict[str, Any] = {
        "path": str(prior_path),
        "rows": int(len(p)),
        "columns": cols,
        "used_for_beet_diagnostic": False,
    }
    field_col = find_field_id_col(cols)
    if field_col is None:
        result["reason_not_used"] = "No recognized field-id column"
        return result, pd.DataFrame()

    beet_prob_cols = [
        c for c in cols
        if ("socker" in normalize_crop_name(c))
        and any(tok in normalize_crop_name(c) for tok in ["p_", "prob", "prior", "sannolik"])
    ]
    top_cols = [
        c for c in cols
        if normalize_crop_name(c) in {
            "top1", "top_1", "top1_class", "predicted_class", "prior_top1", "crop_top1"
        }
    ]

    q = p.copy()
    q[field_col] = q[field_col].astype(str)
    actual = panel[panel["history_year"].eq(shock_year)][
        ["current_field_id", "dominant_crop_name", "is_conservart", "is_sugar_beet"]
    ].copy()
    actual["current_field_id"] = actual["current_field_id"].astype(str)

    merged = q.merge(
        actual,
        left_on=field_col,
        right_on="current_field_id",
        how="inner",
    )
    result["matched_2025_fields"] = int(len(merged))

    detail_cols = [field_col, "current_field_id", "dominant_crop_name", "is_conservart", "is_sugar_beet"]

    if beet_prob_cols:
        c = beet_prob_cols[0]
        merged["_beet_prior"] = pd.to_numeric(merged[c], errors="coerce")
        result["beet_probability_column"] = c
        result["beet_prior_nonnull"] = int(merged["_beet_prior"].notna().sum())
        cutoff = float(merged["_beet_prior"].quantile(.90))
        hi = merged[merged["_beet_prior"].ge(cutoff)].copy()
        result["beet_prior_p90_cutoff"] = cutoff
        result["top_decile_beet_prior_fields"] = int(len(hi))
        result["top_decile_actual_conservart"] = int(hi["is_conservart"].sum())
        result["top_decile_actual_sugar_beet"] = int(hi["is_sugar_beet"].sum())
        result["used_for_beet_diagnostic"] = True
        detail_cols += [c, "_beet_prior"]

    if top_cols:
        c = top_cols[0]
        top = merged[c].map(normalize_crop_name)
        beet_top = top.eq(SUGAR_BEET)
        result["top1_column"] = c
        result["top1_beet_fields"] = int(beet_top.sum())
        result["top1_beet_actual_conservart"] = int((beet_top & merged["is_conservart"]).sum())
        result["top1_beet_actual_sugar_beet"] = int((beet_top & merged["is_sugar_beet"]).sum())
        result["used_for_beet_diagnostic"] = True
        detail_cols += [c]

    if not result["used_for_beet_diagnostic"]:
        result["reason_not_used"] = "No recognized sugar-beet probability or top1 column"

    return result, merged[[c for c in detail_cols if c in merged.columns]].copy()


def shock_signature_table(comparison: pd.DataFrame) -> pd.DataFrame:
    beet = comparison[comparison["outcome"].eq("SUGAR_BEET")][
        ["exposure", "difference_pp", "risk_ratio"]
    ].rename(columns={
        "difference_pp": "beet_difference_pp",
        "risk_ratio": "beet_risk_ratio",
    })
    pea = comparison[comparison["outcome"].eq("CONSERVART")][
        ["exposure", "difference_pp", "risk_ratio"]
    ].rename(columns={
        "difference_pp": "pea_difference_pp",
        "risk_ratio": "pea_risk_ratio",
    })
    out = pea.merge(beet, on="exposure", how="outer", validate="one_to_one")
    out["directional_contract_shock_signature"] = (
        out["pea_difference_pp"].gt(0) & out["beet_difference_pp"].lt(0)
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", default=str(DEFAULT_BASE_CONFIG))
    ap.add_argument("--c7c-config", default=str(DEFAULT_C7C_CONFIG))
    ap.add_argument("--akerminne-root", default=str(DEFAULT_AKERMINNE_ROOT))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    base_cfg = load_base_config(Path(args.base_config))
    cfg = load_json(Path(args.c7c_config))
    shock_year = int(cfg["shock_year"])
    placebo_years = [int(x) for x in cfg["placebo_years"]]
    years = placebo_years + [shock_year]

    dirs = municipality_dirs(Path(args.akerminne_root), base_cfg)
    summary = load_frozen_summary(dirs, base_cfg)
    panel = clean_crop_panel(summary)

    events = event_table(panel, years)
    ys = year_summary(events)
    comp = pooled_placebo_comparison(events, shock_year, placebo_years)
    signature = shock_signature_table(comp)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    events_path = out / "broken_ring_field_years.parquet"
    ys_path = out / "broken_ring_by_year.csv"
    comp_path = out / "shock_vs_placebo.csv"
    sig_path = out / "shock_signature.csv"
    events.to_parquet(events_path, index=False)
    ys.to_csv(ys_path, index=False, encoding="utf-8-sig")
    comp.to_csv(comp_path, index=False, encoding="utf-8-sig")
    signature.to_csv(sig_path, index=False, encoding="utf-8-sig")

    outcome_paths = {}
    for label, col in EXPOSURES.items():
        q = actual_outcomes(events, col, shock_year, n=25)
        p = out / f"actual_2025_outcomes_{label}.csv"
        q.to_csv(p, index=False, encoding="utf-8-sig")
        outcome_paths[label] = str(p)

    prior_candidates = discover_prior_2025()
    prior_report = {
        "model_contract": "vaxfoljd-prior-m4-v1.0-rc1 / M4-hard multiclass",
        "found_candidates": [str(p) for p in prior_candidates],
        "selected": None,
        "diagnostic": None,
    }
    m4_detail_path = None
    if prior_candidates:
        selected = prior_candidates[0]
        prior_report["selected"] = str(selected)
        diag, detail = inspect_m4_prior(selected, panel, shock_year)
        prior_report["diagnostic"] = diag
        if len(detail):
            m4_detail_path = out / "m4_prior_2025_beet_diagnostic.parquet"
            detail.to_parquet(m4_detail_path, index=False)

    report = {
        "schema_version": "akerfro-ertor-contract-shock-c7c-v0a",
        "hypothesis": (
            "Fields occupying an expected sugar-beet slot after winter rapeseed -> winter wheat "
            "may disproportionately switch to CONSERVART in 2025 relative to 2019-2024 placebo years."
        ),
        "shock_year": shock_year,
        "placebo_years": placebo_years,
        "ring_state": "t-2 winter rapeseed -> t-1 winter wheat",
        "expected_crop": "sugar beet",
        "substitute_of_interest": "CONSERVART",
        "exposure_definitions": {
            "ring_state": "current t-2 rapeseed and t-1 winter wheat",
            "ring_state_prior_beet_field": "ring_state + any earlier clean sugar beet on same field",
            "ring_state_same_slot_repeat": (
                "ring_state + an earlier completed rapeseed -> winter wheat -> sugar beet triplet on same field"
            ),
        },
        "reuse": {
            "general_ring": "winter rapeseed -> winter wheat -> sugar beet -> spring barley -> winter rapeseed",
            "m4_model_contract": "vaxfoljd-prior-m4-v1.0-rc1",
            "m4_prior_2025": prior_report,
        },
        "guardrails": cfg["guardrails"],
        "artmatch_v0a_untouched": True,
        "outputs": {
            "field_years": str(events_path),
            "by_year": str(ys_path),
            "shock_vs_placebo": str(comp_path),
            "shock_signature": str(sig_path),
            "actual_2025_outcomes": outcome_paths,
            "m4_detail": str(m4_detail_path) if m4_detail_path else None,
        },
    }
    summary_path = out / "c7c_summary.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 128)
    print("ÅkerFrö – Ärter MVP v0a · C7c BROKEN SUGAR-BEET RING / CONTRACT-SHOCK STUDY")
    print("=" * 128)
    print("Expected ring reused: höstraps -> höstvete -> [sockerbeta] -> vårkorn -> höstraps")
    print(f"Shock year: {shock_year} · placebo years: {placebo_years}")
    print("ÄrtMatch v0a: READ-ONLY / unchanged")

    print("\nBY YEAR")
    print(ys.to_string(index=False, formatters={
        "conservart_pct": lambda v: f"{v:.3f}%",
        "sugar_beet_pct": lambda v: f"{v:.3f}%",
        "spring_barley_pct": lambda v: f"{v:.3f}%",
    }))

    print("\n2025 SHOCK VS POOLED PLACEBO 2019-2024")
    print(comp.to_string(index=False, formatters={
        "shock_pct": lambda v: f"{v:.3f}%",
        "placebo_pct": lambda v: f"{v:.3f}%",
        "difference_pp": lambda v: f"{v:+.3f}",
        "risk_ratio": lambda v: "NA" if pd.isna(v) else f"{v:.2f}x",
        "odds_ratio_corrected": lambda v: f"{v:.2f}",
    }))

    print("\nDIRECTIONAL CONTRACT-SHOCK SIGNATURE")
    print(signature.to_string(index=False, formatters={
        "pea_difference_pp": lambda v: f"{v:+.3f}",
        "pea_risk_ratio": lambda v: "NA" if pd.isna(v) else f"{v:.2f}x",
        "beet_difference_pp": lambda v: f"{v:+.3f}",
        "beet_risk_ratio": lambda v: "NA" if pd.isna(v) else f"{v:.2f}x",
    }))

    print("\nACTUAL 2025 OUTCOMES: SAME-SLOT REPEAT")
    print(actual_outcomes(events, "exposure_same_slot", shock_year, 20).to_string(index=False))

    print("\nFROZEN M4 PRIOR REUSE")
    if not prior_candidates:
        print("  prior_2025.parquet not found under targeted C:\\AkerSync* work directories.")
        print("  Ring/placebo test remains complete; M4 2025 diagnostic skipped.")
    else:
        print(f"  Found: {prior_candidates[0]}")
        diag = prior_report["diagnostic"] or {}
        print(f"  Rows: {diag.get('rows')} · matched 2025 fields: {diag.get('matched_2025_fields')}")
        if diag.get("used_for_beet_diagnostic"):
            if "beet_probability_column" in diag:
                print(
                    "  Beet-prior top decile: "
                    f"{diag.get('top_decile_beet_prior_fields')} fields · "
                    f"actual conservärt {diag.get('top_decile_actual_conservart')} · "
                    f"actual sugar beet {diag.get('top_decile_actual_sugar_beet')}"
                )
            if "top1_column" in diag:
                print(
                    "  M4 top1=sugar beet: "
                    f"{diag.get('top1_beet_fields')} fields · "
                    f"actual conservärt {diag.get('top1_beet_actual_conservart')} · "
                    f"actual sugar beet {diag.get('top1_beet_actual_sugar_beet')}"
                )
        else:
            print("  File found but beet columns were not auto-recognized.")
            print("  Columns were saved in c7c_summary.json for a deterministic schema patch.")

    print("\nGUARDRAILS")
    for g in cfg["guardrails"]:
        print("  - " + g)

    print(f"\nBy-year table: {ys_path}")
    print(f"Shock comparison: {comp_path}")
    print(f"Summary: {summary_path}")
    print("=" * 128)
    print("C7c BROKEN SUGAR-BEET RING: PASS")
    print("=" * 128)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
