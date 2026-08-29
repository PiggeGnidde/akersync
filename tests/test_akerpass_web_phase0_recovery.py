from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = runpy.run_path(
    str(ROOT / "src" / "build_akerpass_web_phase0_worktree.py"),
    run_name="phase0_recovery_build",
)
PREFLIGHT = runpy.run_path(
    str(ROOT / "src" / "ensure_akerminne_recovery_local_config.py"),
    run_name="phase0_recovery_preflight",
)


def populate_payload(root: Path, *, markers: bool = False) -> None:
    dist = root / "dist"
    akm = dist / "data" / "akerminne"
    akm.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(33):
        rel = f"data/akerminne/{1200+i:04d}_m{i:02d}.json"
        entries.append({
            "municipality": f"M{i}",
            "municipality_code": f"{1200+i:04d}",
            "file": rel,
            "field_count": 1,
            "field_years": 11,
        })
        path = dist / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (akm / "skane_index.json").write_text(json.dumps({
        "schema_version": "akerminne-skane-web-index-v1",
        "reference_year": 2025,
        "years": list(range(2015, 2026)),
        "municipality_count": 33,
        "field_count": 128636,
        "field_years": 1414996,
        "municipalities": entries,
    }), encoding="utf-8")
    html = "\n".join(BUILD["AKM_UI_MARKERS"]) if markers else "plain base frontend"
    (dist / "index.html").write_text(html, encoding="utf-8")
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "local_paths.json").write_text('{"dist_dir":"dist"}', encoding="utf-8")


def populate_derived(root: Path, *, missing_code: str | None = None) -> Path:
    build = root / "data" / "derived"
    skane = build / "akerminne_v1a" / "skane"
    skane.mkdir(parents=True, exist_ok=True)
    municipalities = []
    for i in range(33):
        code = f"{1200+i:04d}"
        name = f"M{i}"
        municipalities.append({"code": code, "name": name, "current_fields": 1})
        d = skane / "municipalities" / f"{code}_m{i}"
        d.mkdir(parents=True, exist_ok=True)
        for filename in (
            "build_manifest.json",
            "akerminne_year_summary_classified.parquet",
            "akerminne_crop_areas_grouped.parquet",
            "akerminne_components.parquet",
        ):
            if code == missing_code and filename == "akerminne_components.parquet":
                continue
            (d / filename).write_bytes(b"x")
    (skane / "skane_plan.json").write_text(json.dumps({
        "municipality_count": 33,
        "current_fields_total": 128636,
        "municipalities": municipalities,
    }), encoding="utf-8")
    (skane / "skane_qa.md").write_text("PASS", encoding="utf-8")
    (skane / "skane_qa.json").write_text(json.dumps({
        "completed_municipalities": 33,
        "current_fields": 128636,
        "field_years": 1414996,
        "component_rows": 2935686,
        "unknown_crop_combinations": 0,
    }), encoding="utf-8")
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "local_paths.json").write_text('{"build_dir":"data/derived"}', encoding="utf-8")
    return skane


class AkerpassWebPhase0RecoveryTests(unittest.TestCase):
    def test_payload_recovery_does_not_require_retained_ui_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            populate_payload(root, markers=False)
            selected = BUILD["select_akerminne_payload_dist"]([root])
            self.assertEqual(selected, root / "dist")

    def test_complete_derived_batch_is_recovery_level_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            skane = populate_derived(root)
            selected = BUILD["select_akerminne_derived"]([root])
            self.assertEqual(selected, skane)
            self.assertEqual(BUILD["missing_akerminne_derived"](skane), [])
            BUILD["validate_frozen_akerminne_qa"](skane)

    def test_incomplete_derived_batch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            skane = populate_derived(root, missing_code="1207")
            missing = BUILD["missing_akerminne_derived"](skane)
            self.assertTrue(any("1207/akerminne_components.parquet" in x for x in missing))
            self.assertIsNone(BUILD["select_akerminne_derived"]([root]))

    def test_frozen_aggregate_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            skane = populate_derived(root)
            qa_path = skane / "skane_qa.json"
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            qa["component_rows"] -= 1
            qa_path.write_text(json.dumps(qa), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                BUILD["validate_frozen_akerminne_qa"](skane)

    def test_raw_root_inference_uses_existing_common_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            (raw / "jv").mkdir(parents=True)
            cfg = {
                "blocks": str(raw / "jv" / "blocks.gpkg"),
                "skiften": str(raw / "jv" / "skiften.gpkg"),
                "soil_zip": str(raw / "soil.zip"),
            }
            self.assertEqual(PREFLIGHT["infer_raw_root"](cfg), raw)


if __name__ == "__main__":
    unittest.main()
