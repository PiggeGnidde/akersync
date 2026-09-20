import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"198_akerpuls_merge_sh_gated_ranking_freeze_v1.py"
def load():
    s=importlib.util.spec_from_file_location("x",SCRIPT); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=load(); cls.text=SCRIPT.read_text(encoding="utf-8")
    def test_hashes(self):
        self.assertEqual(self.m.EXPECTED_PARQUET_SHA,"288a07042eaa80256541e6c25c14acd9a4b0fc0767822db540f831f0ae668e10")
        self.assertEqual(self.m.EXPECTED_SUMMARY_SHA,"f542da9f5026a5a5215cf881727b68bcce82e71b4ab8c70374468ff674fb5a48")
    def test_counts(self):
        self.assertEqual(self.m.EXPECTED_COUNTS["A_CONFIRMED_HIGH"],1011)
        self.assertEqual(self.m.EXPECTED_COUNTS["B_SAT_HIGH_H_MID"],1171)
        self.assertEqual(sum(self.m.EXPECTED_COUNTS.values()),27146)
    def test_guards(self):
        self.assertIn('"first_audit_pairs_must_be_excluded_from_next_validation":True',self.text)
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)
    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_SH_GATED_RANKING_V1")
if __name__=="__main__": unittest.main()
