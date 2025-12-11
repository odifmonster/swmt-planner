#!/usr/bin/env python

def _mk_read_prop(name):
    return lambda slf: getattr(slf, '_'+name)

class SwmtBase:

    def __init_subclass__(cls, read_only = tuple(), priv = tuple()):
        cls._privs = read_only + priv
        cls._read_only = read_only

        for name in read_only:
            curprop = property(fget=_mk_read_prop(name))
            setattr(cls, name, curprop)
        
        super().__init_subclass__()
    
    def __init__(self, **kwargs):
        cls = type(self)

        priv_names = set(map(lambda name: '_'+name, cls._privs))
        if len(priv_names) > 0 and not priv_names.issubset(kwargs.keys()):
            not_incl = priv_names.difference(kwargs.keys())
            msg = 'Attribute(s) ' + ', '.join([repr(name) for name in not_incl])
            msg += ' not provided to initializer'
            raise ValueError(msg)

        if not set(cls._read_only).isdisjoint(kwargs.keys()):
            overlap = set(cls._read_only).intersection(kwargs.keys())
            msg = 'Attribute name(s) ' + ', '.join([repr(name) for name in overlap])
            msg += ' are reserved for read-only properties'
            raise ValueError(msg)

        for name, value in kwargs.items():
            setattr(self, name, value)