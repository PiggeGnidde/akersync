import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "src" / "106_akerpuls_prelim_fields_2026_stopa0_preflight.py"
spec = importlib.util.spec_from_file_location("akerpuls_stopa0", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestAkerPulsStopA0(unittest.TestCase):
    def test_config_contract(self):
        cfg = json.loads((ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json").read_text(encoding="utf-8"))
        mod.validate_config(cfg)
        self.assertEqual(cfg["snapshots"]["S2_2026_APRIL"], ["2026-04-08", "2026-04-09"])
        self.assertEqual(cfg["snapshots"]["S2_2026_JUNE"], ["2026-06-26", "2026-06-27"])
        self.assertFalse(cfg["scope_guards"]["mass_download_in_preflight"])

    def test_config_rejects_date_change(self):
        cfg = json.loads((ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json").read_text(encoding="utf-8"))
        cfg["snapshots"]["S2_2026_MAY"] = ["2026-05-24"]
        with self.assertRaises(RuntimeError):
            mod.validate_config(cfg)

    def test_config_rejects_pair_rule_change(self):
        cfg = json.loads((ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json").read_text(encoding="utf-8"))
        cfg["sentinel2"]["pair_rule"] = "average"
        with self.assertRaises(RuntimeError):
            mod.validate_config(cfg)


if __name__ == "__main__":
    unittest.main()
