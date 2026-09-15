"""Every `X.HTTP_*` constant must resolve to an imported status module.

THE DEFECT THIS EXISTS FOR: `src/audit_api.py` declares a query parameter
`status: str | None = None` on `get_audit_logs`, and its except-handler writes
`status_code=status.HTTP_500_INTERNAL_SERVER_ERROR`. That name binds to the
PARAMETER, not to `fastapi.status` -- which the module does not import at all.
So the error path raises `AttributeError: 'NoneType' object has no attribute
'HTTP_500_INTERNAL_SERVER_ERROR'` instead of the intended HTTPException(500),
the operator-facing detail is destroyed, and the traceback names the wrong fault.

Stdlib only, no install, no dependency on the application importing cleanly:

    python -m checks.http_status_binding

Exit 0 = every site resolves.  Exit 1 = at least one does not.
Exit 2 = the check could not measure anything and must not be read as a pass.
"""

from __future__ import annotations

import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# A walk that examined nothing must never print "ok". If this floor is ever not
# met, the scan is blinded (src/ moved, parse failure, pattern changed) and the
# correct answer is "I could not tell", not "clean".
MIN_SITES = 1


def module_bindings(tree: ast.Module) -> set[str]:
    """Names bound at module level: imports, defs, and simple assignments."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def function_params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    a = fn.args
    params = {p.arg for p in a.posonlyargs + a.args + a.kwonlyargs}
    if a.vararg:
        params.add(a.vararg.arg)
    if a.kwarg:
        params.add(a.kwarg.arg)
    return params


def main() -> int:
    sites = 0
    offenders: list[str] = []

    for path in sorted((REPO / "src").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"FAIL: {path.relative_to(REPO)} does not parse: {exc}")
            return 2

        bound = module_bindings(tree)

        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = function_params(fn)
            for node in ast.walk(fn):
                if not (
                    isinstance(node, ast.Attribute) and node.attr.startswith("HTTP_")
                ):
                    continue
                if not isinstance(node.value, ast.Name):
                    continue
                sites += 1
                rel = path.relative_to(REPO)
                name = node.value.id
                if name in params:
                    offenders.append(
                        f"  {rel}:{node.lineno} -- `{name}.{node.attr}` resolves to the "
                        f"parameter `{name}` of {fn.name}(), not to fastapi.status"
                    )
                elif name not in bound:
                    offenders.append(
                        f"  {rel}:{node.lineno} -- `{name}.{node.attr}`: `{name}` is never "
                        f"imported or defined at module level in {rel.name}"
                    )

    if sites < MIN_SITES:
        print(f"FAIL: examined {sites} HTTP_* constant site(s); the walk is blinded.")
        return 2

    print(f"HTTP_* constant sites examined: {sites}")

    if offenders:
        print(
            f"\nFAIL: {len(offenders)} site(s) do not resolve to an imported status module:"
        )
        print("\n".join(offenders))
        print("\nEach one raises AttributeError/NameError on the error path it guards,")
        print("destroying the response detail it was written to provide.")
        return 1

    print(f"\nok: all {sites} site(s) resolve to an imported status module.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
