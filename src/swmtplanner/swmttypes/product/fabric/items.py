#!/usr/bin/env python

from ..greige import STYLES
from .color import DYES
from .fabric import Fabric

ITEMS = {}

def load_items(fpath: str):
    if len(globals()['ITEMS']) > 0: return

    with open(fpath) as infile:
        for line in infile:
            line = line.strip()
            if not line: continue

            master, clr, wd, grg, yld, jets = line.split('\t')
            if grg not in STYLES or clr not in DYES: continue

            fab = Fabric(master, DYES[clr], float(wd), STYLES[grg],
                         float(yld), jets.split(','))
            globals()['ITEMS'] = fab
    
    globals()['ITEMS']['EMPTY'] = Fabric('EMPTY', DYES['00001'], 0, STYLES['NONE'], 1, [])
    globals()['ITEMS']['HEAVYSTRIP'] = Fabric('HEAVYSTRIP', DYES['00002'], 0, STYLES['NONE'], 1, [])
    globals()['ITEMS']['STRIP'] = Fabric('STRIP', DYES['00003'], 0, STYLES['NONE'], 1, [])