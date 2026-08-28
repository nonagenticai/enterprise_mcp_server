# `aa_feature_probe` — AA feature-chain harness fixture

Gives the autonomous (AA) `development_feature_new`, `development_feature_update`
and `development_poc` chains a **deterministic red** to turn green. Sibling of
`aa_bugfix_probe/`, which serves `development_bug_fix`.

Not part of the product: `pyproject.toml` sets `packages = ["src"]`, and this
repo's CI runs only `uv sync` plus an import check, so nothing here is collected,
linted or shipped.

## The three seeded gaps

| card type | red check | target | the gap |
|---|---|---|---|
| `development_feature_new` | `check_new.py` | `inventory.py` | `reserve_stock(sku, qty)` does not exist |
| `development_feature_update` | `check_update.py` | `receipts.py` | `format_receipt` has no `currency` keyword |
| `development_poc` | `check_poc.py` | `poc.py` (absent) | no `demo()` wiring the two together |

Each check is independent, so one chain going green never turns another's red
into a false pass.

**These gaps are the work item, and the autonomous development chain is expected to close them.**
If you are that chain: implementing the missing behaviour here is exactly the intended task.

*Human maintainers:* please do not pre-empt it by committing the implementation yourself —
re-running the harness needs the gap back.

`check_update.py` additionally pins the CURRENT output byte-for-byte when
`currency` is omitted, so an update that breaks existing callers fails even
though the new behaviour works.

## Why stdlib only, and no pytest

The AA workspace pod (`codegraph-runtime`) clones the repo into an emptyDir and
then sleeps. Nothing installs dependencies at provision time, and
`/install-dependencies` is docker-only and dead on the k8s path — measured
2026-08-14 as exit 127 from a card reaching for `/workspace/.venv/bin/python`.
The coding-gateway exec is also **argv-only, no shell**, so `uv sync && pytest`
is not even expressible.

A check that needs a venv or a test runner therefore fails *before* it asserts
anything, and the run reports a harness failure wearing the costume of a red
test. Depending on nothing but the standard library means step 1 measures the
work and not the environment.

## How it is driven

```
feature_test_command: ["python", "-m", "aa_feature_probe.check_new"]
test_workdir:         "/workspace"
failing_test_ref:     "aa_feature_probe/check_new.py"
target_files:         ["aa_feature_probe/inventory.py"]
```

Substitute `check_update` / `receipts.py` or `check_poc` / `poc.py` for the
other two chains.

## Expected outcome

A PR authored by `app/code-graph-helper-app` closing exactly one gap, after
which that chain's check exits 0. **Re-running a chain needs its red back**, so
either revert the file or re-seed it.
