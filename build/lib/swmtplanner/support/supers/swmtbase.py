#!/usr/bin/env python

class SwmtBase:

    def __init_subclass__(cls, read_only = tuple(), priv = tuple()):
        super().__init_subclass__()

        cls._privs = read_only + priv
        cls._read_only = read_only

        for name in read_only:
            curprop = property(fget=lambda slf: getattr(slf, '_'+name))
            setattr(cls, name, curprop)
    
    def __init__(self, priv: dict[str] = {}, **kwargs):
        cls = type(self)

        if not set(cls._privs).issubset(priv.keys()):
            not_incl = set(cls._privs).difference(priv.keys())
            msg = 'Attribute(s) ' + ', '.join([repr(name) for name in not_incl])
            msg += ' not provided to initializer'
            raise ValueError(msg)

        if not set(cls._read_only).isdisjoint(kwargs.keys()):
            overlap = set(cls._read_only).intersection(kwargs.keys())
            msg = 'Attribute name(s) ' + ', '.join([repr(name) for name in overlap])
            msg += ' are reserved for read-only properties'
            raise ValueError(msg)
        
        for name, value in priv.items():
            setattr(self, '_'+name, value)

        for name, value in kwargs.items():
            setattr(self, name, value)