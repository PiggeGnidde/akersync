import importlib.util
from pathlib import Path
import tempfile
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src" / "132_akerpuls_true_loo_diagnostic.py"
RUNNER = ROOT / "src" / "133_akerpuls_true_loo_diagnostic_runner.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


base = load(BASE, "akerpuls_true_loo_base_test")
runner = load(RUNNER, "akerpuls_true_loo_runner_test")


class TestTrueLooRunner(unittest.TestCase):
    def test_blind_index_is_sorted_numerically(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            rows = [{"blind_index": str(i), "parent_field_id_2025": f"F{i}"} for i in range(1, 21)]
            # Put 10 before 2, reproducing lexical CSV-order trouble explicitly.
            rows = sorted(rows, key=lambda r: r["blind_index"])
            c3 = td / "c3.csv"
            c5 = td / "c5.csv"
            pd.DataFrame(rows).to_csv(c3, index=False)
            pd.DataFrame(rows[:12]).to_csv(c5, index=False)
            cfg = {
                "blind_review": {
                    "c3_key": str(c3),
                    "c5d_key": str(c5),
                    "c3_labels": ["X"] * 20,
                    "c5d_labels": ["Y"] * 12,
                }
            }
            out = runner.build_blind_cases_numeric(base, cfg)
            got = out[out["dataset"] == "C"]["blind_index"].tolist()
            self.assertEqual(got, list(range(1, 21)))


if __name__ == "__main__":
    unittest.main()
