from __future__ import annotations

import itertools
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

N = 11
Q = 3
RADIUS = 3
SPACE_SIZE = Q ** N
SYMBOLS = "1X2"

BASELINE_GENERATOR = np.array(
    [
        [1, 1, 1, 2, 1, 1, 0, 0, 0, 0, 0],
        [1, 0, 2, 1, 0, 0, 1, 0, 0, 0, 0],
        [1, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0],
        [1, 1, 1, 0, 0, 0, 0, 2, 0, 1, 0],
        [0, 1, 2, 2, 2, 0, 0, 0, 0, 0, 1],
    ],
    dtype=np.int8,
)

BASELINE_PARITY_CHECK = np.array(
    [
        [1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1],
        [0, 1, 0, 0, 2, 0, 0, 0, 2, 2, 1],
        [2, 1, 1, 0, 0, 2, 2, 0, 2, 2, 0],
        [2, 2, 2, 2, 1, 1, 1, 1, 2, 1, 0],
        [0, 2, 2, 2, 2, 2, 0, 0, 2, 2, 1],
        [0, 0, 1, 1, 2, 1, 0, 1, 1, 0, 1],
    ],
    dtype=np.int8,
)


def ball_offsets(n: int = N, radius: int = RADIUS) -> np.ndarray:
    rows: list[list[int]] = []
    for weight in range(radius + 1):
        for positions in itertools.combinations(range(n), weight):
            for values in itertools.product((1, 2), repeat=weight):
                row = [0] * n
                for pos, value in zip(positions, values):
                    row[pos] = value
                rows.append(row)
    return np.asarray(rows, dtype=np.int8)


BALL_OFFSETS = ball_offsets()
BALL_SIZE = int(BALL_OFFSETS.shape[0])


def baseline_code() -> np.ndarray:
    coeffs = np.asarray(list(itertools.product(range(Q), repeat=5)), dtype=np.int8)
    code = (coeffs @ BASELINE_GENERATOR) % Q
    assert code.shape == (243, N)
    return code


def vector_to_id(vector: Sequence[int]) -> int:
    return int(np.ravel_multi_index(tuple(int(x) for x in vector), (Q,) * N))


def id_to_vector(idx: int) -> np.ndarray:
    return np.asarray(np.unravel_index(int(idx), (Q,) * N), dtype=np.int8)


def coverage_ids(vector: Sequence[int]) -> np.ndarray:
    center = np.asarray(vector, dtype=np.int8)
    points = (BALL_OFFSETS + center) % Q
    return np.ravel_multi_index(points.T, (Q,) * N).astype(np.int32, copy=False)


def code_to_ids(code: np.ndarray) -> list[int]:
    return [vector_to_id(row) for row in np.asarray(code)]


def ids_to_code(ids: Iterable[int]) -> np.ndarray:
    return np.asarray([id_to_vector(i) for i in ids], dtype=np.int8)


def verify_code(code: np.ndarray) -> dict:
    code = np.asarray(code, dtype=np.int8)
    if code.ndim != 2 or code.shape[1] != N:
        raise ValueError(f"Expected shape (k,{N}), got {code.shape}")
    if np.any((code < 0) | (code >= Q)):
        raise ValueError("Code symbols must be in {0,1,2}")

    multiplicity = np.zeros(SPACE_SIZE, dtype=np.uint16)
    for row in code:
        multiplicity[coverage_ids(row)] += 1

    uncovered = np.flatnonzero(multiplicity == 0)
    histogram = np.bincount(multiplicity.astype(np.int64))
    return {
        "rows": int(code.shape[0]),
        "space_size": SPACE_SIZE,
        "ball_size": BALL_SIZE,
        "covered": int(SPACE_SIZE - uncovered.size),
        "uncovered": int(uncovered.size),
        "covering_radius_at_most_3": bool(uncovered.size == 0),
        "min_cover_multiplicity": int(multiplicity.min()),
        "max_cover_multiplicity": int(multiplicity.max()),
        "multiplicity_histogram": {int(i): int(v) for i, v in enumerate(histogram) if v},
        "first_uncovered_ids": [int(x) for x in uncovered[:20]],
        "first_uncovered_rows": [row_to_str(id_to_vector(int(x))) for x in uncovered[:20]],
    }


def row_to_str(row: Sequence[int]) -> str:
    return "".join(SYMBOLS[int(x)] for x in row)


def str_to_row(text: str) -> np.ndarray:
    text = text.strip().upper()
    if len(text) != N:
        raise ValueError(f"Expected {N} symbols, got {len(text)}: {text!r}")
    inv = {c: i for i, c in enumerate(SYMBOLS)}
    try:
        return np.asarray([inv[c] for c in text], dtype=np.int8)
    except KeyError as exc:
        raise ValueError("Rows must contain only 1, X, 2") from exc


def save_code(path: str | Path, code: np.ndarray, header: str | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if header:
        for line in header.splitlines():
            lines.append(f"# {line}")
    lines.extend(row_to_str(row) for row in np.asarray(code))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_code(path: str | Path) -> np.ndarray:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(str_to_row(line))
    if not rows:
        raise ValueError(f"No rows found in {path}")
    return np.asarray(rows, dtype=np.int8)


def syndrome_radius3_covered(H: np.ndarray) -> bool:
    H = np.asarray(H, dtype=np.int8) % Q
    syndromes = (BALL_OFFSETS @ H.T) % Q
    powers = Q ** np.arange(H.shape[0], dtype=np.int64)
    ids = syndromes @ powers
    return np.unique(ids).size == Q ** H.shape[0]
