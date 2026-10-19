#!/usr/bin/env python

import os
import pyodbc
from pathlib import Path
from datetime import date, datetime, timedelta
from enum import Enum
import re
from importlib.resources import files


SQLCNF_ENV = 'SQLCONFIG'
REPORTS_ENV = 'SWMTREPORTS'

AUDIT_NAME = 'audit'
GREIGE_NAME = 'greige_assigns'
JETS_NAME = 'jets'
SOP_NAME = 'pa_order_sops'
VARIANTS_NAME = 'variants'
LAST_TKT_NAME = 'last_tkt'
LAST_STYLE_NAME = 'style_changes'
RUNOUT_NAME = 'runout'
THREAD_NAME = 'threaded'
DOFFED_NAME = 'doffed'
SETS_ASSN_NAME = 'assigned_sets'
SETS_ACT_NAME = 'active_sets'
THREAD_TKT_NAME = 'thread_tkt'
ALL_SCAN_NAME = 'scanned'

SQL_MAP = {
    AUDIT_NAME: 'audit_trail.txt',
    GREIGE_NAME: 'greige_assigns.txt',
    JETS_NAME: 'jets.txt',
    SOP_NAME: 'sop_xref.txt',
    VARIANTS_NAME: 'si_variants.txt',
    LAST_TKT_NAME: 'last_tkt.txt',
    LAST_STYLE_NAME: 'last_style.txt',
    RUNOUT_NAME: 'runout.txt',
    THREAD_NAME: 'last_threaded.txt',
    DOFFED_NAME: 'doffed_since_date.txt',
    SETS_ASSN_NAME: 'assigned_sets.txt',
    SETS_ACT_NAME: 'active_sets.txt',
    THREAD_TKT_NAME: 'threaded_since_date.txt',
    ALL_SCAN_NAME: 'scanned_since_date.txt'
}

class _SQLName(str, Enum):
    audit = 'audit'
    greige_assigns = 'greige_assigns'
    jets = 'jets'
    pa_order_sops = 'pa_order_sops'
    variants = 'variants'
    last_tkt = 'last_tkt'
    style_changes = 'style_changes'
    runout = 'runout'
    threaded = 'threaded'
    doffed = 'doffed'
    assigned_sets = 'assigned_sets'
    active_sets = 'active_sets'
    thread_tkt = 'thread_tkt'
    scanned = 'scanned'
    all_pa = 'all_pa'


def load_sql_config() -> dict[str, str]:
    try:
        p = Path(os.environ[SQLCNF_ENV])
        ret: dict[str, str] = {}

        with open(p, mode='r') as f:
            for i, line in enumerate(f):
                line = line.split('#')[0].strip()
                if not line: continue

                if '=' not in line:
                    raise SyntaxError(f'line {i+1}: all statements must be assignments')

                key, val = line.split('=')
                ret[key] = val

        return ret
    except KeyError as e1:
        e1.add_note('SQLCONFIG environment variable not set')
        raise e1
    except IsADirectoryError as e2:
        e2.add_note('SQLCONFIG must point to a valid server config file')
        raise e2

def build_cnxn_str(cnfmap: dict[str, str], driver: str = 'ODBC Driver 17 for SQL Server') -> str:
    required = frozenset(['HOST', 'DATABASE', 'USER', 'PASSWORD'])
    missing = required.difference(cnfmap.keys())

    if len(missing) > 0:
        missing = sorted(list(missing))
        raise KeyError('config file missing values for ' + ', '.join(map(lambda s: repr(s), missing)))

    pairs: list[tuple[str, str]] = []
    pairs.append(('DRIVER', driver))

    server = cnfmap['HOST']
    if 'PORT' in cnfmap:
        server += (',' + cnfmap['PORT'])

    pairs.append(('SERVER', server))
    pairs.append(('UID', cnfmap['USER']))
    pairs.append(('PWD', cnfmap['PASSWORD']))
    pairs.append(('DATABASE', cnfmap['DATABASE']))

    for k, v in cnfmap.items():
        if k in required or k == 'PORT': continue
        pairs.append((k, v))

    return ';'.join(map(lambda x: f'{x[0]}={x[1]}', pairs)) + ';'

def extract_sql_from_file(flines: list[str]) -> str:
    sql_lines = []

    in_repeat = False
    repeat_lines = []
    repeat_s, repeat_e = -1, -1

    for line in flines:
        line = line.strip()
        if not line: continue

        if not in_repeat and line[0] == '&' and line.split()[0][1:] == 'REPEAT':
            in_repeat = True
            num_str = line.split('>>')[1].strip()
            repeat_s, repeat_e = list(map(int, num_str.split(', ')))
            continue

        if in_repeat:
            if line == '&END':
                for i in range(repeat_s, repeat_e + 1):
                    for repl in repeat_lines:
                        sql_lines.append(re.sub(r'%', str(i), repl))
                in_repeat = False
                repeat_lines = []
                repeat_s, repeat_e = -1, -1
            else:
                repeat_lines.append(line)
            continue

        line = re.sub(r'\$([0-9]+)', r'{\g<1>}', line)
        sql_lines.append(line)

    return ' '.join(sql_lines)

def write_sql_result(fpath: Path, res: pyodbc.Cursor):
    lines: list[str] = []

    colnames = map(lambda x: x[0], res.description)
    lines.append('\t'.join(colnames) + '\n')

    nrows = res.rowcount
    i = 0

    while True:
        row = res.fetchone()
        i += 1
        if not row: break
        print(f'\trows fetched: {i} of {nrows}', end='\r')

        lines.append('\t'.join(map(str, row)) + '\n')

    print('\n\tquery complete!')

    i = 0
    with open(fpath, 'w+') as outfile:
        for line in lines:
            outfile.write(line)
            i += 1
            print(f'\trows written: {i} of {nrows}', end='\r')

    print('\n\tfile written!')

def run_query(dt: datetime, fstem: _SQLName, sql: str, cursor: pyodbc.Cursor):
    monday = dt - timedelta(days=dt.weekday())
    wk_start = monday - timedelta(days=3)
    mnth_start = monday - timedelta(days=30)
    end = dt + timedelta(days=1)
    year_start = monday - timedelta(weeks=31)

    if dt.weekday() <= 3:
        wk_start -= timedelta(weeks=1)
        mnth_start -= timedelta(weeks=1)

    start = wk_start
    if fstem == 'jets':
        start = mnth_start
    elif fstem == 'pa_order_sops':
        start = datetime(dt.year-1, dt.month, dt.day)
    elif fstem == 'assigned_sets':
        start = year_start

    if fstem == 'pa_order_sops':
        cursor.execute(sql.format(start.strftime('%Y%m%d')))
    elif fstem in ('doffed', 'thread_tkt', 'scanned'):
        cursor.execute(sql.format(dt.strftime('%Y, %m, %d, %H, %M, %S')))
    elif fstem == 'assigned_sets':
        cursor.execute(sql.format(start.year))
    elif fstem in ('variants', 'last_tkt', 'runout', 'threaded', 'active_sets'):
        cursor.execute(sql)
    else:
        cursor.execute(sql.format(start.strftime('%Y%m%d'), end.strftime('%Y%m%d')))

    fname = f'{fstem}_{dt.strftime('%Y%m%d')}.tsv'
    write_sql_result(Path(os.environ['SWMTREPORTS']) / fname, cursor)

def fetch_pa_sql_data(dt: datetime):
    cnfmap = load_sql_config()
    cnxn_str = build_cnxn_str(cnfmap)

    queries = [AUDIT_NAME, GREIGE_NAME, JETS_NAME]

    print('Connecting to database...', end='\r')
    with pyodbc.connect(cnxn_str) as connection:
        print('Connected to SQL server!                  ')
        with connection.cursor() as cursor:
            for q in queries:
                print(f'Running {q} query...')
                qtxt = files('swmtplanner.data').joinpath(SQL_MAP[q]).read_text().split('\n')
                run_query(dt, q, extract_sql_from_file(qtxt), cursor)

def fetch_named_sql_data(dt: datetime, name: str):
    cnfmap = load_sql_config()
    cnxn_str = build_cnxn_str(cnfmap)

    sql = extract_sql_from_file(files('swmtplanner.data').joinpath(SQL_MAP[name]).read_text().split('\n'))

    print('Connecting to database...', end='\r')
    with pyodbc.connect(cnxn_str) as connection:
        print('Connected to SQL server!     ')
        with connection.cursor() as cursor:
            print(f'Running {name} query...')
            run_query(dt, name, sql, cursor)