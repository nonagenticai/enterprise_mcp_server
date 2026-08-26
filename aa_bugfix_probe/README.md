# `aa_bugfix_probe` — AA IT Flow-2 (bug) harness fixture

This package exists to give the autonomous (AA) `development_bug_fix` chain a
**deterministic red** to reproduce and fix. It is not part of the product; it is
not packaged (`pyproject.toml` sets `packages = ["src"]`) and this repo's CI
runs only `uv sync` plus an import check, so nothing here is collected or linted.

## The defect, on purpose

`calc.compute_total(a, b)` returns `a - b`. `check.py` asserts
`compute_total(2, 3) == 5` and therefore exits 1.

**Do not fix this by hand.** Turning the `-` into a `+` is the thing under test.

## Why stdlib only, and no pytest

The AA workspace pod (`codegraph-runtime`) clones the repo into an emptyDir and
then sleeps. Nothing installs dependencies at provision time, and
`/install-dependencies` is docker-only and dead on the k8s path — measured
2026-08-14 as exit 127 from a `verification_test` card reaching for
`/workspace/.venv/bin/python`.

A `bug_test_command` that needs a venv or a test runner therefore fails *before*
it asserts anything, and the run reports a harness failure wearing the costume of
a red test. Depending on nothing but the standard library means
`reproduce_failing_test` measures the bug and not the environment.

## How it is driven

```
bug_test_command: ["python", "-m", "aa_bugfix_probe.check"]
test_workdir:     "/workspace"
failing_test_ref: "aa_bugfix_probe/check.py"
target_files:     ["aa_bugfix_probe/calc.py"]
```

Fired by `n8n_custom_nodes/scripts/drive-it-flow-bug.sh`, which POSTs a project
with `it_flow: "bug"`. The chain is
`project_start_request_analysis → project_setup → bug_analysis → development_bug_fix`,
ending in a pull request against this repo.

## Expected outcome

A PR authored by `app/code-graph-helper-app` changing `a - b` to `a + b`, after
which `python -m aa_bugfix_probe.check` exits 0. **Close that PR without merging**
— re-running the harness needs the red back.
