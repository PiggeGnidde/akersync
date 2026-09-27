from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_c", ROOT / "src/96_akervatten_c_full_linkage.py"
)
assert spec and spec.loader
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


class TestAkerVattenCFullLinkage(unittest.TestCase):
    def test_chunk_ranges_full_population(self):
        q = C.chunk_ranges(128636, 1000)
        self.assertEqual(len(q), 129)
        self.assertEqual(q[0], (1, 0, 1000))
        self.assertEqual(q[-1], (129, 128000, 128636))
        self.assertEqual(sum(e-s for _,s,e in q), 128636)

    def test_checkpoint_filename(self):
        p = C.checkpoint_path(Path("x"), 0, 1000)
        self.assertEqual(p.name, "fields_000001_001000.parquet")
        p = C.checkpoint_path(Path("x"), 128000, 128636)
        self.assertEqual(p.name, "fields_128001_128636.parquet")

    def test_checkpoint_validates_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "q.parquet"
            df = pd.DataFrame({
                "blockid":["1","2"],
                "skiftesbeteckning":["A","B"],
                "x":[1,2],
            })
            C.atomic_parquet(df, path)
            keys = df[["blockid","skiftesbeteckning"]]
            self.assertTrue(C.checkpoint_valid(path, keys))

            wrong = pd.DataFrame({
                "blockid":["1","3"],
                "skiftesbeteckning":["A","B"],
            })
            self.assertFalse(C.checkpoint_valid(path, wrong))

    def test_tile_plan_is_deterministic(self):
        a = C.tile_plan((350123.0, 6130123.0, 475999.0, 6259000.0), 20000.0)
        b = C.tile_plan((350123.0, 6130123.0, 475999.0, 6259000.0), 20000.0)
        self.assertEqual(a, b)
        self.assertGreater(len(a), 1)
        self.assertEqual(a[0]["minx"] % 20000, 0)
        self.assertEqual(a[0]["miny"] % 20000, 0)

    def test_duration_format(self):
        self.assertEqual(C.fmt_duration(0), "00:00:00")
        self.assertEqual(C.fmt_duration(3661), "01:01:01")


if __name__ == "__main__":
    unittest.main()
