"""ÅkerKontext · VattenTryck — VT-A1c VISS inventory probe.

Reads VISS_API_KEY from repository-root .env (never prints it), probes the
machine-readable VISS groundwater pressure/impact/risk endpoints for Skåne,
and writes reproducible raw JSON plus a compact manifest under data/derived.

This is an inventory/probe step: no score, no legal inference, no field join.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
OUT_DIR = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1c"
BASE_URL = "https://viss.lansstyrelsen.se/API"

METHODS = [
    "waters",
    "measuregroundwaterpressures",
    "measuregroundwaterpressuremotivations",
    "measuregroundwaterimpacts",
    "measuregroundwaterimpactmotivations",
    "waterriskclassifications",
]


def load_env(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"Missing local secrets file: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def viss_call(method: str, api_key: str, **kwargs):
    params = {"method": method, "apikey": api_key, "format": "json", **kwargs}
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AkerSync-VISS-inventory/0a"})
    with urllib.request.urlopen(req, timeout=180) as response:
        payload = response.read()
        status = getattr(response, "status", None)
    text = payload.decode("utf-8-sig")
    return json.loads(text), len(payload), status


def shape_summary(data):
    if isinstance(data, list):
        keys = sorted({k for row in data[:100] if isinstance(row, dict) for k in row})
        first = data[0] if data else None
        return {"type": "list", "records": len(data), "keys_first_100": keys, "first_record": first}
    if isinstance(data, dict):
        return {"type": "dict", "keys": sorted(data.keys()), "first_record": None}
    return {"type": type(data).__name__, "first_record": None}


def safe_error(exc: Exception) -> str:
    # Never include the request URL because it contains the API key.
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTPError {exc.code}: {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"URLError: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def main() -> int:
    load_env(ENV_PATH)
    api_key = os.environ.get("VISS_API_KEY")
    if not api_key:
        raise RuntimeError("VISS_API_KEY missing from repository-root .env")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 76)
    print("ÅkerKontext · VattenTryck — VT-A1c VISS inventory")
    print("Scope: Skåne (countycode=12), groundwater")
    print("API key loaded: YES (value never printed or persisted)")
    print("=" * 76)

    manifest = {
        "checkpoint": "VT-A1c",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"countycode": "12", "watercategory": "GW"},
        "methods": {},
    }

    for method in METHODS:
        print(f"\n[{method}]")
        kwargs = {"countycode": "12"}
        if method == "waters":
            kwargs["watercategory"] = "GW"
        try:
            data, nbytes, status = viss_call(method, api_key, **kwargs)
            outfile = OUT_DIR / f"{method}.json"
            outfile.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            summary = shape_summary(data)
            manifest["methods"][method] = {
                "ok": True,
                "http_status": status,
                "response_bytes": nbytes,
                "output": str(outfile.relative_to(ROOT)),
                **{k: v for k, v in summary.items() if k != "first_record"},
            }
            print(f"  PASS  bytes={nbytes:,}  type={summary['type']}")
            if summary.get("records") is not None:
                print(f"  records={summary['records']:,}")
            if summary.get("keys_first_100"):
                print("  keys:", ", ".join(summary["keys_first_100"]))
            if summary.get("first_record") is not None:
                preview = json.dumps(summary["first_record"], ensure_ascii=False)
                print("  first-record preview:", preview[:1200])
        except Exception as exc:
            err = safe_error(exc)
            manifest["methods"][method] = {"ok": False, "error": err}
            print("  PROBE_FAIL", err)

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for x in manifest["methods"].values() if x["ok"])
    print("\n" + "=" * 76)
    print(f"VT-A1c probe complete: {ok}/{len(METHODS)} methods returned JSON")
    print(f"Manifest: {manifest_path.relative_to(ROOT)}")
    print("Raw outputs are under data/derived and are intentionally not committed.")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {safe_error(exc)}", file=sys.stderr)
        raise
