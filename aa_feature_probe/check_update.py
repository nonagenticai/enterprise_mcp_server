"""Failing check for AA `development_feature_update`.

Run as: python -m aa_feature_probe.check_update
Exit 0 == green, exit 1 == red.

Specifies a BACKWARD-COMPATIBLE `currency` keyword on `format_receipt`:
  * omitted  -> output is byte-identical to today's (existing callers unaffected)
  * "EUR"    -> every amount, TOTAL included, is prefixed "EUR "
"""

import sys

from aa_feature_probe.receipts import format_receipt

ITEMS = [("widget", 3), ("gasket", 7)]
BASELINE = "widget  3\ngasket  7\nTOTAL  10"
WITH_CCY = "widget  EUR 3\ngasket  EUR 7\nTOTAL  EUR 10"


def main() -> int:
    failures: list[str] = []

    if format_receipt(ITEMS) != BASELINE:
        failures.append(
            "format_receipt(items) must stay byte-identical when currency is omitted; "
            f"got {format_receipt(ITEMS)!r}"
        )

    try:
        actual = format_receipt(ITEMS, currency="EUR")
    except TypeError:
        failures.append("format_receipt does not accept a `currency` keyword argument")
    else:
        if actual != WITH_CCY:
            failures.append(f"format_receipt(items, currency='EUR') == {actual!r}, expected {WITH_CCY!r}")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: format_receipt supports currency and stays backward compatible")
    return 0


if __name__ == "__main__":
    sys.exit(main())
