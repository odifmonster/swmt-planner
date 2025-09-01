#!/usr/bin/env python

import os

from .greige import GreigeStyle

_STYLES = {}

def init():
    if len(globals()['_STYLES']) > 0:
        return
    
    fpath = os.path.join(os.path.dirname(__file__), 'greige-sizes.dat')
    with open(fpath) as srcfile:
        for line in srcfile:
            line = line.strip()
            if not line: continue

            name, load_tgt = line.split('\t')
            load_tgt = float(load_tgt)
            globals()['_STYLES'][name] = GreigeStyle(name, load_tgt)

    globals()['_STYLES']['NONE'] = GreigeStyle('NONE', 0)

def get_style(name):
    if name not in globals()['_STYLES']:
        return None
    return globals()['_STYLES'][name]