from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

VERSION = "akerswap-b123-sjobo-v0a"
RNG_SEED = 2601005

N_CASES = 24
MIN_CASE_FIELDS = 90
MAX_CASE_FIELDS = 180
HUB_SEP_MIN_M = 2500.0
HUB_SEP_MAX_M = 6500.0
CASE_RADIUS_M = 4500.0
MIN_FIELDS_PER_SIDE = 25

FRAG_LEVELS = (0.10, 0.20)
K_VALUES = (1, 2, 3)
SPARSE_BUDGETS = (0.01, 0.02, 0.05, 0.10, 0.20, 0.40)

AREA_TOL = 0.20
SCORE_TOL = 10.0
DRIFT_TOL = 10.0

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "akerswap_b123_sjobo_v0a"

A_GPKG_CANDIDATES = [
    ROOT / "work" / "akerswap_a_sjobo_v0a" / "sjobo_fields_core.gpkg",
    Path(r"C:\AkerSync-AkerAccess\work\akerswap_a_sjobo_v0a\sjobo_fields_core.gpkg"),
]
A_VERDICT_CANDIDATES = [
    ROOT / "work" / "akerswap_a_sjobo_v0a" / "verdict.json",
    Path(r"C:\AkerSync-AkerAccess\work\akerswap_a_sjobo_v0a\verdict.json"),
]


def first_existing(paths):
    for p in paths:
        if p.exists():
            return p
    return None


def pct(x):
    return f"{100.0 * float(x):.1f}%"


def load_a():
    vp = first_existing(A_VERDICT_CANDIDATES)
    gp = first_existing(A_GPKG_CANDIDATES)
    if vp is None or gp is None:
        raise SystemExit(
            "FEL: hittar inte ÅkerSwap A-output. Kör RUN_AKERSWAP_A.bat först."
        )
    verdict = json.loads(vp.read_text(encoding="utf-8"))
    if verdict.get("verdict") not in ("PASS", "MARGINAL"):
        raise SystemExit(
            f"FEL: ÅkerSwap A verdict={verdict.get('verdict')}; B ska inte köras."
        )
    g = gpd.read_file(gp)
    if g.crs is None:
        raise SystemExit("FEL: ÅkerSwap A GPKG saknar CRS.")
    g = g.to_crs(3006)
    need = {"field_id", "area_ha", "score", "drift", "geometry"}
    missing = need - set(g.columns)
    if missing:
        raise SystemExit(f"FEL: A-output saknar kolumner: {sorted(missing)}")
    g = g.dropna(subset=["area_ha", "score", "drift", "geometry"]).copy()
    g = g[~g.geometry.is_empty].reset_index(drop=True)
    return verdict, gp, g


def weighted_centers(points, weights, k, rng, max_iter=50):
    """Deterministic-ish weighted k-means centers used only as operational-hub proxies."""
    n = len(points)
    k = int(max(1, min(k, n)))
    w = np.asarray(weights, float)
    w = np.maximum(w, 1e-9)

    centroid = np.average(points, axis=0, weights=w)
    d0 = np.sum((points - centroid) ** 2, axis=1)
    centers = [points[int(np.argmax(d0 * w))].copy()]

    while len(centers) < k:
        c = np.vstack(centers)
        d2 = np.min(((points[:, None, :] - c[None, :, :]) ** 2).sum(axis=2), axis=1)
        idx = int(np.argmax(d2 * w))
        if any(np.allclose(points[idx], x) for x in centers):
            idx = int(rng.integers(0, n))
        centers.append(points[idx].copy())

    centers = np.vstack(centers)
    for _ in range(max_iter):
        d2 = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        lab = np.argmin(d2, axis=1)
        new = centers.copy()
        for j in range(k):
            m = lab == j
            if m.any():
                new[j] = np.average(points[m], axis=0, weights=w[m])
            else:
                far = np.min(d2, axis=1)
                new[j] = points[int(np.argmax(far * w))]
        if np.max(np.sqrt(((new - centers) ** 2).sum(axis=1))) < 1.0:
            centers = new
            break
        centers = new
    return centers


def distances_to_hubs(points, hubs):
    d = np.sqrt(((points[:, None, :] - hubs[None, :, :]) ** 2).sum(axis=2))
    return np.min(d, axis=1) / 1000.0


def logistics_cost(owner, area, dist_a, dist_b):
    return float(np.sum(area[owner == 0] * dist_a[owner == 0]) +
                 np.sum(area[owner == 1] * dist_b[owner == 1]))


def pair_candidates(owner, area, score, drift, dist_a, dist_b):
    ia = np.where(owner == 0)[0]
    ib = np.where(owner == 1)[0]
    rows = []
    for i in ia:
        aa = area[i]
        for j in ib:
            rel = abs(aa - area[j]) / max((aa + area[j]) / 2.0, 1e-9)
            if rel > AREA_TOL:
                continue
            if abs(score[i] - score[j]) > SCORE_TOL:
                continue
            if abs(drift[i] - drift[j]) > DRIFT_TOL:
                continue
            before = aa * dist_a[i] + area[j] * dist_b[j]
            after = aa * dist_b[i] + area[j] * dist_a[j]
            gain = before - after
            if gain <= 1e-9:
                continue
            changed_area = aa + area[j]
            rows.append((i, j, gain, changed_area, gain / changed_area))
    return rows


def greedy_select(rows, total_area, budget_frac=None):
    if budget_frac is None:
        ordered = sorted(rows, key=lambda x: x[2], reverse=True)
        budget = math.inf
    else:
        ordered = sorted(rows, key=lambda x: x[4], reverse=True)
        budget = float(total_area) * float(budget_frac)

    used_a, used_b = set(), set()
    gain = 0.0
    changed = 0.0
    selected = []

    for i, j, g, a, eff in ordered:
        if i in used_a or j in used_b:
            continue
        if changed + a > budget + 1e-9:
            continue
        used_a.add(i)
        used_b.add(j)
        gain += g
        changed += a
        selected.append((i, j, g, a, eff))
    return gain, changed, selected


def core_equiv(i, j, area, score, drift):
    rel = abs(area[i] - area[j]) / max((area[i] + area[j]) / 2.0, 1e-9)
    return (
        rel <= AREA_TOL
        and abs(score[i] - score[j]) <= SCORE_TOL
        and abs(drift[i] - drift[j]) <= DRIFT_TOL
    )


def make_fragmented(base_owner, target_frac, area, score, drift, rng):
    owner = base_owner.copy()
    total_area = float(area.sum())
    target = total_area * target_frac

    aidx = np.where(base_owner == 0)[0]
    bidx = np.where(base_owner == 1)[0]
    candidates = []
    for i in aidx:
        for j in bidx:
            if core_equiv(i, j, area, score, drift):
                candidates.append((i, j))
    rng.shuffle(candidates)

    changed = 0.0
    used = set()
    chosen = []
    for i, j in candidates:
        if i in used or j in used:
            continue
        ca = area[i] + area[j]
        if changed + ca > target * 1.10 and changed >= target * 0.75:
            continue
        owner[i], owner[j] = 1, 0
        used.add(i)
        used.add(j)
        chosen.append((i, j))
        changed += ca
        if changed >= target:
            break

    return owner, changed / total_area, chosen


def generate_cases(g, rng):
    points = np.column_stack([g.geometry.centroid.x.to_numpy(),
                              g.geometry.centroid.y.to_numpy()])
    tree = cKDTree(points)
    order = rng.permutation(len(g))
    cases = []
    used_centers = []

    for i in order:
        if len(cases) >= N_CASES:
            break

        js = tree.query_ball_point(points[i], HUB_SEP_MAX_M)
        js = [j for j in js if j != i and HUB_SEP_MIN_M <= np.linalg.norm(points[j] - points[i]) <= HUB_SEP_MAX_M]
        if not js:
            continue
        rng.shuffle(js)

        accepted = False
        for j in js[:30]:
            mid = (points[i] + points[j]) / 2.0
            if used_centers and min(np.linalg.norm(mid - c) for c in used_centers) < 1800.0:
                continue

            near_i = np.linalg.norm(points - points[i], axis=1)
            near_j = np.linalg.norm(points - points[j], axis=1)
            dmin = np.minimum(near_i, near_j)
            idx = np.where(dmin <= CASE_RADIUS_M)[0]
            if len(idx) < MIN_CASE_FIELDS:
                continue
            idx = idx[np.argsort(dmin[idx])[:MAX_CASE_FIELDS]]
            base = (near_j[idx] < near_i[idx]).astype(np.int8)

            if min(np.sum(base == 0), np.sum(base == 1)) < MIN_FIELDS_PER_SIDE:
                continue

            cases.append({
                "case_id": f"S{len(cases)+1:02d}",
                "indices": idx,
                "seed_a": i,
                "seed_b": j,
                "seed_sep_km": float(np.linalg.norm(points[i] - points[j]) / 1000.0),
                "base_owner": base,
            })
            used_centers.append(mid)
            accepted = True
            break

        if accepted:
            continue

    if len(cases) < 12:
        raise SystemExit(f"FEL: kunde bara skapa {len(cases)} syntetiska lokala cases.")
    return cases, points


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(RNG_SEED)

    print("=" * 96)
    print("ÅkerSwap B1+B2+B3 - sammanhållen falsifieringssprint")
    print("Version:", VERSION)
    print("=" * 96)

    a_verdict, a_gpkg, g = load_a()
    print("A verdict:", a_verdict["verdict"])
    print("A fields :", len(g))
    print("A source :", a_gpkg)

    cases, all_points = generate_cases(g, rng)
    print("Synthetic local cases:", len(cases))

    rows = []
    sparse_rows = []
    assignment_rows = []

    for ci, case in enumerate(cases, 1):
        idx = case["indices"]
        sub = g.iloc[idx].copy().reset_index(drop=True)
        points = np.column_stack([sub.geometry.centroid.x.to_numpy(),
                                  sub.geometry.centroid.y.to_numpy()])
        area = sub.area_ha.to_numpy(float)
        score = sub.score.to_numpy(float)
        drift = sub.drift.to_numpy(float)
        base_owner = case["base_owner"].copy()

        scenarios = [("CONTROL", base_owner, 0.0, [])]
        for frag in FRAG_LEVELS:
            owner, actual, injected = make_fragmented(
                base_owner, frag, area, score, drift,
                np.random.default_rng(RNG_SEED + 1000 * ci + int(frag * 100))
            )
            scenarios.append((f"FRAG{int(frag*100)}", owner, actual, injected))

        print(f"  {case['case_id']}: n={len(sub):3d}, seedsep={case['seed_sep_km']:.2f} km")

        for scenario, owner, actual_frag, injected in scenarios:
            for local_i, fid in enumerate(sub.field_id.astype(str)):
                assignment_rows.append({
                    "case_id": case["case_id"],
                    "scenario": scenario,
                    "field_id": fid,
                    "owner": int(owner[local_i]),
                    "area_ha": float(area[local_i]),
                    "score": float(score[local_i]),
                    "drift": float(drift[local_i]),
                })

            for k in K_VALUES:
                hubs_a = weighted_centers(
                    points[owner == 0], area[owner == 0], k,
                    np.random.default_rng(RNG_SEED + 10000 * ci + 100 * k)
                )
                hubs_b = weighted_centers(
                    points[owner == 1], area[owner == 1], k,
                    np.random.default_rng(RNG_SEED + 20000 * ci + 100 * k)
                )
                dist_a = distances_to_hubs(points, hubs_a)
                dist_b = distances_to_hubs(points, hubs_b)
                before = logistics_cost(owner, area, dist_a, dist_b)

                cand = pair_candidates(owner, area, score, drift, dist_a, dist_b)
                full_gain, full_changed, selected = greedy_select(cand, float(area.sum()), None)
                gain_pct = full_gain / before if before > 0 else 0.0

                rows.append({
                    "case_id": case["case_id"],
                    "scenario": scenario,
                    "k_hubs": k,
                    "n_fields": len(sub),
                    "seed_sep_km": case["seed_sep_km"],
                    "actual_injected_swap_fraction": actual_frag,
                    "baseline_area_km": before,
                    "candidate_pairs": len(cand),
                    "selected_swaps": len(selected),
                    "full_greedy_gain_area_km": full_gain,
                    "full_greedy_gain_pct": gain_pct,
                    "full_changed_area_fraction": full_changed / float(area.sum()),
                })

                for budget in SPARSE_BUDGETS:
                    gg, ch, sel = greedy_select(cand, float(area.sum()), budget)
                    sparse_rows.append({
                        "case_id": case["case_id"],
                        "scenario": scenario,
                        "k_hubs": k,
                        "budget_fraction": budget,
                        "gain_area_km": gg,
                        "gain_pct_of_baseline": gg / before if before > 0 else 0.0,
                        "changed_area_fraction": ch / float(area.sum()),
                        "captured_fraction_of_full_gain": gg / full_gain if full_gain > 0 else 0.0,
                        "n_swaps": len(sel),
                    })

    res = pd.DataFrame(rows)
    sp = pd.DataFrame(sparse_rows)
    ass = pd.DataFrame(assignment_rows)

    res.to_csv(OUT / "b123_case_results.csv", index=False, encoding="utf-8-sig")
    sp.to_csv(OUT / "b3_sparse_curves.csv", index=False, encoding="utf-8-sig")
    ass.to_parquet(OUT / "synthetic_case_assignments.parquet", index=False)

    summary = []
    for scenario in ("CONTROL", "FRAG10", "FRAG20"):
        for k in K_VALUES:
            q = res[(res.scenario == scenario) & (res.k_hubs == k)]
            summary.append({
                "scenario": scenario,
                "k_hubs": k,
                "n_cases": len(q),
                "median_gain_pct": float(q.full_greedy_gain_pct.median()),
                "p25_gain_pct": float(q.full_greedy_gain_pct.quantile(0.25)),
                "p75_gain_pct": float(q.full_greedy_gain_pct.quantile(0.75)),
                "median_changed_area_fraction": float(q.full_changed_area_fraction.median()),
                "median_candidate_pairs": float(q.candidate_pairs.median()),
            })
    summ = pd.DataFrame(summary)
    summ.to_csv(OUT / "b12_summary.csv", index=False, encoding="utf-8-sig")

    sparse_summary = []
    for scenario in ("FRAG10", "FRAG20"):
        for k in K_VALUES:
            for budget in SPARSE_BUDGETS:
                q = sp[
                    (sp.scenario == scenario)
                    & (sp.k_hubs == k)
                    & np.isclose(sp.budget_fraction, budget)
                ]
                sparse_summary.append({
                    "scenario": scenario,
                    "k_hubs": k,
                    "budget_fraction": budget,
                    "median_captured_fraction_of_full_gain": float(q.captured_fraction_of_full_gain.median()),
                    "median_gain_pct_of_baseline": float(q.gain_pct_of_baseline.median()),
                    "median_actual_changed_area_fraction": float(q.changed_area_fraction.median()),
                })
    ssum = pd.DataFrame(sparse_summary)
    ssum.to_csv(OUT / "b3_sparse_summary.csv", index=False, encoding="utf-8-sig")

    def med_gain(scenario, k):
        q = summ[(summ.scenario == scenario) & (summ.k_hubs == k)]
        return float(q.iloc[0].median_gain_pct)

    def sparse_capture(scenario, k, budget):
        q = ssum[
            (ssum.scenario == scenario)
            & (ssum.k_hubs == k)
            & np.isclose(ssum.budget_fraction, budget)
        ]
        return float(q.iloc[0].median_captured_fraction_of_full_gain)

    control1 = med_gain("CONTROL", 1)
    frag10_1 = med_gain("FRAG10", 1)
    frag20_1 = med_gain("FRAG20", 1)
    frag20_2 = med_gain("FRAG20", 2)
    frag20_3 = med_gain("FRAG20", 3)
    survival2 = frag20_2 / frag20_1 if frag20_1 > 0 else 0.0
    survival3 = frag20_3 / frag20_1 if frag20_1 > 0 else 0.0
    capture5_k2 = sparse_capture("FRAG20", 2, 0.05)
    capture10_k2 = sparse_capture("FRAG20", 2, 0.10)

    # Transparent engineering verdict, not a claim about real ownership patterns.
    sanity_ok = control1 <= 0.05
    multi_hub_survives = frag20_2 >= 0.03 and survival2 >= 0.25
    sparse_useful = capture10_k2 >= 0.40

    if sanity_ok and multi_hub_survives and sparse_useful:
        verdict = "SUPPORTED"
    elif multi_hub_survives or sparse_useful:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    result = {
        "version": VERSION,
        "a_verdict": a_verdict["verdict"],
        "n_cases": len(cases),
        "b_verdict": verdict,
        "control_single_hub_median_gain_pct": control1,
        "frag10_single_hub_median_gain_pct": frag10_1,
        "frag20_single_hub_median_gain_pct": frag20_1,
        "frag20_two_hub_median_gain_pct": frag20_2,
        "frag20_three_hub_median_gain_pct": frag20_3,
        "frag20_two_hub_survival_ratio": survival2,
        "frag20_three_hub_survival_ratio": survival3,
        "frag20_two_hub_capture_at_5pct": capture5_k2,
        "frag20_two_hub_capture_at_10pct": capture10_k2,
        "caveat": (
            "Synthetic fragmented portfolios test the mechanism, not prevalence of fragmentation "
            "among real Swedish farm businesses."
        ),
    }
    (OUT / "verdict.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    md = [
        "# ÅkerSwap STOPPUNKT B1+B2+B3",
        "",
        f"Version: {VERSION}",
        f"A verdict: {a_verdict['verdict']}",
        f"B technical verdict: {verdict}",
        "",
        "## Vad testades",
        "",
        f"- {len(cases)} lokala Sjöbo-cases byggda automatiskt från riktiga fält.",
        "- CONTROL: geografiskt klustrad tvåbrukar-baseline.",
        "- FRAG10/FRAG20: 10/20 % ungefär likvärdig areal korsbyttes syntetiskt.",
        "- B1: single-hub greedy pair-swap lower bound.",
        "- B2: samma test med 2 och 3 infererade operationella hubbar per brukare.",
        "- B3: swap-budget 1/2/5/10/20/40 % av total areal.",
        "",
        "## Huvudresultat",
        "",
        f"- CONTROL k=1 median gain: {pct(control1)}",
        f"- FRAG10 k=1 median gain: {pct(frag10_1)}",
        f"- FRAG20 k=1 median gain: {pct(frag20_1)}",
        f"- FRAG20 k=2 median gain: {pct(frag20_2)}",
        f"- FRAG20 k=3 median gain: {pct(frag20_3)}",
        f"- k=2 survival vs k=1: {pct(survival2)}",
        f"- k=3 survival vs k=1: {pct(survival3)}",
        f"- FRAG20 k=2: 5 % swap-budget captures median {pct(capture5_k2)} of full greedy gain.",
        f"- FRAG20 k=2: 10 % swap-budget captures median {pct(capture10_k2)} of full greedy gain.",
        "",
        "## Tolkning / begränsning",
        "",
        "Detta är en falsifieringssprint av mekanismen, inte en skattning av hur fragmenterade riktiga gårdar är.",
        "Brukaridentitet saknas; FRAG10/20 är syntetiska men byggs av verkliga Sjöbo-skiften och bevarar",
        "ÅkerSwap CORE-likvärdighet (areal, ÅkerScore, ÅkerDrift) i den injicerade korsningen.",
        "Greedy pair-swap är en enkel lower-bound solver, inte global MILP-optimum.",
        "",
        "## STOPP",
        "",
        "Ingen webb och ingen riktig pilot byggs här. Resultatet ska tillbaka till projektledarchatten för prioritering.",
    ]
    (OUT / "STOPPUNKT_B123.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("")
    print("=" * 96)
    print("AKERSWAP_B123_RESULT")
    print("B_VERDICT=" + verdict)
    print(f"CASES={len(cases)}")
    print("CONTROL_K1_MEDIAN_GAIN=" + pct(control1))
    print("FRAG10_K1_MEDIAN_GAIN=" + pct(frag10_1))
    print("FRAG20_K1_MEDIAN_GAIN=" + pct(frag20_1))
    print("FRAG20_K2_MEDIAN_GAIN=" + pct(frag20_2))
    print("FRAG20_K3_MEDIAN_GAIN=" + pct(frag20_3))
    print("FRAG20_K2_SURVIVAL=" + pct(survival2))
    print("FRAG20_K3_SURVIVAL=" + pct(survival3))
    print("FRAG20_K2_CAPTURE_5PCT=" + pct(capture5_k2))
    print("FRAG20_K2_CAPTURE_10PCT=" + pct(capture10_k2))
    print("OUT=" + str(OUT))
    print("=" * 96)


if __name__ == "__main__":
    run()
