#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "local_paths.json"
RAW = Path(r"C:\AkerSyncRaw\jv_skane_2025")
BLOCKS = RAW / "arslager_block_skane_2025.gpkg"
SKIFTEN = RAW / "arslager_skifte_skane_2025.gpkg"
BACKUP = ROOT / "config" / "local_paths.json.before_jv_skane_2025.bak"


def main():
    for p in (CFG, BLOCKS, SKIFTEN):
        if not p.exists():
            raise SystemExit(f"SAKNAS: {p}")

    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    old_blocks = cfg.get("blocks")
    old_skiften = cfg.get("skiften")

    if not BACKUP.exists():
        shutil.copy2(CFG, BACKUP)

    cfg["blocks"] = str(BLOCKS)
    cfg["skiften"] = str(SKIFTEN)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"blocks:  {old_blocks}  ->  {cfg['blocks']}")
    print(f"skiften: {old_skiften}  ->  {cfg['skiften']}")
    print("Backup:", BACKUP)
    print("\nKomplett Skåne 2025-rådata konfigurerad.")
    print("Nästa steg: CHECK_INPUTS.bat, därefter PLAN_SKANE_DEM.bat.")


if __name__ == "__main__":
    main()
