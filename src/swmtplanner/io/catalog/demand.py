#!/usr/bin/env python

from ..loaders import Column, Table, ExcelFile, ExcelTableLoader
from ._converters import _strip

PA_DEMAND_FILE = ExcelFile('scheduling', 'pa_dmnd_{}', date_fmt='%Y%m%d',
                           sheet_name='Fab shortage')

PA_DEMAND = Table('pa_demand', (
    Column('item', 'string', src_name='PA Item', converter=_strip),
    Column('bill_to', 'int64', src_name='Bill To'),
    Column('plant', 'string', src_name='Plant', converter=_strip),
    Column('ship_day', 'int64', src_name='Ship Day'),
    Column('past_due', 'float64', src_name="FAB req'd past due", read_na_as=0.0),
    *(Column(f'wk{i}', 'float64', src_name=f"FAB req'd WK{i}", read_na_as=0.0)
      for i in range(0, 9)),
), index=Column('part_no', 'string', src_name='Ply1 Item', converter=_strip))

PA_DEMAND_LOADER = ExcelTableLoader(PA_DEMAND, PA_DEMAND_FILE)
