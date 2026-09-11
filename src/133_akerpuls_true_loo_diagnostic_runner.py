#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility runner for C6 TRUE-LOO diagnostic.

The frozen 132 implementation read blind_index as strings and sorted before
numeric conversion, yielding lexical order 1,10,11,...,2,... and a false
"indices not consecutive" guard failure. This runner changes only that I/O
ordering bug: convert blind_index to integer first, then sort numerically.
All segmentation logic, frozen TRUE-LOO criteria, labels and guardrails remain
identical to 132.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "132_akerpuls_true_loo_diagnostic.py"


def load_base():
    spec = importlib.util.spec_from_file_location("akerpuls_true_loo_base", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_blind_cases_numeric(mod, cfg: dict[str, Any]) -> pd.DataFrame:
    br = cfg["blind_review"]
    frames = []
    specs = [
        ("C", Path(br["c3_key"]), list(br["c3_labels"]), "C3"),
        ("C5", Path(br["c5d_key"]), list(br["c5d_labels"]), "C5D"),
    ]
    for dataset, path, labels, source in specs:
        if not path.exists():
            raise FileNotFoundError(path)
        x = pd.read_csv(path, dtype=str)
        if len(x) != len(labels):
            raise RuntimeError(f"{source}: blind key rows {len(x)} != labels {len(labels)}")
        x["blind_index"] = pd.to_numeric(x["blind_index"], errors="raise").astype(int)
        x = x.sort_values("blind_index").reset_index(drop=True)
        if x["blind_index"].tolist() != list(range(1, len(x) + 1)):
            raise RuntimeError(f"{source}: blind indices not consecutive")
        x["visual_label"] = labels
        x["blind_source"] = source
        x["dataset"] = dataset
        x["field_id_normalized"] = x["parent_field_id_2025"].map(mod.normalize_field_id)
        frames.append(x)
    return pd.concat(frames, ignore_index=True, sort=False)


def main() -> int:
    mod = load_base()
    mod.build_blind_cases = lambda cfg: build_blind_cases_numeric(mod, cfg)
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
