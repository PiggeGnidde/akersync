import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"204_akerpuls_merge_c_low_hprior_independent_validation_viewer_v1.py"
def load():
    s=importlib.util.spec_from_file_location("cval",SCRIPT); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=load(); cls.text=SCRIPT.read_text(encoding="utf-8")
    def test_design(self):
        self.assertEqual(self.m.EXPECTED_REMAINING_C,29)
        self.assertEqual(self.m.EXPECTED_MATCHES,29)
        self.assertEqual(self.m.EXPECTED_SAMPLE,58)
        self.assertEqual(self.m.EXPECTED_EXCLUDED_UNION,200)
    def test_parent_freeze(self):
        self.assertEqual(self.m.EXPECTED_AB_VALIDATION_FREEZE_SHA,"333e3c9738cf56f9a3fadf37c46a7883c508ec70bd25975eb214132fb65ffc8d")
    def test_predeclared_paired_analysis(self):
        self.assertIn('"primary_test":"exact two-sided McNemar on matched broad-positive labels"',self.text)
        self.assertIn('"paired_exclusion":"exclude matched pair if either member is EJ_BEDÖMBAR"',self.text)
    def test_no_mutation(self):
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)
    def test_status(self):
        self.assertEqual(self.m.STATUS,"PASS_TO_C_LOW_HPRIOR_INDEPENDENT_BLIND_VALIDATION")
if __name__=="__main__": unittest.main()
