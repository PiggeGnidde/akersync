#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.freeze_artmatch_v0a import sha256_file, snapshot_name


class TestFreezeArtMatchV0a(unittest.TestCase):
    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.txt"
            p.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(p),
                hashlib.sha256(b"abc").hexdigest(),
            )

    def test_snapshot_name_is_path_stable(self):
        self.assertEqual(
            snapshot_name(Path("a/b/c.json")),
            "a__b__c.json",
        )


if __name__ == "__main__":
    unittest.main()
