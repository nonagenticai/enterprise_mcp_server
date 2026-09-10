"""Import census: every module in this repository is imported, and therefore EXECUTED.

WHY THIS FILE EXISTS. None of this repo's three CI jobs can see an import-time error such as a
`NameError` raised by module top-level code:

* `compile` runs `py_compile` over every tracked `.py`. That only PARSES. A module that
  references a name it never imported parses perfectly and fails only when it is executed.
* `tests` runs `testpaths = ["tests"]`, and before this file that suite imported almost nothing
  from `src/` -- one module out of two dozen. Whatever it did not import, it did not execute.
* `smoke` never installs the project. It imports the third-party `fastmcp` and asserts nothing
  about this repository's own code at all.

That is not hypothetical. A contributor removed `import json` from a module in which `os` was
also used-but-unimported, and all three checks stayed green. Nothing in CI executed the module.

WHAT THIS ASSERTS. Each discovered module is its own parametrized test case that calls
`importlib.import_module`, so module top-level code actually runs and a failure names the
offending module rather than collapsing the whole census into one opaque red.

The module list is DISCOVERED, never hardcoded: a hardcoded list stops covering new modules
silently, and silence is the exact failure mode this file exists to remove. The corollary is
that a broken discovery glob would yield zero parameters and pytest would report a green,
empty census -- a gate that counts no sites cannot fail one -- so `test_discovery_is_not_empty`
is a load-bearing guard, not a formality. `test_extra_modules_exist` is the same guard for the
paths listed by hand, which is how `examples/ticketing_api.py` is covered after its move out of
the repository root.

⚠️ ONE HONEST LIMIT. `import_module` returns the cached module if a sibling test already
imported it (today: `src.http_utils` and `examples.ticketing_api`), so for those two this file
re-asserts rather than re-executes. Coverage is not lost -- an import-time error in either would
already red that sibling's collection. Every other module here is executed by nothing else.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

# Modules that live outside `src/` and would otherwise go uncovered. Paths, not dotted names,
# so that `test_extra_modules_exist` can fail loudly when one is moved or renamed again.
EXTRA_MODULE_PATHS = (REPO_ROOT / "examples" / "ticketing_api.py",)

# `src/` currently holds 24 importable modules. The floor is deliberately well below that: it
# has to fail a discovery that collapses to nothing without turning every new or deleted module
# into a red build.
MINIMUM_EXPECTED_MODULES = 15


def _module_name(path: Path) -> str:
    """Convert a repo-relative .py path into the dotted name used to import it."""
    parts = list(path.resolve().relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _discover_modules() -> list[str]:
    """Walk `src/` for importable modules, plus the hand-listed paths outside it."""
    discovered = [
        _module_name(path)
        for path in sorted(SRC_DIR.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    discovered += [_module_name(path) for path in EXTRA_MODULE_PATHS if path.is_file()]
    return discovered


MODULES = _discover_modules()


@pytest.fixture(scope="session", autouse=True)
def _repo_root_on_sys_path() -> None:
    """`src.*` and `examples.*` resolve relative to the repo root, so it must be importable."""
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def test_discovery_is_not_empty() -> None:
    """A census that discovers nothing passes and proves nothing. Fail loudly instead."""
    assert len(MODULES) >= MINIMUM_EXPECTED_MODULES, (
        f"Discovered only {len(MODULES)} module(s) under {SRC_DIR} "
        f"({MODULES}); expected at least {MINIMUM_EXPECTED_MODULES}. "
        "The discovery glob is broken, or the source layout moved."
    )


@pytest.mark.parametrize("path", EXTRA_MODULE_PATHS, ids=lambda p: p.name)
def test_extra_modules_exist(path: Path) -> None:
    """A hand-listed path that has moved must fail, not silently drop out of the census."""
    assert path.is_file(), (
        f"{path} is listed in EXTRA_MODULE_PATHS but does not exist. "
        "It was moved or deleted; update the list rather than leaving it uncovered."
    )


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    """Import the module for real, so its top-level code executes and can fail."""
    assert importlib.import_module(module_name) is not None
