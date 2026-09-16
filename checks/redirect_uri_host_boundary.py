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
        ("http://localhost{lab}.example/cb", "suffix glued to localhost"),
        ("http://localhost.{lab}.com/cb", "localhost as a leading label"),
        ("http://{lab}localhost/cb", "prefix glued to localhost"),
        ("http://localhost{lab}/cb", "no dot, glued directly"),
        ("http://{lab}.localhost.{lab2}.net/cb", "localhost buried mid-name"),
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
LEGITIMATE = [
    "https://app.example.com/callback",
    "https://example.com/cb?x=1",
    "http://localhost/cb",
    "http://localhost:8080/cb",
]


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
        for node in ast.walk(func):
            if not isinstance(node, ast.For):
                continue
            if "redirect_uri" not in ast.unparse(node.iter):
                continue
            var = node.target.id if isinstance(node.target, ast.Name) else None
            if var is None:
                continue
            for index, stmt in enumerate(node.body):
                if not isinstance(stmt, ast.If):
                    continue
                raises = any(isinstance(s, ast.Raise) for s in ast.walk(stmt))
                if not raises:
                    continue
                test = stmt.test
                negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                expr = test.operand if negated else test

                # ⚠️ EXECUTE THE LOOP-BODY PREFIX, not just the `if` test.
                # A correct fix may well bind a local first (`parsed = urlparse(uri)`) and
                # test that. Evaluating the test ALONE then raises NameError and this oracle
                # reports "measured nothing" -- which is honest but useless, because a gate a
                # correct fix cannot turn green is not a gate. Measured: an early version did
                # exactly this and scored exit 2 against a genuine urlparse-based repair.
                prefix = [s for s in node.body[:index] if not isinstance(s, ast.Return)]
                module = ast.Module(
                    body=[
                        *prefix,
                        ast.Assign(
                            targets=[ast.Name(id="__verdict", ctx=ast.Store())],
                            value=expr,
                        ),
                    ],
                    type_ignores=[],
                )
                ast.fix_missing_locations(module)
                code = compile(module, filename="<acceptance>", mode="exec")

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
                            ns[missing] = importlib.import_module(missing)
                    else:  # pragma: no cover
                        raise RuntimeError(
                            "too many unresolved names in the acceptance expression"
                        )
                    value = bool(ns["__verdict"])
                    return value if _negated else not value

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

    if len(hostile) < 5:
        print(f"HARNESS: generated only {len(hostile)} hostile cases, expected 5.")
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

    for uri in LEGITIMATE:
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
        f"legitimate URIs accepted: {len(LEGITIMATE) - len(wrongly_rejected)}/{len(LEGITIMATE)}"
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

    print(
        "\nAll cases correct: acceptance is decided by the parsed host, not a prefix."
    )
    return EXIT_FIXED


if __name__ == "__main__":
    sys.exit(main())
