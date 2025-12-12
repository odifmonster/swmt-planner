#!/usr/bin/env python

from .greige import Greige

STYLES = {}

def load_styles(fpath: str):
    if len(globals()['STYLES']) > 0: return

    with open(fpath) as infile:
        for line in infile:
            line = line.strip()
            if not line: continue

            style, family, roll_avg, rate, gauge, top_set, top_pct, btm_set, btm_pct, mchns = line.split('\t')
            if family == 'None':
                globals()['STYLES'][style] = Greige(style, roll_avg)
            else:
                globals()['STYLES'][style] = Greige(style, roll_avg, family=family,
                                                    rate=float(rate), gauge=int(gauge),
                                                    top_set=top_set, top_pct=float(top_pct),
                                                    btm_set=btm_set, btm_pct=float(btm_pct),
                                                    machines=mchns.split(','))