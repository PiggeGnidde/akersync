import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "148_akerpuls_d1s3g_review_diagnostic_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3g", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3GReviewDiagnosticV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_as_bool(self):
        s = pd.Series([True, False, "true", "FALSE", "1", "0", "yes", "no", None])
        got = self.m.as_bool(s).tolist()
        self.assertEqual(got, [True, False, True, False, True, False, True, False, False])

    def test_finite(self):
        self.assertEqual(self.m.finite("0.25"), 0.25)
        self.assertIsNone(self.m.finite("nan"))
        self.assertIsNone(self.m.finite(None))

    def test_script_is_zero_network_zero_pu_diagnostic(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("urllib", text)
        self.assertNotIn("boto3", text)
        self.assertNotIn("fetch_tiff", text)
        self.assertNotIn("oauth(", text)
        self.assertIn("D1S3F_STATUS_REMAINS=REVIEW", text)
        self.assertIn("FULL_SKANE_S3_AUTHORIZED=FALSE", text)


if __name__ == "__main__":
    unittest.main()
