from ..aacyc_alpha.core import a as _a  # cycle: gamma.core -> alpha.core closes the loop


def c():
    return 'c'


def chain():
    return _a()
