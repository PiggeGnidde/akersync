from __future__ import annotations

import argparse
import json
from pathlib import Path

from ternary_cover import BASELINE_GENERATOR, BASELINE_PARITY_CHECK, baseline_code, save_code, verify_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "solutions" / "k243_linear.txt"))
    args = parser.parse_args()
    code = baseline_code()
    report = verify_code(code)
    save_code(args.output, code, header="Verified ternary covering code for K_3(11,3).\n243 rows; map 0/1/2 to Stryktips symbols 1/X/2.\nWith two correct spikes this guarantees at least 10 correct of 13.")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("\nGenerator G:")
    print(BASELINE_GENERATOR)
    print("\nParity check H:")
    print(BASELINE_PARITY_CHECK)
    print(f"\nWrote {args.output}")
    return 0 if report["covering_radius_at_most_3"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
