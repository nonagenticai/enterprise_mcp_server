"""Redirect-URI validation must compare the HOST, not a string prefix.

THE DEFECT THIS CATCHES
-----------------------
`src/api.py :: register_client` (POST /register) validates OAuth redirect URIs with

    if not uri.startswith(("https://", "http://localhost")):
        raise HTTPException(400, "Redirect URIs must use HTTPS except for localhost")

`str.startswith` is a raw prefix test, not a host-boundary test, so any hostname that merely
BEGINS with the characters `localhost` satisfies it over plain HTTP. Measured against the
shipped expression:

    http://localhost.attacker.example/cb   -> ACCEPTED   (real host: localhost.attacker.example)
    http://localhostx.evil.com/cb          -> ACCEPTED   (real host: localhostx.evil.com)

An OAuth client may therefore be registered whose redirect target is an attacker-controlled
domain reached over cleartext HTTP -- which is precisely what the guard exists to prevent. The
400 whose message reads "must use HTTPS except for localhost" never fires for those inputs.

SEVERITY, STATED HONESTLY
-------------------------
`register_client` is gated by `Depends(requires_permission("oauth:register"))`, so this is NOT
anonymously reachable. It is defence-in-depth against a compromised or malicious AUTHORISED
registrant, not an open door. Recorded here so no reader over- or under-reads it.

CORRECT BEHAVIOUR
-----------------
Accept a URI only if its scheme is `https`, or its scheme is `http` AND its PARSED hostname is
exactly a loopback name (`localhost` / `127.0.0.1` / `::1`). `urlparse(uri).hostname` is the
only thing that answers "which host is this really".

WHY THIS CHECK EXECUTES THE REAL EXPRESSION RATHER THAN MATCHING ITS SHAPE
--------------------------------------------------------------------------
A structural check ("the file must not call `startswith`") is gameable and, worse, dictates one
implementation. This oracle instead LOCATES the acceptance decision in the real source and
EVALUATES it against generated URIs, so it grades BEHAVIOUR:

  * any implementation that genuinely compares the parsed host passes -- `urlparse`, a regex
    with a host anchor, a helper function, an allowlist of loopback names;
  * any implementation that accepts a non-loopback host over http fails.

⛔ AND THE CASES ARE GENERATED, NOT ENUMERATED. A hand-written list of bad hostnames loses a
race against a rule tuned to that list: a denylist stripping `localhost.attacker.example` would
pass a fixed sweep while leaving the defect live. Fresh random labels each run close that.
(Learned the expensive way on a sibling oracle, where FIVE distinct non-fixes each scored a
perfect hand-picked sweep and exited 0.)

Run from the repository root:

    python -m checks.redirect_uri_host_boundary

Exit codes:
    0 - every generated hostile host is REJECTED and every legitimate URI is still ACCEPTED.
    1 - at least one hostile host accepted (expected on today's main), OR a legitimate URI
        broken by an over-correction. The two are reported SEPARATELY and never merged --
        a change that blocks `http://localhost:8080` is not a fix.
    2 - the harness measured nothing: the function, the loop, or the acceptance decision could
        not be located, or no safe label could be drawn. "This check measured nothing; do not
        read it as a pass."
"""

import ast
import importlib
import random
import string
import sys
from pathlib import Path
from urllib.parse import urlparse

EXIT_FIXED, EXIT_DEFECT, EXIT_NO_MEASUREMENT = 0, 1, 2

# Compound statements under which a `raise`'s reachability cannot be folded into a boolean.
# Module-level on purpose: defined inside the extractor's loop it was a late-bound capture
# (ruff B023) -- harmless in practice, but a constant belongs at exactly one scope.
_UNFOLDABLE = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Match,
)

SRC = Path(__file__).resolve().parent.parent / "src" / "api.py"
TARGET_FUNC = "register_client"
LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}
_LABEL_ALPHABET = string.ascii_lowercase
_MAX_ATTEMPTS = 200


def _safe_label() -> str:
    """A random DNS label that is not itself a loopback name."""
    for _ in range(_MAX_ATTEMPTS):
        label = "".join(
            random.choice(_LABEL_ALPHABET) for _ in range(random.randint(4, 8))
        )
        if label not in LOOPBACK and "localhost" not in label:
            return label
    raise RuntimeError(f"no safe label in {_MAX_ATTEMPTS} attempts")


def _should_accept(uri: str) -> bool:
    """The REFERENCE rule. Used only to construct fair questions -- never to grade."""
    parsed = urlparse(uri)
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and (parsed.hostname or "") in LOOPBACK


def generate_hostile_uris() -> list[tuple[str, str]]:
    """(uri, why) for hostnames that merely START WITH or CONTAIN `localhost`.

    Every one has a parsed hostname that is NOT loopback, over http, so a correct
    implementation must reject all of them.
    """
    out: list[tuple[str, str]] = []
    for shape, why in (
        # --- host-position gluing: the literal bytes 'localhost' inside a larger host ---
        ("http://localhost{lab}.example/cb", "suffix glued to localhost"),
        ("http://localhost.{lab}.com/cb", "localhost as a leading label"),
        ("http://{lab}localhost/cb", "prefix glued to localhost"),
        ("http://localhost{lab}/cb", "no dot, glued directly"),
        ("http://{lab}.localhost.{lab2}.net/cb", "localhost buried mid-name"),
        # --- ⛔ USERINFO: 'localhost' is NOT the host at all, it is the credential. ---
        # `http://localhost:@attacker.example/cb` parses to hostname=attacker.example, yet the
        # string still STARTS WITH 'http://localhost:'. An adversarial review passed the whole
        # oracle with `startswith("http://localhost/") or startswith("http://localhost:")` --
        # a smarter prefix rule that is still a prefix rule -- because every case above puts
        # 'localhost' in host position. These put it in userinfo, where only a real URL parse
        # can tell the difference. This is the classic embedded-credentials redirect bypass.
        (
            "http://localhost:@{lab}.example/cb",
            "userinfo: 'localhost:' as empty-password user",
        ),
        (
            "http://localhost:{lab2}@{lab}.example/cb",
            "userinfo: 'localhost' as user with a password",
        ),
        ("http://localhost@{lab}.example/cb", "userinfo: bare 'localhost@'"),
        (
            "http://localhost:8080@{lab}.example/cb",
            "userinfo: mimics a port before the real host",
        ),
    ):
        uri = shape.format(lab=_safe_label(), lab2=_safe_label())
        if _should_accept(uri):  # pragma: no cover - fairness guard
            continue
        out.append((uri, why))
    return out


# Must KEEP being accepted. These catch an over-correction.
#
# ⚠️ `http://127.0.0.1:3000/cb` is DELIBERATELY ABSENT, and its absence is the point.
# Today's main REJECTS it: the shipped prefix test allows `http://localhost` but not
# loopback-by-IP, so a perfectly ordinary dev callback is refused. That is a real, separate
# observation -- but it is a BEHAVIOUR CHANGE, not this defect. Including it here would make
# this oracle demand a feature alongside the fix, so a change that correctly repairs the
# host-boundary bug would still fail. One oracle, one property.
# ⇒ If loopback-by-IP should be accepted, that is its own card. Recorded, not required.
#
# ⛔ GENERATED, for the same reason the hostile side is. A second adversarial review passed the
# oracle with `startswith("http://localhost:") and "@" not in uri` -- 9/9, 4/4, exit 0 -- because
# no fixed legitimate case carried an `@` outside the host. That rule wrongly rejects
# `http://localhost:8080/cb?state=x@y`. A fixed fixture on ONE side of a generated oracle is
# exactly the asymmetry that lets a heuristic hide. So these vary path, query and fragment, and
# deliberately place `@` and `localhost`-lookalikes where a real URL parse must NOT care.
def generate_legitimate_uris() -> list[str]:
    a, b = _safe_label(), _safe_label()
    port = random.choice(("3000", "5173", "8080", "8443"))
    cands = [
        f"https://{a}.example.com/callback",
        f"https://{a}.example.com/cb?state={b}",
        f"https://{a}.example.com/cb?next=user@{b}.example",  # '@' in QUERY
        f"https://{a}.example.com/cb#frag@{b}",  # '@' in FRAGMENT
        "http://localhost/cb",
        f"http://localhost:{port}/cb",
        f"http://localhost:{port}/cb?state=x@y",  # '@' in QUERY on a loopback host
        f"http://localhost/{a}/cb?redirect=localhost{b}",  # lookalike only in the path/query
    ]
    fair = [u for u in cands if _should_accept(u)]
    if len(fair) != len(
        cands
    ):  # pragma: no cover - a reference-rule bug, not a real case
        raise RuntimeError("generated a 'legitimate' URI the reference rule rejects")
    return fair


def _extract_acceptance(tree: ast.AST) -> callable | None:
    """Find the redirect-URI acceptance decision inside register_client and return it as a
    callable of one argument.

    Looks for `if not <expr>: raise HTTPException(...)` (or `if <expr>: raise ...`) inside a
    loop whose iterable mentions redirect_uris. Returns a callable evaluating <expr> with the
    loop variable bound, so ANY expression shape is graded by what it accepts.
    """
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if func.name != TARGET_FUNC:
            continue

        # Locals the loop body may READ that were bound earlier in the function -- e.g. the
        # conveyor's first real fix (ems PR #159) did `_loopback_hosts = {...}` before the loop.
        # Inside the simulated __check those are free variables, and an earlier version tried
        # to IMPORT them as modules (ModuleNotFoundError -> exit 2 on a correct fix). Only
        # CALL-FREE assignments are pre-evaluated: literals, sets, tuples, constants. A DB call
        # or any other side effect in the prefix must never run inside an oracle.
        def _call_free(n: ast.AST) -> bool:
            return not any(
                isinstance(x, ast.Call | ast.Await | ast.Yield | ast.YieldFrom)
                for x in ast.walk(n)
            )

        for node in ast.walk(func):
            if not isinstance(node, ast.For):
                continue
            pre_loop: list[ast.stmt] = []
            for st in func.body:
                if st is node:
                    break
                if (
                    isinstance(st, ast.Assign | ast.AnnAssign)
                    and st.value is not None
                    and _call_free(st.value)
                ):
                    pre_loop.append(st)
            if "redirect_uri" not in ast.unparse(node.iter):
                continue
            var = node.target.id if isinstance(node.target, ast.Name) else None
            if var is None:
                continue
            # ⚠️ SIMULATE THE WHOLE LOOP BODY, not one `if` test.
            # The real code accepts a URI iff NO guard in the loop raises. Two earlier
            # versions graded a single expression and each was wrong in a different way:
            #   * evaluating only the `if` test raised NameError against a fix that bound a
            #     local first (`parsed = urlparse(uri)`) -> exit 2, "measured nothing";
            #   * grading only the FIRST `if...raise` scored a fully-correct fix 0/9 when a
            #     harmless earlier guard (`if len(uri) > 2048: raise`) preceded it -> a
            #     conveyor that rejects a correct security fix outright.
            # So: rewrite the loop body as a function where every `if X: raise` becomes
            # `if X: return False`, other statements pass through in order, and the tail is
            # `return True`. Locals, ordering and multiple guards all behave as shipped.
            guards = 0

            # ⛔ REWRITE EACH `raise` STATEMENT IN PLACE, RECURSING ONLY THROUGH `if`.
            # A third adversarial review broke the previous transform, which collapsed an
            # OUTER `if` to `return False` whenever a `raise` appeared ANYWHERE in its subtree.
            # That graded the outer condition, not the REACHABILITY of the raise:
            #     if <correct condition>:
            #         if False:
            #             raise HTTPException(400, ...)
            # scored 9/9, 8/8, exit 0 -- while validating NOTHING at runtime. A false PASS
            # certifying a total regression is the single worst thing this file could do.
            # Replacing the `raise` statement itself, in place, folds every enclosing `if`
            # naturally: the dead `if False:` above becomes `if False: return False`, never
            # fires, the URI is accepted, and the oracle correctly reds. A raise under any
            # NON-`if` compound (for/while/try/with) or any continue/break/return means
            # reachability cannot be folded into a boolean -- so REFUSE TO GRADE (exit 2)
            # rather than guess. "Measured nothing" is the only honest answer there.
            def _rewrite(stmts: list[ast.stmt]) -> list[ast.stmt]:
                nonlocal guards
                out: list[ast.stmt] = []
                for s in stmts:
                    if isinstance(s, ast.Raise):
                        guards += 1
                        out.append(ast.Return(value=ast.Constant(value=False)))
                    elif isinstance(s, ast.If):
                        out.append(
                            ast.If(
                                test=s.test,
                                body=_rewrite(s.body) or [ast.Pass()],
                                orelse=_rewrite(s.orelse),
                            )
                        )
                    elif isinstance(s, _UNFOLDABLE):
                        if any(isinstance(x, ast.Raise) for x in ast.walk(s)):
                            raise RuntimeError(
                                f"a raise sits under a {type(s).__name__} inside the loop; "
                                "its reachability cannot be folded into a boolean"
                            )
                        out.append(
                            s
                        )  # no raise inside: plain computation, pass through
                    elif isinstance(s, ast.Continue):
                        # `continue` in a validate-or-raise loop means "this URI passed,
                        # move to the next one" -- it IS the accept path. The conveyor's first
                        # real fix (ems PR #159) used exactly this idiom and an earlier version
                        # refused it with exit 2 ("a skip is not a reject") -- a correct fix
                        # graded as unmeasurable. In a per-item validation loop, skip == accept.
                        out.append(ast.Return(value=ast.Constant(value=True)))
                    elif isinstance(s, ast.Return | ast.Break):
                        raise RuntimeError(  # noqa: TRY004 -- a refusal to grade, not a type error; main() maps it to exit 2
                            f"{type(s).__name__} inside the validation loop; this oracle "
                            "cannot fold its effect into a per-URI verdict and will not guess"
                        )
                    else:
                        out.append(s)
                return out

            body = _rewrite(node.body)
            if guards == 0:
                continue  # this loop rejects nothing -- not the validation loop
            body.append(ast.Return(value=ast.Constant(value=True)))
            check_fn = ast.FunctionDef(
                name="__check",
                args=ast.arguments(
                    posonlyargs=[],
                    args=[ast.arg(arg=var)],
                    kwonlyargs=[],
                    kw_defaults=[],
                    defaults=[],
                ),
                body=body,
                decorator_list=[],
                returns=None,
                type_params=[],
            )
            module = ast.Module(
                body=[
                    *pre_loop,
                    check_fn,
                    ast.Assign(
                        targets=[ast.Name(id="__verdict", ctx=ast.Store())],
                        value=ast.Call(
                            func=ast.Name(id="__check", ctx=ast.Load()),
                            args=[ast.Name(id=var, ctx=ast.Load())],
                            keywords=[],
                        ),
                    ),
                ],
                type_ignores=[],
            )
            ast.fix_missing_locations(module)
            code = compile(module, filename="<acceptance>", mode="exec")
            negated = True  # __verdict IS the accept verdict; no inversion below
            if True:

                def accepts(uri: str, _code=code, _var=var, _negated=negated) -> bool:
                    # `if not X: raise`  => X is the ACCEPT predicate
                    # `if X: raise`      => X is the REJECT predicate
                    #
                    # ⚠️ RESOLVE MISSING NAMES DYNAMICALLY, don't pre-seed a guess list.
                    # An earlier version seeded only `urlparse` and scored exit 2 against a
                    # perfectly good `re.match` repair -- i.e. it graded the IMPLEMENTATION,
                    # not the property, and would have refused a legitimate fix. Any stdlib
                    # module the real expression reaches for is imported on demand, so
                    # urlparse / re / ipaddress / socket all work equally.
                    ns: dict[str, object] = {_var: uri, "urlparse": urlparse}
                    for _ in range(12):
                        try:
                            exec(_code, ns, ns)  # noqa: S102
                            break
                        except NameError as exc:
                            missing = getattr(exc, "name", None)
                            if not missing:
                                raise
                            try:
                                ns[missing] = importlib.import_module(missing)
                            except ModuleNotFoundError:
                                raise RuntimeError(
                                    f"free variable {missing!r} in the validation loop is not a "
                                    "module and was not bound by a call-free assignment before "
                                    "the loop; this oracle cannot supply it"
                                ) from None
                    else:  # pragma: no cover
                        raise RuntimeError(
                            "too many unresolved names in the acceptance expression"
                        )
                    return bool(
                        ns["__verdict"]
                    )  # __check already returns the accept verdict

                return accepts
    return None


def main() -> int:
    if not SRC.exists():
        print(f"HARNESS: {SRC} not found.")
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT

    try:
        tree = ast.parse(SRC.read_text())
    except SyntaxError as exc:
        print(f"HARNESS: could not parse {SRC}: {exc}")
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT

    try:
        accepts = _extract_acceptance(tree)
    except Exception as exc:  # pragma: no cover
        print(f"HARNESS: extracting the acceptance decision failed: {exc!r}")
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT

    if accepts is None:
        print(
            f"HARNESS: no redirect-URI acceptance decision found in {TARGET_FUNC}. "
            "It may have moved into a helper -- this check cannot grade what it cannot locate."
        )
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT

    try:
        hostile = generate_hostile_uris()
    except RuntimeError as exc:
        print(f"HARNESS: {exc}")
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT

    try:
        legitimate = generate_legitimate_uris()
    except RuntimeError as exc:
        print(f"HARNESS: {exc}")
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT
    if len(legitimate) != 8:
        print(
            f"HARNESS: generated {len(legitimate)} legitimate cases, expected exactly 8."
        )
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT

    if len(hostile) != 9:
        print(
            f"HARNESS: generated {len(hostile)} hostile cases, expected exactly 9 (5 host-position + 4 userinfo)."
        )
        print("This check measured nothing; do not read it as a pass.")
        return EXIT_NO_MEASUREMENT

    wrongly_accepted, wrongly_rejected = [], []

    for uri, why in hostile:
        try:
            verdict = accepts(uri)
        except Exception as exc:  # the real expression raised
            print(f"HARNESS: acceptance expression raised on {uri!r}: {exc!r}")
            print("This check measured nothing; do not read it as a pass.")
            return EXIT_NO_MEASUREMENT
        if verdict:
            wrongly_accepted.append((uri, why, urlparse(uri).hostname))

    for uri in legitimate:
        try:
            verdict = accepts(uri)
        except Exception as exc:
            print(f"HARNESS: acceptance expression raised on {uri!r}: {exc!r}")
            print("This check measured nothing; do not read it as a pass.")
            return EXIT_NO_MEASUREMENT
        if not verdict:
            wrongly_rejected.append(uri)

    print(
        f"hostile hosts rejected:   {len(hostile) - len(wrongly_accepted)}/{len(hostile)}"
    )
    print(
        f"legitimate URIs accepted: {len(legitimate) - len(wrongly_rejected)}/{len(legitimate)}"
    )

    if wrongly_accepted:
        print("\nACCEPTED A NON-LOOPBACK HOST OVER HTTP (the defect):")
        for uri, why, host in wrongly_accepted:
            print(f"  {uri:52s} host={host}  [{why}]")

    if wrongly_rejected:
        print("\n⛔ LEGITIMATE URI REJECTED (over-correction -- NOT a fix):")
        for uri in wrongly_rejected:
            print(f"  {uri}")

    if wrongly_accepted or wrongly_rejected:
        return EXIT_DEFECT

    # ⚠️ Deliberately does NOT claim "decided by the parsed host". An earlier version printed
    # that on evidence which did not establish it: a smarter prefix rule passed every case.
    # This oracle can only certify what it measured -- rejection of these generated shapes --
    # so that is all it says.
    print(
        "\nAll generated hostile shapes rejected and all legitimate URIs accepted "
        "(host-position gluing AND userinfo placement)."
    )
    return EXIT_FIXED


if __name__ == "__main__":
    sys.exit(main())
