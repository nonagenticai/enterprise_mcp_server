"""Failing demo check for AA `development_poc`.

Run as: python -m aa_feature_probe.check_poc
Exit 0 == green, exit 1 == red.

Specifies a proof-of-concept module `aa_feature_probe.poc` exposing `demo()`
that wires the probe's two existing pieces together end to end: reserve stock,
then render a receipt for what was reserved.
"""

import sys


def main() -> int:
    try:
        from aa_feature_probe import poc
    except ImportError:
        print("FAIL: aa_feature_probe.poc does not exist")
        return 1

    demo = getattr(poc, "demo", None)
    if demo is None:
        print("FAIL: aa_feature_probe.poc.demo is not defined")
        return 1

    result = demo()
    if not isinstance(result, str):
        print(f"FAIL: demo() should return a receipt string, got {type(result).__name__}")
        return 1
    if "TOTAL" not in result:
        print(f"FAIL: demo() output should contain a TOTAL line, got {result!r}")
        return 1

    print("PASS: poc.demo() renders an end-to-end receipt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
