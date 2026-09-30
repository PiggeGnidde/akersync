#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small dependency-free local secret loader for ÅkerSync worktrees.

Contract:
- secrets live in repo-root .env
- .env is git-ignored
- environment variables override .env
- secret values are never printed by this module
"""
from __future__ import annotations

import os
from pathlib import Path


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def get_secret(name: str, root: Path | None = None, required: bool = True) -> str | None:
    env = os.environ.get(name)
    if env:
        return env
    base = root or Path(__file__).resolve().parents[1]
    value = _parse_env(base / ".env").get(name)
    if value:
        return value
    if required:
        raise RuntimeError(
            f"Saknar secret {name}. Lägg den i {base / '.env'} som {name}=... "
            "eller sätt motsvarande environment variable."
        )
    return None
