from __future__ import annotations

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


def populate(build_dir: Path, missing: str | None = None) -> None:
    for rel in REQUIRED:
        if rel == missing:
            continue
        path = build_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


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


if __name__ == "__main__":
    unittest.main()
