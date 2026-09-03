from __future__ import annotations

import argparse
import json
from pathlib import Path

from ternary_cover import load_code, verify_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Exact verifier for a ternary radius-3 cover.")
    parser.add_argument("solution", nargs="?", default=str(Path(__file__).resolve().parents[1] / "solutions" / "k243_linear.txt"))
    args = parser.parse_args()
    code = load_code(args.solution)
    report = verify_code(code)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["covering_radius_at_most_3"]:
        print(f"\nPASS: {report['rows']} rows cover all 177147 outcomes within Hamming distance <= 3.")
        return 0
    print(f"\nFAIL: {report['uncovered']} outcomes are not covered.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
