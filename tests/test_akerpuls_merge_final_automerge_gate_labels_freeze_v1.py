import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"209_akerpuls_merge_final_automerge_gate_labels_freeze_v1.py"

def load():
    s=importlib.util.spec_from_file_location("fglabels",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_parent_identity(self):
        self.assertEqual(self.m.EXPECTED_VIEWER_FREEZE_SHA,"5d2c7be7be353fdcba39ff10f289a4cb0484793c768622e7df6f0bcae951d43e")
        self.assertEqual(self.m.EXPECTED_SAMPLE_POPULATION_SHA,"2fae45bc19ace2c4a4aa00477e0fa0072f6c8be86b970649e85a8ef8a9849244")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA,"00ec0b06dd5b0d909b535b8694d8c6959fc9d3f7ad0e421dddf1facf24e8dfb3")

    def test_rows(self):
        self.assertEqual(self.m.EXPECTED_ROWS,80)

    def test_no_reveal_or_mutation(self):
        self.assertIn('"blind_key_contents_revealed":False',self.text)
        self.assertIn('"thresholds_changed":False',self.text)
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"geometry_mutated":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_LABELS_V1")

if __name__=="__main__":
    unittest.main()
