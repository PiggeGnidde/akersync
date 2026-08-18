#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility runner for Value Regression v0f.

The v0f report writer passes one-element Python lists to the inherited
pct_error_from_log helper.  NumPy arithmetic inside that helper expects arrays.
This runner keeps the v0f analysis unchanged but makes the inherited helper
robust by coercing its two arguments to float arrays before the analysis starts.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


def load_v0f():
    path = Path(__file__).resolve().with_name("20f_value_regression_class1971_v0f.py")
    spec = importlib.util.spec_from_file_location("value_class1971_v0f", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte importera {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    v0f = load_v0f()
    original_load_module = v0f.load_module

    def compatible_load_module(path, name):
        mod = original_load_module(path, name)
        if name == "value_v0a" and hasattr(mod, "pct_error_from_log"):
            original_pct_error = mod.pct_error_from_log

            def pct_error_from_log_compatible(y, pred):
                return original_pct_error(
                    np.asarray(y, dtype=float),
                    np.asarray(pred, dtype=float),
                )

            mod.pct_error_from_log = pct_error_from_log_compatible
        return mod

    v0f.load_module = compatible_load_module
    return v0f.main()


if __name__ == "__main__":
    raise SystemExit(main())
