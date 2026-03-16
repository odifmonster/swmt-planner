#!/usr/bin/env python

from .greige import Greige

STYLES = {}

def load_styles(fpath: str):
    if len(globals()['STYLES']) > 0: return

    with open(fpath) as infile:
        for line in infile:
            line = line.strip()
            if not line: continue

            style, family, roll_avg, gauge, top_set, top_pct, btm_set, btm_pct, mchns = line.split('\t')
            if family == 'None':
                globals()['STYLES'][style] = Greige(style, roll_avg)
            else:
                pairs = mchns.split(';')
                mchn_mat = []
                for pair in pairs:
                    mchn, rate = pair.split(',')
                    mchn_mat.append((mchn, float(rate)))
                globals()['STYLES'][style] = Greige(style, roll_avg, family=family,
                                                    gauge=int(gauge),
                                                    top_set=top_set, top_pct=float(top_pct),
                                                    btm_set=btm_set, btm_pct=float(btm_pct),
                                                    machines=mchn_mat)
    
    globals()['STYLES']['NONE'] = Greige('NONE', 1)