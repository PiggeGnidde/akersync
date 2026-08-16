#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
from pathlib import Path

import rasterio

from common import load_config

RES_M = 10.0
FLOAT_BYTES = 4


def gib(n: float) -> float:
    return n / (1024 ** 3)


def memory_info():
    """Return (total_bytes, available_bytes) without external dependencies."""
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        s = MEMORYSTATUSEX()
        s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return int(s.ullTotalPhys), int(s.ullAvailPhys)
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        total = page * os.sysconf("SC_PHYS_PAGES")
        avail = page * os.sysconf("SC_AVPHYS_PAGES")
        return int(total), int(avail)
    except Exception:
        return None, None


def aligned(v, res, up=False):
    import math
    return (math.ceil(v / res) if up else math.floor(v / res)) * res


def main():
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / "config" / "local_paths.json")
    dem_dir = Path(cfg["dem_dir"])
    if not dem_dir.exists():
        raise SystemExit(f"DEM-mapp saknas: {dem_dir}")

    paths = sorted(dem_dir.glob("*.tif"))
    if not paths:
        raise SystemExit("Inga DEM-filer hittades.")

    left = bottom = float("inf")
    right = top = float("-inf")
    readable = 0
    epsgs = set()
    source_bytes = 0
    for i, p in enumerate(paths, 1):
        source_bytes += p.stat().st_size
        try:
            with rasterio.open(p) as ds:
                b = ds.bounds
                left = min(left, b.left); bottom = min(bottom, b.bottom)
                right = max(right, b.right); top = max(top, b.top)
                epsgs.add(ds.crs.to_epsg() if ds.crs else None)
                readable += 1
        except rasterio.errors.RasterioIOError:
            pass
        if i % 500 == 0:
            print(f"Läser DEM-metadata: {i:,}/{len(paths):,}", end="\r", flush=True)
    print(" " * 70, end="\r")

    if readable == 0:
        raise SystemExit("Inga läsbara DEM-rutor.")

    left = aligned(left, RES_M)
    bottom = aligned(bottom, RES_M)
    right = aligned(right, RES_M, up=True)
    top = aligned(top, RES_M, up=True)
    width = int(round((right - left) / RES_M))
    height = int(round((top - bottom) / RES_M))
    cells = width * height
    raster_bytes = cells * FLOAT_BYTES

    # Current validated engine creates five uncompressed Float32 working rasters:
    # DEM mosaic, filled DEM, slope, DInf SCA and TWI. Whitebox may additionally
    # need transient scratch space, so use a conservative disk margin.
    persistent_work = raster_bytes * 5
    disk_recommended = raster_bytes * 12

    # RAM cannot be predicted exactly for WhiteboxTools. The current rasterio
    # mosaic itself materializes one full Float32 raster (~1x). Classify using
    # conservative multiples of one raster, and print the assumptions instead
    # of pretending to know Whitebox's exact peak allocation.
    ram_min_available = raster_bytes * 8
    ram_comfort_available = raster_bytes * 16

    local_base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    work_dir = local_base / "AkerSyncHydroWork_v09b"
    work_dir.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(work_dir)
    total_ram, avail_ram = memory_info()

    print("=" * 78)
    print("ÅkerSync · hydrologi-preflight · hela Skåne")
    print("=" * 78)
    print(f"DEM-filer:                 {len(paths):,} ({readable:,} läsbara)")
    print(f"DEM CRS:                   {sorted(epsgs, key=lambda x: (x is None, x))}")
    print(f"DEM källfiler på disk:     {gib(source_bytes):.1f} GiB")
    print(f"Mosaik-bbox EPSG:3006:     {left:.0f}, {bottom:.0f}, {right:.0f}, {top:.0f}")
    print(f"Arbetsgrid @ {RES_M:g} m:       {width:,} × {height:,} = {cells/1e6:.1f} Mpix")
    print(f"Ett Float32-raster:        {gib(raster_bytes):.2f} GiB")
    print(f"5 mellanraster, rå storlek:{gib(persistent_work):.2f} GiB")
    print(f"Konservativ diskbudget:    {gib(disk_recommended):.1f} GiB")
    print(f"Whitebox work-dir:         {work_dir}")
    print(f"Ledigt på work-disken:     {gib(disk.free):.1f} GiB")
    if total_ram is not None:
        print(f"RAM totalt / ledigt nu:    {gib(total_ram):.1f} / {gib(avail_ram):.1f} GiB")
    else:
        print("RAM:                       kunde inte läsas automatiskt")
    print()
    print("RAM-bedömningen är en preflight, inte ett löfte om Whitebox peak-RAM.")
    print(f"  försiktig min-nivå ledigt: ~{gib(ram_min_available):.1f} GiB (8× ett raster)")
    print(f"  bekväm nivå ledigt:        ~{gib(ram_comfort_available):.1f} GiB (16× ett raster)")

    disk_ok = disk.free >= disk_recommended
    if avail_ram is None:
        ram_state = "OKÄND"
    elif avail_ram >= ram_comfort_available:
        ram_state = "GRÖN"
    elif avail_ram >= ram_min_available:
        ram_state = "GUL"
    else:
        ram_state = "RÖD"

    print()
    print(f"Disk: {'GRÖN' if disk_ok else 'RÖD'}")
    print(f"RAM:  {ram_state}")
    if not disk_ok:
        print("PREFLIGHT: STOPP — frigör disk eller byt Whitebox work-dir före hydrologi.")
        return 2
    if ram_state == "RÖD":
        print("PREFLIGHT: STOPP — nuvarande full-Skåne-körning är för riskabel i RAM.")
        print("Nästa kodsteg blir då tiled/regionvis hydrologi med överlapp, inte att chansa.")
        return 3
    if ram_state == "GUL":
        print("PREFLIGHT: GUL — tekniskt plausibelt men vi bör besluta innan full körning.")
        return 0
    print("PREFLIGHT: GRÖN — resurserna ser rimliga ut för nuvarande 10 m-motor.")
    print("Kör ändå inte BUILD_ALL förrän preflight-utskriften har granskats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
