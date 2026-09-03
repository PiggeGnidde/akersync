from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ternary_cover import BALL_SIZE, BASELINE_GENERATOR, BASELINE_PARITY_CHECK, SPACE_SIZE, baseline_code, row_to_str, str_to_row, verify_code


def test_ball_size():
    assert BALL_SIZE == 1563
    assert SPACE_SIZE == 177147


def test_generator_parity_check():
    assert np.all((BASELINE_PARITY_CHECK @ BASELINE_GENERATOR.T) % 3 == 0)


def test_row_round_trip():
    text = "1X21X21X21X"
    assert row_to_str(str_to_row(text)) == text


def test_baseline_exact_cover():
    code = baseline_code()
    assert code.shape == (243, 11)
    assert np.unique(code, axis=0).shape[0] == 243
    report = verify_code(code)
    assert report["uncovered"] == 0
    assert report["covering_radius_at_most_3"]
