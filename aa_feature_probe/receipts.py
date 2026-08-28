"""Deterministic update gap for the AA `development_feature_update` chain.

`format_receipt` EXISTS and works, but only renders bare numbers. The seeded
work is to EXTEND it with a `currency` keyword argument without breaking its
existing callers — an update, not a new function.

Do not extend it by hand; that is the thing under test.
"""


def format_receipt(items: list[tuple[str, int]]) -> str:
    """Render ``items`` as ``NAME  AMOUNT`` lines plus a TOTAL line.

    THE SEEDED GAP: there is no ``currency`` parameter.
    aa_feature_probe/check_update.py specifies one that prefixes every amount
    and defaults to no prefix so existing callers are unaffected.
    """
    lines = [f"{name}  {amount}" for name, amount in items]
    lines.append(f"TOTAL  {sum(a for _, a in items)}")
    return "\n".join(lines)
