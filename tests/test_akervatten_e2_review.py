from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_e2", ROOT / "src/99_akervatten_e2_review.py"
)
assert spec and spec.loader
E2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E2)


class TestAkerVattenE2Review(unittest.TestCase):
    def test_max_true_run_event(self):
        dates = pd.to_datetime([
            "2020-01-01","2020-01-02","2020-01-03",
            "2020-01-05","2020-01-06"
        ])
        vals = pd.Series([5,5,5,5,5])
        q = E2.max_true_run_event(pd.Series(dates), vals, 10)
        self.assertEqual(q["days"], 3)
        self.assertEqual(q["start"], "2020-01-01")
        self.assertEqual(q["end"], "2020-01-03")

    def test_max_true_run_event_threshold(self):
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        vals = pd.Series([5,15,5,5,20])
        q = E2.max_true_run_event(pd.Series(dates), vals, 10)
        self.assertEqual(q["days"], 2)
        self.assertEqual(q["start"], "2020-01-03")
        self.assertEqual(q["end"], "2020-01-04")


if __name__ == "__main__":
    unittest.main()
