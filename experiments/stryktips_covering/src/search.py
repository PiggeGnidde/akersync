from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from ternary_cover import BALL_OFFSETS, N, Q, SPACE_SIZE, baseline_code, code_to_ids, coverage_ids, id_to_vector, ids_to_code, save_code, verify_code


class SearchEngine:
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.shape = (Q,) * N
        kernel = np.zeros(self.shape, dtype=np.float64)
        kernel[tuple(BALL_OFFSETS.T)] = 1.0
        self.kernel_fft = np.fft.fftn(kernel)
        self.cover_cache: dict[int, np.ndarray] = {}

    def cover(self, row_id: int) -> np.ndarray:
        row_id = int(row_id)
        hit = self.cover_cache.get(row_id)
        if hit is None:
            hit = coverage_ids(id_to_vector(row_id))
            self.cover_cache[row_id] = hit
        return hit

    def counts(self, rows: list[int]) -> np.ndarray:
        c = np.zeros(SPACE_SIZE, dtype=np.int16)
        for row_id in rows:
            c[self.cover(row_id)] += 1
        return c

    def exact_scores(self, counts: np.ndarray) -> np.ndarray:
        uncovered = (counts == 0).reshape(self.shape).astype(np.float64)
        score = np.fft.ifftn(np.fft.fftn(uncovered) * self.kernel_fft).real
        return np.rint(score).astype(np.int32, copy=False).ravel()

    def randomized_best_center(self, counts: np.ndarray, forbidden: set[int], top_pool: int = 128, rank_temperature: float = 4.0) -> int:
        scores = self.exact_scores(counts)
        pool_size = min(top_pool + len(forbidden), SPACE_SIZE)
        pool = np.argpartition(scores, -pool_size)[-pool_size:]
        pool = pool[np.argsort(scores[pool])[::-1]]
        valid = [int(x) for x in pool if int(x) not in forbidden][:top_pool]
        if not valid:
            raise RuntimeError("No candidate center available")
        k = len(valid)
        ranks = np.arange(k, dtype=np.float64)
        p = np.exp(-ranks / max(rank_temperature, 1e-6))
        p /= p.sum()
        return valid[int(self.rng.choice(k, p=p))]

    def destroy_repair(self, source_rows: list[int], target: int, destroy: int, top_pool: int, forbid_removed: bool) -> tuple[list[int], np.ndarray]:
        if target >= len(source_rows):
            raise ValueError("target must be smaller than source size for destroy/repair")
        destroy = max(len(source_rows) - target + 1, min(destroy, len(source_rows) - 1))
        removed_positions = set(map(int, self.rng.choice(len(source_rows), destroy, replace=False)))
        removed_ids = {source_rows[i] for i in removed_positions}
        rows = [r for i, r in enumerate(source_rows) if i not in removed_positions]
        counts = self.counts(rows)
        rowset = set(rows)
        while len(rows) < target:
            forbidden = set(rowset)
            if forbid_removed:
                forbidden.update(removed_ids)
            new = self.randomized_best_center(counts, forbidden, top_pool=top_pool)
            rows.append(new)
            rowset.add(new)
            counts[self.cover(new)] += 1
        return rows, counts

    def kick_fixed_k(self, rows: list[int], counts: np.ndarray, steps: int, candidate_sample: int = 96, removal_sample: int = 96, temperature: float = 40.0) -> tuple[list[int], np.ndarray, int]:
        rows = list(rows)
        rowset = set(rows)
        cur_uncovered = int(np.sum(counts == 0))
        best_rows = list(rows)
        best_counts = counts.copy()
        best_uncovered = cur_uncovered
        for step in range(steps):
            uncovered_ids = np.flatnonzero(counts == 0)
            if uncovered_ids.size == 0:
                return rows, counts, 0
            point_id = int(self.rng.choice(uncovered_ids))
            point = id_to_vector(point_id)
            centers = (point[None, :] - BALL_OFFSETS) % Q
            center_ids = np.ravel_multi_index(centers.T, self.shape)
            if center_ids.size > candidate_sample:
                center_ids = self.rng.choice(center_ids, candidate_sample, replace=False)
            best_gain = -1
            add_id = None
            for candidate in center_ids:
                candidate = int(candidate)
                if candidate in rowset:
                    continue
                gain = int(np.sum(counts[self.cover(candidate)] == 0))
                if gain > best_gain:
                    best_gain = gain
                    add_id = candidate
            if add_id is None:
                continue
            counts[self.cover(add_id)] += 1
            sample_n = min(removal_sample, len(rows))
            positions = self.rng.choice(len(rows), sample_n, replace=False)
            best_loss = 10**9
            remove_pos = None
            for pos in positions:
                pos = int(pos)
                loss = int(np.sum(counts[self.cover(rows[pos])] == 1))
                if loss < best_loss:
                    best_loss = loss
                    remove_pos = pos
            old_id = rows[int(remove_pos)]
            counts[self.cover(old_id)] -= 1
            new_uncovered = int(np.sum(counts == 0))
            temp = max(0.5, temperature * (1.0 - step / max(steps, 1)))
            accept = new_uncovered <= cur_uncovered or self.rng.random() < math.exp((cur_uncovered - new_uncovered) / temp)
            if accept:
                rowset.remove(old_id)
                rowset.add(add_id)
                rows[int(remove_pos)] = add_id
                cur_uncovered = new_uncovered
                if cur_uncovered < best_uncovered:
                    best_uncovered = cur_uncovered
                    best_rows = list(rows)
                    best_counts = counts.copy()
                    if best_uncovered == 0:
                        return best_rows, best_counts, 0
            else:
                counts[self.cover(old_id)] += 1
                counts[self.cover(add_id)] -= 1
        return best_rows, best_counts, best_uncovered


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=int, default=242)
    p.add_argument("--minutes", type=float, default=10.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--destroy-min", type=int, default=4)
    p.add_argument("--destroy-max", type=int, default=18)
    p.add_argument("--top-pool", type=int, default=32)
    p.add_argument("--kick-steps", type=int, default=250)
    p.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[1] / "solutions"))
    args = p.parse_args()
    if args.target >= 243:
        raise SystemExit("--target is intended for values below the 243-row baseline")
    engine = SearchEngine(args.seed)
    baseline_ids = code_to_ids(baseline_code())
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.minutes * 60.0
    restart = 0
    best_uncovered = SPACE_SIZE
    best_rows = None
    print(f"Searching for K_3(11,3) <= {args.target}; time budget={args.minutes:g} min; seed={args.seed}")
    while time.monotonic() < deadline:
        restart += 1
        destroy = int(engine.rng.integers(args.destroy_min, args.destroy_max + 1))
        forbid_removed = bool(engine.rng.integers(0, 2))
        rows, counts = engine.destroy_repair(baseline_ids, target=args.target, destroy=destroy, top_pool=args.top_pool, forbid_removed=forbid_removed)
        uncovered = int(np.sum(counts == 0))
        if args.kick_steps:
            rows, counts, uncovered = engine.kick_fixed_k(rows, counts, steps=args.kick_steps)
        if uncovered < best_uncovered:
            best_uncovered = uncovered
            best_rows = list(rows)
            partial = outdir / f"best_partial_k{args.target}.txt"
            save_code(partial, ids_to_code(best_rows), header=f"PARTIAL candidate, target={args.target}, uncovered={best_uncovered}, seed={args.seed}")
            print(f"restart={restart:5d} NEW BEST: uncovered={best_uncovered} destroy={destroy} forbid_removed={forbid_removed}")
        if uncovered == 0:
            solution = outdir / f"k{args.target}_FOUND.txt"
            save_code(solution, ids_to_code(rows), header=f"FOUND radius-3 ternary covering code with {args.target} rows; seed={args.seed}; restart={restart}")
            report = verify_code(ids_to_code(rows))
            print(json.dumps(report, indent=2))
            if not report["covering_radius_at_most_3"]:
                raise RuntimeError("Internal search/verifier disagreement")
            print(f"\nSUCCESS: verified solution written to {solution}")
            return 0
    print(f"\nNo full {args.target}-row cover found in this run. Best uncovered={best_uncovered} after {restart} restarts.")
    if best_rows is not None:
        print(f"Checkpoint: {outdir / f'best_partial_k{args.target}.txt'}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
