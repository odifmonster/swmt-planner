#!/usr/bin/env python

import typer, os, warnings, pandas as pd
from typing_extensions import Annotated, Optional
from pathlib import Path
from enum import Enum

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
                str_cols = ['Dyelot', 'Machine', 'Color']
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

def _detect_dirpath(root: str):
    workbooks = set()
    for value in globals()['_INFO_MAP'].values():
        if value[0] is None:
            workbooks.add(value[1])
    
    dirtups = os.walk(root)
    valid_paths = []
    for dirpath, _, filenames in dirtups:
        if workbooks.issubset(set(filenames)):
            valid_paths.append(os.path.abspath(dirpath))
    
    if len(valid_paths) == 0:
        raise ValueError(f'\'{root}\' does not contain a valid default directory')
    
    if len(valid_paths) > 0:
        msg = 'Found multiple valid default directories, using first option: '
        msg += f'\'{valid_paths[0]}\''
        warnings.warn(msg, category=RuntimeWarning)
    return valid_paths[0]

def _detect_outpath(info: str):
    srcdir = os.path.dirname(os.path.dirname(__file__))
    dirtups = os.walk(srcdir)
    fname = info.replace('_', '-') + '.dat'
    for dirpath, _, filenames in dirtups:
        if fname in filenames:
            return os.path.join(dirpath, fname)
    raise ValueError(f'Could not find \'{fname}\' file to update in project tree')

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
        case 'jet_info' | 'adaptive_orders':
            return df
        case 'pa_inventory':
            df['Item'] = df['Item'].str.upper()
            sub_df = df[(df['Quality'] == 'A') & df['ASSIGNED_ORDER'].isna()]
            return sub_df
        case 'pa_demand_plan':
            sub_df = df[~df['PA Fin Item'].isna()]
            return sub_df
        case _:
            raise ValueError(f'Unknown excel info \'{info}\'')

class _Name(str, Enum):
    greige_translation = 'greige_translation'
    greige_sizes = 'greige_sizes'
    dye_formulae = 'dye_formulae'
    fabric_items = 'fabric_items'
    jet_info = 'jet_info'
    pa_inventory = 'pa_inventory'
    adaptive_orders = 'adaptive_orders'
    pa_demand_plan = 'pa_demand_plan'

class _DirKind(str, Enum):
    explicit = 'explicit'
    detected = 'detected'

_NameArg = typer.Argument(help='The name of the info from excel_info.dat',
                          case_sensitive=False)
_DKindArg = typer.Argument(help='The type of default directory path being provided',
                           case_sensitive=False)
_DirArg = typer.Argument(help='The path to the directory to search for the files',
                         exists=True, dir_okay=True, file_okay=False, resolve_path=True)
_OutOpt = typer.Option('--output', '-o',
                       help='An explicit path to the desired output file',
                       dir_okay=False, file_okay=True, writable=True, resolve_path=True)

def to_tsv_file(
        name: Annotated[_Name, _NameArg],
        dirkind: Annotated[_DirKind, _DKindArg],
        dirpath: Annotated[Path, _DirArg],
        outpath: Annotated[Path | None, _OutOpt] = None):
    
    if dirkind == _DirKind.explicit:
        default_dir = str(dirpath)
    else:
        default_dir = _detect_dirpath(str(dirpath))

    if outpath is None:
        outpath = _detect_outpath(name.value)
    else:
        outpath = str(outpath)

    assert outpath is not None

    df = load_df(name.value, default_dir)
    outfile = open(outpath, mode='w+')

    for i in df.index:
        if name == 'fabric_items':
            colnames = list(filter(lambda colname: 'JET' not in colname, df.columns))
            items = [df.loc[i, colname] for colname in colnames]
            jets = []
            for jetidx in (1,2,3,4,7,8,9,10):
                if not pd.isna(df.loc[i, f'JET {jetidx}']):
                    jets.append(f'Jet-{jetidx:02}')
            if not jets: continue
            items.append(' '.join(jets))
            row = '\t'.join([str(x) for x in items])
        else:
            row = '\t'.join([str(df.loc[i, colname]) for colname in df.columns])
        outfile.write(row+'\n')
    
    outfile.close()