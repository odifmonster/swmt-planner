#!/usr/bin/env python

"""The run-selection page: every run from the registry as a large, clickable
card. Picking one sets the dashboard's run and highlights the card. See
`swmtplanner/dashboard/app/DESIGN.md` (Phase 2 — Run selection)."""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from .formatting import format_cell

if TYPE_CHECKING:
    from ..manifest import TableSpec

__all__ = ['RunSelectionPage', 'RunButton', 'list_runs']


def list_runs(cursor: Any, runs_spec: 'TableSpec') -> list[tuple]:
    """Every run, most recent first: `(run_id, created_at, start_date,
    total_score)`. The registry is **not** run-scoped, so this is a direct query
    rather than a `Table`/`Query`."""
    cursor.execute(
        f'SELECT run_id, created_at, start_date, total_score '
        f'FROM `{runs_spec.name}` ORDER BY run_id DESC'
    )
    return list(cursor.fetchall())


def _fmt_score(value: Any) -> str:
    return '—' if value is None else f'{value:,.2f}'


class RunButton(QFrame):
    """A clickable run card: bold `Run N`, then the date run, the start date, and
    the total score. Emits `clicked(run_id)`; `set_selected` toggles the
    highlight."""

    clicked = pyqtSignal(int)

    def __init__(
        self, run_id: int, created_at: Any, start_date: Any,
        total_score: Any, parent: 'QWidget | None' = None,
    ) -> None:
        super().__init__(parent)
        self.run_id = run_id
        self.setObjectName('runButton')
        self.setProperty('selected', 'false')
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._title = QLabel(f'Run {run_id}')
        self._title.setObjectName('runTitle')
        self._title.setProperty('selected', 'false')
        self._details = QLabel(
            f'run on {format_cell(created_at)}\n'
            f'start date: {format_cell(start_date)}\n'
            f'total score: {_fmt_score(total_score)}'
        )
        self._details.setObjectName('runDetails')
        self._details.setProperty('selected', 'false')
        for label in (self._title, self._details):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._details)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.run_id)
        super().mousePressEvent(event)

    def set_selected(self, on: bool) -> None:
        for elem in (self, self._title, self._details):
            elem.setProperty('selected', 'true' if on else 'false')
            elem.style().unpolish(elem)
            elem.style().polish(elem)


class RunSelectionPage(QWidget):
    """A scrollable column of `RunButton`s. Emits `run_chosen(run_id)` and keeps
    the chosen card highlighted."""

    run_chosen = pyqtSignal(int)

    def __init__(
        self, cursor: Any, runs_spec: 'TableSpec',
        parent: 'QWidget | None' = None,
    ) -> None:
        super().__init__(parent)
        self._cursor = cursor
        self._runs_spec = runs_spec
        self._buttons: dict[int, RunButton] = {}
        self._selected: int | None = None

        self._column = QWidget()
        self._vbox = QVBoxLayout(self._column)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._column)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll)
        self.reload()

    def reload(self) -> None:
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._buttons.clear()
        for run_id, created_at, start_date, total_score in list_runs(
            self._cursor, self._runs_spec,
        ):
            btn = RunButton(run_id, created_at, start_date, total_score)
            btn.clicked.connect(self._on_click)
            self._vbox.addWidget(btn)
            self._buttons[run_id] = btn
        self._vbox.addStretch(1)
        if self._selected in self._buttons:
            self._buttons[self._selected].set_selected(True)

    def _on_click(self, run_id: int) -> None:
        self.set_selected(run_id)
        self.run_chosen.emit(run_id)

    def set_selected(self, run_id: int) -> None:
        if self._selected in self._buttons:
            self._buttons[self._selected].set_selected(False)
        self._selected = run_id
        if run_id in self._buttons:
            self._buttons[run_id].set_selected(True)
