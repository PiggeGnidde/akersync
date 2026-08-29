#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feature/akerprestation-web-phase0-v0a"

LEGACY_REQUIRED = (
    "geometry_payload.json",
    "soil_payload.json",
    "geometry_v1a_skiften.csv",
    "akerscore_soil_v0c/akerscore_soil_skiften.csv",
    "akervarde_v1_0_rc1_freeze/model_coefficients.csv",
    "akerdrift_fast_v2_hybrid_rc1/akerdrift_fast_v2_hybrid_rc1_skane.parquet",
    "topography_features_blocks.csv",
    "hydrology_features_final.csv",
)


def _abs_from(worktree: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else worktree / path


def worktrees(repo_root: Path = ROOT) -> list[Path]:
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo_root,
        text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError("git worktree list failed: " + proc.stderr.strip())
    roots: list[Path] = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            roots.append(Path(line[len("worktree "):].strip()))
    return roots


def build_dir_for_worktree(worktree: Path) -> Path:
    cfg_path = worktree / "config" / "local_paths.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            return _abs_from(worktree, str(cfg.get("build_dir", "data/derived")))
        except Exception:
            pass
    return worktree / "data" / "derived"


def missing_legacy(build_dir: Path) -> list[str]:
    return [rel for rel in LEGACY_REQUIRED if not (build_dir / rel).exists()]


def select_legacy_build_dir(candidates: Iterable[Path]) -> Path:
    checked: list[tuple[Path, list[str]]] = []
    for worktree in candidates:
        build_dir = build_dir_for_worktree(worktree)
        missing = missing_legacy(build_dir)
        checked.append((build_dir, missing))
        if not missing:
            return build_dir
    lines = ["No Git worktree contains a complete legacy AkerPass derived artifact set."]
    for build_dir, missing in checked:
        lines.append(f"  {build_dir}: missing {len(missing)} -> " + ", ".join(missing))
    raise RuntimeError("\n".join(lines))


def current_config() -> tuple[dict, Path, Path]:
    cfg_path = ROOT / "config" / "local_paths.json"
    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    current_build = _abs_from(ROOT, str(cfg.get("build_dir", "data/derived")))
    current_dist = _abs_from(ROOT, str(cfg.get("dist_dir", "dist")))
    return cfg, current_build, current_dist


def run(script: str, config_path: Path | None = None) -> None:
    cmd = [sys.executable, script]
    if config_path is not None:
        cmd += ["--config", str(config_path)]
    suffix = f" --config {config_path}" if config_path else ""
    print(f"\n>>> {script}{suffix}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> int:
    print("=" * 96)
    print("AkerPass WEB FAS 0 · worktree-aware legacy artifact reuse")
    print("=" * 96)

    cfg, current_build, current_dist = current_config()
    phase0_context = current_build / "akerprestation_phase0" / "skane" / "field_static_context.parquet"
    if not phase0_context.exists():
        raise FileNotFoundError(f"Missing frozen phase 0 context in current worktree: {phase0_context}")

    roots = worktrees()
    legacy_build = select_legacy_build_dir(roots)
    print(f"Current phase0 build_dir: {current_build}")
    print(f"Legacy AkerPass build_dir: {legacy_build}")
    print(f"WEB output dist_dir:       {current_dist}")
    if legacy_build == current_build:
        print("Legacy artifacts are local to this worktree.")
    else:
        print("Legacy artifacts will be REUSED READ/BUILD-SOURCE from another Git worktree; no raw rebuild.")

    runtime = dict(cfg)
    runtime["build_dir"] = str(legacy_build)
    runtime["dist_dir"] = str(current_dist)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", prefix="akerpass_phase0_legacy_",
            delete=False,
        ) as handle:
            json.dump(runtime, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)

        # Legacy build is executed against its existing derived artifacts but writes dist here.
        run("src/40_build_akervarde_public_index.py", temp_path)
        run("src/41_build_akerpass_public_data.py", temp_path)
        run("src/42_build_akerpass_frontend.py", temp_path)
        run("src/43_verify_akerpass_web_v1.py", temp_path)

        # Phase 0 enrichment deliberately switches back to THIS worktree's frozen context.
        run("src/41b_enrich_akerpass_phase0_web.py")
        run("src/42b_patch_akerpass_frontend_phase0.py")
        run("src/43b_verify_akerpass_web_phase0.py")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    print("\n" + "=" * 96)
    print("AKERPASS WEB FAS 0 WORKTREE RUNNER: PASS")
    print("=" * 96)
    print("dist/index.html contains historic class 1-10 + dominant SKO in Historik / referens.")
    print("No AkerScore, AkerVarde or AkerDrift model logic was changed or recalibrated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
