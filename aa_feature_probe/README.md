# aa_feature_probe

A deterministic acceptance probe for the AA `development_feature_new` chain.

Stdlib only, on purpose — a probe that reaches for a venv or a test runner
measures the environment instead of the work.

## Files

- `inventory.py` — module under test. `stock_level` exists; `reserve_stock`
  is the seeded gap that the autonomous chain must add.
- `check_new.py` — executable acceptance check (stdlib only).

## Run

    python aa_feature_probe/check_new.py

Exits 0 on success, 1 on failure.
