"""One third of a deliberate CROSS-COMPONENT import cycle: alpha -> beta -> gamma -> alpha.

The gamma -> alpha edge has been DEFERRED to break the cycle:
the module-level import of src.aacyc_alpha.core is removed, and the symbol is imported
locally inside the function that uses it.
"""


def c():
    return 'c'


def chain():
    import src.aacyc_alpha.core as _alpha
    return _alpha.a()
