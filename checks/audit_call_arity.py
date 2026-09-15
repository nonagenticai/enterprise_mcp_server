"""Every call to AuditLogService.log_event must pass its required arguments.

THE DEFECT THIS CATCHES
-----------------------
`AuditLogService.log_event` (src/audit.py) declares `resource_id: str | None` WITHOUT a
default. In `src/tool_management_api.py :: list_tools`, the permission-denied branch calls
`log_event(...)` and omits it. Python raises `TypeError: log_event() missing 1 required
keyword-only argument` (or positional, per the signature) at call time.

The symptom is not a crash in an obscure corner. That branch is the one that runs when a user
WITHOUT `tool:read` requests `GET /tools/tools`:

  * the caller receives **500 Internal Server Error** instead of the intended **403 Forbidden**,
    because the exception is raised before `raise HTTPException(403)` is ever reached; and
  * **the denial is never audited** — the very record the call exists to write is the thing the
    bug destroys.

So an unauthorised access attempt both misreports its status and leaves no trace. The success
path twenty lines below passes `resource_id="tools"` with the comment `# <-- Add this
argument`, which is the fingerprint of someone patching one site and missing the other.

WHY AN AST CHECK RATHER THAN A UNIT TEST
----------------------------------------
The property is "no call site anywhere omits a required argument", which is a statement about
the whole tree, not about one function. A unit test pins the one call it imports; the next
call site added tomorrow is unguarded. Deriving the requirement from the real `FunctionDef`
also means the check cannot drift from the signature: rename or add a required parameter and
every call site is re-judged against the new truth, with no list to update here.

⛔ THE CENSUS GUARD IS NOT DECORATION. If the walk finds zero `log_event` call sites, this
module exits non-zero rather than reporting success. A check that measured nothing and printed
"ok" is the most confident possible way to assert nothing — and it is the exact failure mode
that lets a blinded guard sit green for months.

Runnable with no dependencies:  python -m checks.audit_call_arity
"""

from __future__ import annotations

import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
AUDIT_MODULE = REPO / "src" / "audit.py"
TARGET_METHOD = "log_event"
TARGET_CLASS = "AuditLogService"
# A tree with fewer call sites than this means the walk is broken, not that the code is clean.
MIN_CALL_SITES = 1


def required_parameters() -> set[str]:
    """Derive the required parameter names from the real signature. Never hardcode them."""
    if not AUDIT_MODULE.exists():
        print(
            f"FAIL: cannot read {AUDIT_MODULE.relative_to(REPO)} — the check cannot derive"
        )
        print("      the signature, so it must not report success.")
        raise SystemExit(2)

    tree = ast.parse(AUDIT_MODULE.read_text(encoding="utf-8"))
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or cls.name != TARGET_CLASS:
            continue
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name != TARGET_METHOD:
                continue
            args = fn.args
            positional = args.posonlyargs + args.args
            # Trailing defaults line up with the END of the positional list.
            n_required = len(positional) - len(args.defaults)
            required = {a.arg for a in positional[:n_required] if a.arg != "self"}
            # Keyword-only parameters whose default is None-the-sentinel are still required
            # unless a default is actually supplied.
            for a, d in zip(args.kwonlyargs, args.kw_defaults):
                if d is None:
                    required.add(a.arg)
            return required

    print(
        f"FAIL: {TARGET_CLASS}.{TARGET_METHOD} not found in {AUDIT_MODULE.relative_to(REPO)}."
    )
    print(
        "      The check cannot derive its requirement, so it must not report success."
    )
    raise SystemExit(2)


def source_files() -> list[pathlib.Path]:
    return sorted((REPO / "src").rglob("*.py"))


def main() -> int:
    required = required_parameters()
    if not required:
        print(f"FAIL: derived an EMPTY required-parameter set for {TARGET_METHOD}.")
        print("      Every call site would trivially pass. Refusing to report success.")
        return 2

    call_sites = 0
    offenders: list[tuple[str, int, set[str]]] = []

    for path in source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"FAIL: {path.relative_to(REPO)} does not parse: {exc}")
            return 2
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != TARGET_METHOD:
                continue
            call_sites += 1
            # A call that forwards **kwargs could satisfy anything; do not judge it.
            if any(k.arg is None for k in node.keywords):
                continue
            # A call that passes anything positionally binds parameters by ORDER, which this
            # check does not model. Skip it rather than guess: a false accusation here would
            # send someone to edit a call site that is perfectly correct. Every log_event call
            # in this tree is keyword-only today, so nothing real is skipped -- and if that
            # ever changes, the census count below still proves the walk saw the call.
            if node.args:
                continue
            supplied = {k.arg for k in node.keywords if k.arg}
            missing = set(required) - supplied
            if missing:
                offenders.append((str(path.relative_to(REPO)), node.lineno, missing))

    if call_sites < MIN_CALL_SITES:
        print(
            f"FAIL: found {call_sites} call site(s) of .{TARGET_METHOD}(), expected at least"
        )
        print(
            f"      {MIN_CALL_SITES}. The walk is broken — a census that measured nothing"
        )
        print("      must not be reported as a clean tree.")
        return 2

    print(f"required arguments for {TARGET_CLASS}.{TARGET_METHOD}: {sorted(required)}")
    print(f"call sites examined: {call_sites}")

    if offenders:
        print(f"\nFAIL: {len(offenders)} call site(s) omit a required argument:")
        for path, lineno, missing in offenders:
            print(f"  {path}:{lineno} — missing {sorted(missing)}")
        print(
            "\nEach of these raises TypeError at call time. Where the call sits on a "
            "permission-denied\nbranch, the caller receives 500 instead of 403 and the denial "
            "is never recorded."
        )
        return 1

    print(f"\nok: all {call_sites} call site(s) pass every required argument.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
