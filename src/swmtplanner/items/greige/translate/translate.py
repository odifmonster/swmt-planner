#!/usr/bin/env python

import os

_ITEM_MAP = {}

def init():
    if len(globals()['_ITEM_MAP']) > 0:
        return
    
    fpath = os.path.join(os.path.dirname(__file__), 'inv-items.dat')
    with open(fpath) as srcfile:
        for line in srcfile:
            line = line.strip()
            if not line: continue

            inv, plan = line.split('\t')
            globals()['_ITEM_MAP'][inv] = plan

def translate_name(name):
    if name not in globals()['_ITEM_MAP']:
        return None
    return globals()['_ITEM_MAP'][name]