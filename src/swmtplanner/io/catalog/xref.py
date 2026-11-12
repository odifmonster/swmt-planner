#!/usr/bin/env python

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ...core.products import Shade
from ..loaders import Column, Table, ExcelFile, ExcelTableLoader
from ._converters import _strip, _is_x, _is_active

XREF_FILE = ExcelFile('pa_supply', 'PA Master Xref', sheet_name='Xref')

FABRICS = Table('fabrics', (
    Column('item', 'string', src_name='PA FIN ITEM', read_na_as='', converter=_strip),
    Column('greige', 'string', src_name='GREIGE ITEM', read_na_as='', converter=_strip),
    Column('style', 'string', src_name='STYLE', read_na_as='', converter=_strip),
    Column('width', 'float64', src_name='WD'),
    Column('yld', 'float64', src_name='Yield'),
    Column('formula', 'Int64', src_name='COLOR NUMBER'),
    Column('color', 'string', src_name='COLOR NAME', read_na_as='', converter=_strip),
    Column('shade', 'Int64', src_name='SHADE RATING'),
    Column('active', 'bool', src_name='STATUS', read_na_as='', converter=_is_active),
    *(Column(f'jet{i}', 'bool', src_name=f'JET {i}', read_na_as='', converter=_is_x)
      for i in range(1, 11)),
    Column('tanks', 'bool', src_name='TANKS', read_na_as='', converter=_is_x),
), index=Column('part_no', 'string', src_name='PLY 1 PART #', read_na_as='', converter=_strip))

SHADE_RATINGS = {
    0: Shade.LIGHT0,
    1: Shade.LIGHT1,
    2: Shade.MEDIUM,
    3: Shade.BLACK,
    4: Shade.SD_BLACK,
}

GREIGE_STYLES_SHEET = ExcelFile('pa_supply', 'PA Master Xref', sheet_name='Greige Styles')

GREIGE_STYLES = Table('greige_styles', (
    Column('master', 'string', src_name='GreigeAlt2', converter=_strip),
    Column('std_wt', 'float64', src_name='Target'),
), index=Column('alias', 'string', src_name='GreigeAlt', converter=_strip))

GREIGE_STYLE_LOADER = ExcelTableLoader(GREIGE_STYLES, GREIGE_STYLES_SHEET)


@dataclass(frozen=True)
class XrefFabricLoader(ExcelTableLoader):
    aliases: ExcelTableLoader

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        df = super().load(cfg, dt, override_name)
        masters = self.aliases.load(cfg, dt, override_name)['master']
        df['greige'] = df['greige'].map(masters).fillna(df['greige']).astype('string')
        return df


FABRIC_LOADER = XrefFabricLoader(FABRICS, XREF_FILE, GREIGE_STYLE_LOADER)
