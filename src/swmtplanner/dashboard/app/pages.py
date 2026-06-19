#!/usr/bin/env python

"""The content pages other than run selection: the raw-view page (a `PagedGrid`
over a chosen table for the selected run) and the not-yet-built pretty view. See
`swmtplanner/dashboard/app/DESIGN.md` (Phase 2)."""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from ..sqlload.table import Table
from .grid import PagedGrid

if TYPE_CHECKING:
    from ..manifest import TableSpec

__all__ = ['RawViewPage', 'PrettyViewPage', 'message_page']


def message_page(text: str) -> QWidget:
    """A simple centered-message page (e.g. the no-run-selected prompt)."""
    page = QWidget()
    label = QLabel(text)
    label.setObjectName('message')
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout = QVBoxLayout(page)
    layout.addWidget(label)
    return page


class RawViewPage(QWidget):
    """The raw view: one `PagedGrid` per table, cached for the current run so a
    table keeps its state across navigation. A new table shows a "Loading…"
    placeholder while its `Table` builds; a cached table appears instantly."""

    def __init__(self, cursor: Any, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        self._cursor = cursor
        self._run_id: int | None = None
        self._grids: dict[str, PagedGrid] = {}

        self._loading = message_page('Loading…')
        self._stack = QStackedWidget()
        self._stack.addWidget(self._loading)
        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)

    def show_table(self, spec: 'TableSpec', run_id: int) -> None:
        if run_id != self._run_id:
            self._clear_cache(run_id)
        cached = self._grids.get(spec.name)
        if cached is not None:                      # restore prior state
            self._stack.setCurrentWidget(cached)
            return
        # First load: show "Loading…" and force a synchronous repaint (of the
        # whole window, so the new header paints too) before the blocking build.
        self._stack.setCurrentWidget(self._loading)
        self.window().repaint()
        grid = PagedGrid()
        grid.show_table(Table(spec, self._cursor, run_id))
        self._stack.addWidget(grid)
        self._grids[spec.name] = grid
        self._stack.setCurrentWidget(grid)

    def _clear_cache(self, run_id: int) -> None:
        self._run_id = run_id
        for grid in self._grids.values():
            self._stack.removeWidget(grid)
            grid.deleteLater()
        self._grids.clear()


class PrettyViewPage(QWidget):
    """Placeholder for the planner-specific pretty view (a later phase)."""

    def __init__(self, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        label = QLabel('Pretty view — not yet implemented.')
        label.setObjectName('message')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
