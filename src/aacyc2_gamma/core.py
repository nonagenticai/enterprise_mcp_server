"""One third of a deliberate CROSS-COMPONENT import cycle: alpha -> beta -> gamma -> alpha.

THE SEEDED DEFECT IS STRUCTURAL, NOT BEHAVIOURAL. The module-level edge is real and the
architecture analyzer sees it (three directories => three components), but the `import x.y as y`
form binds the MODULE OBJECT lazily, so the package still imports and behaviour is intact.
A `from x.y import name` form raises ImportError on a partially initialized module and leaves
no behaviour to preserve -- that is not a refactoring fixture, it is a broken one.

CROSS-DIRECTORY IS NON-NEGOTIABLE. component_extractor aggregates by DIRECTORY and drops
intra-component edges before Tarjan runs, so a same-directory cycle is INVISIBLE to the
analyzer (it returns `cycles: []` -- a vacuous PASS). Three directories, three components.
"""


def c():
    return 'c'


def chain():
    import src.aacyc2_alpha.core as _alpha
    return _alpha.a()
