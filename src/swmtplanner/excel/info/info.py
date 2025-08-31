#!/usr/bin/env python

from typing import TypedDict

from ..parser.lexer import TokType
from ..parser.tree import Info

class PandasKWArgs(TypedDict, total=False):
    sheet_name: str
    header: int | None
    skiprows: int
    nrows: int
    names: list[str]
    usecols: str | list[str]

def _get_type_err(info, kwarg):
    if type(kwarg.value) is list:
        typename = 'list'
    else:
        typename = kwarg.value.kind.lower()
    return TypeError(f'Info for \'{info.name}\': \'{kwarg.name}\' cannot be ' + \
                     f'{typename}')

def _parse_excel_info(info: Info):
    raw_info = {}

    for kwarg in info.kwargs:
        match kwarg.name:
            case 'folder' | 'workbook' | 'sheet' | 'col_ranges':
                if type(kwarg.value) is list:
                    raise _get_type_err(info, kwarg)
                val = kwarg.value.value
            case 'start_row' | 'end_row':
                if type(kwarg.value) is list or kwarg.value.kind != TokType.NUM:
                    raise _get_type_err(info, kwarg)
                val = int(kwarg.value.value)
            case 'col_names' | 'subst_names':
                if type(kwarg.value) is not list:
                    val = [kwarg.value.value]
                else:
                    val = list(map(lambda a: a.value, kwarg.value))
            case _:
                raise KeyError(f'Unrecognized argument {repr(kwarg.name)}')
        
        raw_info[kwarg.name] = val
    
    return raw_info

def parse_pd_args(info: Info):
    raw_info = _parse_excel_info(info)
    dirpath = None

    for name in ('workbook', 'sheet'):
        if name not in raw_info:
            raise KeyError(f'Info for \'{info.name}\' missing \'{name}\' argument')
    
    fname = raw_info['workbook']
    pd_kwargs: PandasKWArgs = {
        'sheet_name': raw_info['sheet']
    }
    if 'folder' in raw_info:
        dirpath = raw_info['folder']

    if 'subst_names' in raw_info:
        if 'col_ranges' not in raw_info:
            raise ValueError(f'Info for \'{info.name}\' provides substitute column ' + \
                             'names without specifying corresponding excel columns')
        if 'col_names' in raw_info:
            raise ValueError(f'Info for \'{info.name}\' provides substitute column ' + \
                             'names and actual column names, unclear which to use')
        pd_kwargs['names'] = raw_info['subst_names']
        pd_kwargs['usecols'] = raw_info['col_ranges']
        pd_kwargs['header'] = None
    elif 'col_names' in raw_info:
        pd_kwargs['usecols'] = raw_info['col_names']
    elif 'col_ranges' in raw_info:
        pd_kwargs['usecols'] = raw_info['col_ranges']
    
    start = 0
    if 'start_row' in raw_info:
        start = raw_info['start_row']
        pd_kwargs['skiprows'] = raw_info['start_row']-1

    if 'end_row' in raw_info:
        pd_kwargs['nrows'] = raw_info['end_row']-start+1

    return dirpath, fname, pd_kwargs