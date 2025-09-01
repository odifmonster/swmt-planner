#!/usr/bin/env python

import typer, os, pandas as pd
from typing_extensions import Annotated

from .parser import tree
from .info import parse_pd_args

_INFO_MAP = {}

def init():
    datpath = os.path.join(os.path.dirname(__file__), 'excel_info.dat')
    datfile = open(datpath)
    info_list = tree.parse(datfile)
    datfile.close()

    for info in info_list:
        dirpath, fname, pd_kwargs = parse_pd_args(info)
        pd_kwargs['dtype'] = {}
        match info.name:
            case 'greige_translation':
                str_cols = ['inventory', 'plan']
            case 'greige_sizes':
                str_cols = ['greige']
            case 'dye_formulae':
                str_cols = ['COLOR NAME']
            case 'fabric_items':
                str_cols = ['GREIGE ITEM', 'STYLE', 'COLOR NAME', 'COLOR NUMBER',
                            'PA FIN ITEM']
                str_cols += list(map(lambda i: f'JET {i}', (1,2,3,4,7,8,9,10)))
            case 'jet_info':
                str_cols = ['jet', 'alt_jet']
            case 'pa_inventory':
                str_cols = ['Roll', 'Item', 'Quality', 'ASSIGNED_ORDER']
            case 'adaptive_orders':
                str_cols = ['Dyelot', 'Machine']
            case 'pa_714':
                str_cols = ['Item', 'Dye Order']
            case 'pa_demand_plan':
                str_cols = ['PA Fin Item']
            case _:
                raise KeyError(f'Unknown excel info \'{info.name}\'')
        
        for str_col in str_cols:
            pd_kwargs['dtype'][str_col] = 'string'
        globals()['_INFO_MAP'][info.name] = (dirpath, fname, pd_kwargs)

def get_read_args(name):
    if name not in globals()['_INFO_MAP']:
        raise KeyError(f'No info for \'{name}\'')
    return globals()['_INFO_MAP'][name]

def _convert_dyelot(dl: str):
    if '@' in dl:
        return pd.dl[:dl.find('@')]
    if '/' in dl:
        return dl[:dl.find('/')]
    missing = 10 - len(dl)
    return '0'*missing+dl

def load_df(info, default_dir):
    dirpath, fname, pd_kwargs = get_read_args(info)
    if dirpath is None:
        fpath = os.path.join(default_dir, fname)
    else:
        fpath = os.path.join(dirpath, fname)
    
    df: pd.DataFrame = pd.read_excel(fpath, **pd_kwargs)

    match info:
        case 'greige_translation':
            df['inventory'] = df['inventory'].str.upper()
            df['plan'] = df['plan'].str.upper()
            sub_df = df[~df['plan'].str.contains(r'USED|DEV')]
            return sub_df
        case 'greige_sizes':
            df['greige'] = df['greige'].str.upper()
            return df
        case 'dye_formulae':
            sub_df = df[~(df['COLOR NAME'].isna() | df['COLOR NUMBER'].isna())]
            sub_df = sub_df[~sub_df['SHADE RATING'].isna()]
            return sub_df
        case 'fabric_items':
            df['GREIGE ITEM'] = df['GREIGE ITEM'].str.upper()
            sub_df = df[~(df['COLOR NUMBER'].isna() | df['SHADE RATING'].isna())]
            sub_df = sub_df[~(sub_df['Yield'].isna() | sub_df['PA FIN ITEM'].isna())]
            sub_df = sub_df[~sub_df['GREIGE ITEM'].str.contains('CAT')]
            return sub_df
        case 'jet_info':
            return df
        case 'pa_inventory':
            df['Item'] = df['Item'].str.upper()
            sub_df = df[(df['Quality'] == 'A') & df['ASSIGNED_ORDER'].isna()]
            return sub_df
        case 'adaptive_orders':
            df['Dyelot2'] = df['Dyelot'].map(_convert_dyelot)
            return df
        case 'pa_demand_plan':
            sub_df = df[~df['PA Fin Item'].isna()]
            return sub_df
        case _:
            raise ValueError(f'Unknown excel info \'{info}\'')
        
def to_tsv_file(
        name: Annotated[str, typer.Argument(help="The name of the info from excel_info.dat")],
        default_dir: Annotated[str, typer.Argument(help="The folder to search when 'folder' is not provided")],
        outpath: Annotated[str, typer.Argument(help="The path to which to write the output")]
        ):
    df = load_df(name, default_dir)
    outfile = open(outpath, mode='w+')

    for i in df.index:
        if name == 'fabric_items':
            colnames = list(filter(lambda colname: 'JET' not in colname, df.columns))
            items = [df.loc[i, colname] for colname in colnames]
            jets = []
            for jetidx in (1,2,3,4,7,8,9,10):
                if not pd.isna(df.loc[i, f'JET {jetidx}']):
                    jets.append(f'Jet-{i:02}')
            items.append(' '.join(jets))
            row = '\t'.join([str(x) for x in items])
        else:
            row = '\t'.join([str(df.loc[i, colname]) for colname in df.columns])
        outfile.write(row+'\n')
    
    outfile.close()