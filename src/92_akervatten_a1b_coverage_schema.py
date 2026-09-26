#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT A1b coverage/schema audit.

This audit:
- reconstructs the old 70,399-field robust eligibility from full 128,636-field inputs,
- separates DATA_MISSING from AVAILABLE_BUT_NOT_OLD_ROBUST,
- inventories static-context terrain/hydrology columns by pattern,
- summarizes raw coverage and distributions.

No new MarkTorka/MarkVäta score is defined here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_a1b.json"
DEFAULT_WORK = ROOT / "work" / "akervatten_mvp_v0a" / "a1b_coverage_schema"

KEY = ["blockid", "skiftesbeteckning"]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        low_memory=False,
        dtype={"blockid": "string", "skiftesbeteckning": "string"},
    )


def pct(n: int, d: int) -> float:
    return 100.0 * n / d if d else np.nan


def finite_coverage(series: pd.Series) -> tuple[int, float]:
    x = pd.to_numeric(series, errors="coerce")
    ok = np.isfinite(x)
    return int(ok.sum()), pct(int(ok.sum()), len(x))


def numeric_quantiles(series: pd.Series) -> dict[str, float | int | None]:
    x = pd.to_numeric(series, errors="coerce")
    x = x[np.isfinite(x)]
    if x.empty:
        return {"n_valid": 0}
    q = x.quantile([0.01,0.05,0.10,0.25,0.50,0.75,0.90,0.95,0.99])
    return {
        "n_valid": int(len(x)),
        "min": float(x.min()),
        "p01": float(q.loc[0.01]),
        "p05": float(q.loc[0.05]),
        "p10": float(q.loc[0.10]),
        "p25": float(q.loc[0.25]),
        "p50": float(q.loc[0.50]),
        "p75": float(q.loc[0.75]),
        "p90": float(q.loc[0.90]),
        "p95": float(q.loc[0.95]),
        "p99": float(q.loc[0.99]),
        "max": float(x.max()),
    }


def reconstruct_old_eligibility(
    soil: pd.DataFrame,
    hydro: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    needed_soil = {
        "blockid","skiftesbeteckning","area_ha",
        "clay_mean","sand_mean",
        "clay_coverage_pct","sand_coverage_pct",
        "clay_n_pix","sand_n_pix",
    }
    needed_hydro = {"blockid","skiftesbeteckning","twi_mean","twi_n_cells"}
    missing = sorted((needed_soil - set(soil.columns)) | (needed_hydro - set(hydro.columns)))
    if missing:
        raise RuntimeError("A1b missing columns needed for old robust filter: " + ", ".join(missing))

    x = soil[list(needed_soil)].merge(
        hydro[list(needed_hydro)],
        on=KEY, how="left", validate="one_to_one"
    )
    f = cfg["old_robust_filter"]

    area = pd.to_numeric(x["area_ha"], errors="coerce")
    clay = pd.to_numeric(x["clay_mean"], errors="coerce")
    sand = pd.to_numeric(x["sand_mean"], errors="coerce")
    clay_cov = pd.to_numeric(x["clay_coverage_pct"], errors="coerce")
    sand_cov = pd.to_numeric(x["sand_coverage_pct"], errors="coerce")
    clay_pix = pd.to_numeric(x["clay_n_pix"], errors="coerce")
    sand_pix = pd.to_numeric(x["sand_n_pix"], errors="coerce")
    twi = pd.to_numeric(x["twi_mean"], errors="coerce")
    twi_cells = pd.to_numeric(x["twi_n_cells"], errors="coerce")

    core_missing = (
        ~np.isfinite(clay) |
        ~np.isfinite(sand) |
        ~np.isfinite(twi)
    )

    old_robust = (
        area.ge(float(f["min_area_ha"]))
        & clay_cov.ge(float(f["min_soil_coverage_pct"]))
        & sand_cov.ge(float(f["min_soil_coverage_pct"]))
        & clay_pix.ge(int(f["min_soil_pixels"]))
        & sand_pix.ge(int(f["min_soil_pixels"]))
        & twi_cells.ge(int(f["min_twi_cells"]))
        & ~core_missing
    )

    x["core_missing"] = core_missing
    x["old_robust"] = old_robust
    x["a1b_data_status"] = np.select(
        [core_missing, old_robust],
        ["DATA_MISSING", "OLD_ROBUST"],
        default="AVAILABLE_BUT_NOT_OLD_ROBUST",
    )
    return x


def exclusion_reasons(x: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    f = cfg["old_robust_filter"]
    checks = {
        "area_lt_1ha": pd.to_numeric(x["area_ha"], errors="coerce").lt(float(f["min_area_ha"])),
        "clay_coverage_lt_90": pd.to_numeric(x["clay_coverage_pct"], errors="coerce").lt(float(f["min_soil_coverage_pct"])),
        "sand_coverage_lt_90": pd.to_numeric(x["sand_coverage_pct"], errors="coerce").lt(float(f["min_soil_coverage_pct"])),
        "clay_pixels_lt_10": pd.to_numeric(x["clay_n_pix"], errors="coerce").lt(int(f["min_soil_pixels"])),
        "sand_pixels_lt_10": pd.to_numeric(x["sand_n_pix"], errors="coerce").lt(int(f["min_soil_pixels"])),
        "twi_cells_lt_25": pd.to_numeric(x["twi_n_cells"], errors="coerce").lt(int(f["min_twi_cells"])),
        "clay_missing": ~np.isfinite(pd.to_numeric(x["clay_mean"], errors="coerce")),
        "sand_missing": ~np.isfinite(pd.to_numeric(x["sand_mean"], errors="coerce")),
        "twi_missing": ~np.isfinite(pd.to_numeric(x["twi_mean"], errors="coerce")),
    }
    rows = []
    n = len(x)
    for name, mask in checks.items():
        rows.append({
            "reason": name,
            "n_fields": int(mask.sum()),
            "pct_all_fields": pct(int(mask.sum()), n),
            "n_among_nonrobust": int((mask & ~x["old_robust"]).sum()),
            "pct_nonrobust": pct(int((mask & ~x["old_robust"]).sum()), int((~x["old_robust"]).sum())),
        })
    return pd.DataFrame(rows).sort_values("n_fields", ascending=False, kind="mergesort")


def raw_coverage_summary(soil: pd.DataFrame, hydro: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("soil","clay_mean"),("soil","sand_mean"),("soil","silt_mean"),
        ("soil","clay_coverage_pct"),("soil","sand_coverage_pct"),("soil","silt_coverage_pct"),
        ("soil","clay_n_pix"),("soil","sand_n_pix"),("soil","silt_n_pix"),
        ("hydrology","twi_mean"),("hydrology","twi_p50"),("hydrology","twi_p90"),
        ("hydrology","twi_n_cells"),
    ]
    tables = {"soil":soil, "hydrology":hydro}
    rows = []
    for source, col in specs:
        df = tables[source]
        if col not in df.columns:
            rows.append({"source":source,"column":col,"present":False})
            continue
        n_valid, coverage = finite_coverage(df[col])
        q = numeric_quantiles(df[col])
        rows.append({
            "source":source, "column":col, "present":True,
            "n_valid":n_valid, "coverage_pct":coverage,
            **{k:v for k,v in q.items() if k!="n_valid"},
        })
    return pd.DataFrame(rows)


def static_context_inventory(static: pd.DataFrame, terms: list[str]) -> tuple[pd.DataFrame,pd.DataFrame]:
    terms_l = [t.lower() for t in terms]
    rows = []
    for col in static.columns:
        lower = col.lower()
        matched = [t for t in terms_l if t in lower]
        if not matched:
            continue
        s = static[col]
        non_null = int(s.notna().sum())
        numeric = pd.to_numeric(s, errors="coerce")
        finite = np.isfinite(numeric)
        row = {
            "column":col,
            "matched_terms":";".join(matched),
            "dtype":str(s.dtype),
            "non_null":non_null,
            "coverage_pct":pct(non_null,len(static)),
            "numeric_valid":int(finite.sum()),
            "numeric_coverage_pct":pct(int(finite.sum()),len(static)),
            "n_unique_non_null":int(s.nunique(dropna=True)),
        }
        if finite.any():
            q = numeric_quantiles(s)
            for k,v in q.items():
                if k!="n_valid":
                    row[k]=v
        rows.append(row)

    matches = pd.DataFrame(rows)
    all_cols = pd.DataFrame({
        "column": list(static.columns),
        "dtype": [str(static[c].dtype) for c in static.columns],
        "non_null": [int(static[c].notna().sum()) for c in static.columns],
        "coverage_pct": [pct(int(static[c].notna().sum()),len(static)) for c in static.columns],
    })
    return matches, all_cols


def verify_old_subset_matches(
    reconstructed: pd.DataFrame,
    old_water: pd.DataFrame,
) -> dict[str, Any]:
    rk = {
        tuple(row) for row in reconstructed.loc[reconstructed["old_robust"], KEY].astype("string").itertuples(index=False, name=None)
    }
    wk = {
        tuple(row) for row in old_water[KEY].astype("string").itertuples(index=False, name=None)
    }
    return {
        "reconstructed_old_robust_n":len(rk),
        "old_water_prospect_n":len(wk),
        "intersection":len(rk & wk),
        "reconstructed_only":len(rk - wk),
        "old_water_only":len(wk - rk),
        "exact_key_match":rk==wk,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--legacy-root", default=r"C:\AkerSyncRepo")
    ap.add_argument("--prestation-root", default=r"C:\AkerSync-Prestation")
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    legacy = Path(args.legacy_root)
    prestation = Path(args.prestation_root)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    paths = {
        "soil": legacy / cfg["inputs"]["soil"],
        "hydrology": legacy / cfg["inputs"]["hydrology"],
        "water_prospect": legacy / cfg["inputs"]["water_prospect"],
        "prestation_static_context": prestation / cfg["inputs"]["prestation_static_context"],
    }
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError("A1b missing local inputs:\n  " + "\n  ".join(missing))

    soil = read_csv(paths["soil"])
    hydro = read_csv(paths["hydrology"])
    old_water = read_csv(paths["water_prospect"])
    static = pd.read_parquet(paths["prestation_static_context"])

    reconstructed = reconstruct_old_eligibility(soil,hydro,cfg)
    reasons = exclusion_reasons(reconstructed,cfg)
    coverage = raw_coverage_summary(soil,hydro)
    static_matches, static_all = static_context_inventory(static,cfg["static_context_search_terms"])
    exact = verify_old_subset_matches(reconstructed,old_water)

    status_counts = reconstructed["a1b_data_status"].value_counts().rename_axis("data_status").reset_index(name="n_fields")
    status_counts["pct_fields"] = 100.0*status_counts["n_fields"]/len(reconstructed)

    problems = []
    if len(reconstructed) != 128636:
        problems.append(f"full population is {len(reconstructed):,}, expected 128,636")
    if len(static) != 128636:
        problems.append(f"static context is {len(static):,}, expected 128,636")
    if not exact["exact_key_match"]:
        problems.append("reconstructed old robust subset does not exactly match old water_prospect keys")

    result = {
        "schema_version":"akervatten-mvp-v0a-a1b-result",
        "status":"PASS" if not problems else "FAIL",
        "population_fields":int(len(reconstructed)),
        "data_status_counts":status_counts.to_dict(orient="records"),
        "old_robust_reconstruction":exact,
        "static_context_rows":int(len(static)),
        "static_context_columns":int(len(static.columns)),
        "static_context_pattern_matches":int(len(static_matches)),
        "guardrails":cfg["guardrails"],
        "problems":problems,
    }

    status_counts.to_csv(work/"data_status_counts.csv",index=False,encoding="utf-8-sig")
    reasons.to_csv(work/"old_robust_exclusion_reasons.csv",index=False,encoding="utf-8-sig")
    coverage.to_csv(work/"raw_core_coverage.csv",index=False,encoding="utf-8-sig")
    static_matches.to_csv(work/"static_context_pattern_matches.csv",index=False,encoding="utf-8-sig")
    static_all.to_csv(work/"static_context_all_columns.csv",index=False,encoding="utf-8-sig")
    reconstructed[KEY+["a1b_data_status","core_missing","old_robust"]].to_parquet(
        work/"a1b_field_data_status.parquet",index=False
    )
    (work/"a1b_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*112)
    print("ÅkerVatten MVP v0a · STOPPUNKT A1b COVERAGE / SCHEMA AUDIT")
    print("="*112)

    print("\nDATA STATUS · 128,636 FIELD POPULATION")
    print(status_counts.to_string(index=False,formatters={"pct_fields":lambda v:f"{v:.2f}%"}))

    print("\nOLD 70,399-FIELD FILTER RECONSTRUCTION")
    for k,v in exact.items():
        print(f"  {k:28s}: {v}")

    print("\nOLD ROBUST FILTER · EXCLUSION REASONS")
    print(reasons.to_string(index=False,formatters={
        "pct_all_fields":lambda v:f"{v:.2f}%",
        "pct_nonrobust":lambda v:f"{v:.2f}%",
    }))

    print("\nRAW CORE COVERAGE")
    showcols=[c for c in ["source","column","present","n_valid","coverage_pct","p10","p50","p90"] if c in coverage.columns]
    print(coverage[showcols].to_string(index=False,formatters={
        "coverage_pct":lambda v:f"{v:.2f}%" if pd.notna(v) else "",
        "p10":lambda v:f"{v:.3f}" if pd.notna(v) else "",
        "p50":lambda v:f"{v:.3f}" if pd.notna(v) else "",
        "p90":lambda v:f"{v:.3f}" if pd.notna(v) else "",
    }))

    print("\nPRESTATION STATIC CONTEXT · TERRAIN/HYDROLOGY NAME MATCHES")
    print(f"  rows={len(static):,} cols={len(static.columns)} matched_cols={len(static_matches)}")
    if len(static_matches):
        display_cols=[c for c in ["column","matched_terms","dtype","coverage_pct","numeric_coverage_pct","p10","p50","p90"] if c in static_matches.columns]
        print(static_matches[display_cols].to_string(index=False,formatters={
            "coverage_pct":lambda v:f"{v:.2f}%",
            "numeric_coverage_pct":lambda v:f"{v:.2f}%",
            "p10":lambda v:f"{v:.3f}" if pd.notna(v) else "",
            "p50":lambda v:f"{v:.3f}" if pd.notna(v) else "",
            "p90":lambda v:f"{v:.3f}" if pd.notna(v) else "",
        }))
    else:
        print("  No columns matched configured terrain/hydrology search terms.")

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  - "+p)

    print(f"\nOutputs: {work}")
    print("="*112)
    print(f"AKERVATTEN A1b COVERAGE / SCHEMA AUDIT: {result['status']}")
    print("="*112)
    return 0 if not problems else 2


if __name__=="__main__":
    raise SystemExit(main())
