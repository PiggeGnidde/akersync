#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2B implementation-only owner-rasterization fix.

The first D2B execution exposed a reproducibility guard on one field where the
FULL4 separation reconstructed from a candidate-only rasterization differed from
the already frozen D2A value. D2A rasterized *all* owner fields in a cell before
extracting any one field. Candidate-only rasterization can change pixel
ownership where 2025 polygons touch/overlap at raster scale.

This wrapper applies a narrowly scoped source patch in memory so D2B uses the
same all-owner-field rasterization/order as D2A, while leaving the D2B scientific
contract, TRUE-LOO thresholds, history prior, fusion artifact and P90/P95 tiers
unchanged. The historical failed implementation remains intact in src/155_....

The wrapper also binds the per-cell cache key to this file via the patched
module's THIS global, intentionally invalidating cells produced by the failed
candidate-only implementation.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src" / "155_akerpuls_d2b_full_skane_true_loo_fusion_v1.py"
THIS = Path(__file__).resolve()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"D2B owner-raster fix expected exactly one {label} match, got {n}")
    return text.replace(old, new, 1)


def patched_source() -> str:
    text = BASE.read_text(encoding="utf-8")

    text = _replace_once(
        text,
        "def process_cell_true_loo(cid: str, candidates: pd.DataFrame, candidate_ids: list[str],\n"
        "                          cubes, valids, labels, variants, b2, b2cfg, tloo, tlcfg) -> pd.DataFrame:\n",
        "def process_cell_true_loo(cid: str, candidates: pd.DataFrame, candidate_ids: list[str],\n"
        "                          cubes, valids, labels, owner_label_by_id, variants, b2, b2cfg, tloo, tlcfg) -> pd.DataFrame:\n",
        "process_cell_true_loo signature",
    )

    text = _replace_once(
        text,
        "    for local_pos, fid in enumerate(candidate_ids, 1):\n"
        "        rec = cindex.loc[fid]\n"
        "        fm = labels == local_pos\n",
        "    for fid in candidate_ids:\n"
        "        rec = cindex.loc[fid]\n"
        "        if fid not in owner_label_by_id:\n"
        "            raise RuntimeError(f\"D2B {fid}: candidate missing from D2A owner-label map\")\n"
        "        fm = labels == int(owner_label_by_id[fid])\n",
        "candidate label lookup",
    )

    text = _replace_once(
        text,
        "            cc = candidates[candidates.analysis_cell_id.astype(str).eq(cid)].copy()\n"
        "            candidate_ids = sorted(cc.parent_field_id_2025.astype(str).tolist())\n"
        "            wb = (float(cp.normalization_minx), float(cp.normalization_miny), float(cp.normalization_maxx), float(cp.normalization_maxy))\n",
        "            cc = candidates[candidates.analysis_cell_id.astype(str).eq(cid)].copy()\n"
        "            candidate_ids = sorted(cc.parent_field_id_2025.astype(str).tolist())\n"
        "            owner_ids = sorted(part.loc[part.analysis_cell_id.astype(str).eq(cid), \"parent_field_id_2025\"].astype(str).tolist())\n"
        "            if len(owner_ids) != int(cp.owner_fields):\n"
        "                raise RuntimeError(f\"D2B owner-field count mismatch {cid}: {len(owner_ids)} != {cp.owner_fields}\")\n"
        "            if not set(candidate_ids).issubset(set(owner_ids)):\n"
        "                raise RuntimeError(f\"D2B candidate population is not a subset of D2A owner fields in {cid}\")\n"
        "            owner_pos = [id_to_pos[x] for x in owner_ids]\n"
        "            owner_geoms = [g.geometry.iloc[p] for p in owner_pos]\n"
        "            owner_label_by_id = {fid: i + 1 for i, fid in enumerate(owner_ids)}\n"
        "            wb = (float(cp.normalization_minx), float(cp.normalization_miny), float(cp.normalization_maxx), float(cp.normalization_maxy))\n",
        "owner-field reconstruction",
    )

    text = _replace_once(
        text,
        "                \"candidate_ids\": candidate_ids, \"normalization_window\": list(wb),\n",
        "                \"candidate_ids\": candidate_ids, \"owner_ids\": owner_ids, \"normalization_window\": list(wb),\n",
        "cache owner-id binding",
    )

    text = _replace_once(
        text,
        "                if candidate_ids:\n"
        "                    cand_pos = [id_to_pos[x] for x in candidate_ids]\n"
        "                    cand_geoms = [g.geometry.iloc[p] for p in cand_pos]\n"
        "                    cubes, valids, labels, _ = d2a_mod.read_owner_cell_arrays(datasets, band_maps, features, cand_geoms)\n"
        "                    loo_df = process_cell_true_loo(cid, cc, candidate_ids, cubes, valids, labels,\n"
        "                                                   variants, b2, b2cfg, tloo, tlcfg)\n",
        "                if candidate_ids:\n"
        "                    cubes, valids, labels, _ = d2a_mod.read_owner_cell_arrays(datasets, band_maps, features, owner_geoms)\n"
        "                    loo_df = process_cell_true_loo(cid, cc, candidate_ids, cubes, valids, labels,\n"
        "                                                   owner_label_by_id, variants, b2, b2cfg, tloo, tlcfg)\n",
        "all-owner rasterization",
    )

    return text


def build_patched_module() -> Any:
    source = patched_source()
    code = compile(source, str(BASE), "exec")
    ns: dict[str, Any] = {"__name__": "akerpuls_d2b_owner_raster_fixed_impl", "__file__": str(BASE)}
    exec(code, ns, ns)
    # Bind cache provenance to the fix wrapper rather than the historical failed
    # implementation. This forces all old candidate-only cell caches to rebuild.
    ns["THIS"] = THIS
    return SimpleNamespace(**ns)


def main() -> int:
    print("D2B_IMPLEMENTATION_FIX=OWNER_RASTERIZATION_IDENTICAL_TO_D2A", flush=True)
    mod = build_patched_module()
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
