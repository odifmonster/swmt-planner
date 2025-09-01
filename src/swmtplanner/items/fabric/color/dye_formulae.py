#!/usr/bin/env python

import os

from .color import Color

_COLORS = {}

def init():
    if len(globals()['_COLORS']) > 0:
        return
    
    fpath = os.path.join(os.path.dirname(__file__), 'dye-formulae.dat')
    with open(fpath) as srcfile:
        for line in srcfile:
            line = line.strip()
            if not line: continue

            name, number, shade = line.split('\t')
            number = int(float(number))
            shade = int(float(shade))
            globals()['_COLORS'][f'{number:05}'] = Color(number, name, shade)
    
    globals['_COLORS']['00001'] = Color(1, 'EMPTY', 'EMPTY')
    globals['_COLORS']['00002'] = Color(2, 'HEAVYSTRIP', 'HEAVYSTRIP')
    globals['_COLORS']['00003'] = Color(3, 'STRIP', 'STRIP')

def get_color(number):
    if number not in globals()['_COLORS']:
        return None
    return globals()['_COLORS'][number]