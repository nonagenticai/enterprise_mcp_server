"""One half of a deliberate import cycle: orders <-> billing.

THE SEEDED DEFECT is structural, not behavioural. `orders` imports `billing`
and `billing` imports `orders`, so the two modules form a dependency cycle that
`capture_baseline_cycles` is expected to find and a refactor is expected to
remove — typically by extracting the shared rate/rounding logic into a third
module that both depend on.

The cycle is importable on purpose (each side touches the other only at call
time), because a probe that cannot be imported measures the harness rather than
the refactor. Breaking the cycle is the intended task for the autonomous
refactoring chain.
"""

import aa_refactor_probe.billing as billing

TAX_RATE = 0.21
ROUNDING = 2


def order_total(lines: list[tuple[str, float]]) -> float:
    """Return the tax-inclusive total for ``lines``."""
    net = sum(amount for _, amount in lines)
    return round(net * (1 + TAX_RATE), ROUNDING)


def order_summary(lines: list[tuple[str, float]]) -> str:
    """Human-readable one-liner, delegating the currency rendering to billing."""
    return f"{len(lines)} line(s), {billing.render_amount(order_total(lines))}"
