"""Deterministic red for the AA IT Flow-2 (bug) harness.

Stdlib only, on purpose. The AA workspace pod (`codegraph-runtime`) clones the
repo into an emptyDir and then sleeps — nothing installs dependencies at
provision time, and `/install-dependencies` is docker-only and dead on the k8s
path. So a `bug_test_command` that reaches for `/workspace/.venv/bin/python`
or
for pytest exits 127 before it ever asserts anything, and the run reports a
harness failure dressed as a red test.

Keeping the probe importable with nothing but the standard library means the
chain's `reproduce_failing_test` step measures the BUG and not the environment.
"""


def compute_total(a: int, b: int) -> int:
    """Return the sum of ``a`` and ``b``.

    THE SEEDED DEFECT: this subtracts. `aa_bugfix_probe/check.py` asserts
    ``compute_total(2, 3) == 5`` and therefore fails. The AA
    `development_bug_fix` chain is expected to turn this into ``a + b`` and open
    a pull request. Do not "fix" it by hand — that is the thing under test.
    """
    return a + b
