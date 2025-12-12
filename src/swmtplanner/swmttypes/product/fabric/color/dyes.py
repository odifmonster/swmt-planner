#!/usr/bin/env python

from .shade import Shade
from .color import Color

DYES = {}

def load_dyes(fpath: str):
    if len(globals()['DYES']) > 0: return

    with open(fpath) as infile:
        for line in infile:
            line = line.strip()
            if not line: continue

            formula, name, shade_val = line.split('\t')
            formula = int(formula)
            globals()['DYES'][f'{formula:05}'] = Color(formula, name,
                                                       Shade.from_int(int(shade_val)))
    
    globals()['DYES']['00001'] = Color(1, 'EMPTY', Shade.from_str('EMPTY'))
    globals()['DYES']['00002'] = Color(2, 'HEAVYSTRIP', Shade.from_str('HEAVYSTRIP'))
    globals()['DYES']['00003'] = Color(3, 'STRIP', Shade.from_str('STRIP'))