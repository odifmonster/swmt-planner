#!/usr/bin/env python

from ..loaders import Column, Table, JSONFile, JSONTableLoader

KNIT_MACHINES_FILE = JSONFile('inputs', 'knit-machine-master', orient='index')

KNIT_MACHINES = Table('knit_machines', (
    Column('gauge', 'int64'),
    Column('width', 'int64'),
    Column('is_new', 'bool'),
    Column('rpm', 'int64'),
    Column('attrs', 'object', converter=tuple),
), index=Column('machine', 'string', src_name='index'))

KNIT_MACHINE_LOADER = JSONTableLoader(KNIT_MACHINES, KNIT_MACHINES_FILE)

NEW_MACHINES_ONLY = frozenset({'AU7992T2A'})
