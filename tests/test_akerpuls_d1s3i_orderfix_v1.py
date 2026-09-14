import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "150b_akerpuls_d1s3i_full_skane_s3_plan_orderfix_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3i_orderfix", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3IOrderFixV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_canonical_date_order_ignores_snapshot_mapping_key_order(self):
        # Mirrors the order produced when D0b stable JSON serialization sorts keys.
        contract = {
            "frozen_snapshots": {
                "S2_2026_APRIL": ["2026-04-08", "2026-04-09"],
                "S2_2026_JULY": ["2026-07-09"],
                "S2_2026_JUNE": ["2026-06-26", "2026-06-27"],
                "S2_2026_MAY": ["2026-05-25"],
            }
        }
        self.assertEqual(
            self.m.canonical_flatten_snapshot_dates(contract),
            [
                "2026-04-08", "2026-04-09", "2026-05-25",
                "2026-06-26", "2026-06-27", "2026-07-09",
            ],
        )

    def test_fix_is_validation_only_wrapper(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("parent.flatten_snapshot_dates = canonical_flatten_snapshot_dates", text)
        self.assertNotIn("urllib", text)
        self.assertNotIn("boto3", text)
        self.assertNotIn("download_file", text)


if __name__ == "__main__":
    unittest.main()
