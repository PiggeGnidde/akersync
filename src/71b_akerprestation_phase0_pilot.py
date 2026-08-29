#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility entrypoint for the phase 0 Skurup pilot.

Patches the frozen ÅkerMinne locator and, when the generated frozen history
parquet is no longer retained locally, falls back to the immutable freeze
contract + exact 2025 reference identity domain. GIS overlay/checkpoint
behavior remains unchanged.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import akerprestation_phase0_overlay_core as overlay_core
from akerprestation_phase0_akerminne_locator import (
    find_strict_frozen_akerminne_field_year_file,
)
from akerprestation_phase0_akerminne_contract import discover_frozen_or_contract

# The original pilot imports this symbol by name. Patch the overlay module
# before loading the pilot so retained canonical artifacts are located strictly.
overlay_core.find_frozen_akerminne_field_year_file = find_strict_frozen_akerminne_field_year_file

pilot_path = SRC / "71_akerprestation_phase0_pilot.py"
spec = importlib.util.spec_from_file_location("akerprestation_phase0_pilot_base", pilot_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load pilot module: {pilot_path}")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

_original_discover = pilot.discover_frozen_akerminne


def _discover_with_contract(repo_root: Path, municipality_code: str, municipality: str, pilot_ids: set[str]):
    return discover_frozen_or_contract(
        repo_root,
        municipality_code,
        municipality,
        pilot_ids,
        strict_discover=_original_discover,
    )


pilot.discover_frozen_akerminne = _discover_with_contract
raise SystemExit(pilot.main())
