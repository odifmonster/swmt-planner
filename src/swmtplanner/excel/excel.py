#!/usr/bin/env python

import typer, pandas as pd, datetime as dt, os
from pathlib import Path
from typing import Annotated
from enum import Enum

from .info import INFO_MAP, load_info_map
from ._updates import _grg_trans_file, _grg_style_file, _dyes_file, _pa_items_file, \
    df_cols_as_str
from ._fab_reports import _load_pa_floor_mos, _pa_dmnd_report, _pa_process_report, \
    _pa_priority_mos_report, _pa_rework_report, _load_dye_orders1, _load_dye_orders2
from ._audit_report import _audit_summary

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
    outfile.write('REPORTS = <PATH TO REPORTS FOLDER HERE>\n')
    outfile.write('WORKBOOK = <PATH TO MAIN WORKBOOK HERE>\n')
    outfile.write('OUTPUT = <PATH TO CURRENT OUTPUT FILE HERE>\n')
    outfile.write('MASTER = <PATH TO MASTER XREF FILE HERE>\n\n')

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

    outfile.write('adaptive1_orders:\n    folder=$FOLDER\n')
    outfile.write('    workbook=$WORKBOOK\n    sheet="Orders in Dye"\n')
    outfile.write('    col_names=job, dyelot, machine, start, end, item1, item2, panels, ')
    outfile.write('qty, "double?", Customer\n\n')

    outfile.write('adaptive2_orders:\n    folder=$FOLDER\n')
    outfile.write('    workbook="Dyelots.xlsx"\n    sheet=Sheet1\n')
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

    outfile.write('lam_release:\n    folder=$FOLDER\n    workbook=$WORKBOOK\n')
    outfile.write('    sheet="Lam Release"\n    col_names="Stock Item", "Lam Item", "Plant", "Ply1 Item", ')
    outfile.write('"PA Item", "Active?", "Add\'l pull (weeks)", ...\n')
    outfile.write('    "Lam On-Hand", "Lam Cust Contain GP12", "PH Raw", ')
    outfile.write('"Ply1 On-Hand", "LAM add\'l WL factor", ...\n')
    outfile.write('    "Conversion to Yards", "SCH PD", "SCH+0", "SCH+1", ')
    outfile.write('"SCH+2", "Past Due", "Total Inv", ...\n')
    outfile.write('    "RLS+0", "RLS+1", "RLS+2", "RLS+3", "RLS+4", "RLS+5", ')
    outfile.write('"RLS+6", "RLS+7", "RLS+8", "Schedule Day"\n\n')

    outfile.write('pa_reqs:\n    folder=$FOLDER\n')
    outfile.write('    workbook=$WORKBOOK\n    sheet="Fab shortage 9-15"\n')
    outfile.write('    col_names="PA Item", "Ply1 Item", "FAB req\'d past due",')
    outfile.write(' $req_wks, "PA Fin", ...\n')
    outfile.write('        "Inspection", "Frame", "Dye Orders"\n\n')

    outfile.write('pa_714:\n    folder=$FOLDER\n    workbook=$WORKBOOK\n')
    outfile.write('    sheet=714\n    col_names="Sales Rep", Item, "Order Type", ')
    outfile.write('"Line Width", "Dye Order", "DO Qty", ...\n')
    outfile.write('    "Fin Item", "Fin Yds"\n\n')
    
    outfile.write('dye_plan:\n    folder=$FOLDER\n    workbook=$OUTPUT\n')
    outfile.write('    sheet=roll_allocation\n\n')

    outfile.write('pa_raw_demand:\n    folder=$FOLDER\n    workbook=$OUTPUT\n')
    outfile.write('    sheet=demand\n\n')
    
    outfile.write('dye_plan_inv:\n    folder=$FOLDER\n    workbook=$OUTPUT\n')
    outfile.write('    sheet=inventory\n\n')
    
    outfile.write('pa_audit:\n    folder=$REPORTS\n    workbook="audit"\n    sheet=Placeholder\n\n')

    outfile.write('pa_greige_assigns:\n    folder=$REPORTS\n')
    outfile.write('    workbook="greige_assigns"\n    sheet=Placeholder\n\n')

    outfile.write('pa_seconds:\n    folder=$REPORTS\n    workbook="1503.xlsx"\n')
    outfile.write('    sheet="Seconds Report"\n    col_names="ROLL", "DEFECT", "REASON"')
    
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

    sched_df['week'] = sched_df['start'].apply(lambda d: (d.isocalendar().year, d.isocalendar().week))
    sched_df['is_new1'] = sched_df['roll1'].str.contains('NEW|PLAN')
    sched_df['is_new2'] = sched_df['roll2'].str.contains('NEW|PLAN')

    def map_to_alt_grg(g):
        return grg_df.loc[g, 'GreigeAlt2']
    sched_df['greige2'] = sched_df['greige'].apply(map_to_alt_grg).astype('string')

    inv_df['greige2'] = inv_df['greige'].apply(map_to_alt_grg).astype('string')
    is_new = inv_df['roll_id'].str.contains('NEW|PLAN')
    is_small = (inv_df['lbs'] < 300) & (inv_df['used'] == 0)
    to_drop = inv_df[is_new | is_small].index
    inv_df = inv_df.drop(index=to_drop)

    grouped_inv = inv_df.groupby('greige2').agg(lbs=pd.NamedAgg(column='lbs', aggfunc='sum'))

    weeks = sorted(sched_df['week'].unique())
    grg_data = { str(w[1]): [] for w in weeks }
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
            
            if alt_grg not in grouped_inv.index:
                cur_inv = 0
            else:
                cur_inv = grouped_inv.loc[alt_grg, 'lbs']
            rem_inv = cur_inv + extra_prod - old_used
            
            cur_safety = max(0, sfty_tgt - rem_inv)
            grg_data[str(week[1])] += [cur_inv, new_used, cur_safety, new_used + cur_safety]
            extra_prod += cur_safety
    
    idx = pd.MultiIndex.from_tuples(grg_idx, names=['item', 'kind'])
    grg_reqs = pd.DataFrame(data=grg_data, index=idx)

    grg_reqs.to_excel(writer, sheet_name='greige_reqs', float_format='%.2f')
    
class _ReportName(str, Enum):
    pa_dmnd = 'pa_dmnd'
    pa_floor_status = 'pa_floor_status'
    pa_reworks = 'pa_reworks'
    pa_priority_mos = 'pa_priority_mos'
    pa_dye_orders = 'pa_dye_orders'
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
    today = start.strftime('%Y%m%d')
    fname = f'{name.name}_{today}.xlsx'
    i = 1
    while os.path.exists(os.path.join(outdir, fname)):
        i += 1
        fname = f'{name.name}_{today}_{i}.xlsx'
    outpath = os.path.join(outdir, fname)
    writer = pd.ExcelWriter(outpath, date_format='MM/DD',
                            datetime_format='MM/DD/YYYY HH:MM')

    load_info_map(infopath)

    if name not in (_ReportName.greige_demand, _ReportName.pa_audit_sum, _ReportName.pa_dye_orders,
                    _ReportName.pa_dmnd):
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
    else:
        match name:
            case _ReportName.pa_dmnd:
                _pa_dmnd_report(writer)
            case _ReportName.pa_audit_sum:
                suffix = f'_{start.strftime('%Y%m%d')}.tsv'
                fpath1, _ = INFO_MAP['pa_audit']
                fpath2, _ = INFO_MAP['pa_greige_assigns']
                fpath3, _ = INFO_MAP['pa_mo_to_jet']

                fpath1 += suffix
                fpath2 += suffix
                fpath3 += suffix
                _audit_summary(writer, fpath1, fpath2, fpath3)
            case _ReportName.greige_demand:
                _greige_reqs(writer)
            case _ReportName.pa_dye_orders:
                df = _load_dye_orders1()
                df.to_excel(writer, sheet_name='Orders in Dye', index=False)
    
    writer.close()