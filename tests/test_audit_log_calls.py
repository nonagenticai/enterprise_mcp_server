"""Every `log_event(...)` call under `src/` must bind to `AuditLogService.log_event`'s signature.

`AuditLogService.log_event` (src/audit.py) declares several parameters without a default,
including `resource_id`. A call site that omits one raises `TypeError` at call time. On a
permission-denied branch that means the caller receives a 500 instead of a 403 and the
denial is never written to the audit log -- the one record the call exists to produce.

`tests/test_tool_list_denial_audit.py` exercises one such branch end to end. This file covers
the rest of the tree: it walks every Python module under `src/`, finds every call whose callee
is named `log_event`, and binds its arguments against the real signature obtained with
`inspect.signature`. Adding or renaming a required parameter re-judges every call site
automatically; there is no list of names to keep in sync here.

A walk that finds no call sites fails rather than passing, so a moved `src/` directory or a
renamed method cannot turn this into a test that checks nothing.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

from src.audit import AuditLogService

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
METHOD = "log_event"


def _call_sites() -> list[tuple[pathlib.Path, ast.Call]]:
    sites: list[tuple[pathlib.Path, ast.Call]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if name == METHOD:
                sites.append((path, node))
    return sites


def _signature_without_self() -> inspect.Signature:
    sig = inspect.signature(AuditLogService.log_event)
    params = [p for name, p in sig.parameters.items() if name != "self"]
    return sig.replace(parameters=params)


def test_signature_has_required_parameters() -> None:
    sig = _signature_without_self()
    required = [
        p.name
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    # If this ever becomes empty, every call site binds trivially and the test below proves
    # nothing; fail so the test gets revisited instead.
    assert required, (
        "log_event has no required parameters; the call-site test is vacuous"
    )
    assert "resource_id" in required


def test_every_log_event_call_passes_every_required_argument() -> None:
    sig = _signature_without_self()
    sites = _call_sites()
    assert sites, (
        f"found 0 calls to {METHOD}() under src/; the walk found nothing to check"
    )

    offenders: list[str] = []
    checked = 0
    for path, call in sites:
        # `*args` / `**kwargs` forwarding can satisfy anything; it cannot be judged statically.
        if any(isinstance(a, ast.Starred) for a in call.args) or any(
            k.arg is None for k in call.keywords
        ):
            continue
        checked += 1
        args = [None] * len(call.args)
        kwargs = {k.arg: None for k in call.keywords}
        try:
            sig.bind(*args, **kwargs)
        except TypeError as exc:
            offenders.append(f"{path.relative_to(REPO)}:{call.lineno}: {exc}")

    assert checked, (
        f"all {len(sites)} {METHOD}() call(s) were skipped; nothing was checked"
    )
    assert not offenders, (
        f"{len(offenders)} of {checked} {METHOD}() call(s) do not match "
        f"AuditLogService.log_event{sig}:\n  " + "\n  ".join(offenders)
    )
