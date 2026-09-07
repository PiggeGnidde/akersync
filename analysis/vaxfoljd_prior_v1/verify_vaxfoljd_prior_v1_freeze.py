#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

EXPECTED_ZIP_SHA256 = "bb6be8437027573a525c8344c34ce372e49b867ec52a67f2466475d6cf60ce6e"
EXPECTED_ZIP_BYTES = 327664
EXPECTED_CONTENT = {
    "AkerPuls_Vaxtfoljdsprior_Technical_Note_V1.docx": "6affc684ac76e334a7db5367cdee0c41f78c8d8420a5e303382d8e59af551311",
    "vaxfoljd_data_contract.md": "6bc319939aa64e87891fda225ecf8295f67895990da9312e3348c5e38b900e9d",
    "vaxfoljd_model_card.md": "9e13f9c50cb1a38a3bae1353adb0148acf0c8014b40813279efdce2b9884aded",
    "vaxfoljd_prior_formulas.md": "2c802149fc1890304b2deb8f1c011af03d153c0d5ebb02dcb4981f5fd2570f69",
}

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def resolve_default(repo_root: Path) -> Path:
    candidates = [
        repo_root / "work" / "vaxtfoljd_prior_v1_freeze" / "vaxfoljd_prior_v1_freeze.zip",
        repo_root / "work" / "vaxfoljd_prior_v1_freeze" / "vaxfoljd_prior_v1_freeze.zip",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", nargs="?", type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    path = args.zip_path.resolve() if args.zip_path else resolve_default(repo_root)
    print(f"Freeze ZIP: {path}")
    if not path.exists():
        print("FAIL: freeze ZIP does not exist", file=sys.stderr)
        return 2
    if path.stat().st_size != EXPECTED_ZIP_BYTES:
        print(f"FAIL: bytes {path.stat().st_size} != {EXPECTED_ZIP_BYTES}", file=sys.stderr)
        return 3
    actual_zip_sha = sha256_file(path)
    if actual_zip_sha != EXPECTED_ZIP_SHA256:
        print(f"FAIL: ZIP SHA256 {actual_zip_sha}", file=sys.stderr)
        return 4
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        for name, expected_sha in EXPECTED_CONTENT.items():
            if name not in names:
                print(f"FAIL: missing ZIP member {name}", file=sys.stderr)
                return 5
            actual = sha256_bytes(zf.read(name))
            if actual != expected_sha:
                print(f"FAIL: member SHA256 mismatch {name}: {actual}", file=sys.stderr)
                return 6
    print("PASS: vaxfoljd-prior-m4-v1.0-rc1 local freeze matches Git contract")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
