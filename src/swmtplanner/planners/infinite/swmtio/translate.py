#!/usr/bin/env python

"""Translations: how one source (a SQL result set, a local file) becomes a
pandas dataframe, declared column by column.

A translation is purely columnar — every source row becomes one dataframe
row — and is made of `Column`s gathered into a `Table`. Each column's values
go through a fixed pipeline: nulls are replaced with `read_na_as`, then the
`converter` (if any) is applied to every value, then the column is cast to
`dtype` (if any). Nothing here knows source names beyond carrying them: the
loaders in `.loaders` use `Column.src_name` to pick columns out of a source
and hand `Table.from_tuples` rows already in declared order.

Conversion errors are not scanned for; they raise from wherever they occur.

See `planners/infinite/swmtio/DESIGN.md` ("Translations").
"""

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd


def _is_null(value: Any) -> bool:
    """`True` for the null stand-ins a source can hand us: `None`, `NaN`
    (Python or numpy float), pandas' `NA` / `NaT`."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, (float, np.floating)) and math.isnan(value)


@dataclass(frozen=True)
class Column:
    """One dataframe column and how its values are produced.

    `name` is the column's name in the result; `src_name` its name in the
    source when that differs (`None` → the source uses `name` too). `dtype`
    is the pandas dtype the column is forced to, or `None` to leave pandas'
    inference alone. `converter` is applied to every value, nulls included
    once they have been replaced with `read_na_as` (default `None`, which
    also normalises `NaN` to `None`)."""
    name: str
    src_name: str | None = None
    dtype: str | None = None
    converter: Callable[[Any], Any] | None = None
    read_na_as: Any = None

    @property
    def source(self) -> str:
        """The column's name in the source: `src_name` if set, else `name`."""
        return self.name if self.src_name is None else self.src_name

    def apply(self, values: Iterable[Any]) -> pd.Series:
        """Run `values` through the pipeline — null replacement, conversion,
        cast — and return the resulting series (named `name`)."""
        out = [self.read_na_as if _is_null(v) else v for v in values]
        if self.converter is not None:
            out = [self.converter(v) for v in out]
        series = pd.Series(out, name=self.name)
        if self.dtype is not None:
            series = series.astype(self.dtype)
        return series


@dataclass(frozen=True)
class Table:
    """A named set of `Column`s in dataframe order. `name` is the label the
    loaders key on; it need not be a physical table or file name."""
    name: str
    columns: tuple[Column, ...]

    @property
    def names(self) -> tuple[str, ...]:
        """The result column names, in order."""
        return tuple(c.name for c in self.columns)

    @property
    def sources(self) -> tuple[str, ...]:
        """The source column names, in declared order."""
        return tuple(c.source for c in self.columns)

    def from_tuples(self, data: Iterable[tuple]) -> pd.DataFrame:
        """Build the dataframe from `data`: one tuple per row, positions
        matching `columns`. Every tuple must have exactly `len(columns)`
        entries (`ValueError` otherwise); nothing else is validated up
        front — a failing conversion or cast raises where it happens."""
        width = len(self.columns)
        rows = []
        for i, row in enumerate(data):
            if len(row) != width:
                raise ValueError(
                    f'table {self.name!r}: row {i} has {len(row)} values, '
                    f'expected {width}')
            rows.append(tuple(row))
        per_col = [[row[j] for row in rows] for j in range(width)]
        frame = pd.DataFrame(
            {col.name: col.apply(vals) for col, vals in zip(self.columns, per_col)})
        if not rows:
            # No rows: keep the declared columns so the empty frame is shaped.
            frame = frame.reindex(columns=list(self.names))
        return frame
