"""Every `X.HTTP_*` reference under `src/` must resolve to a real status constant.

`get_audit_logs` in `src/audit_api.py` once wrote `status.HTTP_500_INTERNAL_SERVER_ERROR` in
a function that declares a query parameter named `status`, in a module that never imported
`fastapi.status`. The name bound to the parameter, so the error path raised `AttributeError`
instead of returning the intended 500, and the error detail was lost.
`tests/test_audit_api_error_path.py` pins that one handler's behaviour. This file covers every
module under `src/`.

For each `X.HTTP_*` attribute reference it asserts that:

* `X` is not shadowed by a parameter of an enclosing function;
* `X` is bound at module level by an import; and
* the imported object really has that `HTTP_*` attribute (so a typo such as
  `status.HTTP_404_NOTFOUND` fails here rather than on the error path it guards).

A walk that finds no references fails rather than passing.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"

_UNRESOLVED = object()


def _module_name(path: pathlib.Path) -> str:
    return ".".join(path.relative_to(REPO).with_suffix("").parts)


def _resolve_import(module: str, name: str | None) -> Any:
    """Return the object an import statement binds, or _UNRESOLVED."""
    try:
        if name is None:
            return importlib.import_module(module)
        mod = importlib.import_module(module)
        if hasattr(mod, name):
            return getattr(mod, name)
        return importlib.import_module(f"{module}.{name}")
    except ImportError:
        return _UNRESOLVED


def _module_imports(tree: ast.Module) -> dict[str, ast.stmt]:
    """Module-level names bound by import statements, mapped to the statement."""
    names: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                names[bound] = node
    return names


def _bound_object(stmt: ast.stmt, bound: str, path: pathlib.Path) -> Any:
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            if (alias.asname or alias.name.split(".")[0]) == bound:
                target = alias.name if alias.asname else alias.name.split(".")[0]
                return _resolve_import(target, None)
    elif isinstance(stmt, ast.ImportFrom):
        module = stmt.module or ""
        if stmt.level:
            package = _module_name(path).split(".")[: -stmt.level]
            module = ".".join([*package, module] if module else package)
        for alias in stmt.names:
            if (alias.asname or alias.name) == bound:
                return _resolve_import(module, alias.name)
    return _UNRESOLVED


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    a = fn.args
    names = {p.arg for p in a.posonlyargs + a.args + a.kwonlyargs}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


class _Collector(ast.NodeVisitor):
    """Collects (node, enclosing parameter names) for every `Name.HTTP_*` attribute."""

    def __init__(self) -> None:
        self.scopes: list[set[str]] = []
        self.sites: list[tuple[ast.Attribute, set[str]]] = []

    def _visit_function(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Decorators, defaults and annotations are evaluated in the ENCLOSING scope.
        for d in fn.decorator_list:
            self.visit(d)
        self.visit(fn.args)
        if fn.returns:
            self.visit(fn.returns)
        self.scopes.append(_params(fn))
        for stmt in fn.body:
            self.visit(stmt)
        self.scopes.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.visit(node.args)
        self.scopes.append(_params(node))
        self.visit(node.body)
        self.scopes.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("HTTP_") and isinstance(node.value, ast.Name):
            enclosing = set().union(*self.scopes) if self.scopes else set()
            self.sites.append((node, enclosing))
        self.generic_visit(node)


def test_every_http_status_reference_resolves() -> None:
    sites = 0
    modules: set[str] = set()
    offenders: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = _module_imports(tree)
        collector = _Collector()
        collector.visit(tree)
        rel = path.relative_to(REPO)

        for node, enclosing in collector.sites:
            sites += 1
            modules.add(str(rel))
            name = node.value.id  # type: ignore[attr-defined]
            ref = f"{rel}:{node.lineno}: `{name}.{node.attr}`"
            if name in enclosing:
                offenders.append(
                    f"{ref} -- `{name}` is a parameter of an enclosing function"
                )
                continue
            stmt = imports.get(name)
            if stmt is None:
                offenders.append(f"{ref} -- `{name}` is not imported at module level")
                continue
            obj = _bound_object(stmt, name, path)
            if obj is _UNRESOLVED:
                offenders.append(
                    f"{ref} -- the import binding `{name}` cannot be resolved"
                )
            elif not isinstance(getattr(obj, node.attr, None), int):
                offenders.append(
                    f"{ref} -- `{node.attr}` is not an integer constant on "
                    f"{getattr(obj, '__name__', type(obj).__name__)}"
                )

    assert sites, (
        "found 0 HTTP_* references under src/; the walk found nothing to check"
    )
    assert not offenders, (
        f"{len(offenders)} of {sites} HTTP_* reference(s) in {len(modules)} module(s) "
        "do not resolve:\n  " + "\n  ".join(offenders)
    )
