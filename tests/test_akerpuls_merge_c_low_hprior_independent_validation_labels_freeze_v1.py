import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"206_akerpuls_merge_c_low_hprior_independent_validation_labels_freeze_v1.py"

def load():
    s=importlib.util.spec_from_file_location("clabel",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_parent_hashes(self):
        self.assertEqual(self.m.EXPECTED_VIEWER_FREEZE_SHA,"b5c621cb6e3cd80a3906ad489a8ab05d8abd37cfeca090f6f7a777fa89f899ed")
        self.assertEqual(self.m.EXPECTED_SAMPLE_POPULATION_SHA,"c0af9da308d6e250eaca7fa149b64f993bfa91d2af6e3eb533cb3a97023fcd45")
        self.assertEqual(self.m.EXPECTED_MATCHING_SHA,"e19ced20288d334c6e9943df91242f5d1f780ed6b51a26e78c1e205c6c455aec")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA,"81c0ea5e69c8cbcc6032cc860d3581447ab514b83bf890be6f0c6938f453d53d")

    def test_exact_user_export(self):
        self.assertEqual(self.m.EXPECTED_LABELS_SHA,"8d769eb915a32f0b2f73be3c58ee28e2921d1357261f46c4fd09c118e90c3dd6")
        self.assertEqual(self.m.EXPECTED_ROWS,58)

    def test_no_reveal(self):
        self.assertIn('"blind_key_contents_revealed":False',self.text)
        self.assertIn('"matching_diagnostic_contents_revealed":False',self.text)
        self.assertIn('"arms_joined":False',self.text)

    def test_no_operational_mutation(self):
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)
        self.assertIn('"geometry_mutated":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_LABELS_V1")

if __name__=="__main__":
    unittest.main()
