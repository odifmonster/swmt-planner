#!/usr/bin/env python

"""`PagedGrid` — the embeddable raw grid: a `QTableView` (with a `FilterHeader`)
over the current page of a `Table`, plus top-right forward/back paging. Issues no
SQL of its own — it drives a `Table` from `sqlload` and opens a `FilterPopup` per
column. See `../DESIGN.md`."""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from ...manifest import RUN_ID
from ..filters import FilterHeader, FilterPopup
from .model import PageModel

if TYPE_CHECKING:
    from ...sqlload.table import Table

__all__ = ['PagedGrid', 'ROWS_PER_PAGE']

# Fixed page size; the grid sizes its view to show this many rows.
ROWS_PER_PAGE = 20


class PagedGrid(QWidget):
    """An embeddable grid over one `Table`: a column-name header row (with filter
    glyphs), the current page of rows, and top-right back/forward buttons. Bind a
    table with `show_table`; the buttons call `prev_page` / `next_page`."""

    def __init__(self, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        self._table: 'Table | None' = None
        self._cols: list = []            # display Column specs (name + type)
        self._popup: 'FilterPopup | None' = None

        self._back = QToolButton()
        self._back.setText('◀')
        self._fwd = QToolButton()
        self._fwd.setText('▶')
        self._back.clicked.connect(self._prev)
        self._fwd.clicked.connect(self._next)
        self._back.setEnabled(False)
        self._fwd.setEnabled(False)

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self._back)
        top.addWidget(self._fwd)

        self._model = PageModel([])
        self._view = QTableView()
        self._view.setModel(self._model)
        self._header = FilterHeader(self._view)
        self._view.setHorizontalHeader(self._header)
        self._header.filter_requested.connect(self._on_filter_requested)
        self._header.filter_cleared.connect(self._on_filter_cleared)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._view.setAlternatingRowColors(True)
        self._view.verticalHeader().setVisible(False)
        self._header.setStretchLastSection(True)
        self._size_view()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._view)

    def show_table(self, table: 'Table') -> None:
        """Bind `table`, reset to page 1, and render it."""
        self._table = table
        table.set_page_size(ROWS_PER_PAGE)
        self._cols = [c for c in table.schema.columns if c.name != RUN_ID]
        columns = [c.name for c in self._cols]
        self._model.reset(columns, table.next_page())
        # Start wide enough to show each full column name (+ filter button); the
        # header's sectionSizeFromContents reserves the button width.
        self._view.resizeColumnsToContents()
        self._update_buttons()

    # ----- filters -----

    def _on_filter_requested(self, col: int) -> None:
        if self._table is None:
            return
        column = self._cols[col]
        self._popup = FilterPopup(
            column.name, column.type,
            unique_getter=lambda name=column.name: self._table.unique(name),
            on_apply=(lambda kind, rule, name=column.name, i=col:
                      self._apply_filter(name, i, kind, rule)),
            parent=self,
        )
        x = self._header.sectionViewportPosition(col)
        anchor = self._view.viewport().mapToGlobal(QPoint(x, self._header.height()))
        self._popup.move(anchor)
        self._popup.show()

    def _apply_filter(self, name: str, col: int, kind: str, rule: Any) -> None:
        self._table.apply_filter_to(name, kind, rule)
        self._model.set_rows(self._table.next_page())
        self._update_buttons()
        self._header.set_filtered(col, True)

    def _on_filter_cleared(self, col: int) -> None:
        if self._table is None:
            return
        self._table.remove_filter(self._cols[col].name)
        self._model.set_rows(self._table.next_page())
        self._update_buttons()
        self._header.set_filtered(col, False)

    # ----- paging -----

    def _next(self) -> None:
        if self._table is not None:
            self._model.set_rows(self._table.next_page())
            self._update_buttons()

    def _prev(self) -> None:
        if self._table is not None:
            self._model.set_rows(self._table.prev_page())
            self._update_buttons()

    def _update_buttons(self) -> None:
        start, end = self._table.displayed_range
        self._back.setEnabled(start > 0)
        self._fwd.setEnabled(end < self._table.nrows)

    def _size_view(self) -> None:
        row_h = self._view.verticalHeader().defaultSectionSize()
        header_h = self._view.horizontalHeader().sizeHint().height()
        self._view.setMinimumHeight(header_h + row_h * ROWS_PER_PAGE + 2)
