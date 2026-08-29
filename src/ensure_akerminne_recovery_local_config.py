#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "config" / "akerminne_local.json"
PROJECT = ROOT / "config" / "local_paths.json"


def worktrees() -> list[Path]:
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=ROOT,
        text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError("git worktree list failed: " + proc.stderr.strip())
    return [Path(line[9:].strip()) for line in proc.stdout.splitlines() if line.startswith("worktree ")]


def valid_raw_root(path: Path) -> bool:
    return path.is_absolute() and path.exists() and path.is_dir()


def read_valid_config(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_root = Path(str(doc["raw_root"]))
        return {"raw_root": str(raw_root)} if valid_raw_root(raw_root) else None
    except Exception:
        return None


def infer_raw_root(project: dict) -> Path | None:
    parents: list[Path] = []
    for key in ("blocks", "skiften", "soil_zip"):
        value = project.get(key)
        if not value:
            continue
        path = Path(str(value))
        if path.is_absolute():
            parents.append(path.parent if path.suffix else path)
    if not parents:
        return None
    try:
        common = Path(os.path.commonpath([str(p) for p in parents]))
    except Exception:
        return None
    if len(common.parts) < 2 or not valid_raw_root(common):
        return None
    return common


def main() -> int:
    if TARGET.exists():
        current = read_valid_config(TARGET)
        if current is None:
            raise RuntimeError(f"Existing {TARGET} is invalid; refusing to overwrite it silently")
        print(f"ÅkerMinne local config: OK · {TARGET} · raw_root={current['raw_root']}")
        return 0

    for root in worktrees():
        candidate = root / "config" / "akerminne_local.json"
        if candidate.resolve() == TARGET.resolve() or not candidate.exists():
            continue
        doc = read_valid_config(candidate)
        if doc is None:
            continue
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"ÅkerMinne local config restored from worktree: {candidate}")
        print(f"  -> {TARGET}")
        print(f"  raw_root={doc['raw_root']}")
        return 0

    if not PROJECT.exists():
        raise FileNotFoundError(PROJECT)
    project = json.loads(PROJECT.read_text(encoding="utf-8-sig"))
    raw_root = infer_raw_root(project)
    if raw_root is None:
        raise RuntimeError(
            "No valid akerminne_local.json exists in any worktree and raw_root cannot be inferred "
            "safely from config/local_paths.json"
        )
    doc = {"raw_root": str(raw_root)}
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("ÅkerMinne local config recreated from existing project raw-data paths")
    print(f"  {TARGET}")
    print(f"  raw_root={raw_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
