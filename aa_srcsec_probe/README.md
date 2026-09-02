# aa_srcsec_probe — source-security probe fixture

**This is a probe, not product.** Nothing imports it, no service runs it, and it is
excluded from nothing because ems CI runs no scanner and no lint (`.github/workflows/ci.yml`
is a single hosted import smoke). It exists so the non-agentic system's
`development_source_security_patch` card type can be exercised end to end against a real
finding instead of a hypothetical one.

## What is here

| file | role |
|---|---|
| `queries.py` | the subject — a user-lookup helper whose SQL is assembled with the `%` operator before `execute()` |
| `check_srcsec.py` | the oracle — pins the lookup behaviour a patch must preserve |

## How it is graded

The card's verdict is the **scanner delta**, not the oracle: `scan_baseline` and `rescan` both
call `scanContainerSecurity`, and `compare_findings` passes only if
`critical_count + high_count` **strictly drops**. `coding-security`'s regex engine rates this
pattern **HIGH** (`security_detector.py`, `id="sql_injection_python_1"`); bandit's own `B608` is
MEDIUM and de-dupes into the same finding with the higher severity winning.

The oracle answers a different question: *did the count drop because the problem was fixed, or
because the code was deleted?* Deleting `get_user_by_id` would score a perfect delta. So
`check_srcsec.py` asserts only the observable contract — the right row for a known id, `None`
for an unknown one — and says nothing about how the statement is assembled, which is the part a
patch is free to change. Its fake cursor accepts both the one-argument and the parameterized
two-argument `execute()` call, so a correct patch keeps it green.

## Rules this fixture follows (each paid for by a past failure)

- **State what the code does today, never what a fix should be.** ems #104 and #109 were both
  fixed because a probe's prose contradicted or pre-empted the code and the worker believed the
  prose. The earlier draft of this fixture told the worker to "rewrite it to a parameterized
  query"; a probe that hands over its own answer proves the plumbing, not the diagnosis.
- **The oracle is not the subject.** Do not edit `check_srcsec.py` to make a drive pass.
- **The scan is whole-workspace.** `scan_baseline` sends `requestBody: {}`, so findings from
  every file in `/workspace` pool into one pair of counts — including the repo's root
  `Dockerfile`. A patch to some *other* file also drops the total, so check the PR's diff and
  the card's `out_of_scope_files` before believing a pass.

## Restoring it

This probe is consumed if its PR merges. To restore, revert the merge for this directory —
`queries.py` must end up with the `%`-formatted `execute()` call again and `check_srcsec.py`
must still exit 0.
