def c():
    return 'c'


def chain():
    from ..aacyc_alpha.core import a as _a
    return _a()