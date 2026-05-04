#!/usr/bin/env python

from collections import namedtuple

FlexDate = namedtuple('FlexDate', ['month', 'weekday', 'n'])
FixedDate = namedtuple('FixedDate', ['month', 'day'])

def load_holidays(path):
    ret = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                break
            
            kind, *elems = line.split(',')
            if kind == 'flex':
                ret.append(FlexDate(int(elems[0]), int(elems[1]), int(elems[2])))
            else:
                ret.append(FixedDate(int(elems[0]), int(elems[1])))
    
    return ret