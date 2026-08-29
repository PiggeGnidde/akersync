#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility entrypoint for the phase 0 Skurup pilot.

Patches only the frozen ÅkerMinne artifact locator before executing the
existing pilot. GIS overlay/checkpoint behavior remains unchanged.
"""
from __future__ import annotations

import runpy
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

# The original pilot imports this symbol by name. Patch the module before the
# pilot is loaded so it binds the strict deterministic locator.
overlay_core.find_frozen_akerminne_field_year_file = find_strict_frozen_akerminne_field_year_file

runpy.run_path(str(SRC / "71_akerprestation_phase0_pilot.py"), run_name="__main__")
