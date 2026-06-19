#!/usr/bin/env python

"""`PageModel` — a read-only `QAbstractTableModel` over the current page of `Row`s
in the table's display-column order. A keyed table gets a leading **checkbox
column** (view column 0) wired to `Row.select` / `Row.deselect`; foreign-key
columns render as blue underlined links. See `../DESIGN.md` (Phases 2, 4)."""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from ..formatting import format_cell

if TYPE_CHECKING:
    from ...sqlload.table import Row

__all__ = ['PageModel']

_DISPLAY = Qt.ItemDataRole.DisplayRole
_CHECK = Qt.ItemDataRole.CheckStateRole
_FOREGROUND = Qt.ItemDataRole.ForegroundRole
_FONT = Qt.ItemDataRole.FontRole

_CHECKED = Qt.CheckState.Checked
_UNCHECKED = Qt.CheckState.Unchecked

_FK_LINK = '#1565c0'        # FK cells render as blue underlined links


class PageModel(QAbstractTableModel):
    """One page of `Row`s. With `has_checkbox`, view column 0 is a checkbox tied
    to each `Row`'s selection; the data columns shift right by one. FK columns
    (named in `fk_cols`) render as links. `set_rows` swaps the page; `reset`
    swaps the columns / table shape. Emits `selection_changed` when a checkbox is
    toggled."""

    selection_changed = pyqtSignal()

    def __init__(
        self, columns: list[str], rows: 'list[Row] | None' = None,
        has_checkbox: bool = False, fk_cols: 'set[str] | None' = None,
    ) -> None:
        super().__init__()
        self._columns = list(columns)
        self._rows: 'list[Row]' = list(rows or [])
        self._has_cb = has_checkbox
        self._fk_cols = set(fk_cols or ())

    @property
    def _offset(self) -> int:
        return 1 if self._has_cb else 0

    def _data_col(self, view_col: int) -> int:
        """Map a view column to a data-column index (`-1` for the checkbox)."""
        return view_col - self._offset

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns) + self._offset

    def row_at(self, row_idx: int) -> 'Row':
        """The `Row` backing display row `row_idx` (for FK navigation)."""
        return self._rows[row_idx]

    def data(self, index: QModelIndex, role: int = _DISPLAY) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        dcol = self._data_col(index.column())
        if dcol < 0:                                   # the checkbox column
            if role == _CHECK:
                return _CHECKED if row.selected else _UNCHECKED
            return None
        if role == _DISPLAY:
            return format_cell(row.data[dcol])
        if self._columns[dcol] in self._fk_cols and row.data[dcol] is not None:
            if role == _FOREGROUND:
                return QColor(_FK_LINK)
            if role == _FONT:
                font = QFont()
                font.setUnderline(True)
                return font
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if self._has_cb and index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(
        self, index: QModelIndex, value: Any, role: int = _DISPLAY,
    ) -> bool:
        if self._has_cb and index.column() == 0 and role == _CHECK:
            row = self._rows[index.row()]
            if Qt.CheckState(value) == _CHECKED:
                row.select()
            else:
                row.deselect()
            self.dataChanged.emit(index, index, [_CHECK])
            self.selection_changed.emit()
            return True
        return False

    def headerData(self, section: int, orientation, role: int = _DISPLAY) -> Any:
        if role != _DISPLAY:
            return None
        if orientation == Qt.Orientation.Horizontal:
            dcol = self._data_col(section)
            return '' if dcol < 0 else self._columns[dcol]
        return section + 1                  # 1-based row number within the page

    def set_rows(self, rows: 'list[Row]') -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def reset(
        self, columns: list[str], rows: 'list[Row]',
        has_checkbox: bool = False, fk_cols: 'set[str] | None' = None,
    ) -> None:
        self.beginResetModel()
        self._columns = list(columns)
        self._rows = list(rows)
        self._has_cb = has_checkbox
        self._fk_cols = set(fk_cols or ())
        self.endResetModel()
