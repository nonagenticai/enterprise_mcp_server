"""Failing acceptance check for AA `development_feature_new`.

Run as: python -m aa_feature_probe.check_new
Exit 0 == green, exit 1 == red. No test runner, no dependencies.

Specifies `reserve_stock(sku, qty)`:
  * returns True and decrements stock when qty is available
  * returns False and leaves stock untouched when it is not
  * raises ValueError when qty is negative
"""

import sys

from aa_feature_probe import inventory


def main() -> int:
    reserve = getattr(inventory, "reserve_stock", None)
    if reserve is None:
        print("FAIL: aa_feature_probe.inventory.reserve_stock is not defined")
        return 1

    failures: list[str] = []

    if reserve("WIDGET-1", 4) is not True:
        failures.append("reserve_stock('WIDGET-1', 4) should return True")
    if inventory.stock_level("WIDGET-1") != 6:
        failures.append(
            f"stock_level('WIDGET-1') should be 6 after reserving 4, "
            f"got {inventory.stock_level('WIDGET-1')}"
        )
    if reserve("WIDGET-2", 1) is not False:
        failures.append("reserve_stock('WIDGET-2', 1) should return False (none on hand)")
    if inventory.stock_level("WIDGET-2") != 0:
        failures.append("a refused reservation must not change stock")
    try:
        reserve("WIDGET-1", -1)
    except ValueError:
        pass
    else:
        failures.append("reserve_stock with a negative qty should raise ValueError")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: reserve_stock satisfies the acceptance criteria")
    return 0


if __name__ == "__main__":
    sys.exit(main())
