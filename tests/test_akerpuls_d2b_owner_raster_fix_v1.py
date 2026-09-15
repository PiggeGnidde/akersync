import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "156_akerpuls_d2b_owner_raster_fix_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d2b_owner_fix", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2BOwnerRasterFixV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.src = cls.m.patched_source()

    def test_patch_compiles(self):
        compile(self.src, str(self.m.BASE), "exec")

    def test_uses_all_d2a_owner_fields_not_candidate_only_geometries(self):
        self.assertIn("owner_ids = sorted(part.loc[part.analysis_cell_id.astype(str).eq(cid)", self.src)
        self.assertIn("owner_geoms = [g.geometry.iloc[p] for p in owner_pos]", self.src)
        self.assertIn("read_owner_cell_arrays(datasets, band_maps, features, owner_geoms)", self.src)
        self.assertNotIn("cand_geoms = [g.geometry.iloc[p] for p in cand_pos]", self.src)

    def test_candidate_masks_use_exact_d2a_owner_label_map(self):
        self.assertIn("owner_label_by_id = {fid: i + 1 for i, fid in enumerate(owner_ids)}", self.src)
        self.assertIn("fm = labels == int(owner_label_by_id[fid])", self.src)
        self.assertNotIn("for local_pos, fid in enumerate(candidate_ids, 1):", self.src)

    def test_cache_is_bound_to_full_owner_population(self):
        self.assertIn('"candidate_ids": candidate_ids, "owner_ids": owner_ids', self.src)

    def test_scientific_contract_text_is_unchanged(self):
        # The fix is implementation-only: frozen TRUE-LOO and fusion machinery
        # stays in the historical D2B source and is not redeclared here.
        wrapper = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("0.781017", wrapper)
        self.assertNotIn("0.843688", wrapper)
        self.assertNotIn("minimum_each_child_dice_each_omission", wrapper)
        self.assertNotIn("prototype_p_splitmerge_2026", wrapper)

    def test_no_network_or_geometry_mutation_path_added(self):
        wrapper = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("boto3", wrapper)
        self.assertNotIn("requests.", wrapper)
        self.assertNotIn("urllib", wrapper)
        self.assertNotIn("to_file(", wrapper)


if __name__ == "__main__":
    unittest.main()
