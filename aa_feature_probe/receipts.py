"""Deterministic update gap for the AA `development_feature_update` chain.

`format_receipt` EXISTS and works, but only renders bare numbers. The work item is
to EXTEND it with a `currency` keyword argument without breaking its existing
callers — an update, not a new function. The autonomous `development_feature_update`
chain is expected to make that change in this file.
"""


def format_receipt(items: list[tuple[str, int]], currency: str | None = None) -> str:
    """Render ``items`` as ``NAME  AMOUNT`` lines plus a TOTAL line.

    If ``currency`` is provided (e.g. ``"EUR"``), every amount -- including the
    TOTAL -- is prefixed with ``"<currency> "``. Omitting ``currency`` keeps the
    output byte-identical to the previous bare-number behaviour.
    """
    prefix = f"{currency} " if currency is not None else ""
    lines = [f"{name}  {prefix}{amount}" for name, amount in items]
    lines.append(f"TOTAL  {prefix}{sum(a for _, a in items)}")
    return "\n".join(lines)}], 