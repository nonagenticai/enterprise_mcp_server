"""Characterisation check for the AA refactoring chains.

Run as: python -m aa_refactor_probe.check
Exit 0 == green, exit 1 == red.

Unlike the bug and feature probes this check is GREEN and MUST STAY GREEN: the
refactoring procedures run `verify_tests_green` after rewriting the modules, so
this file pins the behaviour that a cycle-breaking refactor must preserve.
"""

import sys

from aa_refactor_probe import billing, orders

LINES = [("widget", 100.0), ("gasket", 50.0)]


def main() -> int:
    failures: list[str] = []

    if orders.order_total(LINES) != 181.5:
        failures.append(f"order_total == {orders.order_total(LINES)}, expected 181.5")
    if billing.invoice_total(LINES) != 181.5:
        failures.append(f"invoice_total == {billing.invoice_total(LINES)}, expected 181.5")
    if not billing.invoice_matches_order(LINES):
        failures.append("invoice_total and order_total must agree")
    if orders.order_summary(LINES) != "2 line(s), 181.50":
        failures.append(f"order_summary == {orders.order_summary(LINES)!r}")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: order/billing behaviour is unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
