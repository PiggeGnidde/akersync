#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility runner for Value Regression v0h.

Some predeclared property-mix terms are structurally constant in a sample tier
(e.g. forest_share_frac == 0 in NOFOREST samples).  OLS should drop such a term,
not reject the whole design matrix.  This runner preserves the predeclared model
families but removes zero-variance predictors inside each exact analysis subset
before fitting.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    here = Path(__file__).resolve().parent
    v0h = load_script(here / "20h_value_kt_expanded_v0h.py", "value_v0h")
    original_load_module = v0h.load_module

    def patched_load_module(path, name):
        mod = original_load_module(path, name)
        if name == "value_v0g" and hasattr(mod, "fit_loo"):
            original_fit = mod.fit_loo

            def adaptive_fit(v0a, df, ycol, terms):
                kept = []
                dropped = []
                for t in terms:
                    if t not in df.columns:
                        kept.append(t)  # let original helper handle missing columns
                        continue
                    x = pd.to_numeric(df[t], errors="coerce")
                    finite = x[np.isfinite(x)]
                    if len(finite) and finite.nunique(dropna=True) <= 1:
                        dropped.append(t)
                    else:
                        kept.append(t)
                if dropped:
                    print("    zero-variance terms dropped:", ", ".join(dropped))
                return original_fit(v0a, df, ycol, kept)

            mod.fit_loo = adaptive_fit
        return mod

    v0h.load_module = patched_load_module
    return v0h.main()


if __name__ == "__main__":
    raise SystemExit(main())
