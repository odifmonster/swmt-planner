#!/usr/bin/env python

"""`grid` — table rendering: `PageModel` (a `QAbstractTableModel` over one page of
`Row`s) and `PagedGrid` (the embeddable, paged `QTableView` widget with per-column
filter glyphs). See `../DESIGN.md`."""

from .model import PageModel
from .grid import PagedGrid, ROWS_PER_PAGE

__all__ = ['PageModel', 'PagedGrid', 'ROWS_PER_PAGE']
