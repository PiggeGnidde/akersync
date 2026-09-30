#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from analysis.akeraccess_v0a.prepare_review_b2 import (
    is_pasture_name,
    map_legacy_label,
)


class TestAkerAccessReviewB2(unittest.TestCase):
    def test_pasture_name(self):
        tokens = ["betesmark", "slåtteräng"]
        self.assertTrue(is_pasture_name("Betesmark", tokens))
        self.assertTrue(is_pasture_name("Betesmark och slåtteräng", tokens))
        self.assertFalse(is_pasture_name("Vall", tokens))
        self.assertFalse(is_pasture_name("Vete (höst)", tokens))

    def test_legacy_correct_plain_maps_rank1(self):
        self.assertEqual(
            map_legacy_label("CORRECT_ENTRY", ""),
            ("RANK1_PLAUSIBLE", "legacy_correct"),
        )

    def test_legacy_correct_alt_note(self):
        label, basis = map_legacy_label(
            "CORRECT_ENTRY", "Cyan är inte bästa väg, jag hävdar den lila"
        )
        self.assertEqual(label, "OTHER_CANDIDATE_BETTER")
        self.assertIn("alternative", basis)

    def test_legacy_missed(self):
        self.assertEqual(
            map_legacy_label("MISSED_ENTRY", "syns sliten mark"),
            ("ACCESS_VISIBLE_NOT_CANDIDATE", "legacy_missed"),
        )

    def test_greenhouse_exclusion(self):
        self.assertEqual(
            map_legacy_label("WRONG_ENTRY", "Åkern har växthus"),
            ("EXCLUDE_OTHER", "legacy_greenhouse_note"),
        )


if __name__ == "__main__":
    unittest.main()
