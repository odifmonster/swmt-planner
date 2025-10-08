#!/usr/bin/env python

import os, re, pandas as pd, json, datetime as dt, math

from . import engine

_INFO = {}

def _check_required_keys(name: str, block: dict):
    req_map = {
        'Excel': { 'folder', 'workbook', 'sheet' },
        'CSV': { 'folder', 'file' },
        'JSON': { 'folder', 'file' },
        'ProductInfo': { 'dye_formulae', 'fab_items', 'greige_styles' },
        'DyeOrders': { 'adaptive', 'pa_714', 'fab_items' },
        'PADyePlan': { 'future_orders', 'avail_greige', 'safety_tgts' },
        'LamData': { 'move_times', 'lam_items', 'lam_release' },
        'PAReqs': { 'lam_data', 'pa_xref', 'pa_wip', 'pa_wip_do' }
    }
    required = req_map[block['@dtype']]
    if required.intersection(block.keys()) != required:
        missing = required.difference(block.keys())
        msg = f'{block['@dtype']} block {repr(name)} missing values for ' + ', '.join([repr(x) for x in missing])
        raise RuntimeError(msg)

def df_cols_as_str(df: pd.DataFrame, cols: list[str]):
    for col in cols:
        df[col] = df[col].astype('string')
    return df

def _load_excel(name: str, block: dict):
    fpath = os.path.join(block['folder'].data, block['workbook'].data)
    pdargs = {
        'sheet_name': block['sheet'].data, 'header': 0
    }

    start = 1
    if 'start_row' in block:
        pdargs['skiprows'] = block['start_row'].data - 1
        start = block['start_row'].data
    if 'end_row' in block:
        pdargs['nrows'] = block['end_row'].data - start + 1

    if 'col_names' in block:
        if 'col_ranges' in block:
            msg = f'In block {repr(name)}: Cannot use both {repr(block['col_ranges'].data)} and ' + \
                ', '.join([repr(x.data) for x in block['col_names']]) + 'as columns'
            raise RuntimeError(msg)
        if 'subst_names' in block:
            msg = f'In block {repr(name)}: Cannot use both ' + \
                ', '.join([repr(x.data) for x in block['subst_names']]) + ' and ' + \
                ', '.join([repr(x.data) for x in block['col_names']]) + ' as columns'
            raise RuntimeError(msg)
        pdargs['usecols'] = list(map(lambda x: x.data, block['col_names']))
    
    if 'subst_names' in block:
        if 'col_ranges' not in block:
            msg = f'In block {repr(name)}: Missing excel column ranges corresponding to names ' + \
                ', '.join([repr(x.data) for x in block['subst_names']])
            raise RuntimeError(msg)
        pdargs['usecols'] = block['col_ranges'].data
        pdargs['names'] = list(map(lambda x: x.data, block['subst_names']))
        pdargs['header'] = None
    
    if 'col_ranges' in block and 'usecols' not in pdargs:
        pdargs['usecols'] = block['col_ranges'].data
    
    df = pd.read_excel(fpath, **pdargs)
    return df

def _load_csv(name: str, block: dict):
    fpath = os.path.join(block['folder'].data, block['file'].data)
    return pd.read_csv(fpath)

def _load_json(name: str, block: dict):
    fpath = os.path.join(block['folder'].data, block['file'].data)
    src = open(fpath)
    res = json.loads(src.read())
    src.close()
    return res

def _series_first(srs: pd.Series):
    return list(srs)[0]

def _convert_fab_items(fab_df: pd.DataFrame):
    no_fin = fab_df['PA FIN ITEM'].isna()
    no_yld = fab_df['Yield'].isna()
    no_color = fab_df['COLOR NUMBER'].isna()
    no_shade = fab_df['SHADE RATING'].isna()
    status_ok = (fab_df['STATUS'] == 'A') | fab_df['STATUS'].isna()

    drop_rows = fab_df[no_fin | no_yld | no_color | no_shade | ~status_ok].index
    fab_df = fab_df.drop(drop_rows)

    fab_df.loc[:, 'GREIGE ITEM'] = fab_df['GREIGE ITEM'].str.upper().apply(lambda s: s.strip())
    fab_df.loc[:, 'STYLE'] = fab_df['STYLE'].apply(lambda s: s.strip())
    fab_df['WD2'] = fab_df['WD'].apply(lambda wd: str(int(wd)) if int(wd) == wd else str(wd)).astype('string')
    fab_df['item'] = fab_df.agg(lambda r: f'FF-{r['STYLE']}-{int(r['COLOR NUMBER'])}-{r['WD2']}',
                                axis=1)
    
    return fab_df

def _load_product_info(name: str, block: dict):
    dye_df = _load_block('dye_formulae', block['dye_formulae'])
    fab_df = _load_block('fab_items', block['fab_items'])
    grg_df = _load_block('greige_styles', block=['greige_styles'])

    dye_df = dye_df[~(dye_df['COLOR NUMBER'].isna() | dye_df['SHADE RATING'].isna())]
    dye_df['COLOR NUMBER'] = dye_df['COLOR NUMBER'].astype('int64')
    unique_dyes = dye_df.groupby('COLOR NUMBER').agg(
        name=pd.NamedAgg(column='COLOR NAME', aggfunc=_series_first),
        shade=pd.NamedAgg(column='SHADE RATING', aggfunc=_series_first)
    )
    unique_dyes = unique_dyes.reset_index()

    fab_df = _convert_fab_items(fab_df)
    fab_df = fab_df.merge(grg_df, how='left', left_on='GREIGE ITEM', right_on='GreigeAlt')
    fab_df = fab_df[~fab_df['GREIGE ITEM'].isna()]

    def _get_jets(row):
        jets = []
        for i in filter(lambda i: i < 4 or i > 5, range(10)):
            if not pd.isna(row[f'JET {i+1}']):
                jets.append(f'Jet-{i+1:02}')
        return ' '.join(jets)
    
    fab_df['jets'] = fab_df.agg(_get_jets, axis=1)

    fab_df = fab_df.groupby('item').agg(
        master=pd.NamedAgg(column='STYLE', aggfunc=_series_first),
        greige=pd.NamedAgg(column='GREIGE ITEM', aggfunc=_series_first),
        color_num=pd.NamedAgg(column='COLOR NUMBER', aggfunc=_series_first),
        wip_width1=pd.NamedAgg(column='WD', aggfunc=lambda x: _series_first(x) * 2),
        wip_width2=pd.NamedAgg(column='WD', aggfunc=lambda x: _series_first(x) * 3),
        yld=pd.NamedAgg(column='Yield', aggfunc=_series_first),
        jets=pd.NamedAgg(column='jets', aggfunc=_series_first)
    )
    fab_df = fab_df.reset_index()

    return {
        'dye_formulae': unique_dyes,
        'fab_items': fab_df,
        'greige_styles': grg_df
    }

def _load_dye_orders(name: str, block: dict):
    adaptive = _load_block('adaptive', block['adaptive'])
    pa_714 = _load_block('pa_714', block['pa_714'])
    fab_items = _load_block('fab_items', block['fab_items'])
    fab_items = _convert_fab_items(fab_items)
    fab_items = fab_items[~fab_items['GREIGE ITEM'].str.contains('CAT')]

    bad_rows = pa_714[pa_714['Sales Rep'] == 'Sales Rep'].index
    pa_714 = pa_714.drop(bad_rows)
    for col in ('Line Width', 'Dye Order', 'DO Qty'):
        pa_714[col] = pa_714[col].astype('float64')

    def convert_dye_order(x):
        if pd.isna(x):
            return ''
        return f'{int(x):010}'
    pa_714['mo'] = pa_714['Dye Order'].apply(convert_dye_order)

    dye_data = {
        'job': [], 'dyelot': [], 'item': [], 'machine': [], 'start': [], 'end': []
    }

    for i in adaptive.index:
        if pd.isna(adaptive.loc[i, 'StartTime']) or pd.isna(adaptive.loc[i, 'EndTime']):
            continue

        job_id = adaptive.loc[i, 'JobID']
        lots = job_id.split('@')[0].split('/')
        for lot in lots:
            dye_data['job'].append(job_id)
            dye_data['dyelot'].append(lot)
            dye_data['start'].append(adaptive.loc[i, 'StartTime'])
            dye_data['end'].append(adaptive.loc[i, 'EndTime'])
            
            if re.match('[0-9]{10}', lot):
                item_rows = pa_714[pa_714['mo'] == lot]
                if len(item_rows) > 0:
                    first = list(item_rows.index)[0]
                    stock_item = pa_714.loc[first, 'Item']
                    comps = stock_item.split('-')

                    try:
                        color = int(comps[-1])
                        master = '-'.join(comps[:-1])
                        width = pa_714.loc[first, 'Line Width']

                        fab_matches2 = fab_items[(fab_items['STYLE'] == master[3:]) & (fab_items['COLOR NUMBER'] == color) \
                                                & (fab_items['WD'] == width/2)]
                        fab_matches3 = fab_items[(fab_items['STYLE'] == master[3:]) & (fab_items['COLOR NUMBER'] == color) \
                                                & (fab_items['WD'] == width/3)]
                        if len(fab_matches2) == 0 and len(fab_matches3) == 0:
                            dye_data['item'].append('NONE')
                        elif len(fab_matches2) > 0:
                            first = list(fab_matches2.index)[0]
                            dye_data['item'].append(fab_items.loc[first, 'item'])
                        else:
                            first = list(fab_matches3.index)[0]
                            dye_data['item'].append(fab_items.loc[first, 'item'])
                    except ValueError:
                        dye_data['item'].append(stock_item)
                else:
                    dye_data['item'].append('NONE')
            elif 'HEAVY STRIP' in lot:
                dye_data['item'].append('HEAVYSTRIP')
            elif 'STRIP' in lot:
                dye_data['item'].append('STRIP')
            else:
                dye_data['item'].append('NONE')
            dye_data['machine'].append(adaptive.loc[i, 'Machine'])
    
    return pd.DataFrame(data=dye_data)

def _load_dye_plan(name: str, block: dict):
    inv_df = _load_block('avail_greige', block['avail_greige'])
    sched_df = _load_block('future_orders', block['future_orders'])
    grg_df = _load_block('safety_tgts', block['safety_tgts'])

    grg_df = grg_df.set_index('GreigeAlt')

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

    return {
        'avail_greige': grouped_inv,
        'future_orders': sched_df,
        'safety_tgts': grg_df
    }

type _MoveTimes = dict[str, list[dict[str, int | dict[str]]]]

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

def _build_move_times(move_times: _MoveTimes, lam_items: pd.DataFrame):
    lam_items = lam_items.rename(columns={'Cust #': 'Customer', 'ProgramName': 'Program'})
    pull_data = {
        'Plant': [], 'Customer': [], 'Program': [], 'Stock Item': [],
        'Ply1 Item': [], 'Ship Day': [], 'Schedule Day': [], 'Hard Pull': [],
        'Soft Pull': []
    }

    days_map = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4
    }

    for lam, grp in lam_items.groupby('Stock Item'):
        ndays = 0
        first = list(grp.index)[0]
        skip_flag = False

        for delay_name in move_times:
            for item in move_times[delay_name]:
                attrs = item['attributes']
                if any(map(lambda a: pd.isna(lam_items.loc[first, a]), attrs.keys())):
                    skip_flag = True
                    break

                is_match = lambda a: lam_items.loc[first, a] == attrs[a]
                if all(map(is_match, attrs.keys())):
                    ndays += item['pull_days']
                    break
            
            if skip_flag:
                break
        
        if skip_flag: continue

        ship_days = grp['Ship Day'].unique()
        day_set = set()
        for ship_str in ship_days:
            if not pd.isna(ship_str):
                day_set |= _parse_ship_days(ship_str)
        
        days = list(map(lambda s: days_map[s], day_set))
        if not days:
            ship_day = 2
        else:
            ship_day = min(days)

        sched_day = max(grp['Schedule Day'])
        if pd.isna(sched_day):
            sched_day = 3
        
        pull_data['Stock Item'].append(lam)
        for col in ('Plant', 'Customer', 'Program', 'Ply1 Item'):
            pull_data[col].append(lam_items.loc[first, col])
        pull_data['Ship Day'].append(ship_day)
        pull_data['Schedule Day'].append(sched_day-1)
        pull_data['Hard Pull'].append(ndays)
        pull_data['Soft Pull'].append(ndays+3)
    
    return pd.DataFrame(data=pull_data).set_index('Stock Item')

def _subtract_business_days(start: dt.datetime, ndays: int):
    res = start
    while ndays > 0:
        wkday = res.weekday()
        if ndays > wkday:
            ndays -= wkday
            res -= dt.timedelta(days=wkday+2)
        else:
            res -= dt.timedelta(days=ndays)
            ndays = 0
    return res

def _load_lam_data(name: str, block: dict, weekof: dt.datetime):
    move_times = _load_block('move_times', block['move_times'])
    lam_items = _load_block('lam_items', block['lam_items'])
    lam_items = df_cols_as_str(lam_items, ['Stock Item', 'Ply1 Item'])

    pull_df = _build_move_times(move_times, lam_items)
    raw_release = _load_block('lam_release', block['lam_release'])
    raw_release = df_cols_as_str(raw_release, ['Stock Item', 'Ply1 Item'])

    rls_cols = ['lam', 'ply1', 'plant', 'hard_date', 'soft_date', 'qty']
    rls_data = { col: [] for col in rls_cols }

    cur_week = weekof
    for key, grp in raw_release.groupby(['Stock Item', 'Plant']):
        lam, plant = key
        first = list(grp.index)[0]

        if lam not in pull_df.index:
            continue

        ship = int(pull_df.loc[lam, 'Ship Day'])
        sched = int(pull_df.loc[lam, 'Schedule Day'])
        hard_pull = int(pull_df.loc[lam, 'Hard Pull'])
        soft_pull = int(pull_df.loc[lam, 'Soft Pull'])

        fin_on_hand = max(grp['Total Inv'])
        increase = max(grp['Customer up-front increase'])
        cum_qty = 0 - fin_on_hand - increase
        for wks in range(-1, 9):
            req_col = f'RLS+{wks}'
            if wks < 0:
                req_col = 'Past Due'

            raw_cur_qty = sum(grp[req_col])
            cum_qty += raw_cur_qty
            if raw_cur_qty <= 0 or cum_qty <= 0: continue

            rls_data['lam'].append(lam)
            rls_data['ply1'].append(raw_release.loc[first, 'Ply1 Item'])
            rls_data['plant'].append(plant)

            ship_date = weekof + dt.timedelta(weeks=wks) + dt.timedelta(days=ship)
            hard_date = _subtract_business_days(ship_date, hard_pull)
            soft_date = _subtract_business_days(ship_date, soft_pull)
            soft_wkday = soft_date.weekday()
            if soft_wkday < sched:
                soft_wkday += 7
            soft_date -= dt.timedelta(days=soft_wkday-sched)
            rls_data['hard_date'].append(hard_date)
            rls_data['soft_date'].append(soft_date)
            rls_data['qty'].append(min(raw_cur_qty, cum_qty))
    
    lam_reqs = pd.DataFrame(data=rls_data)

    return {
        'lam_reqs': lam_reqs, 'raw_release': raw_release
    }

def _load_pa_reqs(name: str, block: dict, weekof: dt.datetime):
    lam_data = _load_block('lam_data', block['lam_data'])
    pa_xref = _load_block('pa_xref', block['pa_xref'])
    pa_wip = _load_block('pa_wip', block['pa_wip'])
    pa_wip_do = _load_block('pa_wip_do', block['pa_wip_do'])

    cur_week_num = weekof.isocalendar()[1]

    lam_reqs: pd.DataFrame = lam_data['lam_reqs']

def _load_block(name: str, block: dict):
    _check_required_keys(name, block)

    match block['@dtype']:
        case 'Excel':
            return _load_excel(name, block)
        case 'CSV':
            return _load_csv(name, block)
        case 'JSON':
            return _load_json(name, block)
        case 'ProductInfo':
            return _load_product_info(name, block)
        case 'DyeOrders':
            return _load_dye_orders(name, block)
        case 'PADyePlan':
            return _load_dye_plan(name, block)
        case 'PAReqs':
            return _load_block('lam_data', block['lam_data'])
        case 'LamData':
            weekof_str = globals()['_INFO']['INPUT_ARGS']['req_weekof'].data
            year, month, day = int(weekof_str[:4]), int(weekof_str[4:6]), int(weekof_str[-2:])
            weekof = dt.datetime(year, month, day)
            print(weekof)
            return _load_lam_data(name, block, weekof)
        case _:
            raise RuntimeError('Not working yet')

def init_info(fpath: str, **kwargs):
    buffer = open(fpath)
    f = engine.file.File(buffer)
    tstream = engine.tokenized.Tokenized(f)
    stmts = engine.parser.parse(tstream)
    res = engine.interpret(stmts, **kwargs)

    for k in res:
        globals()['_INFO'][k] = res[k]
    
def load_data(name: str):
    if name not in globals()['_INFO']:
        raise KeyError(f'Unrecognized data {repr(name)}')
    return _load_block(name, globals()['_INFO'][name])