import importlib.util, unittest
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"src"/"115_akerpuls_prelim_fields_2026_b4_diagnostic.py"
spec=importlib.util.spec_from_file_location("b4",P); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class TestB4Morphology(unittest.TestCase):
    def test_bisecting_split_touches_outer(self):
        interior=np.zeros((20,30),dtype=bool); interior[2:18,2:28]=True
        c0=interior.copy(); c0[:,15:]=False
        c1=interior.copy(); c1[:,:15]=False
        metrics,_=mod.morphology_metrics(c0,c1,interior,interior,ndi,10)
        self.assertTrue(metrics["both_children_touch_outer"])
        self.assertGreaterEqual(metrics["interface_pixels"],10)
        self.assertGreaterEqual(metrics["interface_outer_endpoint_components"],2)

    def test_internal_island_fails_outer_touch(self):
        interior=np.zeros((20,30),dtype=bool); interior[2:18,2:28]=True
        c0=np.zeros_like(interior); c0[7:13,10:18]=True
        c1=interior & ~c0
        metrics,_=mod.morphology_metrics(c0,c1,interior,interior,ndi,10)
        self.assertFalse(metrics["both_children_touch_outer"])
        self.assertFalse(metrics["child0_touches_outer"])

    def test_anchor_summary(self):
        keys=["a","b","c"]; passed={"a":True,"b":False,"c":True}; anchors={"a":"CLEAR","b":"FALSE"}
        s=mod.summarize_anchor_rule(keys,passed,anchors,"CLEAR","FALSE")
        self.assertEqual(s["anchor_positive_retained"],1)
        self.assertEqual(s["anchor_negative_rejected"],1)

if __name__=="__main__": unittest.main()
