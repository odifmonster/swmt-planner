#!/usr/bin/env python

import typer, pandas as pd, datetime as dt, os
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

def _grg_dmnd(start: dt.datetime, writer):
    schedpath, schedargs = INFO_MAP['dye_plan']
    sched_df: pd.DataFrame = pd.read_excel(schedpath, **schedargs)
    sched_df = df_cols_as_str(sched_df, 'jet', 'job', 'lot', 'greige', 'roll1',
                              'roll2', 'item', 'color')
    
    def get_wk_num(d: dt.datetime):
        return d.isocalendar().week
    sched_df['week'] = sched_df['start'].apply(get_wk_num)
    sched_df['is_new'] = sched_df['roll1'].str.contains('PLAN') | \
        sched_df['roll1'].str.contains('NEW') | sched_df['roll2'].str.contains('PLAN') | \
        sched_df['roll2'].str.contains('NEW')
    
    invpath, invargs = INFO_MAP['dye_plan_inv']
    inv_df: pd.DataFrame = pd.read_excel(invpath, **invargs)
    inv_df = df_cols_as_str(inv_df, 'roll_id', 'greige')

    grgpath, grgargs = INFO_MAP['greige_styles']
    grg_df: pd.DataFrame = pd.read_excel(grgpath, **grgargs)
    grg_df = df_cols_as_str(grg_df, 'GreigeAlt', 'GreigeAlt2')

    inv_df = inv_df[(inv_df['lbs'] > 100) & ~(inv_df['roll_id'].str.contains('NEW') | \
                                              inv_df['roll_id'].str.contains('PLAN'))]
    
    weeks = sched_df['week'].unique()
    grg_data = { str(week): [] for week in sorted(weeks) }
    grg_idxs = []

    for grg, group in sched_df.groupby('greige'):
        grg_idxs += [(grg, 'hard'), (grg, 'soft'), (grg, 'total')]
        for week in sorted(weeks):
            old_df = group[~group['is_new'] & (group['week'] < week)]
            new_df = group[group['is_new'] & (group['week'] < week)]
            used_old = sum(old_df['lbs1']) + sum(old_df['lbs2'])
            used_new = sum
    
class _ReportName(str, Enum):
    pa_floor_status = 'pa_floor_status'
    pa_reworks = 'pa_reworks'
    pa_priority_mos = 'pa_priority_mos'
    all_pa_1427 = 'all_pa_1427'
    greige_demand = 'greige_demand'

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
    outpath = os.path.join(outdir, fname)
    writer = pd.ExcelWriter(outpath, date_format='MM/DD')

    if name != _ReportName.greige_demand:
        load_info_map(infopath)
        mo_df = _load_pa_floor_mos()
        today = dt.date.today().strftime('%Y%m%d')
        fname = f'{name.name}_{today}.xlsx'
        i = 1
        while os.path.exists(os.path.join(outdir, fname)):
            i += 1
            fname = f'{name.name}_{today}_{i}.xlsx'
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