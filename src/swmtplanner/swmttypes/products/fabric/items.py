#!/usr/bin/env python

from ..greige import STYLES
from .color import DYES
from .fabric import FabricItem

ITEMS = {}

def load_items(fpath: str):
    if len(globals()['ITEMS']) > 0: return

    with open(fpath) as infile:
        for line in infile:
            line = line.strip()
            if not line: continue

            item, master, grg, clr, yld, jets = line.split('\t')
            clr = int(clr)
            if grg not in STYLES or f'{clr:05}' not in DYES: continue

            fab = FabricItem(item, master, STYLES[grg], DYES[f'{clr:05}'], float(yld),
                             jets.split(','))
            globals()['ITEMS'][item] = fab

    globals()['ITEMS']['EMPTY'] = FabricItem('EMPTY', 'NONE', STYLES['NONE'], DYES['00001'], 1, [])
    globals()['ITEMS']['HEAVYSTRIP'] = FabricItem('HEAVYSTRIP', 'NONE', STYLES['NONE'],
                                                  DYES['00002'], 1, [])
    globals()['ITEMS']['STRIP'] = FabricItem('STRIP', 'NONE', STYLES['NONE'], DYES['00003'], 1, [])