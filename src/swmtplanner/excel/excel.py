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

    outpath = os.path.join(os.path.dirname(__file__), '..', 'swmttypes', 'products', 'greige',
                           'translate.py')
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
    df = df_cols_as_str(df, 'Greige', 'GreigeAlt')

    outpath = os.path.join(os.path.dirname(__file__), '..', 'swmttypes', 'products', 'greige',
                           'styles.py')
    outfile = open(outpath, mode='w+')

    outfile.write('#!/usr/bin/env python\n\n')
    outfile.write('from .greige import GreigeStyle\n\n')
    outfile.write('STYLES = {\n')

    for i in df.index:
        item = df.loc[i, 'GreigeAlt']
        roll_tgt = df.loc[i, 'Target']
        roll_diff = 40
        if roll_tgt <= 400:
            load_tgt = roll_tgt
            roll_diff = 20
        else:
            load_tgt = roll_tgt / 2

        outfile.write(' '*4 + f'\'{item}\': GreigeStyle(\'{item}\', ')
        outfile.write(f'{load_tgt-20:.1f}, {load_tgt+20:.1f}, ')
        outfile.write(f'{roll_tgt-roll_diff:.1f}, {roll_tgt+roll_diff:.1f}),\n')

    outfile.write(' '*4 + f'\'NONE\': GreigeStyle(\'NONE\', 0, 1, 0, 1),\n')
    
    outfile.write('}')
    outfile.truncate()
    outfile.close()

def _dyes_file():
    fpath, pdargs = INFO_MAP['dye_formulae']
    df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    df = df_cols_as_str(df, 'COLOR NAME')
    df = df[~(df['COLOR NUMBER'].isna() | df['SHADE RATING'].isna())]

    outpath = os.path.join(os.path.dirname(__file__), '..', 'swmttypes', 'products', 'fabric',
                           'color', 'dyes.py')
    outfile = open(outpath, mode='w+')

    outfile.write('#!/usr/bin/env python\n\n')
    outfile.write('from .shade import Shade\nfrom .color import Color\n\n')
    outfile.write('DYES = {\n')

    for fmla, group in df.groupby('COLOR NUMBER'):
        formula = int(fmla)
        name = list(group['COLOR NAME'])[0]
        shade_val = list(group['SHADE RATING'])[0]
        outfile.write(' '*4 + f'\'{formula:05}\': Color({formula}, ')
        outfile.write(f'\'{name}\', Shade.from_int({int(shade_val)})),\n')

    outfile.write(' '*4 + f'\'00001\': Color(1, \'EMPTY\', ')
    outfile.write(f'Shade.from_str(\'EMPTY\')),\n')
    outfile.write(' '*4 + f'\'00002\': Color(2, \'HEAVYSTRIP\', ')
    outfile.write(f'Shade.from_str(\'HEAVYSTRIP\')),\n')
    outfile.write(' '*4 + f'\'00003\': Color(3, \'STRIP\', ')
    outfile.write(f'Shade.from_str(\'STRIP\')),\n')

    outfile.write('}')
    outfile.truncate()
    outfile.close()

def _pa_items_file():
    fpath, pdargs = INFO_MAP['pa_fin_items']
    pa_df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    pa_df = pa_df[~(pa_df['PA FIN ITEM'].isna() | pa_df['Yield'].isna())]
    pa_df = pa_df[~(pa_df['COLOR NUMBER'].isna() | pa_df['SHADE RATING'].isna())]
    pa_df['GREIGE ITEM'] = pa_df['GREIGE ITEM'].str.upper().apply(lambda s: s.strip())
    pa_df['STYLE'] = pa_df['STYLE'].apply(lambda s: s.strip())
    pa_df['PA FIN ITEM'] = pa_df['PA FIN ITEM'].apply(lambda s: s.strip())

    jet_cols = list(map(lambda i: f'JET {i+1}',
                        filter(lambda i: i not in (4, 5), range(10))))
    pa_df = df_cols_as_str(pa_df, 'GREIGE ITEM', 'STYLE', 'COLOR NAME',
                           'PA FIN ITEM', *jet_cols)

    fpath, pdargs = INFO_MAP['greige_styles']
    grg_df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    grg_df = df_cols_as_str(grg_df, 'Greige', 'GreigeAlt')

    pa_df = pa_df.merge(grg_df, how='left', left_on='GREIGE ITEM',
                        right_on='GreigeAlt')
    pa_df = pa_df[~pa_df['GreigeAlt'].isna()]

    outpath = os.path.join(os.path.dirname(__file__), '..', 'swmttypes', 'products', 'fabric',
                           'items.py')
    outfile = open(outpath, mode='w+')

    outfile.write('#!/usr/bin/env python\n\n')
    outfile.write('from ..greige import STYLES\n')
    outfile.write('from .color import DYES\n')
    outfile.write('from .fabric import FabricItem\n\n')
    outfile.write('ITEMS = {\n')

    for item, group in pa_df.groupby('PA FIN ITEM'):
        idx = list(group.index)[0]
        master = group.loc[idx, 'STYLE']
        grg_id = group.loc[idx, 'GREIGE ITEM']
        clr_num = int(group.loc[idx, 'COLOR NUMBER'])
        yld = group.loc[idx , 'Yield']
        outfile.write(' '*4 + f'\'{item}\': FabricItem(\'{item}\', \'{master}\', ')
        outfile.write(f'STYLES[\'{grg_id}\'], DYES[\'{clr_num:05}\'], {yld}, ')

        allowed_jets = []
        for i in filter(lambda i: i not in (4, 5), range(10)):
            if not pd.isna(group.loc[idx, f'JET {i+1}']):
                allowed_jets.append(f'Jet-{i+1:02}')
        
        outfile.write('[' + ', '.join([repr(jid) for jid in allowed_jets]) + ']),\n')

    outfile.write(' '*4 + '\'EMPTY\': FabricItem(\'EMPTY\', \'NONE\', ')
    outfile.write('STYLES[\'NONE\'], DYES[\'00001\'], 1, []),\n')
    outfile.write(' '*4 + '\'HEAVYSTRIP\': FabricItem(\'HEAVYSTRIP\', \'NONE\', ')
    outfile.write('STYLES[\'NONE\'], DYES[\'00002\'], 1, []),\n')
    outfile.write(' '*4 + '\'STRIP\': FabricItem(\'STRIP\', \'NONE\', ')
    outfile.write('STYLES[\'NONE\'], DYES[\'00003\'], 1, []),\n')
    
    outfile.write('}')
    outfile.truncate()
    outfile.close()

def update_file(name: _DataNameAnno):
    match name:
        case _DataName.greige_translation:
            _grg_trans_file()
        case _DataName.greige_styles:
            _grg_style_file()
        case _DataName.dye_formulae:
            _dyes_file()
        case _DataName.pa_fin_items:
            _pa_items_file()
        case _:
            print('No file to update.')