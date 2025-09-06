#!/usr/bin/env python

INFO_MAP = {
    'dye_formulae': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/New XREF file.xlsx', {
        'sheet_name': 'Xref',
        'header': 0,
        'usecols': [
            'COLOR NAME',
            'COLOR NUMBER',
            'SHADE RATING',
        ],
    }),
    'pa_fin_items': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/New XREF file.xlsx', {
        'sheet_name': 'Xref',
        'header': 0,
        'usecols': [
            'GREIGE ITEM',
            'STYLE',
            'Yield',
            'COLOR NAME',
            'COLOR NUMBER',
            'PA FIN ITEM',
            'JET 1',
            'JET 2',
            'JET 3',
            'JET 4',
            'JET 7',
            'JET 8',
            'JET 9',
            'JET 10',
            'SHADE RATING',
        ],
    }),
    'greige_styles': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/master.xlsx', {
        'sheet_name': 'greige info',
        'header': 0,
    }),
    'greige_translation': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/LamDemandPlanning.xlsx', {
        'sheet_name': 'Greige Style Translation',
        'header': None,
        'skiprows': 1,
        'usecols': 'A:B',
        'names': [
            'inventory',
            'plan',
        ],
    }),
    'jet_info': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/master.xlsx', {
        'sheet_name': 'jets',
        'header': 0,
    }),
    'pa_inventory': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/PA plant orders against Lam demand 20250901.xlsx', {
        'sheet_name': '1427',
        'header': 0,
        'skiprows': 3,
        'usecols': [
            'Roll',
            'Item',
            'Quality',
            'Pounds',
            'ASSIGNED_ORDER',
        ],
    }),
    'adaptive_orders': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/PA plant orders against Lam demand 20250901.xlsx', {
        'sheet_name': 'Adaptive',
        'header': 0,
        'usecols': [
            'Machine',
            'StartTime',
            'EndTime',
            'FinItem',
            'DyelotID1',
            'DyelotID2',
            'Qty',
        ],
    }),
    'si_release': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/SI release 20250825.xlsx', {
        'sheet_name': 'Vendor Release Report - Weekly ',
        'header': None,
        'skiprows': 2,
        'nrows': 23,
        'usecols': 'F,AS:AT',
        'names': [
            'greige',
            'daily_lbs',
            'weekly_lbs',
        ],
    }),
    'wf_release': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/SI release 20250825.xlsx', {
        'sheet_name': 'Vendor Release Report - Weekly ',
        'header': None,
        'skiprows': 28,
        'nrows': 7,
        'usecols': 'F,AU',
        'names': [
            'greige',
            'weekly_lbs',
        ],
    }),
    'pa_reqs': ('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/PA plant orders against Lam demand 20250901.xlsx', {
        'sheet_name': 'Fab shortage 9-4',
        'header': 0,
    }),
}