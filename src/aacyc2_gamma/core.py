"""One third of a deliberate CROSS-COMPONENT import cycle: alpha -> beta -> gamma -> alpha.

THE SEEDED DEFECT IS STRUCTURAL, NOT BEHAVIOURAL. The module-level edge is real and the
architecture analyzer sees it (three directories => three components). The package still
imports cleanly and the three chain() results -- alpha 'b', beta 'c', gamma 'a' -- are the
behaviour that must be preserved.

CROSS-DIRECTORY IS NON-NEGOTIABLE. component_extractor aggregates by DIRECTORY and drops
intra-component edges before Tarjan runs, so a same-directory cycle is INVISIBLE to the
analyzer (it returns `cycles: []` -- a vacuous PASS). Three directories, three components.
"""
import src.aacyc2_alpha.core as _alpha


def c():
    return 'c'


def chain():
    return _alpha.a()
