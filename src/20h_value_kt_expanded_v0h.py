#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0h — expanded K/T sample.

Purpose
-------
Use ATL's total tax assessment as an offset/normalizer so that built farms and
moderately mixed properties can contribute to the price experiment without
pretending that the entire purchase price is arable-land value.

Target:
    log(K/T exact) = log(purchase_price / tax_assessed_value)

The total tax assessment already reflects the mixed property package.  We then
ask whether market premium/discount to tax value depends on:
  * time and simple geography;
  * property composition (arable/forest/buildings);
  * ATL/fastighetstaxering arable "beskaffenhet";
  * the frozen modern transaction FerrariScore when reconstruction permits it.

Beskaffenhet is NOT a laboratory soil analysis.  It is an official tax-quality
factor describing production capacity + cultivation conditions relative to the
value area.  Mixed ATL strings are parsed as an unweighted mean of the distinct
reported levels and flagged as mixed; this is diagnostic because ATL does not
carry area weights for the individual valuation units.

Drainage is kept as a separate sensitivity diagnostic.  Historic ATL records can
contain the older three-level wording (including system/plant tile drainage),
while current tax rules use two functional classes.  We do not silently merge
those systems into ground truth.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd

import value_multiblock as mb
import value_transaction_soil as txsoil

KT_MIN = 0.50
KT_MAX = 6.00
FERRARI = "tx_ferrari_score"

GEO = ["year_centered", "lat_centered", "lon_centered"]
MIX = GEO + [
    "log_tax_million",
    "aker_share_frac",
    "forest_share_frac",
    "pasture_share_frac",
    "has_smallhouse",
    "has_econ_building",
    "log1p_smallhouse_kvm",
    "log1p_econ_kvm",
]
BESK = MIX + ["aker_beskaffenhet_score", "aker_beskaffenhet_mixed"]

BESK_MAP = {
    "Mycket bättre produktionsförmåga än normalt": 2.0,
    "Bättre produktionsförmåga än normalt": 1.0,
    "Normal produktionsförmåga": 0.0,
    "Sämre produktionsförmåga än normalt": -1.0,
    "Mycket sämre produktionsförmåga än normalt": -2.0,
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def num(s):
    return pd.to_numeric(
        s.astype("string")
        .str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )


def normalized_properties(v) -> str:
    if pd.isna(v):
        return ""
    parts = [x.strip() for x in str(v).split("|") if x.strip()]
    return " | ".join(sorted(set(parts)))


def bool01(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.casefold().isin({"1", "true", "yes", "ja"})


def parse_beskaffenhet(v):
    if pd.isna(v) or not str(v).strip():
        return np.nan, 0, np.nan
    parts = [x.strip() for x in str(v).split("|") if x.strip()]
    vals = [BESK_MAP[x] for x in parts if x in BESK_MAP]
    if not vals:
        return np.nan, int(len(parts) > 1), np.nan
    return float(np.mean(vals)), int(len(set(vals)) > 1), float(max(vals) - min(vals))


def parse_drainage(v):
    """Return diagnostic drainage state; deliberately not a continuous truth scale."""
    text = "" if pd.isna(v) else str(v).strip()
    if not text:
        return "missing", np.nan, 0
    parts = [x.strip() for x in text.split("|") if x.strip()]
    states = []
    for x in parts:
        z = x.casefold()
        if "otillfredsställ" in z or "otillfredsstall" in z:
            states.append("unsatisfactory")
        elif "plantäckdik" in z or "plantackdik" in z or "systemtäckdik" in z or "systemtackdik" in z:
            states.append("legacy_system_tiled")
        elif "tillfredställande dränerad" in z or "tillfredsställande dränerad" in z or "självdränerad" in z or "sjalvdranerad" in z:
            states.append("satisfactory_other")
        else:
            states.append("other")
    uniq = sorted(set(states))
    mixed = int(len(uniq) > 1)
    state = uniq[0] if len(uniq) == 1 else "mixed"
    # score only for a simple sensitivity: bad=-1, satisfactory-other=0,
    # legacy system-tiled=+1. Mixed/other/missing stay NaN.
    score = {"unsatisfactory": -1.0, "satisfactory_other": 0.0, "legacy_system_tiled": 1.0}.get(state, np.nan)
    return state, score, mixed


def load_expanded(atl: Path, since: pd.Timestamp):
    raw = pd.read_csv(atl, sep=";", encoding="utf-8-sig", dtype=str)
    required = [
        "datum", "kopeskilling_kr", "taxeringsvarde_kr", "akermark_ha",
        "total_areal_ha", "lat", "lon", "fastighetsbeteckningar",
    ]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise RuntimeError("ATL CSV saknar kolumner: " + ", ".join(missing))

    d = raw.copy()
    numeric_cols = [
        "kopeskilling_kr", "taxeringsvarde_kr", "kt_tal", "total_areal_ha",
        "jordbruksmark_ha", "akermark_ha", "betesmark_ha", "skogsmark_ha",
        "skogsimpediment_ha", "akerandel_pct", "ekonomibyggnad_kvm_total",
        "smahus_kvm_total", "smahusmark_kvm_total", "lat", "lon",
    ]
    for c in numeric_cols:
        if c in d.columns:
            d[c + "_n"] = num(d[c])
        else:
            d[c + "_n"] = np.nan

    d["date"] = pd.to_datetime(d["datum"], errors="coerce")
    d["year"] = d["date"].dt.year
    d["props_norm"] = d["fastighetsbeteckningar"].apply(normalized_properties)
    if "fastighetsbeteckning" in d.columns:
        fallback = d["fastighetsbeteckning"].fillna("").astype(str).str.strip()
        d.loc[d["props_norm"].eq(""), "props_norm"] = fallback[d["props_norm"].eq("")]
    d["transaction_key"] = (
        d["props_norm"].fillna("") + "|" + d["datum"].fillna("") + "|" + d["kopeskilling_kr"].fillna("")
    )
    d["sale_id"] = d["transaction_key"].map(lambda x: hashlib.sha1(str(x).encode("utf-8")).hexdigest()[:12])
    d["duplicate_transaction"] = d.duplicated("transaction_key", keep="first")
    d = d.loc[~d["duplicate_transaction"]].copy()

    price = d["kopeskilling_kr_n"]
    tax = d["taxeringsvarde_kr_n"]
    aker = d["akermark_ha_n"]
    total = d["total_areal_ha_n"]
    d["kt_exact"] = price / tax
    d["log_kt_exact"] = np.log(d["kt_exact"])
    d["kt_atl_minus_exact"] = d["kt_tal_n"] - d["kt_exact"]

    if "valid_market_sale" in d.columns:
        market = bool01(d["valid_market_sale"])
    else:
        market = pd.Series(True, index=d.index)

    d["q_date"] = d["date"].ge(since)
    d["q_market_sale"] = market
    d["q_price_tax_positive"] = price.gt(0) & tax.gt(0)
    d["q_arable_positive"] = aker.gt(0)
    d["q_total_positive"] = total.gt(0)
    d["q_area_consistent"] = aker.le(total)
    d["q_coords"] = d["lat_n"].notna() & d["lon_n"].notna()
    d["q_kt_main"] = d["kt_exact"].between(KT_MIN, KT_MAX, inclusive="both")
    gates = ["q_date", "q_market_sale", "q_price_tax_positive", "q_arable_positive", "q_total_positive", "q_area_consistent", "q_coords", "q_kt_main"]
    d["expanded_main_eligible"] = d[gates].fillna(False).astype(bool).all(axis=1)

    # Derived mix terms. Use actual ATL component amounts, not the precomputed
    # rounded arable-share field where avoidable.
    den = total.where(total.gt(0))
    d["aker_share_frac"] = (aker / den).clip(0, 1)
    d["forest_share_frac"] = (d["skogsmark_ha_n"].fillna(0) / den).clip(0, 1)
    d["pasture_share_frac"] = (d["betesmark_ha_n"].fillna(0) / den).clip(0, 1)
    d["year_centered"] = d["year"].astype(float) - 2024.0
    d["lat_centered"] = d["lat_n"] - 55.5
    d["lon_centered"] = d["lon_n"] - 13.0
    d["log_tax_million"] = np.log(d["taxeringsvarde_kr_n"] / 1_000_000.0)
    d["log_area_20"] = np.log(d["akermark_ha_n"] / 20.0)
    d["has_smallhouse"] = d["smahus_kvm_total_n"].fillna(0).gt(0).astype(float)
    d["has_econ_building"] = d["ekonomibyggnad_kvm_total_n"].fillna(0).gt(0).astype(float)
    d["log1p_smallhouse_kvm"] = np.log1p(d["smahus_kvm_total_n"].fillna(0).clip(lower=0))
    d["log1p_econ_kvm"] = np.log1p(d["ekonomibyggnad_kvm_total_n"].fillna(0).clip(lower=0))

    besk = d.get("aker_beskaffenhet_raw", pd.Series("", index=d.index)).apply(parse_beskaffenhet)
    d["aker_beskaffenhet_score"] = [x[0] for x in besk]
    d["aker_beskaffenhet_mixed"] = [x[1] for x in besk]
    d["aker_beskaffenhet_range"] = [x[2] for x in besk]

    dr = d.get("dranering_raw", d.get("aker_dranering_raw", pd.Series("", index=d.index))).apply(parse_drainage)
    d["drainage_state"] = [x[0] for x in dr]
    d["drainage_legacy_score"] = [x[1] for x in dr]
    d["drainage_mixed"] = [x[2] for x in dr]

    return raw, d


def sample_masks(d: pd.DataFrame):
    e = d["expanded_main_eligible"].fillna(False).astype(bool)
    forest0 = d["skogsmark_ha_n"].fillna(0).eq(0)
    return {
        "S80_NOFOREST": e & d["aker_share_frac"].ge(0.80) & forest0,
        "S70_NOFOREST": e & d["aker_share_frac"].ge(0.70) & forest0,
        "S50_ALL": e & d["aker_share_frac"].ge(0.50),
        "ALL_ARABLE": e,
    }


def refit_delta(v0g, v0a, df, ycol, base_terms, extra_terms):
    aug = v0g.fit_loo(v0a, df, ycol, base_terms + extra_terms)
    if aug is None:
        return None, None, None
    base = v0g.fit_loo(v0a, aug["data"], ycol, base_terms)
    if base is None or len(base["data"]) != len(aug["data"]):
        return None, None, None
    return base, aug, aug["loo_r2"] - base["loo_r2"]


def add_fit_rows(rows, coef_rows, sample, label, terms, fit):
    if fit is None:
        return
    rows.append({
        "sample": sample, "model": label, "terms": " + ".join(terms),
        "n": len(fit["data"]), "loo_r2": fit["loo_r2"],
        "train_r2": fit["train_r2"], "adj_r2": fit["adj_r2"],
        "median_abs_pct_error_loo": fit["median_ape"],
    })
    for n, b, se, p in zip(fit["names"], fit["beta"], fit["se"], fit["p_value"]):
        coef_rows.append({"sample": sample, "model": label, "term": n, "coefficient": b, "std_error": se, "p_value": p})


def run_kt_models(v0g, v0a, d: pd.DataFrame, outdir: Path):
    model_rows, coef_rows, inc_rows = [], [], []
    masks = sample_masks(d)
    for sample, mask in masks.items():
        x = d.loc[mask].copy().reset_index(drop=True)
        specs = [
            ("GEO", GEO),
            ("MIX", MIX),
            ("MIX_BESK", BESK),
        ]
        if FERRARI in x.columns:
            specs += [
                ("MIX_FERRARI", MIX + [FERRARI]),
                ("MIX_BESK_FERRARI", BESK + [FERRARI]),
            ]
        for label, terms in specs:
            add_fit_rows(model_rows, coef_rows, sample, label, terms, v0g.fit_loo(v0a, x, "log_kt_exact", terms))

        for base_label, base_terms, aug_label, extra in [
            ("MIX", MIX, "MIX_BESK", ["aker_beskaffenhet_score", "aker_beskaffenhet_mixed"]),
            ("MIX", MIX, "MIX_FERRARI", [FERRARI]),
            ("MIX_BESK", BESK, "MIX_BESK_FERRARI", [FERRARI]),
        ]:
            if any(c not in x.columns for c in extra):
                continue
            b, a, delta = refit_delta(v0g, v0a, x, "log_kt_exact", base_terms, extra)
            if b is not None:
                inc_rows.append({
                    "sample": sample, "baseline": base_label, "augmented": aug_label,
                    "n": len(a["data"]), "baseline_loo_r2_same_n": b["loo_r2"],
                    "augmented_loo_r2": a["loo_r2"], "delta_loo_r2": delta,
                    "baseline_median_ape": b["median_ape"], "augmented_median_ape": a["median_ape"],
                })

        # Drainage sensitivity only on rows with an unambiguous numeric legacy/current state.
        dr = x.loc[pd.to_numeric(x["drainage_legacy_score"], errors="coerce").notna()].copy()
        b, a, delta = refit_delta(v0g, v0a, dr, "log_kt_exact", MIX, ["drainage_legacy_score"])
        if b is not None:
            add_fit_rows(model_rows, coef_rows, sample, "MIX_DRAINAGE_SENS", MIX + ["drainage_legacy_score"], a)
            inc_rows.append({
                "sample": sample, "baseline": "MIX", "augmented": "MIX_DRAINAGE_SENS",
                "n": len(a["data"]), "baseline_loo_r2_same_n": b["loo_r2"],
                "augmented_loo_r2": a["loo_r2"], "delta_loo_r2": delta,
                "baseline_median_ape": b["median_ape"], "augmented_median_ape": a["median_ape"],
            })

    comp = pd.DataFrame(model_rows)
    coef = pd.DataFrame(coef_rows)
    inc = pd.DataFrame(inc_rows)
    comp.to_csv(outdir / "kt_model_comparison.csv", index=False, encoding="utf-8-sig")
    coef.to_csv(outdir / "kt_model_coefficients.csv", index=False, encoding="utf-8-sig")
    inc.to_csv(outdir / "kt_incremental_tests.csv", index=False, encoding="utf-8-sig")
    return comp, coef, inc


def descriptive_tables(d: pd.DataFrame, outdir: Path):
    masks = sample_masks(d)
    counts = []
    for name, mask in masks.items():
        x = d.loc[mask]
        counts.append({
            "sample": name, "n": len(x),
            "n_beskaffenhet": int(x["aker_beskaffenhet_score"].notna().sum()),
            "n_drainage_numeric": int(x["drainage_legacy_score"].notna().sum()),
            "n_recon_match20": int(x.get("tx_recon_match_20pct", pd.Series(False, index=x.index)).fillna(False).astype(bool).sum()),
            "n_ferrari": int(x.get(FERRARI, pd.Series(np.nan, index=x.index)).notna().sum()),
            "median_kt_exact": float(x["kt_exact"].median()) if len(x) else np.nan,
        })
    pd.DataFrame(counts).to_csv(outdir / "sample_counts.csv", index=False, encoding="utf-8-sig")

    main = d.loc[d["expanded_main_eligible"].fillna(False).astype(bool)].copy()
    besk_rows = []
    raw_b = main.get("aker_beskaffenhet_raw", pd.Series("", index=main.index)).fillna("")
    for label, x in main.groupby(raw_b, dropna=False):
        if not str(label).strip():
            continue
        besk_rows.append({
            "aker_beskaffenhet_raw": label, "n": len(x),
            "median_kt_exact": x["kt_exact"].median(), "mean_kt_exact": x["kt_exact"].mean(),
            "median_aker_share_pct": 100.0 * x["aker_share_frac"].median(),
        })
    pd.DataFrame(besk_rows).sort_values("n", ascending=False).to_csv(outdir / "beskaffenhet_summary.csv", index=False, encoding="utf-8-sig")

    dr_rows = []
    for state, x in main.groupby("drainage_state", dropna=False):
        dr_rows.append({
            "drainage_state": state, "n": len(x),
            "median_kt_exact": x["kt_exact"].median(), "mean_kt_exact": x["kt_exact"].mean(),
        })
    pd.DataFrame(dr_rows).sort_values("n", ascending=False).to_csv(outdir / "drainage_summary.csv", index=False, encoding="utf-8-sig")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--atl", help="ATL_AkerSync_*_v03.csv; annars filväljare")
    ap.add_argument("--since", default="2020-07-01")
    ap.add_argument("--ferrari-reference", help="Path to agri v0c skifte_ferrari_scores.csv")
    ap.add_argument("--recon-radius-m", type=float, default=3000.0)
    ap.add_argument("--max-link-gap-m", type=float, default=750.0)
    ap.add_argument("--max-blocks", type=int, default=15)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    v0a = load_module(root / "src" / "20_value_regression_v0a.py", "value_v0a")
    v0g = load_module(root / "src" / "20g_value_soil_price_surprise_v0g.py", "value_v0g")
    cfg = v0a.load_config(root / args.config)
    atl = args.atl or v0a.choose_atl_csv()
    if not atl:
        print("Avbrutet: ingen ATL CSV vald.")
        return 2
    atl = Path(atl)
    since = pd.Timestamp(args.since)
    outdir = root / cfg.get("build_dir", "data/derived") / "value_regression_v0h_kt_expanded"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("ÅkerSync · Value Regression v0h · expanded K/T sample")
    print("=" * 100)
    print("ATL:", atl)
    print("Output:", outdir)
    print(f"Date >= {since.date()}, exact K/T main gate {KT_MIN:g}–{KT_MAX:g}")
    print("Target: log(purchase price / total tax assessment)")
    print()

    raw, d = load_expanded(atl, since)
    base = d.loc[d["expanded_main_eligible"].fillna(False).astype(bool)].copy().reset_index(drop=True)
    print(f"ATL rows: {len(raw):,}")
    print(f"Expanded main candidates before GIS: {len(base):,}")
    print(f"  with arable beskaffenhet: {int(base['aker_beskaffenhet_score'].notna().sum()):,}")
    print(f"  with interpretable drainage state: {int(base['drainage_legacy_score'].notna().sum()):,}")

    # Reconstruct only once for all expanded candidates. This remains a strict
    # containing-block anchor; v0h does not silently relax spatial QA to gain n.
    print("[1/4] Reconstructing sold agricultural blocks for expanded candidates...")
    enriched, members = mb.add_features(base, cfg, v0a, args.recon_radius_m, args.max_link_gap_m, args.max_blocks)
    members.to_csv(outdir / "multiblock_members.csv", index=False, encoding="utf-8-sig")
    print(f"Reconstruction ±20%: {int(enriched['tx_recon_match_20pct'].fillna(False).astype(bool).sum()):,}/{len(enriched):,}")

    print("[2/4] Sampling DSMS2025 for reconstructable transactions...")
    enriched, block_soil = txsoil.add_transaction_soil_features(enriched, members, cfg, "tx_recon_match_20pct")
    if len(block_soil):
        block_soil.to_csv(outdir / "transaction_soil_block_features.csv", index=False, encoding="utf-8-sig")

    print("[3/4] Applying frozen class-10 Ferrari reference where transaction soil exists...")
    ferrari_path = v0g.find_ferrari_reference(root, args.ferrari_reference)
    ref10 = v0g.prepare_class10_reference(ferrari_path)
    enriched = v0g.add_transaction_ferrari(enriched, ref10)
    print(f"Transaction FerrariScore: {int(enriched[FERRARI].notna().sum()):,}/{len(enriched):,}")

    enriched.to_csv(outdir / "expanded_kt_features.csv", index=False, encoding="utf-8-sig")
    descriptive_tables(enriched, outdir)

    print("[4/4] K/T model ladder + same-row incremental tests...")
    comp, coef, inc = run_kt_models(v0g, v0a, enriched, outdir)

    counts = pd.read_csv(outdir / "sample_counts.csv", encoding="utf-8-sig")
    lines = [
        "ÅkerSync Value Regression v0h — expanded K/T sample",
        "=" * 84,
        f"ATL source: {atl}",
        f"Raw ATL rows: {len(raw)}",
        f"Expanded main candidates before sample tiers: {len(enriched)}",
        f"Exact K/T gate: {KT_MIN:g}–{KT_MAX:g}",
        "",
        "TARGET",
        "log(K/T exact) = log(purchase price / total tax assessment)",
        "Tax assessment is used as a package-level normalizer; we are NOT calling K/T an arable price.",
        "",
        "ATL BESKAFFENHET",
        "This is fastighetstaxering's arable quality factor: production capacity + cultivation conditions relative to the value area.",
        "It is NOT pH, nutrient status or a laboratory soil sample.",
        "Mixed strings are summarized unweighted and flagged because unit-area weights are absent in the ATL CSV.",
        "",
        "SAMPLE COUNTS",
    ]
    for _, r in counts.iterrows():
        lines.append(
            f"  {r['sample']}: n={int(r['n'])}, beskaffenhet={int(r['n_beskaffenhet'])}, "
            f"drainage={int(r['n_drainage_numeric'])}, recon20={int(r['n_recon_match20'])}, ferrari={int(r['n_ferrari'])}"
        )
    if len(comp):
        lines += ["", "K/T MODELS — sorted within each sample by LOO R2"]
        for sample in counts["sample"]:
            x = comp.loc[comp["sample"].eq(sample)].sort_values("loo_r2", ascending=False)
            for _, r in x.iterrows():
                lines.append(
                    f"  {sample} / {r['model']}: n={int(r['n'])}, LOO={r['loo_r2']:.4f}, medianAPE={r['median_abs_pct_error_loo']:.1f}%"
                )
    if len(inc):
        lines += ["", "INCREMENTAL TESTS — baseline refit on exact augmented rows"]
        for _, r in inc.iterrows():
            lines.append(
                f"  {r['sample']} / {r['baseline']} -> {r['augmented']}: n={int(r['n'])}, "
                f"LOO {r['baseline_loo_r2_same_n']:.4f}->{r['augmented_loo_r2']:.4f}, delta={r['delta_loo_r2']:+.4f}"
            )
    lines += [
        "",
        "DRAINAGE GUARDRAIL",
        "ATL mixes legacy and current drainage wording. Legacy system-tile drainage is retained as a separate diagnostic state.",
        "Government material has explicitly questioned the reliability of historic drainage tax declarations, so this is not ground truth.",
        "",
        "INTERPRETATION",
        "A positive Ferrari increment means modern class-10-like soil helps explain market premium/discount to total tax value.",
        "A zero/negative increment means no out-of-sample evidence in this sample; it is not proof that soil has no intrinsic productive value.",
        "Built/mixed-property samples estimate K/T behavior, not pure kr/ha arable value.",
    ]
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
