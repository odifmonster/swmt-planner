#!/usr/bin/env python

from ..loaders import Column, Table, JSONFile, JSONTableLoader

MASTER_STYLES_FILE = JSONFile('inputs', 'greige-master-styles')

MASTER_STYLES = Table('master_styles',
                      (Column('variant', 'string'),),
                      index=Column('master', 'string'))

MASTER_STYLE_LOADER = JSONTableLoader(MASTER_STYLES, MASTER_STYLES_FILE)
