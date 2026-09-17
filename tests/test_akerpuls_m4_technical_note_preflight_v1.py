import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "176_akerpuls_m4_technical_note_preflight_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_note", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4TechnicalNotePreflightV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_frozen_hashes_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_M0_FREEZE_SHA256, "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051")
        self.assertEqual(self.m.EXPECTED_VAX_ZIP_SHA256, "bb6be8437027573a525c8344c34ce372e49b867ec52a67f2466475d6cf60ce6e")
        self.assertEqual(self.m.EXPECTED_NOTE_SHA256, "6affc684ac76e334a7db5367cdee0c41f78c8d8420a5e303382d8e59af551311")

    def test_note_name_is_exact(self):
        self.assertEqual(self.m.NOTE_SUFFIX, "AkerPuls_Vaxtfoljdsprior_Technical_Note_V1.docx")

    def test_read_only_scope(self):
        low = self.text.lower()
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn("lightgbm.train(", low)
        self.assertNotIn("extractall(", low)
        self.assertIn('"zip_extracted": False', self.text)
        self.assertIn('"model_executed": False', self.text)
        self.assertIn('"m4_prediction_executed": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)

    def test_word_xml_is_read_from_nested_docx(self):
        self.assertIn('dz.read("word/document.xml")', self.text)
        self.assertIn("xml.etree", self.text)

    def test_status_stops_before_reproduction(self):
        self.assertEqual(self.m.STATUS, "PASS_M4_TECHNICAL_NOTE_TEXT_DISCOVERY_STOP")
        self.assertIn("REVIEW_M4_IMPLEMENTATION_DETAILS_THEN_BUILD_REPRODUCTION_GATE", self.text)


if __name__ == "__main__":
    unittest.main()
