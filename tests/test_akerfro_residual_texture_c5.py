#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.residual_texture_c5 import (
    forward_ilr,
    inverse_ilr,
    tensor_basis,
)


class TestAkerFroResidualTextureC5(unittest.TestCase):
    def test_ilr_roundtrip(self):
        clay = np.array([10.0, 20.0, 35.0])
        silt = np.array([30.0, 50.0, 25.0])
        sand = np.array([60.0, 30.0, 40.0])
        z1, z2 = forward_ilr(clay, silt, sand)
        c2, si2, sa2 = inverse_ilr(z1, z2)
        np.testing.assert_allclose(c2, clay, atol=1e-10)
        np.testing.assert_allclose(si2, silt, atol=1e-10)
        np.testing.assert_allclose(sa2, sand, atol=1e-10)

    def test_tensor_basis_shape(self):
        a = np.arange(12, dtype=float).reshape(3, 4)
        b = np.arange(15, dtype=float).reshape(3, 5)
        t = tensor_basis(a, b)
        self.assertEqual(t.shape, (3, 20))

    def test_inverse_ilr_sums_to_100(self):
        z1 = np.array([-1.0, 0.0, 1.0])
        z2 = np.array([0.5, 0.0, -0.5])
        c, s, a = inverse_ilr(z1, z2)
        np.testing.assert_allclose(c + s + a, 100.0, atol=1e-10)


if __name__ == "__main__":
    unittest.main()
