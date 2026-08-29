from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = runpy.run_path(
    str(ROOT / "src" / "build_akerpass_web_phase0_worktree.py"),
    run_name="phase0_worktree",
)
REQUIRED = BUILD["LEGACY_REQUIRED"]
AKM_MARKERS = BUILD["AKM_UI_MARKERS"]


def populate(build_dir: Path, missing: str | None = None) -> None:
    for rel in REQUIRED:
        if rel == missing:
            continue
        path = build_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def populate_akerminne_dist(dist_dir: Path, *, omit_sidecar: int | None = None, markers: bool = True) -> None:
    akm = dist_dir / "data" / "akerminne"
    akm.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(33):
        code = f"{1200 + i:04d}"
        name = "Skurup" if i == 0 else ("Lomma" if i == 1 else f"Kommun{i:02d}")
        rel = f"data/akerminne/{code}_m{i:02d}.json"
        entries.append(
            {
                "municipality": name,
                "municipality_code": code,
                "file": rel,
                "field_count": 1,
                "field_years": 11,
                "size_bytes": 1,
            }
        )
        if omit_sidecar != i:
            path = dist_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
    index = {
        "schema_version": "akerminne-skane-web-index-v1",
        "reference_year": 2025,
        "years": list(range(2015, 2026)),
        "municipality_count": 33,
        "field_count": 128636,
        "field_years": 1414996,
        "sidecar_bytes": 33,
        "municipalities": entries,
    }
    (akm / "skane_index.json").write_text(json.dumps(index), encoding="utf-8")
    html = "\n".join(AKM_MARKERS) if markers else "plain base frontend"
    (dist_dir / "index.html").write_text(html, encoding="utf-8")


class AkerpassWebPhase0WorktreeTests(unittest.TestCase):
    def test_select_legacy_build_dir_uses_first_complete_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad = tmp_path / "bad"
            good = tmp_path / "good"
            (bad / "config").mkdir(parents=True)
            (good / "config").mkdir(parents=True)
            (bad / "config" / "local_paths.json").write_text(
                '{"build_dir":"data/derived"}', encoding="utf-8"
            )
            (good / "config" / "local_paths.json").write_text(
                '{"build_dir":"data/derived"}', encoding="utf-8"
            )
            populate(bad / "data" / "derived", missing="geometry_payload.json")
            populate(good / "data" / "derived")

            selected = BUILD["select_legacy_build_dir"]([bad, good])
            self.assertEqual(selected, good / "data" / "derived")

    def test_select_legacy_build_dir_fails_loudly_if_no_complete_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            only = tmp_path / "only"
            (only / "config").mkdir(parents=True)
            (only / "config" / "local_paths.json").write_text(
                '{"build_dir":"data/derived"}', encoding="utf-8"
            )
            populate(only / "data" / "derived", missing="soil_payload.json")

            with self.assertRaises(RuntimeError) as raised:
                BUILD["select_legacy_build_dir"]([only])
            text = str(raised.exception)
            self.assertIn("soil_payload.json", text)
            self.assertIn("No Git worktree contains", text)

    def test_select_akerminne_dist_requires_full_skane_ui_and_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad = tmp_path / "bad"
            good = tmp_path / "good"
            for root in (bad, good):
                (root / "config").mkdir(parents=True)
                (root / "config" / "local_paths.json").write_text(
                    '{"dist_dir":"dist"}', encoding="utf-8"
                )
            populate_akerminne_dist(bad / "dist", omit_sidecar=7)
            populate_akerminne_dist(good / "dist")

            selected = BUILD["select_akerminne_dist"]([bad, good])
            self.assertEqual(selected, good / "dist")

    def test_select_akerminne_dist_rejects_sidecars_without_all_skane_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "only"
            (root / "config").mkdir(parents=True)
            (root / "config" / "local_paths.json").write_text(
                '{"dist_dir":"dist"}', encoding="utf-8"
            )
            populate_akerminne_dist(root / "dist", markers=False)
            with self.assertRaises(RuntimeError) as raised:
                BUILD["select_akerminne_dist"]([root])
            self.assertIn("AKERMINNE_SKANE_UI_R2", str(raised.exception))

    def test_payload_only_validation_does_not_require_source_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            populate_akerminne_dist(dist)
            (dist / "index.html").unlink()
            self.assertEqual(BUILD["missing_akerminne_web_payload_only"](dist), [])


if __name__ == "__main__":
    unittest.main()
