from __future__ import annotations

import argparse
import itertools
import time

import numpy as np

from ternary_cover import BALL_OFFSETS, Q, syndrome_radius3_covered


def projective_points(m: int = 6) -> np.ndarray:
    points = []
    for tup in itertools.product(range(Q), repeat=m):
        if not any(tup):
            continue
        a = np.asarray(tup, dtype=np.int8)
        first = int(np.flatnonzero(a)[0])
        if a[first] == 2:
            a = (2 * a) % Q
        points.append(tuple(int(x) for x in a))
    return np.asarray(list(dict.fromkeys(points)), dtype=np.int8)


def coverage_score(H: np.ndarray) -> int:
    syndromes = (BALL_OFFSETS @ H.T) % Q
    powers = Q ** np.arange(H.shape[0], dtype=np.int64)
    return int(np.unique(syndromes @ powers).size)


def search(seed: int, steps: int) -> tuple[np.ndarray, int]:
    rng = np.random.default_rng(seed)
    points = projective_points(6)
    chosen = list(map(int, rng.choice(len(points), 11, replace=False)))
    H = points[chosen].T
    score = coverage_score(H)
    best_h, best_score = H.copy(), score
    for step in range(steps):
        j = int(rng.integers(11))
        candidate = int(rng.integers(len(points)))
        if candidate in chosen:
            continue
        old = chosen[j]
        chosen[j] = candidate
        H2 = points[chosen].T
        score2 = coverage_score(H2)
        if score2 >= score or rng.random() < 0.002:
            H, score = H2, score2
        else:
            chosen[j] = old
        if score > best_score:
            best_h, best_score = H.copy(), score
            print(f"step={step} covered_syndromes={best_score}/729")
        if best_score == 729:
            break
    return best_h, best_score


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--steps", type=int, default=100000)
    args = p.parse_args()
    t0 = time.perf_counter()
    H, score = search(args.seed, args.steps)
    print(f"\nBest syndrome coverage: {score}/729")
    print(H)
    print(f"Elapsed: {time.perf_counter() - t0:.3f}s")
    if score == 729:
        assert syndrome_radius3_covered(H)
        print("PASS: this parity-check matrix defines a 243-row radius-3 cover.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
