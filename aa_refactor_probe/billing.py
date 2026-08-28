"""The other half of the deliberate orders <-> billing cycle.

Note the duplicated tax constants: `billing` re-declares what `orders` already
owns, which is why the cycle exists at all. Extracting them is the obvious
refactor and is the intended task for the autonomous refactoring chain.
"""

import aa_refactor_probe.orders as orders

TAX_RATE = 0.21
ROUNDING = 2


def render_amount(amount: float) -> str:
    """Render ``amount`` as a fixed-precision string."""
    return f"{amount:.{ROUNDING}f}"


def invoice_total(lines: list[tuple[str, float]]) -> float:
    """Return the invoice total, which must agree with ``orders.order_total``."""
    net = sum(amount for _, amount in lines)
    return round(net * (1 + TAX_RATE), ROUNDING)


def invoice_matches_order(lines: list[tuple[str, float]]) -> bool:
    """Cross-check the two independently-computed totals."""
    return invoice_total(lines) == orders.order_total(lines)
