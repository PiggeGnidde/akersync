#!/usr/bin/env python3
from __future__ import annotations

from collections import deque
from pathlib import Path
import pandas as pd


def as_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(["true", "1"])


def main():
    root = Path(__file__).resolve().parents[1]
    plan_path = root / "data" / "derived" / "dem_plan_skane.csv"
    miss_path = root / "data" / "derived" / "dem_still_missing_skane.csv"
    if not plan_path.exists() or not miss_path.exists():
        raise SystemExit("Kör PLAN_SKANE_DEM.bat och CHECK_SKANE_DEM.bat först.")

    plan = pd.read_csv(plan_path)
    gaps = pd.read_csv(miss_path)
    if gaps.empty:
        print("Inga saknade DEM-rutor.")
        return

    xs = sorted(plan.lower_left_x.astype(int).unique())
    ys = sorted(plan.lower_left_y.astype(int).unique(), reverse=True)
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    gap_by_xy = {}
    for _, r in gaps.iterrows():
        xy = (int(r.lower_left_x), int(r.lower_left_y))
        core = str(r.core_farmland).lower() in ("true", "1")
        ring = str(r.one_ring).lower() in ("true", "1")
        gap_by_xy[xy] = "C" if core else ("R" if ring else "M")

    print("=" * 72)
    print("ÅkerSync · karta över saknade Skåne DEM-rutor")
    print("=" * 72)
    print("Legend: #=DEM finns, C=saknad core, R=saknad one-ring, M=saknad rectangle-only")
    print("        y visas nord -> syd; x visas väst -> öst\n")

    for y in ys:
        row = ''.join(gap_by_xy.get((x, y), '#') for x in xs)
        print(f"{y:7d}  {row}")
    print("         " + ''.join(str((i // 10) % 10) for i in range(len(xs))))
    print("         " + ''.join(str(i % 10) for i in range(len(xs))))
    print(f"x-index 0={xmin}, {len(xs)-1}={xmax}, steg 2500 m")

    missing = set(gap_by_xy)
    comps = []
    while missing:
        start = next(iter(missing))
        q = deque([start])
        missing.remove(start)
        comp = {start}
        while q:
            x, y = q.popleft()
            for n in ((x-2500,y),(x+2500,y),(x,y-2500),(x,y+2500)):
                if n in missing:
                    missing.remove(n); comp.add(n); q.append(n)
        comps.append(comp)

    print("\nSaknade sammanhängande komponenter:")
    interior_components = 0
    for i, comp in enumerate(sorted(comps, key=len, reverse=True), 1):
        touches = any(x in (xmin,xmax) or y in (ymin,ymax) for x,y in comp)
        flags = ''.join(sorted({gap_by_xy[p] for p in comp}))
        if not touches:
            interior_components += 1
        print(f"  {i:2d}. {len(comp):2d} rutor; typer={flags}; " + ("rör rectangle-kant" if touches else "INLANDSLUCKA"))

    ncore = sum(v == 'C' for v in gap_by_xy.values())
    nring = sum(v == 'R' for v in gap_by_xy.values())
    nrect = sum(v == 'M' for v in gap_by_xy.values())
    print(f"\nTotalt saknas: {len(gap_by_xy)}  C={ncore} R={nring} M={nrect}")
    if interior_components == 0:
        print("TOPOLOGI: alla saknade komponenter når ytterkanten; inga isolerade inlandshål.")
    else:
        print(f"TOPOLOGI: {interior_components} saknad(e) komponent(er) ligger helt inne i rektangeln.")
        print("Kör inte BUILD_ALL innan dessa har granskats.")


if __name__ == "__main__":
    main()
