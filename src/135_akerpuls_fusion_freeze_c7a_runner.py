#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility runner for C7A fusion freeze.

The TRUE-LOO output directory intentionally contains per-dataset, combined and
blind-case CSVs with overlapping columns. The frozen C7 fusion development
population must use the combined all-candidate file only. This runner narrows
that I/O locator without changing the fusion formula or C7 holdout contract.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "134_akerpuls_fusion_freeze_c7a.py"


def load_base():
    spec = importlib.util.spec_from_file_location("akerpuls_c7a_base", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = load_base()

    def locate(root: Path) -> Path:
        p = root / "true_loo_candidates_all.csv"
        if not p.exists():
            raise FileNotFoundError(p)
        return p

    mod.locate_true_loo_csv = locate
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
