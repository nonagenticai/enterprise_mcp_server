"""Standalone, stdlib-only correctness checks.

These are NOT pytest tests and are deliberately outside `testpaths = ["tests"]`, so pytest
does not collect them. Each module is runnable as `python -m checks.<name>` over the standard
library alone, exits 0 when the property holds and 1 when it does not, and is safe to run
inside a bare container with no dependencies installed.
"""
