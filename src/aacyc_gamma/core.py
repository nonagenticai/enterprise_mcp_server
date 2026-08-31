import src.aacyc_alpha.core as _alpha  # cycle: gamma -> alpha closes the loop


def c():
    return 'c'


def chain():
    return _alpha.a()
