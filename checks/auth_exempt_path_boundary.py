"""Auth-exempt paths must match on a PATH-SEGMENT boundary, not a string prefix.

THE DEFECT THIS CATCHES
-----------------------
`src/keycloak_auth/middleware.py :: KeycloakAuthMiddleware._is_excluded_path` decides which
requests skip Keycloak authentication entirely. After an exact-match test against
`PUBLIC_ENDPOINTS` it does

    excluded_prefixes = ["/docs", "/redoc", "/static", "/openapi.json"]
    return any(clean_path.startswith(prefix) for prefix in excluded_prefixes)

`str.startswith` is a raw prefix test, not a path-segment test, so any route whose path merely
BEGINS with those characters is served WITHOUT a token. Measured against the shipped method:

    /docsabc            -> EXEMPT   (not the docs UI)
    /static-x/keys      -> EXEMPT   (not the static mount)
    /openapi.json.bak   -> EXEMPT
    /redocxyz           -> EXEMPT

`dispatch` consults this method BEFORE the `auth_enabled` switch and before any token is read,
so whatever the router does with such a path -- a real handler, a mount, a 404 from an
unauthenticated probe -- happens with no identity attached. The exemption is meant for exactly
four well-known surfaces; the prefix test hands it to an unbounded family of names.

CORRECT BEHAVIOUR
-----------------
A path is exempt by prefix only when it IS the prefix or sits UNDER it as a segment:

    clean_path == prefix or clean_path.startswith(prefix + "/")

Exact `PUBLIC_ENDPOINTS` matches (`/`, `/health`, ...) keep working unchanged.

⚠️ TWO SUFFICIENT SIGNALS -- READ BEFORE READING A VERDICT. The live app constructs the
middleware with no `excluded_paths` (`src/asgi.py: app.add_middleware(KeycloakAuthMiddleware)`),
so `self.excluded_paths` IS `PUBLIC_ENDPOINTS`, and `/docs`, `/redoc`, `/openapi.json` are exempt
by the EXACT block regardless of what the prefix rule does. This oracle grades the method as the
live app runs it, so a repair that narrows the prefix rule to `startswith(prefix + "/")` alone
is behaviourally correct HERE -- `/docs` still passes via the exact list -- and exits 0. That is
the honest measurement of the live disjunction, not a blind spot: the same spelling with the
exact block removed exits 1 (measured in the hardening notes below). Do not read "exit 0" as
"the prefix rule alone is complete".

WHY THIS CHECK EXECUTES THE REAL METHOD RATHER THAN MATCHING ITS SHAPE
----------------------------------------------------------------------
A structural rule ("no `startswith`") is gameable and dictates one implementation. This oracle
LOCATES `_is_excluded_path` in the real source, compiles it -- together with the module-level
constants and helper definitions it reads, and the `self.*` attributes `__init__` binds without
calling anything -- and EVALUATES it against generated paths. It grades BEHAVIOUR:

  * a segment-boundary comparison, a `split("/")[1]` membership test, a regex anchored on `/`
    or `$`, a helper, a `continue`/early-`return` loop: all pass if they separate the sets;
  * any rule that still exempts `/docs{junk}` fails; any rule that stops exempting `/docs/x`
    or `/static/css/x.css` fails SEPARATELY (over-correction is reported, never merged).

The application is NEVER imported: `src.keycloak_auth` needs settings, Keycloak and a DB at
import time. Only `re`-free-of-side-effects stdlib imports found in the file are executed.

⛔ AND THE CASES ARE GENERATED, NOT ENUMERATED. Every hostile and legitimate path carries fresh
random labels, so a denylist tuned to a fixed fixture cannot pass. The REFERENCE rule must
reject every hostile case and accept every legitimate case BEFORE anything is graded; if it
does not, the oracle refuses to grade (exit 2) rather than ask an unfair question.

Run from the repository root:

    python -m checks.auth_exempt_path_boundary

`ORACLE_SRC_OVERRIDE=/path/to/middleware.py` grades that file instead of `src/` -- for
hardening the oracle against candidate fixes without touching the tree. The override is printed
loudly; a verdict over an override is never a verdict over `src/`.

Exit codes:
    0 - every generated hostile path is AUTHENTICATED and every legitimate path is still EXEMPT.
    1 - at least one hostile path exempt (expected on today's main), OR a legitimate path now
        authenticated (an over-correction). Reported separately, never merged.
    2 - the harness measured nothing: file, class, method, `PUBLIC_ENDPOINTS` or the dispatch
        call site could not be located, a free name could not be supplied, the method raised,
        or the reference rule failed its own fairness check.
        "This check measured nothing; do not read it as a pass."
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import random
import string
import sys
from pathlib import Path

EXIT_FIXED, EXIT_DEFECT, EXIT_NO_MEASUREMENT = 0, 1, 2

DEFAULT_SRC = (
    Path(__file__).resolve().parent.parent / "src" / "keycloak_auth" / "middleware.py"
)
TARGET_METHOD = "_is_excluded_path"
CALLER_METHOD = "dispatch"
PUBLIC_LIST_NAME = "PUBLIC_ENDPOINTS"

# THE SPECIFICATION of the prefix exemption -- the four surfaces the shipped method names.
# Hard-coded on purpose: the reference rule must not be derived from the code under test, or
# a fix that silently widened the list would grade itself.
EXEMPT_PREFIXES = ("/docs", "/redoc", "/static", "/openapi.json")

# Builtin constructors the oracle may evaluate over call-free arguments (as in the sibling
# oracle `redirect_uri_host_boundary`). `re.<fn>(...)` is additionally allowed at module /
# class / __init__ level: a regex-based repair typically precompiles its pattern there, and
# refusing it with exit 2 would turn a gradeable WRONG fix into "measured nothing".
_PURE_CTORS = frozenset({"frozenset", "set", "tuple", "list", "dict"})
_PURE_MODULES = frozenset({"re"})
_BUILTIN_DECORATORS = frozenset({"staticmethod", "classmethod", "property"})

_LABEL_ALPHABET = string.ascii_lowercase
# Labels that would collide with a real exempt name and make a "hostile" case legitimate.
_RESERVED_LABELS = frozenset({"docs", "redoc", "static", "health", "openapi"})
_MAX_ATTEMPTS = 200
_MAX_NAME_RESOLUTIONS = 12


def _safe_label() -> str:
    for _ in range(_MAX_ATTEMPTS):
        label = "".join(
            random.choice(_LABEL_ALPHABET) for _ in range(random.randint(4, 8))
        )
        if label not in _RESERVED_LABELS:
            return label
    raise RuntimeError(f"no safe label in {_MAX_ATTEMPTS} attempts")


def _reference_exempt(path: str, public: list[str]) -> bool:
    """The REFERENCE rule. Used only to construct fair questions -- never to grade."""
    clean = path.rstrip("/") or "/"
    if clean in public:
        return True
    return any(clean == p or clean.startswith(p + "/") for p in EXEMPT_PREFIXES)


def generate_hostile_paths(public: list[str]) -> list[tuple[str, str]]:
    """(path, why) for paths that merely START WITH an exempt name. None may be exempt."""
    out: list[tuple[str, str]] = []
    stems = list(EXEMPT_PREFIXES) + [
        p for p in public if p != "/" and p not in EXEMPT_PREFIXES
    ]
    for stem in stems:
        for shape, why in (
            ("{stem}{lab}", "junk glued directly to the exempt name"),
            ("{stem}-{lab}/x", "hyphenated sibling with a sub-path"),
            ("{stem}_{lab}", "underscore sibling (a regex \\b does NOT fire here)"),
            ("{stem}.{lab}", "dotted sibling (a regex \\b DOES fire here)"),
        ):
            out.append((shape.format(stem=stem, lab=_safe_label()), f"{why}: {stem}"))
    a, b = _safe_label(), _safe_label()
    out += [
        (f"/{a}", "arbitrary top-level route: `/` is exact-only, never a prefix"),
        (f"/{a}/{b}", "arbitrary nested route"),
        (f"/{a}/docs", "exempt name in a NON-leading segment"),
        (f"/{a}/static/{b}.css", "exempt name in a NON-leading segment with sub-path"),
    ]
    return out


def generate_legitimate_paths(public: list[str]) -> list[tuple[str, str]]:
    """(path, why) for paths that MUST stay exempt. Catches an over-correction."""
    a, b = _safe_label(), _safe_label()
    cands: list[tuple[str, str]] = [
        ("/docs", "docs UI, exact"),
        ("/docs/", "docs UI, trailing slash"),
        (f"/docs/{a}", "docs UI sub-path (e.g. /docs/oauth2-redirect)"),
        ("/redoc", "redoc UI, exact"),
        ("/openapi.json", "OpenAPI schema, exact"),
        (f"/static/{a}.css", "static asset"),
        (f"/static/css/{b}.css", "nested static asset"),
    ]
    seen = {p for p, _ in cands}
    for entry in public:
        if entry not in seen:
            cands.append((entry, f"{PUBLIC_LIST_NAME} entry"))
            seen.add(entry)
    return cands


# ----------------------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------------------


def _evaluable(n: ast.AST) -> bool:
    """True if evaluating `n` runs no application code (see _PURE_CTORS / _PURE_MODULES)."""
    for x in ast.walk(n):
        if isinstance(x, ast.Await | ast.Yield | ast.YieldFrom):
            return False
        if isinstance(x, ast.Call):
            f = x.func
            if isinstance(f, ast.Name) and f.id in _PURE_CTORS and not x.keywords:
                continue
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in _PURE_MODULES
            ):
                continue
            return False
    return True


def _strip_decorators(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    fn.decorator_list = [
        d
        for d in fn.decorator_list
        if isinstance(d, ast.Name) and d.id in _BUILTIN_DECORATORS
    ]


def _exec_resolving(code, ns: dict) -> None:
    """exec `code` in `ns`, importing any missing STDLIB name on demand (as the sibling oracle
    does) so a repair that reaches for `re` / `posixpath` / `fnmatch` grades equally."""
    for _ in range(_MAX_NAME_RESOLUTIONS):
        try:
            exec(code, ns, ns)  # noqa: S102
            return
        except NameError as exc:
            missing = getattr(exc, "name", None)
            if not missing or missing in ns:
                raise
            if missing not in sys.stdlib_module_names:
                raise RuntimeError(
                    f"free variable {missing!r} is not a stdlib module and was not bound by an "
                    "evaluable assignment; this oracle cannot supply it"
                ) from None
            ns[missing] = importlib.import_module(missing)
    raise RuntimeError("too many unresolved names")  # pragma: no cover


def _extract_predicate(tree: ast.Module):
    """Return (exempt: Callable[[str], bool], public: list[str]).

    Raises RuntimeError with a reason when it cannot -- every reason maps to exit 2.
    """
    ns: dict[str, object] = {"__name__": "<oracle>"}

    # 1. PUBLIC_ENDPOINTS as data -- the reference rule needs the LIST, not the code.
    public: list[str] | None = None
    for st in tree.body:
        if isinstance(st, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == PUBLIC_LIST_NAME for t in st.targets
        ):
            try:
                value = ast.literal_eval(st.value)
            except ValueError as exc:
                raise RuntimeError(
                    f"{PUBLIC_LIST_NAME} is not a literal: {exc}"
                ) from None
            if not isinstance(value, list | tuple | set | frozenset) or not all(
                isinstance(v, str) for v in value
            ):
                raise RuntimeError(f"{PUBLIC_LIST_NAME} is not a collection of str")
            public = list(value)
    if public is None:
        raise RuntimeError(f"module-level {PUBLIC_LIST_NAME} not found")

    # 2. Module level: stdlib imports, helper defs, evaluable constants -- in source order.
    module_stmts: list[ast.stmt] = []
    for st in tree.body:
        if isinstance(st, ast.Import):
            names = [
                a for a in st.names if a.name.split(".")[0] in sys.stdlib_module_names
            ]
            if names:
                module_stmts.append(ast.Import(names=names))
        elif isinstance(st, ast.ImportFrom):
            if (
                st.level == 0
                and st.module
                and st.module.split(".")[0] in sys.stdlib_module_names
            ):
                module_stmts.append(st)
        elif isinstance(st, ast.FunctionDef | ast.AsyncFunctionDef):
            _strip_decorators(st)
            module_stmts.append(st)
        elif isinstance(st, ast.Assign | ast.AnnAssign) and st.value is not None:
            if _evaluable(st.value):
                module_stmts.append(st)

    # 3. The class that owns the predicate, and the proof that dispatch still consults it.
    owner: ast.ClassDef | None = None
    for st in tree.body:
        if isinstance(st, ast.ClassDef) and any(
            isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
            and m.name == TARGET_METHOD
            for m in st.body
        ):
            owner = st
            break
    if owner is None:
        raise RuntimeError(f"no class defines {TARGET_METHOD}")

    caller = next(
        (
            m
            for m in owner.body
            if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
            and m.name == CALLER_METHOD
        ),
        None,
    )
    if caller is None:
        raise RuntimeError(f"{owner.name} has no {CALLER_METHOD}")
    if not any(
        isinstance(x, ast.Attribute) and x.attr == TARGET_METHOD
        for x in ast.walk(caller)
    ):
        raise RuntimeError(
            f"{CALLER_METHOD} no longer consults {TARGET_METHOD}; the decision moved and this "
            "oracle cannot locate it"
        )

    class_body: list[ast.stmt] = []
    init: ast.FunctionDef | None = None
    for m in owner.body:
        if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef):
            if m.name == "__init__":
                init = m
                continue  # simulated below, never executed: it constructs settings + validator
            _strip_decorators(m)
            class_body.append(m)
        elif isinstance(m, ast.Assign | ast.AnnAssign) and m.value is not None:
            if _evaluable(m.value):
                class_body.append(m)
    stub = ast.ClassDef(
        name="__Stub",
        bases=[],
        keywords=[],
        body=class_body or [ast.Pass()],
        decorator_list=[],
        type_params=[],
    )
    module = ast.Module(body=[*module_stmts, stub], type_ignores=[])
    ast.fix_missing_locations(module)
    _exec_resolving(compile(module, filename="<middleware>", mode="exec"), ns)

    if (
        ns.get(PUBLIC_LIST_NAME) != public
    ):  # pragma: no cover - literal_eval vs exec agree
        raise RuntimeError(f"{PUBLIC_LIST_NAME} evaluated differently by two routes")

    # 4. Instantiate WITHOUT running __init__, then replay only its evaluable `self.X = ...`
    #    bindings with the constructor's parameters at their live values: the app does
    #    `app.add_middleware(KeycloakAuthMiddleware)`, so every optional parameter is at its
    #    default. That is what makes `self.excluded_paths = excluded_paths or PUBLIC_ENDPOINTS`
    #    resolve to PUBLIC_ENDPOINTS here, exactly as it does in the running process.
    stub_cls = ns["__Stub"]
    obj = stub_cls.__new__(stub_cls)
    if init is not None:
        init_ns: dict[str, object] = dict(ns)
        init_ns["self"] = obj
        args = init.args
        positional = args.posonlyargs + args.args
        defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
        for param, default in zip(positional, defaults, strict=True):
            if param.arg == "self":
                continue
            init_ns[param.arg] = (
                ast.literal_eval(default) if isinstance(default, ast.Constant) else None
            )
        for param, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            init_ns[param.arg] = (
                ast.literal_eval(default) if isinstance(default, ast.Constant) else None
            )
        replay: list[ast.stmt] = []
        for st in init.body:
            if (
                isinstance(st, ast.Assign | ast.AnnAssign)
                and st.value is not None
                and _evaluable(st.value)
            ):
                targets = st.targets if isinstance(st, ast.Assign) else [st.target]
                if all(
                    isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == "self"
                    for t in targets
                ):
                    replay.append(st)
        if replay:
            mod = ast.Module(body=replay, type_ignores=[])
            ast.fix_missing_locations(mod)
            _exec_resolving(compile(mod, filename="<__init__>", mode="exec"), init_ns)

    method = getattr(obj, TARGET_METHOD, None)
    if not callable(method):
        raise RuntimeError(  # noqa: TRY004 -- a refusal to grade, not a type error; main() maps it to exit 2
            f"{TARGET_METHOD} is not callable on the reconstructed instance"
        )

    def exempt(path: str) -> bool:
        result = method(path)
        if inspect.iscoroutine(result):
            # An async predicate would be TRUTHY as a coroutine object -- a false "exempt"
            # for every path. Run it rather than grade its truthiness.
            import asyncio

            result = asyncio.run(result)
        return bool(result)  # dispatch tests truthiness, so the oracle does too

    return exempt, public


# ----------------------------------------------------------------------------------------
# Verdict
# ----------------------------------------------------------------------------------------


def _no_measurement(reason: str) -> int:
    print(f"HARNESS: {reason}")
    print("This check measured nothing; do not read it as a pass.")
    return EXIT_NO_MEASUREMENT


def main() -> int:
    override = os.environ.get("ORACLE_SRC_OVERRIDE")
    src = Path(override).resolve() if override else DEFAULT_SRC
    if override:
        print(
            f"⚠️  ORACLE_SRC_OVERRIDE is set: grading {src}, NOT src/. "
            "This verdict says nothing about the tree."
        )

    if not src.exists():
        return _no_measurement(f"{src} not found.")
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return _no_measurement(f"could not parse {src}: {exc}")

    try:
        exempt, public = _extract_predicate(tree)
    except Exception as exc:
        return _no_measurement(f"extracting {TARGET_METHOD} failed: {exc!r}")

    try:
        hostile = generate_hostile_paths(public)
        legitimate = generate_legitimate_paths(public)
    except RuntimeError as exc:
        return _no_measurement(str(exc))

    # Fairness: the REFERENCE must separate the sets, or the question is unfair.
    unfair_h = [p for p, _ in hostile if _reference_exempt(p, public)]
    unfair_l = [p for p, _ in legitimate if not _reference_exempt(p, public)]
    if unfair_h or unfair_l:
        return _no_measurement(
            f"reference rule failed its own fairness check: hostile-but-exempt={unfair_h} "
            f"legitimate-but-authenticated={unfair_l}"
        )
    expected_hostile = 4 * len({*EXEMPT_PREFIXES, *(p for p in public if p != "/")}) + 4
    if len(hostile) != expected_hostile:
        return _no_measurement(
            f"generated {len(hostile)} hostile cases, expected {expected_hostile}"
        )
    if len(legitimate) < 7:
        return _no_measurement(
            f"generated {len(legitimate)} legitimate cases, expected >= 7"
        )

    wrongly_exempt: list[tuple[str, str]] = []
    wrongly_authenticated: list[tuple[str, str]] = []
    for path, why in hostile:
        try:
            verdict = exempt(path)
        except Exception as exc:
            return _no_measurement(f"{TARGET_METHOD} raised on {path!r}: {exc!r}")
        if verdict:
            wrongly_exempt.append((path, why))
    for path, why in legitimate:
        try:
            verdict = exempt(path)
        except Exception as exc:
            return _no_measurement(f"{TARGET_METHOD} raised on {path!r}: {exc!r}")
        if not verdict:
            wrongly_authenticated.append((path, why))

    print(
        f"hostile paths authenticated: {len(hostile) - len(wrongly_exempt)}/{len(hostile)}"
    )
    print(
        f"legitimate paths exempt:     "
        f"{len(legitimate) - len(wrongly_authenticated)}/{len(legitimate)}"
    )

    if wrongly_exempt:
        print("\nEXEMPT FROM AUTHENTICATION BY A RAW PREFIX MATCH (the defect):")
        for path, why in wrongly_exempt:
            print(f"  {path:36s} [{why}]")
    if wrongly_authenticated:
        print(
            "\n⛔ LEGITIMATE PATH NOW REQUIRES A TOKEN (over-correction -- NOT a fix):"
        )
        for path, why in wrongly_authenticated:
            print(f"  {path:36s} [{why}]")

    if wrongly_exempt or wrongly_authenticated:
        return EXIT_DEFECT

    # Certifies only what was measured: these generated shapes, under the live construction.
    print(
        "\nAll generated hostile paths require authentication and every legitimate path "
        "stays exempt (glued, hyphenated, underscored, dotted siblings; non-leading segments)."
    )
    return EXIT_FIXED


if __name__ == "__main__":
    sys.exit(main())
