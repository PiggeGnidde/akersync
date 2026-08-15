#!/usr/bin/env python3
"""Run the validated topography engine with the central regional scope.

The validated v0.92 engine in 03_topography.py still contains its historical
three-municipality constant.  This thin adapter deliberately keeps that engine
unchanged while replacing only its municipality scope at runtime.  That lets
Skåne scaling be tested without touching the numerical implementation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from common import MUN_CODES


def load_engine():
    path = Path(__file__).with_name("03_topography.py")
    spec = importlib.util.spec_from_file_location("akersync_topography_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda topografimotorn: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MUN_CODES = dict(MUN_CODES)
    return module


def main():
    engine = load_engine()
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
