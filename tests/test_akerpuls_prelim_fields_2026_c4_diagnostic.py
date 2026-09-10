import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "124_akerpuls_prelim_fields_2026_c4_high_confidence_diagnostic.py"


def load_module():
    spec = importlib.util.spec_from_file_location("c4diag", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestC4Contract(unittest.TestCase):
    def test_candidate_rule_is_unchanged_and_high_conf_is_not_frozen(self):
        c4 = json.loads((ROOT / "config" / "akerpuls_prelim_fields_2026_c4.json").read_text(encoding="utf-8"))
        c2 = json.loads((ROOT / "config" / "akerpuls_prelim_fields_2026_c2.json").read_text(encoding="utf-8"))
        self.assertEqual(c4["split_candidate_rule_unchanged"], c2["locked_split_rule"])
        self.assertTrue(c4["high_confidence_candidate"]["requires_existing_locked_split_candidate"])
        self.assertEqual(c4["high_confidence_candidate"]["minimum_separation_ratio"], 4.0)
        self.assertEqual(c4["high_confidence_candidate"]["status"], "POST_HOC_DEVELOPMENT_CANDIDATE_NOT_VALIDATED")
        self.assertFalse(c4["guards"]["threshold_freeze"])
        self.assertFalse(c4["guards"]["full_skane"])
        labels = [x["visual_label"] for x in c4["c3_development_labels"]]
        self.assertEqual(len(labels), 20)
        self.assertEqual(labels.count("TYDLIG"), 5)
        self.assertEqual(labels.count("MÖJLIG"), 5)
        self.assertEqual(labels.count("TVEKSAM"), 1)
        self.assertEqual(labels.count("FALSK"), 9)

    def test_largest_component_outer_touch_catches_border_speck(self):
        from scipy import ndimage as ndi
        c4 = load_module()
        interior = np.zeros((24, 24), dtype=bool)
        interior[2:22, 2:22] = True

        # Child 1 is mostly a central island, plus a tiny disconnected border speck.
        # The old "any component touches outer" test passes; the largest-component
        # topology test must reject it.
        child1 = np.zeros_like(interior)
        child1[8:15, 8:15] = True
        child1[2, 10] = True
        child0 = interior & ~child1
        iface = (child0 & ndi.binary_dilation(child1, structure=np.ones((3, 3), dtype=bool))) | (
            child1 & ndi.binary_dilation(child0, structure=np.ones((3, 3), dtype=bool))
        )
        m = c4.topology_metrics(child0, child1, interior, iface, ndi)
        self.assertTrue(m["child1_any_component_touches_outer"])
        self.assertFalse(m["largest_child1_touches_outer"])
        self.assertFalse(m["both_largest_children_touch_outer"])
        self.assertGreater(m["child1_components"], 1)

    def test_clean_bisecting_split_has_largest_children_on_outer_boundary(self):
        from scipy import ndimage as ndi
        c4 = load_module()
        interior = np.zeros((24, 24), dtype=bool)
        interior[2:22, 2:22] = True
        child0 = np.zeros_like(interior)
        child0[2:22, 2:12] = True
        child1 = interior & ~child0
        iface = (child0 & ndi.binary_dilation(child1, structure=np.ones((3, 3), dtype=bool))) | (
            child1 & ndi.binary_dilation(child0, structure=np.ones((3, 3), dtype=bool))
        )
        m = c4.topology_metrics(child0, child1, interior, iface, ndi)
        self.assertTrue(m["both_largest_children_touch_outer"])
        self.assertEqual(m["component_count_total"], 2)
        self.assertEqual(m["child_holes_total"], 0)
        self.assertGreaterEqual(m["interface_outer_endpoint_components"], 2)


if __name__ == "__main__":
    unittest.main()
