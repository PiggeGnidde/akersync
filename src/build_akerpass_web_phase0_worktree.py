#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feature/akerprestation-web-phase0-v0a"
EXPECTED_FIELDS = 128_636
EXPECTED_FIELD_YEARS = 1_414_996
EXPECTED_YEARS = list(range(2015, 2026))

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

AKM_UI_MARKERS = (
    "AKERMINNE_PILOT_UI_V1A",
    "AKERMINNE_PILOT_UI_COPY_R1",
    "AKERMINNE_SKANE_UI_R2",
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


def dist_dir_for_worktree(worktree: Path) -> Path:
    cfg_path = worktree / "config" / "local_paths.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            return _abs_from(worktree, str(cfg.get("dist_dir", "dist")))
        except Exception:
            pass
    return worktree / "dist"


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


def missing_akerminne_web(dist_dir: Path) -> list[str]:
    missing: list[str] = []
    html_path = dist_dir / "index.html"
    web_index_path = dist_dir / "data" / "akerminne" / "skane_index.json"
    if not html_path.exists():
        missing.append("index.html")
    else:
        try:
            html = html_path.read_text(encoding="utf-8")
            for marker in AKM_UI_MARKERS:
                if marker not in html:
                    missing.append(f"index marker {marker}")
        except Exception as exc:
            missing.append(f"index.html unreadable ({type(exc).__name__})")

    if not web_index_path.exists():
        missing.append("data/akerminne/skane_index.json")
        return missing
    try:
        doc = json.loads(web_index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        missing.append(f"skane_index unreadable ({type(exc).__name__})")
        return missing

    entries = doc.get("municipalities") or []
    if doc.get("schema_version") != "akerminne-skane-web-index-v1":
        missing.append("wrong skane_index schema")
    if int(doc.get("municipality_count", -1)) != 33 or len(entries) != 33:
        missing.append("skane_index municipality_count != 33")
    if int(doc.get("field_count", -1)) != EXPECTED_FIELDS:
        missing.append("skane_index field_count != 128636")
    if int(doc.get("field_years", -1)) != EXPECTED_FIELD_YEARS:
        missing.append("skane_index field_years != 1414996")
    if doc.get("years") != EXPECTED_YEARS:
        missing.append("skane_index years != 2015-2025")

    for entry in entries:
        rel = str(entry.get("file") or "")
        if not rel or not (dist_dir / rel).exists():
            missing.append(f"sidecar {rel or '<blank>'}")
    return missing


def select_akerminne_dist(candidates: Iterable[Path]) -> Path:
    checked: list[tuple[Path, list[str]]] = []
    for worktree in candidates:
        dist_dir = dist_dir_for_worktree(worktree)
        missing = missing_akerminne_web(dist_dir)
        checked.append((dist_dir, missing))
        if not missing:
            return dist_dir
    lines = ["No Git worktree contains a complete all-Skåne ÅkerMinne web artifact set."]
    for dist_dir, missing in checked:
        preview = ", ".join(missing[:8])
        if len(missing) > 8:
            preview += f", ... (+{len(missing) - 8})"
        lines.append(f"  {dist_dir}: missing/invalid {len(missing)} -> {preview}")
    raise RuntimeError("\n".join(lines))


def copy_akerminne_web(source_dist: Path, target_dist: Path) -> None:
    source = source_dist / "data" / "akerminne"
    target = target_dist / "data" / "akerminne"
    if source.resolve() == target.resolve():
        print("ÅkerMinne sidecars already live in the target dist; no copy needed.")
        return
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    missing = missing_akerminne_web_payload_only(target_dist)
    if missing:
        raise RuntimeError("Copied ÅkerMinne web package is incomplete: " + ", ".join(missing[:12]))
    print(f"ÅkerMinne sidecars copied byte-for-byte source tree: {source} -> {target}")


def missing_akerminne_web_payload_only(dist_dir: Path) -> list[str]:
    web_index_path = dist_dir / "data" / "akerminne" / "skane_index.json"
    if not web_index_path.exists():
        return ["data/akerminne/skane_index.json"]
    try:
        doc = json.loads(web_index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"skane_index unreadable ({type(exc).__name__})"]
    missing: list[str] = []
    entries = doc.get("municipalities") or []
    if (
        doc.get("schema_version") != "akerminne-skane-web-index-v1"
        or int(doc.get("municipality_count", -1)) != 33
        or len(entries) != 33
        or int(doc.get("field_count", -1)) != EXPECTED_FIELDS
        or int(doc.get("field_years", -1)) != EXPECTED_FIELD_YEARS
        or doc.get("years") != EXPECTED_YEARS
    ):
        missing.append("invalid full-Skåne web index contract")
    for entry in entries:
        rel = str(entry.get("file") or "")
        if not rel or not (dist_dir / rel).exists():
            missing.append(f"sidecar {rel or '<blank>'}")
    return missing


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
    print("AkerPass WEB FAS 0 · compose legacy AkerPass + frozen ÅkerMinne + phase-0 context")
    print("=" * 96)

    cfg, current_build, current_dist = current_config()
    phase0_context = current_build / "akerprestation_phase0" / "skane" / "field_static_context.parquet"
    if not phase0_context.exists():
        raise FileNotFoundError(f"Missing frozen phase 0 context in current worktree: {phase0_context}")

    roots = worktrees()
    legacy_build = select_legacy_build_dir(roots)
    akerminne_source_dist = select_akerminne_dist(roots)
    print(f"Current phase0 build_dir: {current_build}")
    print(f"Legacy AkerPass build_dir: {legacy_build}")
    print(f"ÅkerMinne web source dist: {akerminne_source_dist}")
    print(f"WEB output dist_dir:       {current_dist}")
    if legacy_build != current_build:
        print("Legacy model artifacts will be reused from another Git worktree; no raw rebuild.")
    if akerminne_source_dist != current_dist:
        print("Frozen ÅkerMinne web sidecars will be reused from another Git worktree.")

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

        # 1) Rebuild and verify the legacy public AkerPass shell from existing derived artifacts.
        run("src/40_build_akervarde_public_index.py", temp_path)
        run("src/41_build_akerpass_public_data.py", temp_path)
        run("src/42_build_akerpass_frontend.py", temp_path)
        run("src/43_verify_akerpass_web_v1.py", temp_path)

        # 2) Restore the already-built/frozen ÅkerMinne all-Skåne web layer.
        copy_akerminne_web(akerminne_source_dist, current_dist)
        run("src/59_patch_akerpass_akerminne_ui.py")
        run("src/61_revise_akerminne_ui_copy.py")
        run("src/68b_patch_akerpass_akerminne_reused_ui.py")

        # 3) Add frozen phase-0 static context; this changes reference attributes only.
        run("src/41b_enrich_akerpass_phase0_web.py")
        run("src/42b_patch_akerpass_frontend_phase0.py")
        run("src/43b_verify_akerpass_web_phase0.py")

        # 4) Independent final QA requires BOTH ÅkerMinne and phase-0 UI/data to coexist.
        run("src/69b_verify_akerpass_akerminne_phase0_combined.py")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    print("\n" + "=" * 96)
    print("AKERPASS + ÅKERMINNE + PHASE 0 WORKTREE RUNNER: PASS")
    print("=" * 96)
    print("dist/index.html contains ÅkerMinne 2015-2025 plus historic class 1-10 + dominant SKO.")
    print("No AkerScore, AkerVarde or AkerDrift model logic was changed or recalibrated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
