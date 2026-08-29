#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feature/akerprestation-web-phase0-v0a"
AKM_FREEZE_TAG = "akerminne-v1.0"
EXPECTED_FIELDS = 128_636
EXPECTED_FIELD_YEARS = 1_414_996
EXPECTED_COMPONENTS = 2_935_686
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

# Files that define the immutable ÅkerMinne v1.0 calculation/web semantics.
# The regeneration fallback is forbidden if any of these differ from the freeze tag.
FROZEN_AKM_PATHS = (
    "config/akerminne_skane_municipalities.json",
    "config/akerminne_v1a.json",
    "data/reference/akerminne_crop_codes_official",
    "src/51_download_akerminne_pilot.py",
    "src/57_build_akerminne_web_pilot.py",
    "src/59_patch_akerpass_akerminne_ui.py",
    "src/61_revise_akerminne_ui_copy.py",
    "src/62_prepare_akerminne_skane.py",
    "src/63_build_akerminne_municipality.py",
    "src/64_run_akerminne_skane.py",
    "src/65_verify_akerminne_skane.py",
    "src/66_verify_akerminne_skurup_regression.py",
    "src/67_build_akerminne_skane_web.py",
    "src/68_patch_akerpass_akerminne_skane_ui.py",
    "src/69_verify_akerminne_skane_web.py",
    "src/akerminne_history_core.py",
    "src/akerminne_mapping_core.py",
    "src/akerminne_status_core.py",
)


def _abs_from(worktree: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else worktree / path


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    return "".join(ch if ch.isalnum() else "_" for ch in str(text).translate(trans).lower()).strip("_")


def run_cmd(args: list[str], *, label: str | None = None) -> None:
    if label:
        print(f"\n>>> {label}", flush=True)
    print("    " + " ".join(str(x) for x in args), flush=True)
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)


def run(script: str, config_path: Path | None = None) -> None:
    cmd = [sys.executable, script]
    if config_path is not None:
        cmd += ["--config", str(config_path)]
    run_cmd(cmd, label=script)


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


def missing_akerminne_web(dist_dir: Path) -> list[str]:
    missing = missing_akerminne_web_payload_only(dist_dir)
    html_path = dist_dir / "index.html"
    if not html_path.exists():
        missing.append("index.html")
        return missing
    try:
        html = html_path.read_text(encoding="utf-8")
        for marker in AKM_UI_MARKERS:
            if marker not in html:
                missing.append(f"index marker {marker}")
    except Exception as exc:
        missing.append(f"index.html unreadable ({type(exc).__name__})")
    return missing


def select_akerminne_payload_dist(candidates: Iterable[Path]) -> Path | None:
    for worktree in candidates:
        dist_dir = dist_dir_for_worktree(worktree)
        if not missing_akerminne_web_payload_only(dist_dir):
            return dist_dir
    return None


def select_akerminne_dist(candidates: Iterable[Path]) -> Path:
    """Legacy test/helper: require payload plus the old all-Skåne UI markers."""
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
        print("ÅkerMinne sidecars already live in target dist; no copy needed.")
        return
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    missing = missing_akerminne_web_payload_only(target_dist)
    if missing:
        raise RuntimeError("Copied ÅkerMinne web package is incomplete: " + ", ".join(missing[:12]))
    print(f"ÅkerMinne sidecars copied byte-for-byte: {source} -> {target}")


def missing_akerminne_derived(skane_root: Path) -> list[str]:
    plan_path = skane_root / "skane_plan.json"
    missing: list[str] = []
    if not plan_path.exists():
        return ["skane_plan.json"]
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"skane_plan unreadable ({type(exc).__name__})"]
    items = plan.get("municipalities") or []
    if int(plan.get("municipality_count", -1)) != 33 or len(items) != 33:
        missing.append("plan municipality_count != 33")
    if int(plan.get("current_fields_total", -1)) != EXPECTED_FIELDS:
        missing.append("plan current_fields_total != 128636")
    if not (skane_root / "skane_qa.md").exists():
        missing.append("skane_qa.md")
    for item in items:
        code, name = str(item.get("code") or ""), str(item.get("name") or "")
        d = skane_root / "municipalities" / f"{code}_{_slug(name)}"
        for filename in (
            "build_manifest.json",
            "akerminne_year_summary_classified.parquet",
            "akerminne_crop_areas_grouped.parquet",
            "akerminne_components.parquet",
        ):
            if not (d / filename).exists():
                missing.append(f"{code}/{filename}")
                if len(missing) >= 20:
                    return missing
    return missing


def select_akerminne_derived(candidates: Iterable[Path]) -> Path | None:
    for worktree in candidates:
        skane_root = build_dir_for_worktree(worktree) / "akerminne_v1a" / "skane"
        if not missing_akerminne_derived(skane_root):
            return skane_root
    return None


def verify_frozen_akerminne_code() -> None:
    tag_check = subprocess.run(
        ["git", "rev-parse", "--verify", f"{AKM_FREEZE_TAG}^{{commit}}"], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if tag_check.returncode:
        raise RuntimeError(f"Frozen ÅkerMinne tag {AKM_FREEZE_TAG} is unavailable locally")
    diff = subprocess.run(
        ["git", "diff", "--name-only", AKM_FREEZE_TAG, "--", *FROZEN_AKM_PATHS], cwd=ROOT,
        text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if diff.returncode:
        raise RuntimeError("Could not compare ÅkerMinne implementation with freeze tag: " + diff.stderr.strip())
    changed = [x.strip() for x in diff.stdout.splitlines() if x.strip()]
    if changed:
        raise RuntimeError(
            "ÅkerMinne regeneration blocked: frozen implementation differs from akerminne-v1.0:\n  "
            + "\n  ".join(changed)
        )
    print(f"Frozen ÅkerMinne code guard: PASS · {AKM_FREEZE_TAG} semantics unchanged")


def infer_raw_root(project_cfg: dict) -> Path | None:
    candidates: list[Path] = []
    for key in ("blocks", "skiften", "soil_zip"):
        raw = project_cfg.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if path.is_absolute():
            candidates.append(path.parent if path.suffix else path)
    if not candidates:
        return None
    try:
        common = Path(os.path.commonpath([str(x) for x in candidates]))
    except Exception:
        return None
    # Refuse to infer merely a drive root / filesystem root.
    if len(common.parts) < 2 or not common.exists():
        return None
    return common


def find_akerminne_local_config(roots: Iterable[Path], project_cfg: dict, temp_files: list[Path]) -> Path:
    for root in roots:
        path = root / "config" / "akerminne_local.json"
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            raw_root = Path(str(doc["raw_root"]))
            if raw_root.exists():
                print(f"ÅkerMinne raw config reused: {path}")
                return path
        except Exception:
            continue
    raw_root = infer_raw_root(project_cfg)
    if raw_root is None:
        raise RuntimeError(
            "No usable config/akerminne_local.json was found in any worktree, and raw_root "
            "could not be inferred safely from config/local_paths.json."
        )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", prefix="akerminne_local_recovery_", delete=False,
    ) as handle:
        json.dump({"raw_root": str(raw_root)}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        path = Path(handle.name)
    temp_files.append(path)
    print(f"ÅkerMinne raw_root safely inferred from project paths: {raw_root}")
    return path


def raw_history_complete(raw_root: Path, plan_path: Path) -> bool:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for item in plan["municipalities"]:
            safe = str(item["name"]).lower().replace(" ", "_")
            for year in range(2015, 2025):
                path = raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_{safe}_{year}.gpkg"
                if not path.exists():
                    return False
        return True
    except Exception:
        return False


def validate_frozen_akerminne_qa(skane_root: Path) -> None:
    path = skane_root / "skane_qa.json"
    if not path.exists():
        raise FileNotFoundError(path)
    qa = json.loads(path.read_text(encoding="utf-8"))
    checks = {
        "completed_municipalities": 33,
        "current_fields": EXPECTED_FIELDS,
        "field_years": EXPECTED_FIELD_YEARS,
        "component_rows": EXPECTED_COMPONENTS,
        "unknown_crop_combinations": 0,
    }
    bad = [f"{key}={qa.get(key)!r} expected {value!r}" for key, value in checks.items() if int(qa.get(key, -1)) != value]
    if bad:
        raise RuntimeError("Regenerated ÅkerMinne aggregate differs from v1.0 freeze: " + "; ".join(bad))
    print(
        "Frozen ÅkerMinne aggregate: PASS · "
        f"33 municipalities · {EXPECTED_FIELDS:,} fields · {EXPECTED_FIELD_YEARS:,} field-years · "
        f"{EXPECTED_COMPONENTS:,} components · 0 unknown crop combinations"
    )


def regenerate_frozen_akerminne(
    *, current_build: Path, project_cfg_path: Path, project_cfg: dict, roots: list[Path], temp_files: list[Path]
) -> Path:
    verify_frozen_akerminne_code()
    local_cfg = find_akerminne_local_config(roots, project_cfg, temp_files)
    local_doc = json.loads(local_cfg.read_text(encoding="utf-8-sig"))
    raw_root = Path(str(local_doc["raw_root"]))
    skane_root = current_build / "akerminne_v1a" / "skane"

    print("\nNo retained ÅkerMinne web/derived package was found.")
    print("Reproducing ÅkerMinne v1.0 from frozen code + raw/checkpoint data.")
    print("This is resumable and may take time if historical raw files must be downloaded again.")

    run_cmd([
        sys.executable, "src/62_prepare_akerminne_skane.py",
        "--project-local-config", str(project_cfg_path),
        "--output-root", str(skane_root),
    ], label="Prepare frozen ÅkerMinne Skåne plan")

    batch_cmd = [
        sys.executable, "src/64_run_akerminne_skane.py",
        "--skane-root", str(skane_root),
        "--local-config", str(local_cfg),
    ]
    if raw_history_complete(raw_root, skane_root / "skane_plan.json"):
        batch_cmd.append("--skip-download")
        print("Historical raw files 2015-2024 found for all 33 municipalities · download step skipped.")
    else:
        print("Historical raw set is incomplete · frozen downloader/checkpoints will fill missing files.")
    run_cmd(batch_cmd, label="Run/reuse frozen ÅkerMinne Skåne batch")
    run_cmd([
        sys.executable, "src/65_verify_akerminne_skane.py", "--skane-root", str(skane_root)
    ], label="Verify regenerated frozen ÅkerMinne Skåne batch")
    validate_frozen_akerminne_qa(skane_root)
    if missing_akerminne_derived(skane_root):
        raise RuntimeError("Regenerated ÅkerMinne derived package is still incomplete")
    return skane_root


def build_akerminne_web_from_derived(skane_root: Path, target_dist: Path) -> None:
    target = target_dist / "data" / "akerminne"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    run_cmd([
        sys.executable, "src/67_build_akerminne_skane_web.py",
        "--skane-root", str(skane_root),
        "--config", str(ROOT / "config" / "akerminne_v1a.json"),
        "--out-dir", str(target),
    ], label="Build ÅkerMinne 33-municipality sidecars from frozen derived batch")
    run_cmd([sys.executable, "src/59_patch_akerpass_akerminne_ui.py", "--index", str(target_dist / "index.html")])
    run_cmd([sys.executable, "src/61_revise_akerminne_ui_copy.py", "--index", str(target_dist / "index.html")])
    run_cmd([
        sys.executable, "src/68_patch_akerpass_akerminne_skane_ui.py",
        "--index", str(target_dist / "index.html"),
        "--plan", str(skane_root / "skane_plan.json"),
    ])
    run_cmd([
        sys.executable, "src/69_verify_akerminne_skane_web.py",
        "--index-html", str(target_dist / "index.html"),
        "--akm-dir", str(target),
        "--skane-root", str(skane_root),
    ], label="Verify rebuilt ÅkerMinne all-Skåne web layer")


def current_config() -> tuple[dict, Path, Path, Path]:
    cfg_path = ROOT / "config" / "local_paths.json"
    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    current_build = _abs_from(ROOT, str(cfg.get("build_dir", "data/derived")))
    current_dist = _abs_from(ROOT, str(cfg.get("dist_dir", "dist")))
    return cfg, current_build, current_dist, cfg_path


def main() -> int:
    print("=" * 96)
    print("AkerPass WEB FAS 0 · compose legacy AkerPass + frozen ÅkerMinne + phase-0 context")
    print("=" * 96)

    cfg, current_build, current_dist, project_cfg_path = current_config()
    phase0_context = current_build / "akerprestation_phase0" / "skane" / "field_static_context.parquet"
    if not phase0_context.exists():
        raise FileNotFoundError(f"Missing frozen phase 0 context in current worktree: {phase0_context}")

    roots = worktrees()
    legacy_build = select_legacy_build_dir(roots)
    akerminne_payload_dist = select_akerminne_payload_dist(roots)
    akerminne_derived = None if akerminne_payload_dist is not None else select_akerminne_derived(roots)

    print(f"Current phase0 build_dir: {current_build}")
    print(f"Legacy AkerPass build_dir: {legacy_build}")
    print(f"WEB output dist_dir:       {current_dist}")
    if legacy_build != current_build:
        print("Legacy model artifacts will be reused from another Git worktree; no raw rebuild.")
    if akerminne_payload_dist is not None:
        print(f"ÅkerMinne recovery level 1: retained sidecar payload · {akerminne_payload_dist}")
    elif akerminne_derived is not None:
        print(f"ÅkerMinne recovery level 2: retained frozen derived batch · {akerminne_derived}")
    else:
        print("ÅkerMinne recovery level 3: no retained web/derived package · frozen reproduction required")

    runtime = dict(cfg)
    runtime["build_dir"] = str(legacy_build)
    runtime["dist_dir"] = str(current_dist)

    temp_files: list[Path] = []
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", prefix="akerpass_phase0_legacy_", delete=False,
        ) as handle:
            json.dump(runtime, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            runtime_path = Path(handle.name)
        temp_files.append(runtime_path)

        # 1) Rebuild/verify legacy public ÅkerPass shell from existing model artifacts.
        run("src/40_build_akervarde_public_index.py", runtime_path)
        run("src/41_build_akerpass_public_data.py", runtime_path)
        run("src/42_build_akerpass_frontend.py", runtime_path)
        run("src/43_verify_akerpass_web_v1.py", runtime_path)

        # 2) Restore frozen ÅkerMinne. Prefer retained sidecars, then retained derived,
        # finally deterministic reproduction using only akerminne-v1.0 semantics.
        if akerminne_payload_dist is not None:
            copy_akerminne_web(akerminne_payload_dist, current_dist)
            run("src/59_patch_akerpass_akerminne_ui.py")
            run("src/61_revise_akerminne_ui_copy.py")
            run("src/68b_patch_akerpass_akerminne_reused_ui.py")
        else:
            if akerminne_derived is None:
                akerminne_derived = regenerate_frozen_akerminne(
                    current_build=current_build,
                    project_cfg_path=project_cfg_path,
                    project_cfg=cfg,
                    roots=roots,
                    temp_files=temp_files,
                )
            else:
                validate_frozen_akerminne_qa(akerminne_derived)
            build_akerminne_web_from_derived(akerminne_derived, current_dist)

        # 3) Add frozen phase-0 static context; reference attributes only.
        run("src/41b_enrich_akerpass_phase0_web.py")
        run("src/42b_patch_akerpass_frontend_phase0.py")
        run("src/43b_verify_akerpass_web_phase0.py")

        # 4) Independent final QA requires BOTH ÅkerMinne and phase-0 UI/data.
        run("src/69b_verify_akerpass_akerminne_phase0_combined.py")
    finally:
        for path in temp_files:
            try:
                path.unlink(missing_ok=True)
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
