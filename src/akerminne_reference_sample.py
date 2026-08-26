from __future__ import annotations

import pandas as pd

CHECKLIST_COLUMNS = [
    "qa_category", "history_year", "current_field_id", "status",
    "coverage_display", "second_crop_share", "identity_match_confidence",
    "overlap_excess_raw",
]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=CHECKLIST_COLUMNS)


def _spread_pick(frame: pd.DataFrame, n: int, category: str, used_field_ids: set[str]) -> pd.DataFrame:
    """Deterministic time-spread selection with globally unique current fields."""
    if n <= 0 or frame.empty:
        return _empty()
    work = frame[~frame["current_field_id"].astype(str).isin(used_field_ids)].copy()
    if work.empty:
        return _empty()
    work["current_field_id"] = work["current_field_id"].astype(str)
    work["history_year"] = work["history_year"].astype(int)
    work = work.sort_values(["history_year", "current_field_id"], kind="mergesort")
    years = sorted(work["history_year"].unique().tolist())
    if len(years) <= n:
        targets = years
    elif n == 1:
        targets = [years[len(years) // 2]]
    else:
        idx = [round(i * (len(years) - 1) / (n - 1)) for i in range(n)]
        targets = [years[i] for i in idx]

    chosen_idx: list[int] = []
    chosen_fields: set[str] = set()
    for year in targets:
        cand = work[(work["history_year"] == year) & (~work["current_field_id"].isin(chosen_fields))]
        cand = cand[~cand["current_field_id"].isin(used_field_ids)]
        if len(cand):
            i = int(cand.index[0])
            chosen_idx.append(i)
            chosen_fields.add(str(work.loc[i, "current_field_id"]))
        if len(chosen_idx) >= n:
            break

    if len(chosen_idx) < n:
        for i, row in work.iterrows():
            fid = str(row["current_field_id"])
            if i in chosen_idx or fid in chosen_fields or fid in used_field_ids:
                continue
            chosen_idx.append(int(i))
            chosen_fields.add(fid)
            if len(chosen_idx) >= n:
                break

    picked = work.loc[chosen_idx].copy().head(n)
    if len(picked):
        picked.insert(0, "qa_category", category)
        used_field_ids.update(picked["current_field_id"].astype(str))
        return picked[CHECKLIST_COLUMNS].reset_index(drop=True)
    return _empty()


def _ranked_pick(frame: pd.DataFrame, n: int, category: str, used_field_ids: set[str], sort_cols: list[str], ascending: list[bool]) -> pd.DataFrame:
    if n <= 0 or frame.empty:
        return _empty()
    work = frame[~frame["current_field_id"].astype(str).isin(used_field_ids)].copy()
    if work.empty:
        return _empty()
    work["current_field_id"] = work["current_field_id"].astype(str)
    work = work.sort_values(sort_cols + ["history_year", "current_field_id"], ascending=ascending + [True, True], kind="mergesort")
    work = work.drop_duplicates("current_field_id", keep="first").head(n).copy()
    if len(work):
        work.insert(0, "qa_category", category)
        used_field_ids.update(work["current_field_id"].astype(str))
        return work[CHECKLIST_COLUMNS].reset_index(drop=True)
    return _empty()


def build_reference_checklist(classified: pd.DataFrame) -> pd.DataFrame:
    """Build 20 unique QA fields covering time, topology, all statuses and anomalies."""
    required = {
        "history_year", "current_field_id", "status", "coverage_display",
        "second_crop_share", "identity_match_confidence",
        "overlap_excess_raw", "material_overlap_anomaly",
    }
    missing = sorted(required - set(classified.columns))
    if missing:
        raise ValueError(f"classified missing columns: {missing}")

    h = classified[classified["history_year"].astype(int) < 2025].copy()
    used: set[str] = set()
    stable = h[
        (h["status"] == "SINGLE_CROP") &
        (h["identity_match_confidence"].isin(["direct_id", "one_to_one_strict"])) &
        (h["coverage_display"] >= .999) &
        (h["second_crop_share"] < .01) &
        (~h["material_overlap_anomaly"].astype(bool))
    ]
    topo = h[h["identity_match_confidence"].isin(["split", "merge"])]

    stable_pick = _spread_pick(stable, 5, "stable_simple", used)
    topo_pick = _spread_pick(topo, 5, "split_merge", used)

    status_parts = [
        _spread_pick(h[h["status"] == "MIXED_CROPS"], 2, "status_edge", used),
        _spread_pick(h[h["status"] == "PARTIAL_COVERAGE"], 2, "status_edge", used),
        _spread_pick(h[h["status"] == "NO_PUBLIC_MATCH"], 1, "status_edge", used),
    ]
    status_pick = pd.concat(status_parts, ignore_index=True)

    problem = h[
        h["material_overlap_anomaly"].astype(bool) |
        ((h["identity_match_confidence"].isin(["ambiguous", "unmatched"])) & (h["coverage_display"] >= .95))
    ]
    problem_pick = _ranked_pick(problem, 5, "problem", used, ["overlap_excess_raw"], [False])

    out = pd.concat([stable_pick, topo_pick, status_pick, problem_pick], ignore_index=True)
    if len(out) != 20:
        raise RuntimeError(f"reference checklist expected 20 rows, got {len(out)}")
    if out["current_field_id"].nunique() != 20:
        raise RuntimeError("reference checklist must contain 20 unique current fields")
    status_set = set(out["status"].astype(str))
    required_status = {"SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"}
    if not required_status.issubset(status_set):
        raise RuntimeError(f"reference checklist missing statuses: {sorted(required_status - status_set)}")
    if out["history_year"].nunique() < 5:
        raise RuntimeError("reference checklist does not span enough historical years")
    return out.reset_index(drop=True)
