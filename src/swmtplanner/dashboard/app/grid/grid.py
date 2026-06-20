#!/usr/bin/env python

"""`PagedGrid` — the embeddable raw grid: a `QTableView` (with a `FilterHeader`)
over the current page of a `Table`, plus top-right forward/back paging. Issues no
SQL of its own — it drives a `Table` from `sqlload`, opens a `FilterPopup` per
column, and reports FK-cell clicks / row selection for navigation. See
`../DESIGN.md` (Phases 2–4)."""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
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
_CHECKBOX_W = 30


class PagedGrid(QWidget):
    """An embeddable grid over one `Table`: a column-name header row (with filter
    glyphs), an optional leading checkbox column (keyed tables), FK cells as
    links, and top-right back/forward buttons. Bind a table with `show_table`.
    Emits `fk_activated(col, value)` on an FK-cell click and `selection_changed`
    when the checked rows change (incl. a filter rebuild clearing them)."""

    fk_activated = pyqtSignal(str, object)         # (fk column, raw cell value)
    selection_changed = pyqtSignal()

    def __init__(self, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        self._table: 'Table | None' = None
        self._cols: list = []            # display Column specs (name + type)
        self._fk_names: set[str] = set()
        self._cb_offset = 0              # 1 when a checkbox column is present
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
        self._model.selection_changed.connect(self.selection_changed)
        self._view = QTableView()
        self._view.setModel(self._model)
        self._header = FilterHeader(self._view)
        self._view.setHorizontalHeader(self._header)
        self._header.filter_requested.connect(self._on_filter_requested)
        self._header.filter_cleared.connect(self._on_filter_cleared)
        self._view.clicked.connect(self._on_cell_clicked)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._view.setAlternatingRowColors(True)
        self._view.verticalHeader().setVisible(False)
        self._header.setStretchLastSection(True)
        # Hover tracking, so FK links recolor + show a hand cursor under the mouse.
        self._view.setMouseTracking(True)
        self._view.entered.connect(self._on_hover)
        self._view.viewportEntered.connect(self._clear_hover)
        self._view.viewport().installEventFilter(self)
        self._size_view()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._view)

    def show_table(self, table: 'Table') -> None:
        """Bind `table`, reset to page 1, and render it. A keyed table gets a
        leading checkbox column; FK columns render as links."""
        self._table = table
        table.set_page_size(ROWS_PER_PAGE)
        self._cols = [c for c in table.schema.columns if c.name != RUN_ID]
        self._fk_names = {fk.column for fk in table.schema.fks}
        self._cb_offset = 1 if table.schema.pk else 0
        self._header.set_skip_leading(self._cb_offset)
        columns = [c.name for c in self._cols]
        self._model.reset(columns, table.next_page(),
                          has_checkbox=bool(self._cb_offset),
                          fk_cols=self._fk_names)
        # Start wide enough to show each full column name (+ filter button); the
        # header's sectionSizeFromContents reserves the button width.
        self._view.resizeColumnsToContents()
        if self._cb_offset:
            self._header.resizeSection(0, _CHECKBOX_W)
        self._update_buttons()

    @property
    def selected_keys(self) -> set:
        """The selected primary keys of the bound table (empty if none/keyless)."""
        return self._table.selected_keys if self._table is not None else set()

    def mark_filtered(self, col_name: str, on: bool = True) -> None:
        """Set/clear the filter glyph on the column named `col_name` — used by the
        navigation controller for a nav-applied selection / FK-lookup constraint."""
        for i, col in enumerate(self._cols):
            if col.name == col_name:
                self._header.set_filtered(i + self._cb_offset, on)
                return

    # ----- FK navigation -----

    def _fk_target(self, index: Any) -> 'tuple[str, Any] | None':
        """The `(fk_column, raw value)` for `index` if it is a clickable FK cell
        (an FK column with a non-null value), else `None`. Shared by the click and
        hover handlers."""
        if self._table is None or not index.isValid():
            return None
        dcol = index.column() - self._cb_offset
        if dcol < 0 or dcol >= len(self._cols):        # checkbox / out of range
            return None
        name = self._cols[dcol].name
        if name not in self._fk_names:
            return None
        value = self._model.row_at(index.row()).get(name)
        return None if value is None else (name, value)

    def _on_cell_clicked(self, index: Any) -> None:
        target = self._fk_target(index)
        if target is not None:
            self.fk_activated.emit(*target)

    def _on_hover(self, index: Any) -> None:
        is_fk = self._fk_target(index) is not None
        self._view.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if is_fk
            else Qt.CursorShape.ArrowCursor)
        self._model.set_hover(index.row(), index.column())

    def _clear_hover(self) -> None:
        self._view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self._model.set_hover(-1, -1)

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if obj is self._view.viewport() and event.type() == QEvent.Type.Leave:
            self._clear_hover()
        return super().eventFilter(obj, event)

    # ----- filters -----

    def _on_filter_requested(self, col: int) -> None:
        if self._table is None:
            return
        column = self._cols[col - self._cb_offset]
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
        self.selection_changed.emit()         # the rebuild cleared any selection

    def _on_filter_cleared(self, col: int) -> None:
        if self._table is None:
            return
        self._table.remove_filter(self._cols[col - self._cb_offset].name)
        self._model.set_rows(self._table.next_page())
        self._update_buttons()
        self._header.set_filtered(col, False)
        self.selection_changed.emit()

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
