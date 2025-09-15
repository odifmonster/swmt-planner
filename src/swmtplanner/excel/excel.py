#!/usr/bin/env python

import typer, pandas as pd, re, math, datetime as dt
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
                         typer.Argument(help=_INFO_PATH_HELP,
                                        exists=True)]
_OUT_PATH_HELP = 'Path to the file to update'
_OutPathAnno = Annotated[Path,
                         typer.Argument(help=_OUT_PATH_HELP,
                                        writable=True)]

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

def _get_alt_item1(row):
    if pd.isna(row['Nominal\nWidth']):
        return row['Item']
    wd = row['Nominal\nWidth']
    if int(wd) == wd:
        return f'{row['Item']}-{int(wd)}'
    return f'{row['Item']}-{wd}'

def _get_alt_item2(row):
        if row['Code'] == '' or row['Style'] == '' or row['Color'] == '':
            return row['Item']
        if pd.isna(row['Width']):
            return row['Item']

        if int(row['Width']) == row['Width']:
            wd = str(int(row['Width']))
        else:
            wd = str(row['Width'])
        return f'FF {row['Style']}-{row['Color']}-{wd}'

def _get_style(item):
    comps = item.split('-')
    if len(comps) < 2:
        return ''
        
    start = comps[0].split(' ')
    if len(start) < 2:
        return ''
        
    return '-'.join([start[1]] + comps[1:-1])

def _get_color(item):
    comps = item.split('-')
    if len(comps) < 2 or len(comps[-1]) > 5:
        return ''

    return comps[-1]

def _load_pa_floor_mos():
    fpath, pdargs = INFO_MAP['pa_floor_mos']
    mo_df: pd.DataFrame = pd.read_excel(fpath, **pdargs)
    mo_df = df_cols_as_str(mo_df, 'Item\nType', 'Warehouse', 'Customer',
                           'Roll', 'Lot', 'Item', 'Quality', 'Owner',
                           'DEFECT1', 'DEF1_REASON', 'DEFECT2', 'DEF2_REASON',
                           'DEFECT3', 'DEF3_REASON', 'MARKET_SEGMENT')
    
    insp = mo_df['Warehouse'] == 'BG'
    frame = mo_df['Warehouse'] == 'BF'
    slit = mo_df['Warehouse'] == 'BS'
    rework = mo_df['Warehouse'] == 'RW'
    mo_df = mo_df[insp | frame | slit | rework]
    mo_df = mo_df[mo_df['Lot'] != '0']

    mo_df['Item2'] = mo_df[['Nominal\nWidth', 'Item']].agg(_get_alt_item1, axis=1).astype('string')
    mo_df['Style'] = mo_df['Item'].apply(_get_style).astype('string')
    mo_df['Color'] = mo_df['Item'].apply(_get_color).astype('string')
    mo_df['Process'] = mo_df['Warehouse'].apply(_map_warehouse).astype('string')

    return mo_df

def _map_warehouse(wh):
    match wh:
        case 'BG':
            return 'INSPECTION'
        case 'BF':
            return 'FRAME'
        case 'BS':
            return 'SLITTER'
        case 'RW':
            return 'REWORK'
    return 'NONE'

def _pa_process_report(mo_df: pd.DataFrame, writer):
    get_code = lambda item: '' if item[2] != ' ' else item[:2]
    
    mo_df['ItemCode'] = mo_df['Item'].apply(get_code).astype('string')

    first = lambda srs: list(srs)[0]
    by_lot = mo_df.groupby(['Process', 'Lot', 'Quality']).agg(
        Code=pd.NamedAgg(column='ItemCode', aggfunc=first),
        Item=pd.NamedAgg(column='Item', aggfunc=first),
        Style=pd.NamedAgg(column='Style', aggfunc=first),
        Color=pd.NamedAgg(column='Color', aggfunc=first),
        Customer=pd.NamedAgg(column='Customer', aggfunc=first),
        Owner=pd.NamedAgg(column='Owner', aggfunc=first),
        Width=pd.NamedAgg(column='Nominal\nWidth', aggfunc=first),
        Quantity=pd.NamedAgg(column='Quantity', aggfunc='sum'))
    by_lot = by_lot.reset_index()

    by_lot['AltItem'] = by_lot[['Code', 'Item', 'Style', 'Color', 'Width']].agg(_get_alt_item2, axis=1).astype('string')

    by_lot.to_excel(writer, sheet_name='summary', float_format='%.2f', index=False)

def _pa_rework_report(mo_df: pd.DataFrame, writer):
    rwk_df = mo_df[mo_df['Process'] == 'REWORK']
    rwk_df['Code'] = 'RW'
    rwk_df = rwk_df.rename({'Nominal\nWidth': 'Width', 'DEFECT1': 'Defect1',
                            'DEF1_REASON': 'Reason1', 'DEFECT2': 'Defect2',
                            'DEF2_REASON': 'Reason2', 'DEFECT3': 'Defect3',
                            'DEF3_REASON': 'Reason3', 'MARKET_SEGMENT': 'Market'}, axis=1)
    rwk_df['AltItem'] = rwk_df[['Code', 'Item', 'Style', 'Color', 'Width']].agg(_get_alt_item2, axis=1).astype('string')
    rwk_df.to_excel(writer, sheet_name='reworks', float_format='%.2f',
                    columns=['Customer', 'Owner', 'Width', 'Roll', 'Lot',
                             'Item', 'AltItem', 'Quality', 'Quantity',
                             'Defect1', 'Reason1', 'Defect2', 'Reason2',
                             'Defect3', 'Reason3', 'Market'], index=False)

def _parse_ship_day(day_str: str):
    day_str = day_str.lower()
    if 'every' in day_str or 'all' in day_str or 'any' in day_str:
        return { 'monday', 'tuesday', 'wednesday', 'thursday', 'friday' }

    main_pat = '[^a-z]*{}[^a-z]*'
    day_pats = {
        'monday': 'm(on(days?)?)?', 'tuesday': 't(u(e(s(days?)?)?)?)?',
        'wednesday': 'wed(nesdays?)?', 'thursday': 'th(ur(s(days?)?)?)?',
        'friday': 'f(ri(days?)?)?'
    }

    for day in day_pats:
        if re.match(main_pat.format(day_pats[day]), day_str) is not None:
            return day

    return None

def _parse_ship_days(days_str: str):
    if type(days_str) is not str:
        return set()
    
    comps = re.split(',|/|or|and', days_str)
    day_set = set()
    for comp in comps:
        day = _parse_ship_day(comp)
        if type(day) is set:
            return day
        elif day is None:
            print(f'could not parse {repr(comp)}')
        else:
            day_set.add(day)
    return day_set

def _map_ship_day(item, ship_days_data):
    if item in ship_days_data:
        return ship_days_data[item]
    return math.inf    

def _pa_priority_mos_report(start: dt.datetime, mo_df: pd.DataFrame, writer):
    shippath, shipargs = INFO_MAP['lam_ship_dates']
    ship_df: pd.DataFrame = pd.read_excel(shippath, **shipargs)

    reqpath, reqargs = INFO_MAP['pa_reqs']
    reqs_df: pd.DataFrame = pd.read_excel(reqpath, **reqargs)

    ship_df = ship_df[ship_df['Ply1 Item'] != '0']

    days_map = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4
    }

    grouped = ship_df.groupby('Ply1 Item')
    ship_days_data = {}
    for name, group in grouped:
        ship_days = group['Ship Day'].unique()
        
        day_set = set()
        for ship_str in ship_days:
            if not pd.isna(ship_str):
                day_set |= _parse_ship_days(ship_str)

        days = [math.inf] + list(map(lambda x: days_map[x], day_set))
        ship_days_data[name] = min(days)

    reqs_df['Ship Day'] = reqs_df['Ply1 Item'].apply(lambda x: _map_ship_day(x, ship_days_data))

    monday = start - dt.timedelta(days=start.weekday())
    monday = dt.datetime(monday.year, monday.month, monday.day)

    pairs = [(-1, 'past due')]
    for i in range(6):
        pairs.append((i, f'WK{i}'))

    req_data = {
        'item': [], 'pnum': [], 'due_date': [], 'yds': [], 'cum_yds': []
    }

    for i in reqs_df.index:
        fab_id = reqs_df.loc[i, 'PA Item']
        fin = reqs_df.loc[i, 'PA Fin']
        cum_req = 0

        for wk_delta, col_end in pairs:
            req_raw = reqs_df.loc[i, f'FAB req\'d {col_end}']
            if col_end == 'past due':
                pnum = -1
            else:
                pnum = int(col_end[2:])
            wkday = reqs_df.loc[i, 'Ship Day']
            if wkday == math.inf:
                wkday = 2

            lam_due_date = monday + dt.timedelta(weeks=wk_delta, days=wkday)
            due_date = lam_due_date - dt.timedelta(days=5)
            if due_date.weekday() > 4:
                due_date -= dt.timedelta(days=due_date.weekday() - 4)

            cum_req += req_raw
            cur_req_yds = max(0, min(req_raw, cum_req - fin))

            req_data['item'].append(fab_id)
            req_data['pnum'].append(pnum)
            req_data['due_date'].append(due_date)
            req_data['yds'].append(cur_req_yds)
            req_data['cum_yds'].append(cum_req)
    
    orders_df = pd.DataFrame(data=req_data)
    orders_df = df_cols_as_str(orders_df, 'item')

    first = lambda srs: list(srs)[0]
    mo_df = mo_df[(mo_df['Customer'] == '0171910WIP') & (mo_df['Quality'] == 'A')]
    mo_grp_df = mo_df.groupby(['Lot', 'Nominal\nWidth']).agg(
        Process=pd.NamedAgg('Process', first),
        Item=pd.NamedAgg('Item', first),
        ItemWidth=pd.NamedAgg('Item2', first),
        Quantity=pd.NamedAgg('Quantity', 'sum')
    )
    mo_df = mo_grp_df.reset_index()

    mo_data = {
        'mo': [], 'process': [], 'item': [], 'raw_yds': [], 'fin_yds_expected': [],
        'ordered_yds': [], 'pnum': [], 'due_date': []
    }

    for item in orders_df['item'].unique():
        order_idxs = list(orders_df[orders_df['item'] == item].index)
        mo_idxs = list(mo_df[(mo_df['ItemWidth'] == item) & (mo_df['Process'] == 'INSPECTION')].index)

        try:
            item_comps = item.split('-')
            item_no_wd = '-'.join(item_comps[:-1])
            item_wd = float(item_comps[-1])
        except:
            continue

        for proc in ('FRAME', 'SLITTER'):
            sub_df = mo_df[(mo_df['Item'] == item_no_wd) & (mo_df['Process'] == proc)]
            wd2_df = sub_df[sub_df['Nominal\nWidth'] == item_wd*2]
            wd3_df = sub_df[sub_df['Nominal\nWidth'] == item_wd*3]
            mo_idxs += list(wd2_df.index)
            mo_idxs += list(wd3_df.index)

        i, j = 0, 0
        total_prod, total_req = 0, 0
        while i < len(order_idxs) and j < len(mo_idxs):
            o_idx = order_idxs[i]
            m_idx = mo_idxs[j]

            item = orders_df.loc[o_idx, 'item']

            mo_data['mo'].append(mo_df.loc[m_idx, 'Lot'])
            mo_data['process'].append(mo_df.loc[m_idx, 'Process'])
            mo_data['item'].append(item)
            mo_data['raw_yds'].append(mo_df.loc[m_idx, 'Quantity'])

            item_wd = float(item.split('-')[-1])
            true_qty = mo_df.loc[m_idx, 'Quantity']
            if mo_df.loc[m_idx, 'Process'] != 'INSPECTION':
                if mo_df.loc[m_idx, 'Nominal\nWidth'] == item_wd*2:
                    true_qty *= 2 * 0.85
                elif mo_df.loc[m_idx, 'Nominal\nWidth'] == item_wd*3:
                    true_qty *= 3 * 0.85
            else:
                true_qty *= 0.9

            mo_data['fin_yds_expected'].append(true_qty)
            mo_data['ordered_yds'].append(orders_df.loc[o_idx, 'yds'])
            mo_data['pnum'].append(orders_df.loc[o_idx, 'pnum'])
            mo_data['due_date'].append(orders_df.loc[o_idx, 'due_date'])

            if total_prod + true_qty >= total_req + orders_df.loc[o_idx, 'yds']:
                total_req += orders_df.loc[o_idx, 'yds']
                i += 1
            else:
                total_prod += true_qty
                j += 1
    
    prty_mo_df = pd.DataFrame(data=mo_data)
    prty_mo_df = df_cols_as_str(prty_mo_df, 'mo', 'process', 'item')

    prty_mo_df.to_excel(writer, sheet_name='mo_priorities', float_format='%.2f',
                        index=False)
    
class _ReportName(str, Enum):
    pa_floor_status = 'pa_floor_status'
    pa_reworks = 'pa_reworks'
    pa_priority_mos = 'pa_priority_mos'
    all_pa_1427 = 'all_pa_1427'

_REPORT_HELP = 'Name of the report to generate'
_ReportNameAnno = Annotated[_ReportName,
                            typer.Argument(help=_REPORT_HELP)]
_RPRT_OUT_HELP = 'Path to the file to write the report to'
_ReportOutAnno = Annotated[Path,
                           typer.Argument(help=_RPRT_OUT_HELP,
                                          writable=True)]
_START_HELP = 'Start date and time of 0th week of demand ' + \
    '(used to generate priority mos report)'
_StartAnno = Annotated[dt.datetime,
                       typer.Option(help=_START_HELP)]
def generate_report(name: _ReportNameAnno, infopath: _InfoPathAnno,
                    outpath: _ReportOutAnno, start: _StartAnno = dt.datetime.now()):
    load_info_map(infopath)
    mo_df = _load_pa_floor_mos()
    writer = pd.ExcelWriter(outpath, date_format='MM/DD')
    match name:
        case _ReportName.pa_floor_status:
            _pa_process_report(mo_df, writer)
        case _ReportName.pa_reworks:
            _pa_rework_report(mo_df, writer)
        case _ReportName.pa_priority_mos:
            _pa_priority_mos_report(start, mo_df, writer)
        case _ReportName.all_pa_1427:
            _pa_process_report(mo_df, writer)
            _pa_rework_report(mo_df, writer)
            _pa_priority_mos_report(start, mo_df, writer)
    writer.close()