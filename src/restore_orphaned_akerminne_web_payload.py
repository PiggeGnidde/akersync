#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIELDS = 128_636
EXPECTED_FIELD_YEARS = 1_414_996
EXPECTED_COMPONENTS = 2_935_686
EXPECTED_YEARS = list(range(2015, 2026))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


def validate_web_payload(dist_dir: Path) -> tuple[bool, str]:
    index_path = dist_dir / "data" / "akerminne" / "skane_index.json"
    doc = _read_json(index_path)
    if doc is None:
        return False, "missing/unreadable skane_index.json"
    entries = doc.get("municipalities") or []
    if doc.get("schema_version") != "akerminne-skane-web-index-v1":
        return False, "wrong web index schema"
    if int(doc.get("municipality_count", -1)) != 33 or len(entries) != 33:
        return False, "municipality_count != 33"
    if int(doc.get("field_count", -1)) != EXPECTED_FIELDS:
        return False, "field_count != 128636"
    if int(doc.get("field_years", -1)) != EXPECTED_FIELD_YEARS:
        return False, "field_years != 1414996"
    if doc.get("years") != EXPECTED_YEARS:
        return False, "years != 2015-2025"
    for entry in entries:
        rel = str(entry.get("file") or "")
        if not rel or not (dist_dir / rel).is_file():
            return False, f"missing sidecar {rel or '<blank>'}"
    return True, "33 sidecars + full-Skåne index"


def validate_frozen_qa(repo_like_root: Path) -> tuple[bool, str]:
    qa_path = repo_like_root / "data" / "derived" / "akerminne_v1a" / "skane" / "skane_qa.json"
    qa = _read_json(qa_path)
    if qa is None:
        return False, "missing/unreadable skane_qa.json"
    checks = {
        "completed_municipalities": 33,
        "current_fields": EXPECTED_FIELDS,
        "field_years": EXPECTED_FIELD_YEARS,
        "component_rows": EXPECTED_COMPONENTS,
        "unknown_crop_combinations": 0,
    }
    for key, expected in checks.items():
        if int(qa.get(key, -1)) != expected:
            return False, f"QA {key} != {expected}"
    return True, "frozen 33/128636/1414996/2935686/0 QA"


def find_orphaned_sources(repo_root: Path = ROOT) -> list[Path]:
    """Find sibling artifact roots that are not required to be registered Git worktrees."""
    parent = repo_root.parent
    found: list[Path] = []
    try:
        children = sorted((p for p in parent.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        return found
    for child in children:
        if child.resolve() == repo_root.resolve():
            continue
        web_ok, _ = validate_web_payload(child / "dist")
        qa_ok, _ = validate_frozen_qa(child)
        if web_ok and qa_ok:
            found.append(child)
    return found


def restore_payload(repo_root: Path = ROOT) -> tuple[str, Path | None]:
    target_dist = repo_root / "dist"
    target_ok, target_msg = validate_web_payload(target_dist)
    if target_ok:
        print(f"ÅkerMinne payload already valid in current dist: {target_msg}")
        return "already_present", repo_root

    candidates = find_orphaned_sources(repo_root)
    if not candidates:
        print("No validated orphaned sibling ÅkerMinne payload found; normal recovery chain will decide next step.")
        return "not_found", None

    if len(candidates) > 1:
        print("Multiple validated orphaned ÅkerMinne payloads found; using first deterministic path:")
        for candidate in candidates:
            print(f"  {candidate}")

    source_root = candidates[0]
    source_dist = source_root / "dist"
    source_payload = source_dist / "data" / "akerminne"
    target_payload = target_dist / "data" / "akerminne"
    web_ok, web_msg = validate_web_payload(source_dist)
    qa_ok, qa_msg = validate_frozen_qa(source_root)
    if not web_ok or not qa_ok:
        raise RuntimeError(f"Selected orphaned source failed revalidation: web={web_msg}; qa={qa_msg}")

    if target_payload.exists():
        shutil.rmtree(target_payload)
    target_payload.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_payload, target_payload)

    copied_ok, copied_msg = validate_web_payload(target_dist)
    if not copied_ok:
        raise RuntimeError(f"Copied ÅkerMinne payload failed validation: {copied_msg}")

    print("=" * 88)
    print("ORPHANED ÅKERMINNE PAYLOAD RESTORE: PASS")
    print("=" * 88)
    print(f"Source artifact root: {source_root}")
    print(f"Source validation: {web_msg}; {qa_msg}")
    print(f"Copied to: {target_payload}")
    print("No ÅkerMinne historical calculation was rerun.")
    return "restored", source_root


def main() -> int:
    restore_payload(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
