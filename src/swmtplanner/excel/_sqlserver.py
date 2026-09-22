#!/usr/bin/env python

import os
import pyodbc
from pathlib import Path
from datetime import date, timedelta


SQLCNF_ENV = 'SQLCONFIG'
REPORTS_ENV = 'SWMTREPORTS'

AUDIT_NAME = 'audit'
GREIGE_NAME = 'greige_assigns'
JETS_NAME = 'jets'

AUDIT_SQL = (
    'select * from openquery([JOMARPA],'
    '\'select B2VNR as "Trans ID", B2DAT as "Date", B2TIME as "Time", '
    'B2BNR as "Business Unit", B2PLT as "Plant", '
    'case when B2CHA=\'\'0\'\' then B2BBE else substr(B2CHA, 1, 10) end as "Lot", '
    'B2ANR as "Stock Item", B2KDL as "Cust No.", KNA1 as "Cust Name", '
    'B2RNR as "Roll ID", B2CHR5 as "WIP Roll", '
    'B2BEW as "Trans Code", TRNTXT as "Trans Desc", '
    'B2USER as "Username", B2CHR3 as "Machine", B2LO1 as "Loc 1", B2LO2 as "Loc 2", '
    'B2MGES as "Quantity", B2QUAL as "Quality", '
    'RTFILB as "Grade Code", GRDTXT as "Grade Desc", '
    'RTFIL2 as "Defect Code", DFTTXT as "Defect Desc", '
    'VFLX11 as "SOP", PSA25 as "Slit Instruction", XFLX30 as "Mkt Segment" '
    'from TXMYBW00 '
    'left join TXRYRT00 on RTRNR=B2RNR '
    'left join (select distinct KKDN, KNA1 from TXUYKD00) on KKDN=B2KDL '
    'left join (select distinct VBLN, VANR, VFLX11 from TXUYUF01 where VFLX11 is not null) on '
    '(case when B2CHA=''0'' then B2BBE else substr(B2CHA, 1, 10) end)=VBLN and VANR=B2ANR '
    'left join (select distinct PSANR, PSA25 from TXRYPS00 where PSA25 is not null) on PSANR=VFLX11 '
    'left join (select substr(AXANR, 5) as GRDCODE, AXTXT as GRDTXT '
    'from TXMYTX00 where AXBNR=\'\'002\'\' and AXPLT=\'\'PA\'\' and AXANR like \'\'%QCR%\'\') '
    'on GRDCODE=RTFILB '
    'left join (select substr(AXANR, 3) as DFTCODE, AXTXT as DFTTXT '
    'from TXMYTX00 where AXBNR=\'\'002\'\' and AXPLT=\'\'PA\'\' and AXANR like \'\'#O%\'\') '
    'on DFTCODE=RTFIL2 '
    'left join (select substr(AXANR, 4) as TRNCODE, AXTXT as TRNTXT '
    'from TXMYTX00 where AXBNR=\'\'001\'\' and AXPLT=\'\'01\'\' and AXANR like \'\'#TM%\'\') '
    'on TRNCODE=B2BEW '
    'left join TXMYAT03 on XBNR=B2BNR and XPLT=B2PLT and XANR=B2ANR '
    'where B2DAT>{0} and B2DAT<{1} and B2ANR like \'\'FF%\'\' order by B2VNR\')'
)
GREIGE_SQL = (
    'select * from openquery([JOMARPA],'
    '\'select distinct case when B2CHA=\'\'0\'\' then B2BBE else substr(B2CHA, 1, 10) end as "Lot", '
    'RTANR as "Greige Item", RTRNR as "Greige Roll" from TXMYBW00 '
    'left join (select distinct RTANR, RTRNR, RTALN from TXRYRT00 where RTANR like \'\'GF%\'\') on '
    '(case when B2CHA=\'\'0\'\' then B2BBE else substr(B2CHA, 1, 10) end)=RTALN '
    'where B2DAT>{0} and B2DAT<{1} and B2ANR like \'\'FF%\'\'\')'
)
JETS_SQL = (
    'select * from openquery([JOMARPA], '
    '\'select distinct case when B2CHA=\'\'0\'\' then B2BBE else substr(B2CHA, 1, 10) end as "Lot", '
    'B2CHR3 as "Machine" from TXMYBW00 '
    'where B2DAT>{0} and B2DAT<{1} and B2ANR like \'\'FF%\'\' and B2BEW=\'\'06\'\' '
    'and B2LO2=\'\'BD\'\'\')'
)


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

def run_query(dt: date, fstem: str, sql: str, cursor: pyodbc.Cursor):
    monday = dt - timedelta(days=dt.weekday())
    wk_start = monday - timedelta(days=3)
    mnth_start = monday - timedelta(days=30)
    end = dt + timedelta(days=1)

    if dt.weekday() <= 3:
        wk_start -= timedelta(weeks=1)
        mnth_start -= timedelta(weeks=1)

    start = wk_start
    if fstem == 'jets':
        start = mnth_start

    cursor.execute(sql.format(start.strftime('%Y%m%d'), end.strftime('%Y%m%d')))
    fname = f'{fstem}_{dt.strftime('%Y%m%d')}.tsv'
    write_sql_result(Path(os.environ['SWMTREPORTS']) / fname, cursor)

def fetch_sql_data(dt: date):
    cnfmap = load_sql_config()
    cnxn_str = build_cnxn_str(cnfmap)

    pairs = [(AUDIT_NAME, AUDIT_SQL),
             (GREIGE_NAME, GREIGE_SQL),
             (JETS_NAME, JETS_SQL)]

    print('Connecting to database...', end='\r')
    with pyodbc.connect(cnxn_str) as connection:
        print('Connected to SQL server!                  ')
        with connection.cursor() as cursor:
            for name, sql in pairs:
                print(f'Running {name} query...')
                run_query(dt, name, sql, cursor)