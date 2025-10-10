#!/usr/bin/env python

import typer, pandas as pd, numpy as np, datetime as dt, os
from pathlib import Path
from typing import Annotated
from enum import Enum

from .info import INFO_MAP, load_info_map
from ._updates import _grg_trans_file, _grg_style_file, _dyes_file, _pa_items_file, \
    df_cols_as_str
from ._fab_reports import _load_pa_floor_mos, _pa_process_report, \
    _pa_priority_mos_report, _pa_rework_report

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

def _greige_reqs(writer):
    sched_path, sched_args = INFO_MAP['dye_plan']
    inv_path, inv_args = INFO_MAP['dye_plan_inv']
    grg_path, grg_args = INFO_MAP['greige_styles']

    sched_df = pd.read_excel(sched_path, **sched_args)
    sched_df = df_cols_as_str(sched_df, 'jet', 'job', 'lot', 'greige', 'roll1', 'roll2', 'item', 'color')

    grg_df = pd.read_excel(grg_path, **grg_args)
    grg_df = df_cols_as_str(grg_df, 'GreigeAlt', 'GreigeAlt2')
    grg_df = grg_df.set_index('GreigeAlt')

    inv_df = pd.read_excel(inv_path, **inv_args)
    inv_df = df_cols_as_str(inv_df, 'roll_id', 'greige')

    sched_df['week'] = sched_df['start'].apply(lambda d: d.isocalendar().week)
    sched_df['is_new1'] = sched_df['roll1'].str.contains('NEW|PLAN')
    sched_df['is_new2'] = sched_df['roll2'].str.contains('NEW|PLAN')

    def map_to_alt_grg(g):
        return grg_df.loc[g, 'GreigeAlt2']
    sched_df['greige2'] = sched_df['greige'].apply(map_to_alt_grg).astype('string')

    inv_df['greige2'] = inv_df['greige'].apply(map_to_alt_grg).astype('string')
    is_new = inv_df['roll_id'].str.contains('NEW|PLAN')
    is_small = (inv_df['lbs'] <= 100) & (inv_df['used'] == 0)
    to_drop = inv_df[is_new | is_small].index
    inv_df = inv_df.drop(index=to_drop)

    grouped_inv = inv_df.groupby('greige2').agg(lbs=pd.NamedAgg(column='lbs', aggfunc='sum'))

    weeks = sorted(sched_df['week'].unique())
    grg_data = { str(w): [] for w in weeks }
    grg_idx = []

    for alt_grg, group in sched_df.groupby('greige2'):
        extra_prod = 0
        sfty_tgt = sum(grg_df[grg_df['GreigeAlt2'] == alt_grg]['SafetyTgt'])
        grg_idx += [(alt_grg, 'on_hand'), (alt_grg, 'hard'), (alt_grg, 'safety'), (alt_grg, 'total')]
        
        for week in weeks:
            old_df1 = group[~group['is_new1']]
            old_df2 = group[~group['is_new2']]
            old_used = sum(old_df1['lbs1']) + sum(old_df2['lbs2'])
            
            new_df1 = group[group['is_new1'] & (group['week'] == week)]
            new_df2 = group[group['is_new2'] & (group['week'] == week)]
            new_used = sum(new_df1['lbs1']) + sum(new_df2['lbs2'])
            
            rem_inv = grouped_inv.loc[alt_grg, 'lbs'] + extra_prod - old_used
            
            cur_safety = max(0, sfty_tgt - rem_inv)
            grg_data[str(week)] += [grouped_inv.loc[alt_grg, 'lbs'], new_used, cur_safety, new_used + cur_safety]
            extra_prod += cur_safety
    
    idx = pd.MultiIndex.from_tuples(grg_idx, names=['item', 'kind'])
    grg_reqs = pd.DataFrame(data=grg_data, index=idx)

    grg_reqs.to_excel(writer, sheet_name='greige_reqs', float_format='%.2f')

def _audit_summary(date: dt.datetime, writer):
    fpath1, _ = INFO_MAP['pa_2010']
    fpath1 += f'_{date.strftime('%Y%m%d')}.csv'
    
    audit = pd.read_csv(fpath1, dtype={'Lot': 'string'})
    drop_rows = audit[~audit['Valid Lot'] | (audit['Lot'].str[-1] != '0')].index
    audit = audit.drop(drop_rows, axis=0)

    fpath2, pdargs2 = INFO_MAP['pa_seconds']
    start, ext = fpath2.split('.')
    fpath2 = f'{start}_{date.strftime('%Y%m%d')}.{ext}'
    seconds: pd.DataFrame = pd.read_excel(fpath2, **pdargs2, dtype={'ROLL': 'string', 'REASON': 'string'})
    seconds = seconds.set_index('ROLL')

    def _split_raw_dt_val(raw):
        raw = int(raw)
        val3 = raw % 100
        val2 = int((raw % 10000 - val3) / 100)
        val1 = int((raw - val2*100 - val3) / 10000)
        return val1, val2, val3
    
    def _get_timestamp(row):
        y, m, d = _split_raw_dt_val(row['Trans Date'])
        hour, minute, sec = _split_raw_dt_val(row['Trans Time'])
        return dt.datetime(y, m, d, hour=hour, minute=minute, second=sec)
    
    audit['Timestamp'] = audit[['Trans Date', 'Trans Time']].agg(_get_timestamp, axis=1)

    def _get_roll_type(row):
        if row['Lot'] not in row['Roll ID']:
            return 'FIN'
        if len(row['Roll ID']) == 10:
            return 'LOT'
        if len(row['Roll ID']) == 13:
            return 'PANEL'
        return 'ROLL'

    def _get_doff(row):
        if row['Roll Type'] in ('FIN', 'LOT'):
            return np.nan
        return int(row['Roll ID'][10:12])
    
    def _get_panel(row):
        if row['Roll Type'] in ('FIN', 'LOT'):
            return np.nan
        return row['Roll ID'][12]
    
    def _get_insp_roll(row):
        if row['Roll Type'] == 'ROLL':
            return int(row['Roll ID'][-2:])
        return np.nan
    
    audit['Roll Type'] = audit[['Roll ID', 'Lot']].agg(_get_roll_type, axis=1)
    audit['Doff'] = audit[['Roll Type', 'Roll ID']].agg(_get_doff, axis=1)
    audit['Panel'] = audit[['Roll Type', 'Roll ID']].agg(_get_panel, axis=1)
    audit['Insp Roll'] = audit[['Roll Type', 'Roll ID']].agg(_get_insp_roll, axis=1)

    def _get_add_qty(row):
        if row['Trans Desc'] in ('PHYSICAL ADJUSTMENT', 'ADJUST UP', 'REPORT PRODUCTION'):
            return row['Qty']
        if row['Trans Desc'] in ('ADJUST DOWN', 'REPORT CONSUMPTION'):
            return row['Qty'] * -1
        return np.nan
    
    audit['AddQty'] = audit[['Qty', 'Trans Desc']].agg(_get_add_qty, axis=1)

    idx = []
    roll_data = {
        'kind': [], 'mo': [], 'market': [], 'item': [], 'yds': [], 'processed_yds': [],
        'code': [], 'timestamp': []
    }

    for key, grp in audit.groupby(['Roll Type', 'Roll ID']):
        kind, roll = key
        if kind == 'LOT': continue
            
        first = list(grp.index)[0]

        if kind == 'FIN':
            init_opts = grp[grp['Trans Desc'].str.contains('TRANSFER|PRODUCTION')]
            if len(init_opts) == 0: continue

        idx.append(roll)
        max_yds = max(grp['Qty'])
        amts = {}
        
        init_rows_added = grp[(grp['Qty'] == max_yds) & ~pd.isna(grp['AddQty'])]
        init_rows = grp[grp['Qty'] == max_yds]
        first = list(init_rows.index)[0]
        init_code = audit.loc[first, 'Quality Code']
        adjust_code = None

        if len(init_rows_added) == 0:
            if kind == 'FIN':
                amts[init_code] = max_yds
            else:
                amts[init_code] = { 'add': max_yds, 'rem': 0 }

        for i in grp.index:
            if pd.isna(audit.loc[i, 'AddQty']): continue
            add_qty = audit.loc[i, 'AddQty']
            code = audit.loc[i, 'Quality Code']
            trans = audit.loc[i, 'Trans Desc']
            
            if code not in amts:
                if kind == 'FIN':
                    amts[code] = 0
                else:
                    amts[code] = { 'add': 0, 'rem': 0 }

            if kind == 'FIN':
                amts[code] += add_qty
            else:
                if add_qty < 0:
                    amts[code]['rem'] += add_qty*-1
                else:
                    amts[code]['add'] += add_qty
                    
            if code != init_code and audit.loc[i, 'AddQty'] > 0 and adjust_code is not None:
                adjust_code = code

        roll_data['kind'].append(kind)
        pairs = [('mo', 'Lot'), ('market', 'Market Segme'), ('item', 'Fin Item 1')]
        for col1, col2 in pairs:
            roll_data[col1].append(audit.loc[first, col2])

        code = init_code if adjust_code is None else adjust_code
        if kind == 'FIN':
            qty = amts[code]
            processed = 0
        else:
            qty = amts[code]['add']
            processed = amts[code]['rem']
        roll_data['yds'].append(qty)
        roll_data['processed_yds'].append(processed)
        roll_data['code'].append(code)
        roll_data['timestamp'].append(max(grp['Timestamp']))

    by_roll = pd.DataFrame(data=roll_data, index=idx)
    by_roll = by_roll.merge(seconds, left_index=True, right_index=True, how='left')
    by_roll = by_roll.rename(columns={'REASON': 'defect_code', 'DEFECT': 'defect_desc'})

    for i in by_roll.index:
        minval = by_roll.loc[i, 'processed_yds'] - 2
        maxval = minval + 4
        if minval <= by_roll.loc[i, 'yds'] * 2 <= maxval:
            by_roll.loc[i, 'processed_yds'] = by_roll.loc[i, 'yds']
        elif by_roll.loc[i, 'yds'] < minval:
            by_roll.loc[i, 'yds'] = by_roll.loc[i, 'processed_yds']
    
    by_roll.to_excel(writer, sheet_name='audit_raw', index_label='id')
    
class _ReportName(str, Enum):
    pa_floor_status = 'pa_floor_status'
    pa_reworks = 'pa_reworks'
    pa_priority_mos = 'pa_priority_mos'
    all_pa_1427 = 'all_pa_1427'
    greige_demand = 'greige_demand'
    pa_audit_sum = 'pa_audit_sum'

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
    today = dt.date.today().strftime('%Y%m%d')
    fname = f'{name.name}_{today}.xlsx'
    i = 1
    while os.path.exists(os.path.join(outdir, fname)):
        i += 1
        fname = f'{name.name}_{today}_{i}.xlsx'
    outpath = os.path.join(outdir, fname)
    writer = pd.ExcelWriter(outpath, date_format='MM/DD',
                            datetime_format='%Y-%m-%d %H:%M')

    load_info_map(infopath)

    if name not in (_ReportName.greige_demand, _ReportName.pa_audit_sum):
        mo_df = _load_pa_floor_mos()
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
    elif name == _ReportName.pa_audit_sum:
        _audit_summary(start, writer)
    elif name == _ReportName.greige_demand:
        _greige_reqs(writer)
    
    writer.close()