#!/usr/bin/env python

import os

from .fabric import FabricStyle
from .color import Color, get_color
from .. import greige

_STYLES = {}

def init():
    if len(globals()['_STYLES']) > 0:
        return
    
    fpath = os.path.join(os.path.dirname(__file__), 'fabric-items.dat')
    with open(fpath) as srcfile:
        for line in srcfile:
            line = line.strip()
            if not line: continue

            grg_id, master, yld, color_name, color_num, item, shade, jets = line.split('\t')
            grg = greige.get_style(grg_id)
            if grg is None: continue
            yld = float(yld)
            color_num = int(color_num)
            shade = int(float(shade))
            color = Color(color_num, color_name, shade)
            jets = jets.split(' ')
            globals()['_STYLES'][item] = FabricStyle(item, master, grg, color, yld, jets)

    globals()['_STYLES']['NONE'] = FabricStyle('NONE', 'NONE', greige.get_style('NONE'),
                                               get_color('00001'), 1, [])
    globals()['_STYLES']['HEAVYSTRIP'] = FabricStyle(
        'HEAVYSTRIP', 'HEAVYSTRIP', greige.get_style('NONE'), get_color('00002'),
        1, [])
    globals()['_STYLES']['STRIP'] = FabricStyle(
        'STRIP', 'STRIP', greige.get_style('NONE'), get_color('00003'), 1, [])

def get_style(name):
    if name not in globals()['_STYLES']:
        return None
    return globals()['_STYLES'][name]