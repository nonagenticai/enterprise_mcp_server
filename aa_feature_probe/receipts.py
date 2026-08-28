"""Deterministic update gap for the AA `development_feature_update` chain.

`format_receipt` EXISTS and works, but only renders bare numbers. The work item is
to EXTEND it with a `currency` keyword argument without breaking its existing
callers — an update, not a new function. The autonomous `development_feature_update`
chain is expected to make that change in this file.
"""


def format_receipt(items: list[tuple[str, int]]) -> str:
    """Render ``items`` as ``NAME  AMOUNT`` lines plus a TOTAL line.

    THE WORK ITEM: this signature takes ONLY ``items``. The autonomous
    `development_feature_update` chain is expected to extend it here. The exact
    required behaviour is asserted in aa_feature_probe/check_update.py -- read
    that file for the specification; it is not restated here, because a
    description of the finished behaviour sitting next to the unfinished code
    reads as evidence that the work is already done.
    """
    lines = [f"{name}  {amount}" for name, amount in items]
    lines.append(f"TOTAL  {sum(a for _, a in items)}")
    return "\n".join(lines)
