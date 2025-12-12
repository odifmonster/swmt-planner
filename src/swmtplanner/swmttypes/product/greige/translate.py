#!/usr/bin/env python

STYLE_MAP = {}

def load_translations(fpath: str):
    if len(globals()['STYLE_MAP']) > 0:
        return
    
    with open(fpath) as infile:
        for line in infile:
            line = line.strip()
            if not line: continue
            inv, plan = line.split('\t')
            globals()['STYLE_MAP'][inv] = plan