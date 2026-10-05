import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"201_akerpuls_merge_ab_independent_blind_validation_labels_freeze_v1.py"

def load():
    s=importlib.util.spec_from_file_location("ab_labels_freeze",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_frozen_parent_hashes(self):
        self.assertEqual(self.m.EXPECTED_VIEWER_FREEZE_SHA,"c7b7173314255074e0f34c9efbe35a9a464119fa4621ff924dbbbdd500f96fb1")
        self.assertEqual(self.m.EXPECTED_RANKING_FREEZE_SHA,"2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA,"fec621243d0b7cefc33d345be6ee361bd06cdba802a2d72b3925fa3257f7dc5f")

    def test_exact_labels_contract(self):
        self.assertEqual(self.m.EXPECTED_ROWS,100)
        self.assertEqual(self.m.ALLOWED_LABELS,["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"])

    def test_script_does_not_parse_blind_key(self):
        self.assertNotIn("pd.read_csv(BLIND_KEY",self.text)
        self.assertNotIn("read_text", "\n".join(line for line in self.text.splitlines() if "BLIND_KEY" in line and "EXPECTED_" not in line))
        self.assertIn('"blind_key_contents_revealed":False',self.text)

    def test_no_operational_mutation(self):
        self.assertIn('"fusion_executed":False',self.text)
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)
        self.assertIn('"geometry_mutated":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_V1")

if __name__=="__main__":
    unittest.main()
