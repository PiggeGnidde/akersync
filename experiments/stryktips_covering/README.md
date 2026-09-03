# Stryktips / ternary covering code experiment

We want the smallest reduced system for **11 full covers + 2 correct spikes**
that guarantees at least **10 correct of 13**.

For the 11 full-cover matches, a ticket row may differ from the true result in
at most 3 positions. The mathematical problem is therefore

\[
K_3(11,3)
\]

over the ternary Hamming space `{1,X,2}^11`.

There are `3^11 = 177147` possible outcomes. A radius-3 ball contains

`1 + C(11,1)*2 + C(11,2)*2^2 + C(11,3)*2^3 = 1563`

outcomes.

Published tables give the classical bounds `117 <= K_3(11,3) <= 243`.
This experiment starts from a machine-verified 243-row construction and tries
to lower the upper bound.

## What is included

- `solutions/k243_linear.txt` — frozen 243-row baseline, in `1X2` notation.
- `src/verify.py` — exhaustive verifier over all 177147 outcomes.
- `src/search.py` — nonlinear fixed-cardinality heuristic for 242, 241, ...
- `src/find_linear_baseline.py` — independently searches for a 243-row linear
  construction through a 6x11 ternary parity-check matrix.
- `tests/` — regression tests.
- Windows `.bat` launchers.

The verifier is deliberately independent of the search objective: a claimed
solution only passes when every one of the 177147 outcomes is explicitly
covered by a radius-3 ball.

## Windows quick start

From CMD:

```bat
cd /d C:\YOUR_PATH\akersync
git fetch origin
git switch feature/stryktips-covering-v1
cd experiments\stryktips_covering
RUN_TESTS.bat
VERIFY_SOLUTION.bat
```

Expected verification headline:

```text
PASS: 243 rows cover all 177147 outcomes within Hamming distance <= 3.
```

## Try to beat 243

Ten-minute run:

```bat
RUN_SEARCH_242.bat
```

Longer/custom run:

```bat
.venv\Scripts\activate
python src\search.py --target 242 --minutes 120 --seed 17
```

The search writes the best incomplete candidate to
`solutions/best_partial_k242.txt`. If it finds a true cover, it writes
`solutions/k242_FOUND.txt` and immediately runs the exact verifier.

Different seeds can be run in separate terminals or separate machines.

## Reproduce a linear 243 construction

```bat
.venv\Scripts\activate
python src\find_linear_baseline.py --seed 0 --steps 100000
```

This searches for 11 projective columns in `F_3^6` such that every one of the
729 syndromes is representable by an error vector of weight at most 3. Such a
parity-check matrix defines an `[11,5]_3` code: exactly `3^5 = 243` rows with
covering radius at most 3.

## Why the search uses FFT

The literal set-cover matrix would have 177147 candidate rows and 177147
outcome constraints. A row covers 1563 outcomes.

For a current set of uncovered outcomes, the score of **every** possible new
row is a convolution on the group `(Z_3)^11`. `src/search.py` evaluates that
convolution using an 11-dimensional FFT on an array with only 177147 cells.
That gives an exact all-candidate greedy score without storing the huge
incidence matrix.

## Stryktips interpretation

The file rows contain only the 11 helgarderade matches. Append the two chosen
spikes when constructing the actual 13-match ticket. The guarantee is
conditional on both spikes being correct:

- at most 3 misses among the 11 covered matches,
- hence at least 8/11 there,
- plus 2/2 spikes,
- hence at least 10/13 overall.

## Status

V1 establishes and independently verifies the known 243-row upper-bound
construction. The sub-243 search is heuristic; failure to find 242 does **not**
prove that 242 is impossible.
