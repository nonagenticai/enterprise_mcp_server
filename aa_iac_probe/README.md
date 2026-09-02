# aa_iac_probe — IaC-security probe fixture

**This is a probe, not product.** No pipeline applies this Terraform and no AWS account has ever
seen it. It exists so the non-agentic system's `development_iac_security_patch` card type can be
exercised end to end against a real scanner finding.

It is deliberately a **different scanner surface** from `aa_srcsec_probe`: that one is caught by
the source engines (regex/bandit/semgrep), this one by `trivy config` via
`coding-security`'s `iac_scanner`, which maps trivy CRITICAL/HIGH 1:1. One fixture does not
cover both card types.

## What is here

| file | role |
|---|---|
| `insecure_sg.tf` | the subject — a security group whose SSH ingress accepts `0.0.0.0/0` (trivy `AWS-0107`, HIGH) |
| `check_iac.py` | the oracle — pins that the declaration still exists and still exposes SSH |

Path does not matter to the scanner: `iac_scanner.is_iac_scan_candidate()` keys on filename and
extension, and Terraform is scanned per-directory as a module, which is why this `.tf` sits alone
in its own directory.

## How it is graded

The verdict is the scanner delta (`compare_findings`: `critical_count + high_count` must
strictly drop). The oracle exists to stop the degenerate patch: deleting the security group, or
deleting its SSH ingress rule, drops the count to zero and looks perfect. `check_iac.py`
therefore asserts only that the resource still exists, still declares a TCP/22 ingress, and still
declares egress — **never where SSH may be reached from**, which is exactly what a patch should
change. Narrowing the CIDR keeps it green; deleting the rule turns it red.

## Rules this fixture follows

- **State what the manifest declares today, never what a fix should be.** The earlier draft said
  the pipeline "is expected to open a PR that restricts this rule" — that is handing over the
  answer.
- **The oracle is not the subject.** Do not edit `check_iac.py` to make a drive pass.
- **The scan is whole-workspace** (`requestBody: {}`), so this probe's findings pool with
  `aa_srcsec_probe`'s and with the repo's root `Dockerfile`. Drive the two security card types
  **serially**, and check the diff and `out_of_scope_files` before believing a pass.

## Restoring it

Consumed if its PR merges. To restore, the ingress `cidr_blocks` must be `["0.0.0.0/0"]` again
and `check_iac.py` must still exit 0.
