#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerprestation_phase0_akerminne_locator import (
    find_strict_frozen_akerminne_field_year_file,
)
from akerprestation_phase0_overlay_core import sha256_file


@unittest.skipUnless(
    __import__("importlib").util.find_spec("pyarrow") is not None
    or __import__("importlib").util.find_spec("fastparquet") is not None,
    "Parquet engine not installed in test runtime",
)
class FrozenAkerMinneLocatorTests(unittest.TestCase):
    def _fixture(self, td: str, good_hash: bool = True):
        repo = Path(td) / "repo"
        root = Path(td) / "akerminne_root"
        out = root / "municipalities" / "1264_skurup"
        out.mkdir(parents=True)
        (repo / "config").mkdir(parents=True)
        source = Path(td) / "fields.gpkg"
        source.write_bytes(b"frozen-2025-source")
        (repo / "config" / "local_paths.json").write_text(
            json.dumps({"skiften": str(source)}), encoding="utf-8"
        )

        rows = []
        for fid in ("b1|s1", "b2|s2"):
            for year in range(2015, 2026):
                rows.append({"current_field_id": fid, "history_year": year, "status": "SINGLE_CROP"})
        canonical = out / "akerminne_year_summary_classified.parquet"
        pd.DataFrame(rows).to_parquet(canonical, index=False)
        manifest = {
            "municipality": "Skurup",
            "municipality_code": "1264",
            "current_fields": 2,
            "field_years": 22,
            "current_source_sha256": sha256_file(source) if good_hash else "wrong",
        }
        (out / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        # Noise that the old heuristic could inspect. The strict locator must ignore it.
        pd.DataFrame(
            [{"current_field_id": "wrong|id", "history_year": 2025, "reason_flags": "x"}] * 100
        ).to_parquet(out / "akerminne_components.parquet", index=False)
        return repo, root, canonical

    def test_selects_only_canonical_manifest_validated_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, canonical = self._fixture(td, good_hash=True)
            with mock.patch(
                "akerprestation_phase0_akerminne_locator.find_akerminne_skane_roots",
                return_value=[root],
            ):
                found = find_strict_frozen_akerminne_field_year_file(repo, "1264", "Skurup")
            self.assertEqual(found, canonical)

    def test_rejects_current_source_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, _ = self._fixture(td, good_hash=False)
            with mock.patch(
                "akerprestation_phase0_akerminne_locator.find_akerminne_skane_roots",
                return_value=[root],
            ):
                found = find_strict_frozen_akerminne_field_year_file(repo, "1264", "Skurup")
            self.assertIsNone(found)

    def test_rejects_wrong_municipality(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, _ = self._fixture(td, good_hash=True)
            with mock.patch(
                "akerprestation_phase0_akerminne_locator.find_akerminne_skane_roots",
                return_value=[root],
            ):
                found = find_strict_frozen_akerminne_field_year_file(repo, "1280", "Malmö")
            self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
