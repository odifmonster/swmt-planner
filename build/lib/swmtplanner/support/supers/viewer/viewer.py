#!/usr/bin/env python

from ..swmtbase import SwmtBase

def _mk_linked_prop(name):
    prop = property(fget=lambda slf: getattr(slf._link, name))
    return prop

def _copy_linked_func(name):
    def func(slf, *args, **kwargs):
        link_func = getattr(slf._link, name)
        if hasattr(link_func, 'is_setter') and link_func._is_setter == 1:
            cls = type(slf)
            raise RuntimeError(f'\'{cls.__name__}\' objects cannot call methods that ' + \
                               'mutate attributes they are viewing')
        return link_func(*args, **kwargs)
    return func

def setter_like(func):
    func._is_setter = 1
    return func

class Viewer[T](SwmtBase):

    def __init_subclass__(cls, dunders = tuple(), attrs = tuple(), funcs = tuple(),
                          read_only = tuple(), priv = tuple()):
        super().__init_subclass__(read_only=read_only, priv=('link',)+priv)

        dunders = list(map(lambda name: f'__{name}__', dunders))
        for fname in dunders + list(funcs):
            setattr(cls, fname, _copy_linked_func(fname))
        
        for attr in attrs:
            setattr(cls, attr, _mk_linked_prop(attr))
    
    def __init__(self, link, priv: dict[str] = {}, **kwargs):
        newpriv = priv.copy()
        newpriv['link'] = link
        super().__init__(priv=newpriv, **kwargs)