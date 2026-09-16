#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Block-census compatibility fix for ÅkerPuls merge M0 satellite-only v1.

The frozen 2025 skifte layer contains 128,636 skiften and 99,758 unique BLOCKID
values represented by those skiften. The separate block layer has 122,970 block
features, but that is NOT the candidate-population denominator for a merge search
that groups skiften by their BLOCKID.

This wrapper changes only that census contract. Satellite metrics, pilot merge
thresholds, D2A normalization, adjacency rule and all non-mutation guards remain
those of src/169.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src" / "169_akerpuls_merge_m0_satellite_only_v1.py"
EXPECTED_SKIFTE_LAYER_UNIQUE_BLOCK_IDS = 99758
CONTEXT_SEPARATE_BLOCK_LAYER_FEATURES = 122970


def load_base():
    spec = importlib.util.spec_from_file_location("akerpuls_merge_m0_base", BASE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def fixed_validate_config(base, cfg):
    exp = cfg.get("expected", {})
    if int(exp.get("skifte_layer_unique_block_ids_2025", -1)) != EXPECTED_SKIFTE_LAYER_UNIQUE_BLOCK_IDS:
        raise RuntimeError("M0 skifte-layer unique BLOCKID census changed")
    if int(exp.get("separate_block_layer_features_2025_context_only", -1)) != CONTEXT_SEPARATE_BLOCK_LAYER_FEATURES:
        raise RuntimeError("M0 contextual separate-block-layer census changed")
    if cfg.get("adjacency", {}).get("block_population_definition") != "UNIQUE_BLOCKID_VALUES_PRESENT_IN_FROZEN_2025_SKIFTE_LAYER":
        raise RuntimeError("M0 block population definition changed")

    # Preserve every original src/169 contract check. Supply its historical key
    # only to the validator; this does not alter the runtime skifte-layer census.
    compat = copy.deepcopy(cfg)
    compat["expected"]["blocks_2025"] = CONTEXT_SEPARATE_BLOCK_LAYER_FEATURES
    base._original_validate_config(compat)


def fixed_load_frozen_context(base, cfg, d2c):
    # src/169's loader has exactly one legacy blocks_2025 lookup. Feed it the
    # correct denominator: unique BLOCKID values represented in the skifte layer.
    compat = copy.deepcopy(cfg)
    compat["expected"]["blocks_2025"] = EXPECTED_SKIFTE_LAYER_UNIQUE_BLOCK_IDS
    return base._original_load_frozen_context(compat, d2c)


def main() -> int:
    base = load_base()
    base._original_validate_config = base.validate_config
    base._original_load_frozen_context = base.load_frozen_context
    base.validate_config = lambda cfg: fixed_validate_config(base, cfg)
    base.load_frozen_context = lambda cfg, d2c: fixed_load_frozen_context(base, cfg, d2c)
    return int(base.main())


if __name__ == "__main__":
    raise SystemExit(main())
