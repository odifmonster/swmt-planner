#!/usr/bin/env python

import os, typer, pandas as pd
from pathlib import Path
from typing import Annotated
from enum import Enum

from .interpreter import load_info_file
from .info import INFO_MAP

def df_cols_as_str(df: pd.DataFrame, *args):
    for colname in args:
        df[colname] = df[colname].astype('string')
    return df

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

_INFO_HELP = 'The path to the file containing excel data extraction information.'
_InfoSrcAnno = Annotated[Path,
                         typer.Argument(help=_INFO_HELP,
                                        exists=True,
                                        dir_okay=False,
                                        resolve_path=True)]

def write_excel_info(infosrc: _InfoSrcAnno):
    info_map = load_info_file(infosrc)

    outpath = os.path.join(os.path.dirname(__file__), 'info.py')
    outfile = open(outpath,  mode='w+')

    outfile.write('#!/usr/bin/env python\n\n')
    outfile.write('INFO_MAP = {\n')
    
    for name, info in info_map.items():
        fpath, pdargs = info_to_pdargs(name, info)
        outfile.write(' '*4 + f'\'{name}\': ({repr(fpath)}, {{\n')
        for k, v in pdargs.items():
            outfile.write(' '*8 + f'\'{k}\': ')
            match k:
                case 'sheet_name' | 'header' | 'skiprows' | 'nrows':
                    outfile.write(repr(v) + ',\n')
                case 'usecols':
                    if type(v) is list:
                        outfile.write('[\n')
                        for col in v:
                            outfile.write(' '*12 + repr(col) + ',\n')
                        outfile.write(' '*8 + '],\n')
                    else:
                        outfile.write(repr(v) + ',\n')
                case 'names':
                    outfile.write('[\n')
                    for col in v:
                        outfile.write(' '*12 + repr(col) + ',\n')
                    outfile.write(' '*8 + '],\n')
        outfile.write(' '*4 + '}),\n')
    
    outfile.write('}')
    outfile.truncate()

class _DataName(str, Enum):
    dye_formulae = 'dye_formulae'
    pa_fin_items = 'pa_fin_items'
    greige_styles = 'greige_styles'
    greige_translation = 'greige_translation'

_DATA_HELP = 'Name of the data to read from excel and update.'
_DataNameAnno = Annotated[_DataName,
                          typer.Argument(help=_DATA_HELP)]

def _grg_trans_file():
    fpath, pdargs = INFO_MAP['greige_translation']
    df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    df = df_cols_as_str(df, 'inventory', 'plan')

    outpath = os.path.join(os.path.dirname(__file__), '..', 'app', 'item',
                           'greige', 'translate.py')
    outfile = open(outpath, mode='w+')

    outfile.write('#!/usr/bin/env python\n\n')
    outfile.write('GREIGE_STYLE_MAP = {\n')

    for i in df.index:
        inv = df.loc[i, 'inventory']
        plan = df.loc[i, 'plan']
        outfile.write(' '*4 + f'\'{inv}\': \'{plan}\',\n')
    
    outfile.write('}')
    outfile.truncate()
    outfile.close()

def _grg_style_file():
    fpath, pdargs = INFO_MAP['greige_styles']
    df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    df = df_cols_as_str(df, 'greige')

    outpath = os.path.join(os.path.dirname(__file__), '..', 'app', 'item',
                           'greige', 'styles.py')
    outfile = open(outpath, mode='w+')

    outfile.write('#!/usr/bin/env python\n\n')
    outfile.write('from .greige import GreigeStyle\n\n')
    outfile.write('STYLES = {\n')

    for i in df.index:
        item = df.loc[i, 'greige']
        load_tgt = df.loc[i, 'tgt_lbs']
        outfile.write(' '*4 + f'\'{item}\': GreigeStyle(\'{item}\', ')
        outfile.write(f'{load_tgt:.2f}, {load_tgt:.2f}),\n')
    
    outfile.write('}')
    outfile.truncate()
    outfile.close()

def update_file(name: _DataNameAnno):
    match name:
        case _DataName.greige_translation:
            _grg_trans_file()
        case _DataName.greige_styles:
            _grg_style_file()
        case _:
            print('cool')