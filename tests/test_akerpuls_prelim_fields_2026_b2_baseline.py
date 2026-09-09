import importlib.util, unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"src"/"113_akerpuls_prelim_fields_2026_b2_baseline.py"
spec=importlib.util.spec_from_file_location("b2",P); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class TestB2Baseline(unittest.TestCase):
    def test_deterministic_k2_separates_two_clouds(self):
        a=np.tile(np.array([[-2.0,-2.0]]),(40,1))+np.linspace(-.1,.1,40)[:,None]
        b=np.tile(np.array([[ 2.0, 2.0]]),(40,1))+np.linspace(-.1,.1,40)[:,None]
        fit=mod.deterministic_k2(np.vstack([a,b]))
        self.assertIsNotNone(fit)
        lab,cent,between,within=fit
        self.assertGreater(between,2.0)
        self.assertLess(within,0.3)
        self.assertEqual(len(set(lab[:40])),1)
        self.assertEqual(len(set(lab[40:])),1)

    def test_deterministic_k2_constant_is_none(self):
        self.assertIsNone(mod.deterministic_k2(np.ones((30,5))))

if __name__=="__main__": unittest.main()
