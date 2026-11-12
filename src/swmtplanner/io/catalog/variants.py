#!/usr/bin/env python

from ..loaders import Column, Table, SQLQuery, CSVFile, SQLTableLoader, CSVTableLoader
from ._sql import read_sql

SI_VARIANTS_QUERY = SQLQuery(read_sql('si_variants.sql'), 0)
VARIANTS_TSV = CSVFile('inputs', 'variants', '.tsv', sep='\t')


def _bar_columns(i: int) -> tuple[Column, ...]:
    return (
        Column(f'bar{i}_ends', 'int64', read_na_as=0),
        Column(f'bar{i}_merge', 'string'),
        Column(f'bar{i}_vendor', 'string'),
        Column(f'bar{i}_denier', 'int64', read_na_as=0, converter=int),
        Column(f'bar{i}_luster', 'string'),
        Column(f'bar{i}_desc', 'string'),
        Column(f'bar{i}_pct', 'float64', read_na_as=0.0),
        Column(f'bar{i}_rl', 'float64', read_na_as=0.0),
        Column(f'bar{i}_stitch', 'string'),
        Column(f'bar{i}_thread', 'string'),
    )


VARIANTS = Table('variants', (
    Column('variant', 'string'),
    Column('width', 'int64'),
    Column('rack_wt', 'float64'),
    Column('gauge', 'int64'),
    Column('beams', 'int64'),
    *_bar_columns(1), *_bar_columns(2), *_bar_columns(3), *_bar_columns(4),
))

VARIANT_LOADER = SQLTableLoader(VARIANTS, SI_VARIANTS_QUERY)
VARIANT_TSV_LOADER = CSVTableLoader(VARIANTS, VARIANTS_TSV)
