#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Robust runner for step 25 SMHI weather classification.

The first version only tested the N geographically nearest stations. Around
Lomma that can select several historical stations whose records do not cover
2018-2026. The fallback then accepted zero-coverage stations, which propagated
as an all-NaN regional series while the program still completed successfully.

This wrapper keeps the validated step-25 parsing and summaries, but replaces
station selection with target-period-aware scanning and refuses silent all-NaN
output. It can be folded back into step 25 after validation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_base():
    path = ROOT / "src" / "25_satellite_lomma_weather_classification.py"
    spec = importlib.util.spec_from_file_location("akersync_weather25", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def robust_select_stations(base, param_name, param, cat, dates, n_stations, candidates, min_station_coverage):
    target_set = pd.DataFrame({"date": dates})
    d0 = pd.Timestamp(dates.min()).normalize()
    d1 = pd.Timestamp(dates.max()).normalize()

    x = cat.copy()
    # Do not waste requests on stations whose published operating interval does
    # not intersect the target period. Missing from/to metadata is kept.
    eligible = (
        (x["from"].isna() | (pd.to_datetime(x["from"]) <= d1))
        & (x["to"].isna() | (pd.to_datetime(x["to"]) >= d0))
    )
    x = x.loc[eligible].sort_values("distance_km").reset_index(drop=True)
    if x.empty:
        raise RuntimeError(f"{param_name}: inga CORE-stationer överlappar {d0.date()}–{d1.date()}")

    # Scan farther than the old fixed top-10. Stop once we have enough stations
    # that independently cover the requested March-July dates across 2018-2026.
    max_tests = min(len(x), max(int(candidates), 50))
    tested = []
    good = []
    print(f"    periodfilter: {len(x)} stationer överlappar målperioden; provar upp till {max_tests}")

    for r in x.head(max_tests).itertuples(index=False):
        print(f"    provar {r.station_name} ({r.station_key}), {r.distance_km:.1f} km …", end="", flush=True)
        s = base.fetch_station_series(param, r.station_key)
        if s.empty:
            cov = 0.0
        else:
            sub = target_set.merge(s[["date", "value"]], on="date", how="left")
            cov = 100.0 * sub.value.notna().mean()
        print(f" coverage {cov:.1f}%")
        rec = (r, s, cov)
        tested.append(rec)
        if cov >= min_station_coverage:
            good.append(rec)
            if len(good) >= n_stations:
                break

    if good:
        chosen = good[:n_stations]
    else:
        # Never silently accept zero-coverage stations. A partial fallback is OK
        # only when there is substantial real coverage to work with.
        ranked = sorted(tested, key=lambda z: (-z[2], z[0].distance_km))
        positive = [z for z in ranked if z[2] >= 50.0]
        if not positive:
            top = ", ".join(f"{z[0].station_name}:{z[2]:.1f}%" for z in ranked[:5]) or "inga testade"
            raise RuntimeError(
                f"{param_name}: ingen station gav användbar 2018–2026-serie. "
                f"Bästa testade coverage: {top}. Detta är nu ett explicit data/parser-fel, inte ett NaN-resultat."
            )
        chosen = positive[:n_stations]
        print(
            f"    VARNING: bara {len(chosen)} station(er) nådde >=50% coverage; "
            f"ingen nådde målet {min_station_coverage:.1f}% i tillräckligt antal."
        )

    return chosen


def robust_aggregate_region(base, chosen, dates, value_name: str, min_daily_stations: int):
    # If only one genuinely well-covered station exists, allow it instead of
    # requiring two and thereby manufacturing an all-NaN regional series.
    required = min(max(1, int(min_daily_stations)), len(chosen))
    reg, meta = base.aggregate_region(chosen, dates, value_name, required)
    coverage = 100.0 * reg[value_name].notna().mean()
    n1 = int((reg[f"{value_name}_stations"] >= 1).sum())
    n2 = int((reg[f"{value_name}_stations"] >= 2).sum())
    print(
        f"  regional {value_name}: required stations/day={required} | "
        f"coverage {coverage:.1f}% | dagar >=1 station {n1} | >=2 stationer {n2}"
    )
    if coverage < 70.0:
        raise RuntimeError(
            f"{value_name}: regional serie har bara {coverage:.1f}% coverage. "
            "Stoppar hellre än att skriva en missvisande väderklassning."
        )
    return reg, meta


def main() -> int:
    base = load_base()

    def select_patch(param_name, param, cat, dates, n_stations, candidates, min_station_coverage):
        return robust_select_stations(
            base, param_name, param, cat, dates, n_stations, candidates, min_station_coverage
        )

    def aggregate_patch(chosen, dates, value_name, min_daily_stations):
        # Call the original implementation through a saved reference to avoid
        # recursion after monkey-patching.
        return robust_aggregate_region(base_original, chosen, dates, value_name, min_daily_stations)

    # Save a minimal proxy containing the original aggregate implementation.
    class Original:
        pass

    base_original = Original()
    base_original.aggregate_region = base.aggregate_region

    base.select_stations = select_patch
    base.aggregate_region = aggregate_patch
    return base.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
