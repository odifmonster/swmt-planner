#!/usr/bin/env python

from .greige import GreigeStyle

STYLES = {}

def load_styles(fpath: str):
    if len(globals()['STYLES']) > 0: return

    with open(fpath) as infile:
        for line in infile:
            line = line.strip()
            if not line: continue

            style, load_min, load_max, roll_min, roll_max = line.split('\t')
            grg = GreigeStyle(style, float(load_min), float(load_max),
                              float(roll_min), float(roll_max))
            globals()['STYLES'][style] = grg
    
    globals()['STYLES']['NONE'] = GreigeStyle('NONE', 0, 1, 0, 1)