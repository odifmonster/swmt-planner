#!/usr/bin/env python

import typer, pandas as pd
from pathlib import Path
from typing import Annotated
from enum import Enum

from .info import INFO_MAP, load_info_map

def df_cols_as_str(df: pd.DataFrame, *args):
    for colname in args:
        df[colname] = df[colname].astype('string')
    return df

def _grg_trans_file(outpath):
    fpath, pdargs = INFO_MAP['greige_translation']
    df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    df = df_cols_as_str(df, 'inventory', 'plan')

    outfile = open(outpath, mode='w+')

    for i in df.index:
        inv = df.loc[i, 'inventory']
        plan = df.loc[i, 'plan']
        outfile.write('\t'.join([inv, plan]) + '\n')

    outfile.truncate()
    outfile.close()

def _grg_style_file(outpath):
    fpath, pdargs = INFO_MAP['greige_styles']
    df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    df = df_cols_as_str(df, 'Greige', 'GreigeAlt')

    outfile = open(outpath, mode='w+')


    for i in df.index:
        item = df.loc[i, 'GreigeAlt']
        roll_tgt = df.loc[i, 'Target']
        roll_diff = 40
        if roll_tgt <= 400:
            load_tgt = roll_tgt
            roll_diff = 20
        else:
            load_tgt = roll_tgt / 2

        outfile.write(f'{item}\t{load_tgt-20:.1f}\t{load_tgt+20:.1f}\t')
        outfile.write(f'{roll_tgt-roll_diff:.1f}\t{roll_tgt+roll_diff:.1f}\n')

    outfile.truncate()
    outfile.close()

def _dyes_file(outpath):
    fpath, pdargs = INFO_MAP['dye_formulae']
    df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    df = df_cols_as_str(df, 'COLOR NAME')
    df = df[~(df['COLOR NUMBER'].isna() | df['SHADE RATING'].isna())]

    outfile = open(outpath, mode='w+')

    for fmla, group in df.groupby('COLOR NUMBER'):
        formula = int(fmla)
        name = list(group['COLOR NAME'])[0]
        shade_val = list(group['SHADE RATING'])[0]
        outfile.write(f'{formula}\t{name}\t{int(shade_val)}\n')

    outfile.truncate()
    outfile.close()

def _pa_items_file(outpath):
    fpath, pdargs = INFO_MAP['pa_fin_items']
    pa_df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    pa_df = df_cols_as_str(pa_df, 'PA FIN ITEM', 'STATUS', 'STYLE')

    pa_df = pa_df[~(pa_df['PA FIN ITEM'].isna() | pa_df['Yield'].isna())]
    pa_df = pa_df[~(pa_df['COLOR NUMBER'].isna() | pa_df['SHADE RATING'].isna())]
    pa_df = pa_df[(pa_df['STATUS'] == 'A') | pa_df['STATUS'].isna()]

    pa_df['GREIGE ITEM'] = pa_df['GREIGE ITEM'].str.upper().apply(lambda s: s.strip())
    pa_df['STYLE'] = pa_df['STYLE'].apply(lambda s: s.strip())
    pa_df['WD2'] = pa_df['WD'].apply(lambda w: str(int(w)) if int(w) == w else str(w))
    pa_df['item'] = pa_df.agg(lambda r: f'FF {r['STYLE']}-{int(r['COLOR NUMBER']):05}-{r['WD2']}',
                              axis=1)

    jet_cols = list(map(lambda i: f'JET {i+1}',
                        filter(lambda i: i not in (4, 5), range(10))))
    pa_df = df_cols_as_str(pa_df, 'GREIGE ITEM', 'STYLE', 'COLOR NAME',
                           'PA FIN ITEM', 'item', *jet_cols)

    fpath, pdargs = INFO_MAP['greige_styles']
    grg_df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    grg_df = df_cols_as_str(grg_df, 'Greige', 'GreigeAlt')

    pa_df = pa_df.merge(grg_df, how='left', left_on='GREIGE ITEM',
                        right_on='GreigeAlt')
    pa_df = pa_df[~pa_df['GreigeAlt'].isna()]

    outfile = open(outpath, mode='w+')

    for item, group in pa_df.groupby('item'):
        idx = list(group.index)[0]
        master = group.loc[idx, 'STYLE']
        grg_id = group.loc[idx, 'GREIGE ITEM']
        clr_num = int(group.loc[idx, 'COLOR NUMBER'])
        yld = group.loc[idx , 'Yield']

        allowed_jets = []
        for i in filter(lambda i: i not in (4, 5), range(10)):
            if not pd.isna(group.loc[idx, f'JET {i+1}']):
                allowed_jets.append(f'Jet-{i+1:02}')

        outfile.write(f'{item}\t{master}\t{grg_id}\t{clr_num}\t{yld}\t')
        outfile.write(','.join(allowed_jets) + '\n')
    
    outfile.truncate()
    outfile.close()

class _DataName(str, Enum):
    dye_formulae = 'dye_formulae'
    pa_fin_items = 'pa_fin_items'
    greige_styles = 'greige_styles'
    greige_translation = 'greige_translation'

_DATA_HELP = 'Name of the data to read from excel and update.'
_DataNameAnno = Annotated[_DataName,
                          typer.Argument(help=_DATA_HELP)]
_INFO_PATH_HELP = 'Path to the file containing excel reading info'
_InfoPathAnno = Annotated[Path,
                         typer.Argument(help=_INFO_PATH_HELP)]
_OUT_PATH_HELP = 'Path to the file to update'
_OutPathAnno = Annotated[Path,
                         typer.Argument(help=_OUT_PATH_HELP)]

def update_file(infopath: _InfoPathAnno, outpath: _OutPathAnno,
                name: _DataNameAnno):
    load_info_map(infopath)
    match name:
        case _DataName.greige_translation:
            _grg_trans_file(outpath)
        case _DataName.greige_styles:
            _grg_style_file(outpath)
        case _DataName.dye_formulae:
            _dyes_file(outpath)
        case _DataName.pa_fin_items:
            _pa_items_file(outpath)
        case _:
            print('No file to update.')