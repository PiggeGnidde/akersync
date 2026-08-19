#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the ÅkerPass V1 frontend from its source template."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    dist_dir = root / config.get("dist_dir", "dist")
    manifest_path = dist_dir / "municipalities.json"
    template_path = root / "web" / "akerpass_v1.html"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Saknar {manifest_path}. Kör public data-buildern först.")
    if not template_path.exists():
        raise FileNotFoundError(template_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("municipality_count") != 33:
        raise RuntimeError("ÅkerPass V1 kräver exakt 33 skånska kommuner")
    html = template_path.read_text(encoding="utf-8")
    placeholder = "__MUNICIPALITIES_JSON__"
    if html.count(placeholder) != 1:
        raise RuntimeError(f"Templaten ska innehålla exakt en {placeholder}")
    html = html.replace(placeholder, json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    if "__" + "MUNICIPALITIES_JSON__" in html:
        raise RuntimeError("Oersatt manifest-placeholder")
    dist_dir.mkdir(parents=True, exist_ok=True)
    output = dist_dir / "index.html"
    output.write_text(html, encoding="utf-8")
    print(f"FRONTEND: OK · {output} · {output.stat().st_size / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
