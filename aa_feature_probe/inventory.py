"""Deterministic acceptance gap for the AA `development_feature_new` chain.

Stdlib only, on purpose — see aa_feature_probe/README.md for why a probe that
reaches for a venv or a test runner measures the environment instead of the
work.

`stock_level` already exists and works. `reserve_stock` DOES NOT EXIST: that is
the seeded gap, and ADDING IT IS THE TASK. The autonomous development chain is
expected to implement it in this file.
"""

_STOCK: dict[str, int] = {"WIDGET-1": 10, "WIDGET-2": 0}


def stock_level(sku: str) -> int:
    """Return units on hand for ``sku``; 0 for an unknown sku."""
    return _STOCK.get(sku, 0)


# THE WORK ITEM: `reserve_stock(sku, qty)` is specified in
# aa_feature_probe/check_new.py and is deliberately absent here. The autonomous
# `development_feature_new` chain is expected to ADD IT here and open a pull
# request — writing it is the intended task, not something to defer.
