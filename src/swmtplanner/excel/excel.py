#!/usr/bin/env python

import typer, pandas as pd, re, math, datetime as dt, os
from pathlib import Path
from typing import Annotated
from enum import Enum

from .info import INFO_MAP, load_info_map

_INFO_OUT_HELP = 'Path to the new file to generate'
_InfoOutAnno = Annotated[Path, typer.Option(help=_INFO_OUT_HELP,
                                            writable=True, dir_okay=False)]

def gen_info_template(outpath: _InfoOutAnno = 'excel-info.txt'):
    outfile = open(outpath, mode='w+')

    outfile.write('# EDIT DATA SOURCE INFO HERE\n\n')

    outfile.write('# Any text following a pound sign is ignored\n')
    outfile.write('# End a line in ... if you want the next line to be included')
    outfile.write(' as part of the previous one\n')
    outfile.write('# Names with spaces and special characters must be')
    outfile.write(' wrapped in quotes\n')
    outfile.write('# All file paths must be wrapped in quotes\n\n')

    outfile.write('# Values assigned outside of info blocks can be')
    outfile.write(' re-used elsewhere, with a preceding\n')
    outfile.write('# \'$\' to mark it as a reference and not a regular name\n\n')

    outfile.write('FOLDER = <PATH TO MAIN FOLDER HERE>\n')
    outfile.write('WORKBOOK = <PATH TO MAIN WORKBOOK HERE>\n\n')

    outfile.write('# any values that should be interpreted as a list must')
    outfile.write(' be preceded by a *\n')
    outfile.write('*jets = "JET 1", "JET 2", "JET 3", "JET 4", "JET 7", "JET 8",')
    outfile.write(' "JET 9", "JET 10"\n')
    outfile.write('*req_wks = "FAB req\'d WK0", "FAB req\'d WK1", "FAB req\'d WK2",')
    outfile.write(' "FAB req\'d WK3", ...\n')
    outfile.write('    "FAB req\'d WK4", "FAB req\'d WK5"\n\n')

    outfile.write('dye_formulae:\n')
    outfile.write('    # This is always required, must be an absolute path to a file\n')
    outfile.write('    folder=$FOLDER\n    workbook=LamDemandPlanning.xlsx\n')
    outfile.write('    sheet=Xref # This is always required\n')
    outfile.write('    col_names="COLOR NAME", "COLOR NUMBER", "SHADE RATING"\n\n')

    outfile.write('# information about fabric items (which jets they can run on,\n')
    outfile.write('# which greige style they use, etc.)\n')
    outfile.write('pa_fin_items:\n    folder=$FOLDER\n')
    outfile.write('    workbook=LamDemandPlanning.xlsx\n    sheet=Xref\n')
    outfile.write('    col_names="GREIGE ITEM", STYLE, WD, Yield, STATUS,')
    outfile.write(' "COLOR NAME", "COLOR NUMBER", ...\n')
    outfile.write('        "PA FIN ITEM", $jets, "SHADE RATING"\n\n')

    outfile.write('greige_styles: # information about target lbs per greige style roll\n')
    outfile.write('    folder=$FOLDER\n    workbook=LamDemandPlanning.xlsx\n')
    outfile.write('    sheet="Griege Sizes"\n\n')

    outfile.write('greige_translation:\n    folder=$FOLDER\n')
    outfile.write('    workbook=LamDemandPlanning.xlsx\n')
    outfile.write('    sheet="Greige Style Translation"\n')
    outfile.write('    subst_names=inventory, plan ')
    outfile.write('# only use this if the workbook has no column names\n')
    outfile.write('    col_ranges="A:B" # required if providing column names\n')
    outfile.write('    start_row=2 # the first row of data to start reading\n\n')

    outfile.write('jet_info:\n    folder=$FOLDER\n    workbook=master.xlsx\n')
    outfile.write('    sheet=jets\n\n')

    outfile.write('pa_inventory:\n    folder=$FOLDER\n    workbook=$WORKBOOK\n')
    outfile.write('    sheet=1427\n')
    outfile.write('    col_names=Roll, Item, Quality, Pounds, ASSIGNED_ORDER\n')
    outfile.write('    start_row=4\n\n')

    outfile.write('pa_floor_mos:\n    folder=$FOLDER\n')
    outfile.write('    workbook=$WORKBOOK\n    sheet=1427\n')
    outfile.write('    col_names="Item\\nType", Warehouse, Customer, Owner, ')
    outfile.write('Roll, Lot, Item, ...\n')
    outfile.write('        Quality, "Nominal\\nWidth", Quantity, DEFECT1, ')
    outfile.write('DEF1_REASON, DEFECT2, ...\n')
    outfile.write('        DEF2_REASON, DEFECT3, DEF3_REASON, MARKET_SEGMENT\n')
    outfile.write('    start_row=4\n\n')

    outfile.write('adaptive_orders:\n    folder=$FOLDER\n')
    outfile.write('    workbook=$WORKBOOK\n    sheet=Adaptive\n')
    outfile.write('    col_names=Machine, StartTime, EndTime, FinItem, ')
    outfile.write('DyelotID1, DyelotID2, Width, Qty\n\n')

    outfile.write('si_release:\n    folder=$FOLDER\n')
    outfile.write('    workbook="SI release 20250825.xlsx"\n')
    outfile.write('    sheet="Vendor Release Report - Weekly "\n')
    outfile.write('    col_ranges="F,AS:AT"\n')
    outfile.write('    subst_names=greige, daily_lbs, weekly_lbs\n')
    outfile.write('    start_row=3\n    end_row=25\n\n')

    outfile.write('wf_release:\n    folder=$FOLDER\n')
    outfile.write('    workbook="SI release 20250825.xlsx"\n')
    outfile.write('    sheet="Vendor Release Report - Weekly "\n')
    outfile.write('    col_ranges="F,AU"\n    subst_names=greige, weekly_lbs\n')
    outfile.write('    start_row=29\n    end_row=35\n\n')

    outfile.write('lam_ship_dates:\n    folder=$FOLDER\n')
    outfile.write('    workbook=$WORKBOOK\n    sheet="Lam Release"\n')
    outfile.write('    col_names="Stock Item", "Ply1 Item", "Ship Day"\n\n')

    outfile.write('pa_reqs:\n    folder=$FOLDER\n')
    outfile.write('    workbook=$WORKBOOK\n    sheet="Fab shortage 9-15"\n')
    outfile.write('    col_names="PA Item", "Ply1 Item", "FAB req\'d past due",')
    outfile.write(' $req_wks, "PA Fin", ...\n')
    outfile.write('        "Inspection", "Frame", "Dye Orders"')

    outfile.truncate()
    outfile.close()

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
        roll_diff = 60
        if roll_tgt <= 400:
            load_tgt = roll_tgt
            roll_diff = 30
        else:
            load_tgt = roll_tgt / 2

        outfile.write(f'{item}\t{load_tgt-30:.1f}\t{load_tgt+30:.1f}\t')
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
                           'Roll', 'Lot', 'Item', 'Quality', 'Grade', 'Owner',
                           'DEFECT1', 'DEF1_REASON', 'DEFECT2', 'DEF2_REASON',
                           'DEFECT3', 'DEF3_REASON', 'MARKET_SEGMENT')
    
    fin = mo_df['Warehouse'] == 'F1'
    pending = mo_df['Warehouse'] == 'FF'
    pack = mo_df['Warehouse'] == 'BP'
    insp = mo_df['Warehouse'] == 'BG'
    frame = mo_df['Warehouse'] == 'BF'
    slit = mo_df['Warehouse'] == 'BS'
    rework = mo_df['Warehouse'] == 'RW'
    mo_df = mo_df[fin | pending | pack | insp | frame | slit | rework]
    mo_df = mo_df[(mo_df['Lot'] != '0') & (pd.isna(mo_df['Grade']) | (mo_df['Grade'] != 'LOC'))]

    mo_df['Item2'] = mo_df[['Nominal\nWidth', 'Item']].agg(_get_alt_item1, axis=1).astype('string')
    mo_df['Style'] = mo_df['Item'].apply(_get_style).astype('string')
    mo_df['Color'] = mo_df['Item'].apply(_get_color).astype('string')
    mo_df['Process'] = mo_df['Warehouse'].apply(_map_warehouse).astype('string')

    return mo_df

def _load_dye_orders():
    schedpath, schedargs = INFO_MAP['adaptive_orders']
    dyepath, dyeargs = INFO_MAP['pa_714']
    dye_df: pd.DataFrame = pd.read_excel(dyepath, **dyeargs)
    adaptive: pd.DataFrame = pd.read_excel(schedpath, **schedargs)

    bad_rows = dye_df[dye_df['Sales Rep'] == 'Sales Rep']
    dye_df = dye_df.drop(bad_rows.index)
    for col in ('Line Width', 'Dye Order', 'DO Qty'):
        dye_df[col] = dye_df[col].astype('float64')
    
    def convert_dye_order(x):
        if pd.isna(x):
            return ''
        return f'{int(x):010}'
    dye_df['mo'] = dye_df['Dye Order'].apply(convert_dye_order).astype('string')

    dye_data = {
        'job': [], 'dyelot': [], 'machine': [], 'start': [], 'end': []
    }
    for i in adaptive.index:
        if pd.isna(adaptive.loc[i, 'StartTime']): continue
        if pd.isna(adaptive.loc[i, 'EndTime']): continue
        
        job_id = adaptive.loc[i, 'JobID']
        lots = job_id.split('@')[0].split('/')
        for lot in lots:
            if re.match('[0-9]{9}0', lot):
                dye_data['job'].append(job_id)
                dye_data['dyelot'].append(lot)
                dye_data['machine'].append(adaptive.loc[i, 'Machine'])
                dye_data['start'].append(adaptive.loc[i, 'StartTime'])
                dye_data['end'].append(adaptive.loc[i, 'EndTime'])
    sched_df = pd.DataFrame(data=dye_data).merge(dye_df, left_on='dyelot', right_on='mo')
    sched_df = sched_df.sort_values(by='start')

    return sched_df

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
        case 'BP':
            return 'PACKING'
        case 'FF':
            return 'PENDING'
        case 'F1':
            return 'CAN SHIP'
    return 'NONE'

def _pa_process_report(mo_df: pd.DataFrame, writer):
    get_code = lambda item: '' if item[2] != ' ' else item[:2]
    
    mo_df['ItemCode'] = mo_df['Item'].apply(get_code).astype('string')

    first = lambda srs: list(srs)[0]
    def first_market(srs: pd.Series):
        no_na = srs.dropna()
        if len(no_na) == 0:
            return 'NON-AUTO'
        x = list(no_na)[0]
        if x == 'AUTO INT':
            return 'AUTO'
        return 'NON-AUTO'
    
    by_lot = mo_df.groupby(['Process', 'Lot', 'Quality']).agg(
        Code=pd.NamedAgg(column='ItemCode', aggfunc=first),
        Item=pd.NamedAgg(column='Item', aggfunc=first),
        Style=pd.NamedAgg(column='Style', aggfunc=first),
        Color=pd.NamedAgg(column='Color', aggfunc=first),
        Customer=pd.NamedAgg(column='Customer', aggfunc=first),
        Owner=pd.NamedAgg(column='Owner', aggfunc=first),
        Market=pd.NamedAgg(column='MARKET_SEGMENT', aggfunc=first_market),
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
    ship_df = df_cols_as_str(ship_df, 'Stock Item', 'Ply1 Item', 'Ship Day')

    reqpath, reqargs = INFO_MAP['pa_reqs']
    reqs_df: pd.DataFrame = pd.read_excel(reqpath, **reqargs)
    reqs_df = df_cols_as_str(reqs_df, 'PA Item', 'Ply1 Item')

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
        'plant': [], 'item': [], 'lam_item': [], 'pnum': [], 'due_date': [],
        'yds': [], 'cum_yds': []
    }

    for i in reqs_df.index:
        plant = reqs_df.loc[i, 'Plant']
        lam_id = reqs_df.loc[i, 'Ply1 Item']
        fab_id = reqs_df.loc[i, 'PA Item']
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
            cur_req_yds = max(0, min(req_raw, cum_req))

            if cur_req_yds > 100:
                req_data['plant'].append(plant)
                req_data['lam_item'].append(lam_id)
                req_data['item'].append(fab_id)
                req_data['pnum'].append(pnum)
                req_data['due_date'].append(due_date)
                req_data['yds'].append(cur_req_yds)
                req_data['cum_yds'].append(cum_req)
    
    orders_df = pd.DataFrame(data=req_data)
    orders_df = df_cols_as_str(orders_df, 'item')

    dye_df = _load_dye_orders()

    first = lambda srs: list(srs)[0]
    mo_df = mo_df[(mo_df['Customer'] == '0171910WIP') & (mo_df['Quality'] == 'A')
                  & ((mo_df['Grade'] != 'REJ') | pd.isna(mo_df['Grade']))]
    mo_grp_df = mo_df.groupby(['Lot', 'Nominal\nWidth']).agg(
        Warehouse=pd.NamedAgg('Warehouse', first),
        Item=pd.NamedAgg('Item', first),
        ItemWidth=pd.NamedAgg('Item2', first),
        Quantity=pd.NamedAgg('Quantity', 'sum')
    )
    mo_df = mo_grp_df.reset_index()

    mo_data = {
        'mo': [], 'warehouse': [], 'plant': [], 'lam_item': [], 'pa_item': [], 'raw_yds': [],
        'fin_yds_expected': [], 'ordered_yds': [], 'pnum': [], 'due_date': []
    }
    added_mos: set[tuple[str, str]] = set()

    for pa_item in orders_df['item'].unique():
        order_idxs = list(orders_df[orders_df['item'] == pa_item].index)
        mo_idxs = []
        dye_idxs = []
        for proc in ('F1', 'FF', 'BP', 'BG'):
            sub_df = mo_df[(mo_df['ItemWidth'] == pa_item) & (mo_df['Warehouse'] == proc)]
            mo_idxs += list(sub_df.index)

        try:
            item_comps = pa_item.split('-')
            item_no_wd = '-'.join(item_comps[:-1])
            item_wd = float(item_comps[-1])
        except:
            continue

        for proc in ('BF', 'BS'):
            sub_df = mo_df[(mo_df['Item'] == item_no_wd) & (mo_df['Warehouse'] == proc)]
            wd2_df = sub_df[sub_df['Nominal\nWidth'] == item_wd*2]
            wd3_df = sub_df[sub_df['Nominal\nWidth'] == item_wd*3]
            mo_idxs += list(wd2_df.index)
            mo_idxs += list(wd3_df.index)
        
        sub_df = dye_df[dye_df['Item'] == item_no_wd]
        wd2_df = sub_df[sub_df['Line Width'] == item_wd*2]
        wd3_df = sub_df[sub_df['Line Width'] == item_wd*3]
        dye_idxs = list(wd2_df.index) + list(wd3_df.index)

        i, j, k = 0, 0, 0
        total_prod, total_req = 0, 0
        while i < len(order_idxs) and (j < len(mo_idxs) or k < len(dye_idxs)):
            o_idx = order_idxs[i]
            if j < len(mo_idxs):
                m_idx = mo_idxs[j]
                d_idx = -1
            else:
                m_idx = -1
                d_idx = dye_idxs[k]

            pa_item = orders_df.loc[o_idx, 'item']
            lam_item = orders_df.loc[o_idx, 'lam_item']
            plant = orders_df.loc[o_idx, 'plant']
            item_wd = float(pa_item.split('-')[-1])

            if m_idx >= 0:
                true_qty = mo_df.loc[m_idx, 'Quantity']
                if mo_df.loc[m_idx, 'Warehouse'] in ('BF', 'BS'):
                    if mo_df.loc[m_idx, 'Nominal\nWidth'] == item_wd*2:
                        true_qty *= 2 * 0.85
                    elif mo_df.loc[m_idx, 'Nominal\nWidth'] == item_wd*3:
                        true_qty *= 3 * 0.85
                elif mo_df.loc[m_idx, 'Warehouse'] == 'BG':
                    true_qty *= 0.9

                rem_qty = total_req + orders_df.loc[o_idx, 'yds'] - total_prod
                cur_pair = (mo_df.loc[m_idx, 'Lot'], mo_df.loc[m_idx, 'Warehouse'])
            else:
                true_qty = dye_df.loc[d_idx, 'DO Qty']
                if dye_df.loc[d_idx, 'Line Width'] == item_wd*2:
                    true_qty *= 2 * 0.85
                elif dye_df.loc[d_idx, 'Line Width'] == item_wd*3:
                    true_qty *= 3 * 0.85
                
                rem_qty = total_req + orders_df.loc[o_idx, 'yds'] - total_prod
                cur_pair = (dye_df.loc[d_idx, 'mo'], 'DYEHOUSE')

            if rem_qty >= 100 and cur_pair not in added_mos:
                added_mos.add(cur_pair)
                mo_data['mo'].append(cur_pair[0])
                mo_data['warehouse'].append(cur_pair[1])
                mo_data['plant'].append(plant)
                mo_data['lam_item'].append(lam_item)
                mo_data['pa_item'].append(pa_item)
                if m_idx >= 0:
                    mo_data['raw_yds'].append(mo_df.loc[m_idx, 'Quantity'])
                else:
                    mo_data['raw_yds'].append(dye_df.loc[d_idx, 'DO Qty'])
                mo_data['fin_yds_expected'].append(true_qty)
                mo_data['ordered_yds'].append(orders_df.loc[o_idx, 'yds'])
                mo_data['pnum'].append(orders_df.loc[o_idx, 'pnum'])
                mo_data['due_date'].append(orders_df.loc[o_idx, 'due_date'])

            if total_prod + true_qty >= total_req + orders_df.loc[o_idx, 'yds']:
                total_req += orders_df.loc[o_idx, 'yds']
                i += 1
            else:
                total_prod += true_qty
                if j < len(mo_idxs):
                    j += 1
                else:
                    k += 1
    
    prty_mo_df = pd.DataFrame(data=mo_data)
    prty_mo_df = df_cols_as_str(prty_mo_df, 'mo', 'warehouse', 'lam_item', 'pa_item')

    prty_mo_df.to_excel(writer, sheet_name='mo_priorities', float_format='%.2f',
                        index=False)
    orders_df.to_excel(writer, sheet_name='demand', float_format='%.2f',
                       index=False)
    
class _ReportName(str, Enum):
    pa_floor_status = 'pa_floor_status'
    pa_reworks = 'pa_reworks'
    pa_priority_mos = 'pa_priority_mos'
    all_pa_1427 = 'all_pa_1427'

_REPORT_HELP = 'Name of the report to generate'
_ReportNameAnno = Annotated[_ReportName,
                            typer.Argument(help=_REPORT_HELP)]
_RPRT_OUT_HELP = 'Path to the folder to write the report to'
_ReportOutAnno = Annotated[Path,
                           typer.Argument(help=_RPRT_OUT_HELP,
                                          dir_okay=True,
                                          file_okay=False,
                                          exists=True)]
_START_HELP = 'Start date and time of 0th week of demand ' + \
    '(used to generate priority mos report)'
_StartAnno = Annotated[dt.datetime,
                       typer.Option(help=_START_HELP)]
def generate_report(name: _ReportNameAnno, infopath: _InfoPathAnno,
                    outdir: _ReportOutAnno, start: _StartAnno = dt.datetime.now()):
    load_info_map(infopath)
    mo_df = _load_pa_floor_mos()
    today = dt.date.today().strftime('%Y%m%d')
    fname = f'{name.name}_{today}.xlsx'
    i = 1
    while os.path.exists(os.path.join(outdir, fname)):
        i += 1
        fname = f'{name.name}_{today}_{i}.xlsx'
    outpath = os.path.join(outdir, fname)
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