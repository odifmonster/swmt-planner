#!/usr/bin/env python

"""`PageModel` — a read-only `QAbstractTableModel` over the current page of `Row`s
in the table's display-column order. See `../DESIGN.md`."""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ..formatting import format_cell

if TYPE_CHECKING:
    from ...sqlload.table import Row

__all__ = ['PageModel']

_DISPLAY = Qt.ItemDataRole.DisplayRole


class PageModel(QAbstractTableModel):
    """One page of `Row`s. `set_rows` swaps the page; `reset` also swaps the
    columns (a new table)."""

    def __init__(
        self, columns: list[str], rows: 'list[Row] | None' = None,
    ) -> None:
        super().__init__()
        self._columns = list(columns)
        self._rows: 'list[Row]' = list(rows or [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: QModelIndex, role: int = _DISPLAY) -> Any:
        if not index.isValid() or role != _DISPLAY:
            return None
        return format_cell(self._rows[index.row()].data[index.column()])

    def headerData(self, section: int, orientation, role: int = _DISPLAY) -> Any:
        if role != _DISPLAY:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return section + 1                  # 1-based row number within the page

    def set_rows(self, rows: 'list[Row]') -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def reset(self, columns: list[str], rows: 'list[Row]') -> None:
        self.beginResetModel()
        self._columns = list(columns)
        self._rows = list(rows)
        self.endResetModel()
