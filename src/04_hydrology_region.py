#!/usr/bin/env python3
"""Run the validated hydrology engine with the central regional scope.

The numerical hydrology code stays untouched; only the municipality selection
is replaced at runtime.  This makes the Skåne expansion easy to regression-test
against the validated v0.92 engine.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from common import MUN_CODES


def load_engine():
    path = Path(__file__).with_name("04_hydrology.py")
    spec = importlib.util.spec_from_file_location("akersync_hydrology_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda hydrologimotorn: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MUN_CODES = dict(MUN_CODES)
    return module


def main():
    engine = load_engine()
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
