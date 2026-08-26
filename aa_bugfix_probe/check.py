"""Failing check for the AA IT Flow-2 (bug) harness.

Run as: python -m aa_bugfix_probe.check
Exit 0 == green, exit 1 == red. No test runner, no dependencies.
"""

import sys

from aa_bugfix_probe.calc import compute_total

EXPECTED = 5


def main() -> int:
    actual = compute_total(2, 3)
    if actual != EXPECTED:
        print(f"FAIL: compute_total(2, 3) == {actual}, expected {EXPECTED}")
        return 1
    print("PASS: compute_total(2, 3) == 5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
