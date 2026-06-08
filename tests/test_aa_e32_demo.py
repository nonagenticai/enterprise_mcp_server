"""AA E3.2 controlled bug for the LLM code-fix worker demo.

compute_total intentionally SUBTRACTS instead of adding. The LLM code-fix
worker should rewrite compute_total to add, taking test_compute_total from
RED -> GREEN. No patch is supplied to the pipeline; the model generates it.
"""


def compute_total(a, b):
    return a - b  # BUG: should be a + b


def test_compute_total():
    assert compute_total(2, 3) == 5
