from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESTORE = runpy.run_path(
    str(ROOT / "src" / "restore_orphaned_akerminne_web_payload.py"),
    run_name="phase0_orphan_restore",
)


def populate_valid_source(root: Path) -> None:
    akm = root / "dist" / "data" / "akerminne"
    akm.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(33):
        rel = f"data/akerminne/{1200+i:04d}_m{i:02d}.json"
        entries.append({
            "municipality": f"M{i:02d}",
            "municipality_code": f"{1200+i:04d}",
            "file": rel,
            "field_count": 1,
            "field_years": 11,
        })
        path = root / "dist" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    index = {
        "schema_version": "akerminne-skane-web-index-v1",
        "reference_year": 2025,
        "years": list(range(2015, 2026)),
        "municipality_count": 33,
        "field_count": 128636,
        "field_years": 1414996,
        "municipalities": entries,
    }
    (akm / "skane_index.json").write_text(json.dumps(index), encoding="utf-8")

    qa_dir = root / "data" / "derived" / "akerminne_v1a" / "skane"
    qa_dir.mkdir(parents=True, exist_ok=True)
    qa = {
        "completed_municipalities": 33,
        "current_fields": 128636,
        "field_years": 1414996,
        "component_rows": 2935686,
        "unknown_crop_combinations": 0,
    }
    (qa_dir / "skane_qa.json").write_text(json.dumps(qa), encoding="utf-8")


class OrphanedAkerMinneRestoreTests(unittest.TestCase):
    def test_discovers_valid_sibling_not_registered_as_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            current = parent / "current"
            orphan = parent / "old_artifacts"
            current.mkdir()
            populate_valid_source(orphan)
            found = RESTORE["find_orphaned_sources"](current)
            self.assertEqual(found, [orphan])

    def test_requires_frozen_qa_as_well_as_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            current = parent / "current"
            orphan = parent / "old_artifacts"
            current.mkdir()
            populate_valid_source(orphan)
            qa = orphan / "data" / "derived" / "akerminne_v1a" / "skane" / "skane_qa.json"
            qa.unlink()
            self.assertEqual(RESTORE["find_orphaned_sources"](current), [])

    def test_restore_copies_only_web_payload_and_revalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            current = parent / "current"
            orphan = parent / "old_artifacts"
            current.mkdir()
            populate_valid_source(orphan)
            status, source = RESTORE["restore_payload"](current)
            self.assertEqual(status, "restored")
            self.assertEqual(source, orphan)
            ok, _ = RESTORE["validate_web_payload"](current / "dist")
            self.assertTrue(ok)
            self.assertFalse((current / "data" / "derived" / "akerminne_v1a").exists())


if __name__ == "__main__":
    unittest.main()
