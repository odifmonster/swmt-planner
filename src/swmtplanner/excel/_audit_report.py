#!/usr/bin/env python

from typing import TypedDict, Literal, Any
import pandas as pd, datetime as dt, numpy as np, re


_NON_STR_COLS = ('Trans ID', 'Date', 'Time', 'Quantity')

def _as_group(pattern: str):
    return '(' + pattern + ')'
def _as_opt(pattern: str):
    return pattern + '?'

_NUMBER = r'[0-9]+\.[0-9]+|[0-9]+'
_TEXT_REQ = r'[^0-9]+'
_TEXT_OPT = r'[^0-9]*'

_SLIT_INSTR = (
    _as_group(_NUMBER) + _TEXT_REQ + _as_opt(_as_group(_NUMBER))
    + _TEXT_OPT + _as_opt(_as_group(_NUMBER))
)
_WIP_ROLL_ID = r'([0-9]{10})([0-9]{2})?([A-Z])?([0-9]{2})?'


class _RollMove(TypedDict):
    qty: float
    date1: dt.datetime | Any
    date2: dt.datetime | Any


_RollMoves = dict[Literal['A', 'B', 'C'], _RollMove]

    
class _RollData(TypedDict):
    id: str
    kind: Literal['LOT', 'DOFF', 'PANEL', 'ROLL', 'FIN']
    lot: str
    source: str
    item: str
    movements: dict[str, _RollMoves]


def _load_audit_file(fpath: str):
    audit_cols = []
    with open(fpath, encoding='utf-8-sig') as infile:
        header = infile.readline().strip()
        audit_cols.extend(header.split('\t'))

    return pd.read_csv(
        fpath,
        sep='\t',
        dtype={ c: 'string' for c in audit_cols if c not in _NON_STR_COLS }
    )


def _decode_dt(val):
    x3 = val % 100
    val = (val - x3) // 100
    x2 = val % 100
    val = (val - x2) // 100
    x1 = val
    return x1, x2, x3


def _get_timestamp(row):
    y, m, d = _decode_dt(row['Date'])
    hr, minute, sec = _decode_dt(row['Time'])
    return dt.datetime(year=y, month=m, day=d, hour=hr, minute=minute, second=sec)


def _add_qty(row):
    if row['Trans Desc'] in ('ADJUST DOWN', 'REPORT CONSUMPTION', 'TRANSFER OUT'):
        return row['Quantity'] * -1
    if row['Trans Desc'] == 'INVOICE':
        return 0
    return row['Quantity']


def _get_num_val(x):
    if '.' in x:
        return float(x)
    return int(x)


def _parse_sop_width(sop: str):
    parsed = re.match(_SLIT_INSTR, sop)
    num1 = _get_num_val(parsed.group(1))
    num2 = 1 if parsed.group(2) is None else _get_num_val(parsed.group(2))
    num3 = 0 if parsed.group(3) is None else _get_num_val(parsed.group(3))

    panel_a = num1
    panel_b = 0 if num1 * num2 <= 250 else num2
    panel_c = 0 if num3 <= 30 else num3
    panels = num2 if num1 * num2 <= 250 else 1
    waste = num3

    return panel_a, panel_b, panel_c, (panel_a + panel_b) * panels + waste


def _fmt_item_width(item: str, width: int | float):
    if width == 0:
        return ''
    if int(width) == width:
        return item + '-' + str(int(width))
    return item + '-' + str(width)


def _get_items(row):
    if pd.isna(row['Slit Instruction']):
        return row['Stock Item'], row['Stock Item'], '', ''
    fin1_wd, fin2_wd, fin3_wd, wip_wd = _parse_sop_width(row['Slit Instruction'])
    fin1 = _fmt_item_width(row['Stock Item'], fin1_wd)
    fin2 = _fmt_item_width(row['Stock Item'], fin2_wd)
    fin3 = _fmt_item_width(row['Stock Item'], fin3_wd)
    wip = _fmt_item_width(row['Stock Item'], wip_wd)
    return wip, fin1, fin2, fin3


def _fmt_grade_desc(desc):
    if pd.isna(desc):
        return ''
    last = desc.split()[-1]
    start = desc[:-1*len(last)]
    return start.rstrip()


def _process_audit(audit: pd.DataFrame) -> pd.DataFrame:
    audit = audit.replace({'WIP Roll': {'N': np.nan}})
    audit['AddQty'] = audit[['Trans Desc', 'Quantity']].agg(_add_qty, axis=1)
    audit['Timestamp'] = audit[['Date', 'Time']].agg(_get_timestamp, axis=1)
    audit['Grade Desc'] = audit['Grade Desc'].apply(_fmt_grade_desc).astype('string')

    items = audit[['Stock Item', 'Slit Instruction']].apply(_get_items, axis=1, result_type='expand')
    audit.insert(7, 'WIP Item', items[0])
    audit.insert(8, 'Fin Item 1', items[1])
    audit.insert(9, 'Fin Item 2', items[2])
    audit.insert(10, 'Fin Item 3', items[3])

    return audit


def _get_roll_data(audit: pd.DataFrame) -> list[_RollData]:
    rolls = []
    n = len(audit['Roll ID'].unique())
    count = 0

    for roll, grp in audit.groupby('Roll ID'):
        lots = grp[~pd.isna(grp['Lot'])]['Lot']
        lot = max(lots) if len(lots) > 0 else 'NONE'
        
        wip_ids = grp[~pd.isna(grp['WIP Roll'])]['WIP Roll']
        wip_id = max(wip_ids) if len(wip_ids) > 0 else roll

        parsed = re.match(_WIP_ROLL_ID, wip_id)
        doff = None if parsed is None else parsed.group(2)
        panel = None if parsed is None else parsed.group(3)
        roll_idx = None if parsed is None else parsed.group(4)

        item = max(grp['WIP Item'])
        if not panel is None:
            fin1 = max(grp['Fin Item 1'])
            fin2 = max(grp['Fin Item 2'])
            fin3 = max(grp['Fin Item 3'])
            if panel == 'B' and len(fin2) > 0:
                item = fin2
            elif panel == 'C' and len(fin3) > 0:
                item = fin3
            else:
                item = fin1

        source, kind = '', 'LOT'
        if wip_id != roll:
            source, kind = wip_id, 'FIN'
        elif roll_idx:
            source, kind = roll[:-2], 'ROLL'
        elif panel:
            source, kind = lot, 'PANEL'
        elif doff:
            source, kind = lot, 'DOFF'
        
        rolls.append({
            'id': roll,
            'kind': kind,
            'lot': lot,
            'source': source,
            'item': item,
            'movements': {}
        })

        other_info_cols = [
            'Grade Code', 'Grade Desc', 'Defect Code', 'Defect Desc',
            'Mkt Segment'
        ]
        for col in other_info_cols:
            tgt_col = '_'.join([ x.lower() for x in col.split() ])
            non_na = grp[~grp[col].isna()][col]
            rolls[-1][tgt_col] = max(non_na, default='')
        
        cur = rolls[-1]['movements']

        for key, subgrp in grp.groupby(['Loc 1', 'Quality']):
            loc, qual = key
            if loc not in cur:
                cur[loc] = {}
            cur[loc][qual] = {
                'qty': round(sum(subgrp['AddQty']), ndigits=2),
                'date1': min(subgrp['Timestamp']),
                'date2': max(subgrp['Timestamp'])
            }

        count += 1
        print(f'{count} of {n} rolls processed', end='\r')
    print()

    return rolls


def _get_upgrade_trail(data: list[_RollData]) -> pd.DataFrame:
    roll_rows = []
    row_cols = [
        'id', 'kind', 'lot', 'source',
        'item', 'mkt_segment',
        'created', 'last_transact',
        'loc', 'qual', 'qty',
        'grade_code', 'grade_desc',
        'defect_code', 'defect_desc'
    ]

    for roll_data in data:
        x = roll_data['movements']
        for loc in x.keys():
            qty = max([ x[loc][q]['qty'] for q in x[loc].keys() ])
            if round(qty) >= 0:
                create_date = min([ x[loc][q]['date1'] for q in x[loc].keys() ])
            else:
                create_date = np.nan
                
            for qual in x[loc].keys():
                copies = [
                    'id', 'kind', 'lot', 'source',
                    'item', 'mkt_segment',
                    'grade_code', 'grade_desc',
                    'defect_code', 'defect_desc'
                ]
                roll_rows.append({ col: roll_data[col] for col in copies })
                cur = roll_rows[-1]
                cur['created'] = create_date
                cur['last_transact'] = x[loc][qual]['date2']
                cur['loc'] = loc
                cur['qual'] = qual
                cur['qty'] = x[loc][qual]['qty']

    return pd.DataFrame(data=roll_rows, columns=row_cols)


def _get_status_table(trail: pd.DataFrame) -> pd.DataFrame:
    status_rows = []
    status_cols = [
        'id', 'kind', 'lot', 'item',
        'mkt_segment',
        'created', 'last_transact',
        'loc', 'qual', 'yards',
        'grade_code', 'grade_desc',
        'defect_code', 'defect_desc'
    ]

    for roll, grp in trail.groupby('id'):
        copies = [
            'kind', 'lot', 'item', 'mkt_segment',
            'grade_code', 'grade_desc',
            'defect_code', 'defect_desc'
        ]

        max_qty = max(grp['qty'])
        if round(max_qty) <= 0: continue

        max_qty_rows = grp[grp['qty'] == max_qty]

        status_rows.append({ 'id': roll })
        cur = status_rows[-1]

        for col in copies:
            cur[col] = max(grp[~grp[col].isna()][col], default='')

        cur['created'] = min(grp[~grp['created'].isna()]['created'], default=np.nan)
        cur['last_transact'] = max(grp['last_transact'])
        cur['loc'] = max(max_qty_rows['loc'])
        cur['qual'] = max(max_qty_rows['qual'])
        cur['yards'] = max_qty

    return pd.DataFrame(data=status_rows, columns=status_cols).set_index('id')


def _get_lot_data(greige: pd.DataFrame, jets: pd.DataFrame) -> pd.DataFrame:
    lot_rows = []
    lot_cols = [
        'id', 'jet', 'greige_rolls', 'greige_items'
    ]

    for lot, grp in greige.groupby('Lot'):
        machine_rows = jets[(jets['Lot'] == lot) & ~jets['Machine'].isna()]
        grg_rows = grp[~(grp['Greige Item'].isna() | grp['Greige Roll'].isna())]
        machine = max(machine_rows['Machine'], default=np.nan)
        lot_rows.append({
            'id': lot,
            'jet': machine,
            'greige_rolls': ', '.join(list(grg_rows['Greige Roll'].unique())),
            'greige_items': ', '.join(list(grg_rows['Greige Item'].unique()))
        })
    
    return pd.DataFrame(data=lot_rows, columns=lot_cols).set_index('id')


def _audit_summary(writer: pd.ExcelWriter, fpath1: str, fpath2: str, fpath3: str):
    audit = _load_audit_file(fpath1)
    audit = _process_audit(audit)

    roll_data = _get_roll_data(audit)
    upgrade_trail = _get_upgrade_trail(roll_data)
    status = _get_status_table(upgrade_trail)

    greige = pd.read_csv(fpath2, sep='\t', dtype='string')
    drop_rows = greige[greige['Lot'].isna()].index
    greige = greige.drop(drop_rows, axis=0)

    jets = pd.read_csv(fpath3, sep='\t', dtype='string')
    drop_rows = jets[jets['Lot'].isna()].index
    jets = jets.drop(drop_rows, axis=0)

    lot_data = _get_lot_data(greige, jets)

    upgrade_trail.to_excel(writer, sheet_name='raw_data', index=False)
    status.to_excel(writer, sheet_name='roll_status', index_label='id')
    lot_data.to_excel(writer, sheet_name='lot_data', index_label='id')
