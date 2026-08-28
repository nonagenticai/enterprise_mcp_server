# `aa_refactor_probe` — AA refactoring-chain harness fixture

Gives the autonomous (AA) `decoupling_refactoring`, `dependency_refactoring` and
`architecture_refactoring` chains a **real dependency cycle** to remove.

Not part of the product; not packaged, not collected, not linted.

## The seeded defect is structural, not behavioural

`orders.py` and `billing.py` import each other:

```
aa_refactor_probe.orders   ->  aa_refactor_probe.billing
aa_refactor_probe.billing  ->  aa_refactor_probe.orders
```

and each re-declares the same `TAX_RATE` / `ROUNDING` constants. The obvious
refactor is to extract the shared constants and rounding into a third module
both depend on, which breaks the cycle.

The cycle is **importable on purpose** — each side touches the other only at
call time, and `import a.b as c` defers attribute access — so the package
imports cleanly from either direction. A probe that cannot be imported measures
the harness rather than the refactor. Verified both ways:

```
python -c "import aa_refactor_probe.orders"   # ok
python -c "import aa_refactor_probe.billing"  # ok
```

## `check.py` is GREEN and must STAY green

Unlike the bug and feature probes, this check passes today. The refactoring
procedures run `verify_tests_green` *after* rewriting the modules, so `check.py`
is a characterisation test pinning the behaviour a cycle-breaking refactor must
preserve: both totals stay `181.50`, they keep agreeing with each other, and
`order_summary` keeps its exact wording.

That is what makes this fixture meaningful — the chain must remove the cycle
**without** changing behaviour.

## How it is driven

```
test_command:     ["python", "-m", "aa_refactor_probe.check"]
test_workdir:     "/workspace"
target_files:     ["aa_refactor_probe/orders.py", "aa_refactor_probe/billing.py"]
```

The chain additionally runs `capture_baseline_cycles`, `rebuild_code_graph` and
`assert_no_new_cycle` against the code-graph service; this fixture exists so
those steps have a genuine cycle to find rather than an empty graph.

## Expected outcome

A PR that removes the `orders <-> billing` edge in one direction while
`python -m aa_refactor_probe.check` still exits 0.

*Human maintainers:* do not pre-empt the chain by breaking the cycle yourself —
re-running needs it back.
