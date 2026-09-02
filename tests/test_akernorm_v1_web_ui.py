from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PATCH = load("akernorm_web_patch_test", "src/86_patch_akerpass_akernorm_v1_ui.py")
VERIFY = load("akernorm_web_verify_test", "src/87_verify_akernorm_v1_web.py")


class AkerNormWebUiTests(unittest.TestCase):
    def test_ui_patch_is_lazy_all_skane_and_preserves_existing_panels(self):
        html = '<style></style><script>/* AKERMINNE_SKANE_UI_R2 */ function fieldPanel(p){return` ${akerminneSection(p)}\n <details><summary>Historik / referens</summary>`}</script>'
        mapping = {("Kristianstad" if i == 0 else "Skurup" if i == 1 else f"Kommun{i}"): f"data/akernorm/{i}.json" for i in range(33)}
        patched = PATCH.patch_html(html, mapping)
        self.assertEqual(patched.count(PATCH.MARKER), 2)
        self.assertIn("akernormToggle(this)", patched)
        self.assertIn("fetch(file", patched)
        self.assertIn("${akerminneSection(p)}\n ${akernormSection(p)}", patched)
        self.assertIn("Normal produktionsnivå – inte prognos för nästa skördeår", patched)
        self.assertIn("Skiftesanpassad ÅkerNorm: ej tillgänglig ännu", patched)
        self.assertIn("ÅkerNorm ej tillgänglig ännu", patched)
        self.assertIn("Officiell normskörd saknas i SKO", patched)
        self.assertIn("Årsberoende grödkod", patched)
        self.assertIn("Årsvisa grödnamn", patched)
        self.assertIn("@media(max-width:700px)", patched)

    def test_ui_patch_rejects_incomplete_mapping(self):
        html = '<style></style><script>/* AKERMINNE_SKANE_UI_R2 */ function fieldPanel(p){return` ${akerminneSection(p)}\n <details><summary>Historik / referens</summary>`}</script>'
        with self.assertRaisesRegex(RuntimeError, "33 municipalities"):
            PATCH.patch_html(html, {"Kristianstad": "data/akernorm/x.json"})

    def test_protected_inventory_excludes_only_index_and_akernorm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/akerminne").mkdir(parents=True)
            (root / "data/akernorm").mkdir(parents=True)
            (root / "index.html").write_text("patched", encoding="utf-8")
            (root / "municipalities.json").write_text("base", encoding="utf-8")
            (root / "data/akerminne/x.json").write_text("history", encoding="utf-8")
            (root / "data/akernorm/x.json").write_text("norm", encoding="utf-8")
            paths = [row["path"] for row in VERIFY.protected_inventory(root)]
            self.assertEqual(paths, ["data/akerminne/x.json", "municipalities.json"])


if __name__ == "__main__":
    unittest.main()
