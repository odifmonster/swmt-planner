#!/usr/bin/env python

import os

from .interpreter import load_info_file

INFO_MAP = {}

def info_to_pdargs(info_name: str, info: dict[str]):
    items = {}
    for name in ('folder', 'workbook', 'sheet'):
        if name not in info:
            msg = f'Required keyword \'{name}\' missing from info for \'{info_name}\''
            raise KeyError(msg)
        items[name] = info[name]

    fpath = os.path.join(items['folder'], items['workbook'])
    res = { 'sheet_name': items['sheet'], 'header': 0 }

    start = 1
    if 'start_row' in info:
        res['skiprows'] = info['start_row'] - 1
        start = info['start_row']
    if 'end_row' in info:
        res['nrows'] = info['end_row'] - start + 1

    if 'col_names' in info:
        if 'col_ranges' in info:
            msg = f'Cannot use both {repr(info['col_ranges'])} and '
            msg += ', '.join([repr(x) for x in info['col_names']])
            msg += ' as columns'
            raise ValueError(msg)
        if 'subst_names' in info:
            msg = 'Cannot use both ' + ', '.join([repr(x) for x in info['col_names']])
            msg += ' and ' + ', '.join([repr(x) for x in info['subst_names']])
            msg += ' as column names'
            raise ValueError(msg)
        
        res['usecols'] = info['col_names']
    if 'subst_names' in info:
        if 'col_ranges' not in info:
            msg = 'Missing corresponding excel column ranges for names '
            msg += ', '.join([repr(x) for x in info['subst_names']])
            raise ValueError(msg)
        
        res['usecols'] = info['col_ranges']
        res['names'] = info['subst_names']
        res['header'] = None
    if 'col_ranges' in info:
        res['usecols'] = info['col_ranges']

    return fpath, res

def load_info_map(srcpath: str):
    if len(globals()['INFO_MAP']) > 0: return

    raw_map = load_info_file(srcpath)
    
    for name, info in raw_map.items():
        fpath, pdargs = info_to_pdargs(name, info)
        globals()['INFO_MAP'][name] = (fpath, pdargs)