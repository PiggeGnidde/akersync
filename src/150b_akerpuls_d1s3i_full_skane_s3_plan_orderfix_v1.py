#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1-S3i validation-order fix wrapper.

The D0b final execution contract is serialized with sort_keys=True. That makes
its nested frozen_snapshots mapping load in alphabetical snapshot-key order
(APRIL, JULY, JUNE, MAY), while the D1-S3i config lists the exact same six
frozen dates chronologically. The original D1-S3i validator compared those
lists positionally and therefore produced a false "Frozen dates changed"
failure.

This wrapper changes validation representation only: the same frozen date
multiset is canonicalized by ISO date before the parent validator compares it.
All planning, STAC querying, direct-S3 semantics, guards and outputs remain in
the parent implementation unchanged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "src" / "150_akerpuls_d1s3i_full_skane_s3_plan_v1.py"


def load_parent():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3i_parent", PARENT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def canonical_flatten_snapshot_dates(contract: dict[str, Any]) -> list[str]:
    """Return the frozen dates in canonical ISO-date order, independent of JSON key order."""
    dates = [
        str(day)
        for _snapshot, days in contract["frozen_snapshots"].items()
        for day in days
    ]
    return sorted(dates)


def main() -> int:
    parent = load_parent()
    parent.flatten_snapshot_dates = canonical_flatten_snapshot_dates
    print("D1S3I_ORDERFIX=CANONICAL_ISO_DATE_ORDER_VALIDATION_ONLY", flush=True)
    return int(parent.main())


if __name__ == "__main__":
    raise SystemExit(main())
