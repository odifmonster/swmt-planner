#!/usr/bin/env python

from swmtplanner.support import SwmtBase

class Quantity(SwmtBase, read_only=('pcs','yds','lbs')):

    def __init__(self, pcs = None, yds = None, lbs = None):
        super().__init__(_pcs=pcs, _yds=yds, _lbs=lbs)

    def _compare(self, value, func):
        for uom in ('pcs', 'yds', 'lbs'):
            if getattr(self, uom) is not None and getattr(value, uom) is not None:
                return func(getattr(self, uom), getattr(value, uom))
        raise TypeError('Cannot compare quantities with incompatible units')
    
    def _combine(self, value, func):
        qty_map = {}
        for uom in ('pcs', 'yds', 'lbs'):
            if getattr(self, uom) is not None and getattr(value, uom) is not None:
                qty_map[uom] = func(getattr(self, uom), getattr(value, uom))
        if not qty_map:
            raise TypeError('Cannot combine quantities with incompatible units')
        return Quantity(**qty_map)
    
    def _apply(self, func):
        qty_map = {}
        for uom in ('pcs', 'yds', 'lbs'):
            if getattr(self, uom) is not None:
                qty_map[uom] = func(getattr(self, uom))
        return Quantity(**qty_map)

    def __eq__(self, value):
        return self._compare(value, lambda x, y: x == y)
    
    def __le__(self, value):
        return self._compare(value, lambda x, y: x <= y)
    
    def __lt__(self, value):
        return self._compare(value, lambda x, y: x < y)
    
    def __ge__(self, value):
        return self._compare(value, lambda x, y: x >= y)
    
    def __gt__(self, value):
        return self._compare(value, lambda x, y: x > y)
    
    def __add__(self, value):
        return self._combine(value, lambda x, y: x + y)
    
    def __sub__(self, value):
        return self._combine(value, lambda x, y: x - y)
    
    def __mul__(self, scalar):
        return self._apply(lambda x: x*scalar)
    
    def __rmul__(self, scalar):
        return self._apply(lambda x: x*scalar)
    
    def __div__(self, scalar):
        return self._apply(lambda x: x/scalar)
    
    def __str__(self):
        for uom in ('pcs','yds','lbs'):
            if getattr(self, uom) is not None:
                val = round(getattr(self, uom), ndigits=2)
                tgt_uom = uom
                break
        
        return f'{val} {tgt_uom}'