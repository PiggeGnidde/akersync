#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "akerprestation-phase0-v0a"

EXPECTED = {
    "BUILD_AKERPASS_WEB_PHASE0.bat",
    "BUILD_AKERPASS_WEB_PHASE0_WORKTREE.bat",
    "FREEZE_AKERPASS_AKERMINNE_CONTEXT_V1.bat",
    "src/41b_enrich_akerpass_phase0_web.py",
    "src/42b_patch_akerpass_frontend_phase0.py",
    "src/43b_verify_akerpass_web_phase0.py",
    "src/68b_patch_akerpass_akerminne_reused_ui.py",
    "src/69b_verify_akerpass_akerminne_phase0_combined.py",
    "src/77_verify_akerpass_context_freeze_scope.py",
    "src/build_akerpass_web_phase0.py",
    "src/build_akerpass_web_phase0_worktree.py",
    "src/ensure_akerminne_recovery_local_config.py",
    "src/restore_orphaned_akerminne_web_payload.py",
    "tests/test_akerpass_web_phase0.py",
    "tests/test_akerpass_web_phase0_orphan_restore.py",
    "tests/test_akerpass_web_phase0_recovery.py",
    "tests/test_akerpass_web_phase0_worktree.py",
}


def changed_paths(base: str) -> set[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return {line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    args = ap.parse_args()

    actual = changed_paths(args.base)
    extra = sorted(actual - EXPECTED)
    missing = sorted(EXPECTED - actual)
    if extra or missing:
        print("FREEZE SCOPE: FAIL")
        if extra:
            print("Unexpected changed files:")
            for path in extra:
                print(f"  + {path}")
        if missing:
            print("Expected freeze files absent from diff:")
            for path in missing:
                print(f"  - {path}")
        print("Actual changed files:")
        for path in sorted(actual):
            print(f"  {path}")
        return 1

    model_prefixes = (
        "src/31",
        "src/32",
        "src/33",
        "src/34",
        "src/35",
        "src/36",
        "src/37",
        "src/38",
        "src/39",
    )
    model_named = [
        p for p in actual
        if p.startswith(model_prefixes)
        or "akerscore" in p.lower()
        or "akervarde" in p.lower()
        or "akerdrift" in p.lower()
    ]
    # The allowlist intentionally contains no model-calculation files. This second
    # guard makes the freeze report explicit even if the allowlist is edited later.
    if model_named:
        print("FREEZE SCOPE: FAIL - model calculation file detected")
        for path in sorted(model_named):
            print(f"  {path}")
        return 1

    print("FREEZE SCOPE: PASS")
    print(f"Base: {args.base}")
    print(f"Allowed changed files: {len(actual)}")
    print("No AkerScore/AkerVarde/AkerDrift calculation files changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
