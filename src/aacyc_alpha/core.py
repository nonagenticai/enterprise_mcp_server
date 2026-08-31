"""One third of a deliberate CROSS-COMPONENT import cycle: alpha -> beta -> gamma -> alpha.

THE SEEDED DEFECT IS STRUCTURAL, NOT BEHAVIOURAL. The module-level edge is real and the
architecture analyzer sees it (three directories => three components), but the `import x.y as y`
form binds the MODULE OBJECT lazily, so the package still imports and behaviour is intact.
A `from x.y import name` form raises ImportError on a partially initialized module and leaves
no behaviour to preserve -- that is not a refactoring fixture, it is a broken one.
"""
import src.aacyc_beta.core as _beta


def a():
    return 'a'


def chain():
    return _beta.b()
