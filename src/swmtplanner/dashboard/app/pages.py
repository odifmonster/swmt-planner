#!/usr/bin/env python

"""The content pages other than run selection: the raw-view page (now the FK
navigation controller — a stack of `PagedGrid` frames over a chosen table for the
selected run) and the not-yet-built pretty view. See
`swmtplanner/dashboard/app/DESIGN.md` (Phases 2, 4)."""

from typing import TYPE_CHECKING, Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

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
    """The raw view + FK navigation controller. Holds a **stack of frames** (each
    a `PagedGrid` over a constrained `Table`); the top is shown. A sidebar pick
    starts a fresh root; an FK-cell click (forward) and "Go to…" (backward) push a
    new frame; **‹ Back** pops. Emits `current_table_changed(name)` so the shell
    updates its header."""

    current_table_changed = pyqtSignal(str)

    def __init__(
        self, cursor: Any, specs: 'dict[str, TableSpec]',
        back_refs: 'dict[str, tuple[tuple[str, str], ...]]',
        parent: 'QWidget | None' = None,
    ) -> None:
        super().__init__(parent)
        self._cursor = cursor
        self._specs = specs                        # name -> TableSpec
        self._back_refs = back_refs                # ref table -> ((src, fk_col), …)
        self._run_id: int | None = None
        self._frames: 'list[tuple[TableSpec, PagedGrid]]' = []

        self._back_btn = QToolButton()
        self._back_btn.setText('‹ Back')
        self._back_btn.clicked.connect(self._back)
        self._goto_btn = QToolButton()
        self._goto_btn.setText('Go to…')
        self._goto_btn.clicked.connect(self._open_goto)
        self._back_btn.hide()
        self._goto_btn.hide()

        bar = QHBoxLayout()
        bar.addWidget(self._back_btn)
        bar.addStretch(1)
        bar.addWidget(self._goto_btn)

        self._loading = message_page('Loading…')
        self._stack = QStackedWidget()
        self._stack.addWidget(self._loading)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._stack)

    # ----- sidebar root entry -----

    def show_table(self, spec: 'TableSpec', run_id: int) -> None:
        """Start a fresh root view of `spec` for `run_id` (discards any drill
        history — the sidebar is a new root, the Back button retraces drills)."""
        self._run_id = run_id
        self._clear_frames()
        self._push(spec)

    # ----- frame stack -----

    def _push(
        self, spec: 'TableSpec',
        apply: 'Callable[[Table], None] | None' = None,
        mark_col: str | None = None,
    ) -> None:
        # Show "Loading…" and force a synchronous repaint before the blocking
        # build, so the new header/placeholder paint first.
        self._stack.setCurrentWidget(self._loading)
        self.window().repaint()
        table = Table(spec, self._cursor, self._run_id)
        if apply is not None:                       # apply the nav constraint
            apply(table)                            # before the grid renders page 1
        grid = PagedGrid()
        grid.fk_activated.connect(self._on_fk)
        grid.selection_changed.connect(self._update_chrome)
        grid.show_table(table)
        if mark_col is not None:
            grid.mark_filtered(mark_col, True)
        self._stack.addWidget(grid)
        self._frames.append((spec, grid))
        self._stack.setCurrentWidget(grid)
        self.current_table_changed.emit(spec.name)
        self._update_chrome()

    def _back(self) -> None:
        if len(self._frames) <= 1:
            return
        _, grid = self._frames.pop()
        self._stack.removeWidget(grid)
        grid.deleteLater()
        spec, top = self._frames[-1]
        self._stack.setCurrentWidget(top)
        self.current_table_changed.emit(spec.name)
        self._update_chrome()

    def _clear_frames(self) -> None:
        for _, grid in self._frames:
            self._stack.removeWidget(grid)
            grid.deleteLater()
        self._frames.clear()

    # ----- forward (FK click) / backward ("Go to…") navigation -----

    def _on_fk(self, fk_col: str, value: Any) -> None:
        spec, _ = self._frames[-1]
        fk = next((f for f in spec.fks if f.column == fk_col), None)
        if fk is None:
            return
        self._push(
            self._specs[fk.ref_table],
            apply=lambda t: t.apply_filter_to(fk.ref_column, 'selection', {value}),
            mark_col=fk.ref_column,
        )

    def _open_goto(self) -> None:
        spec, grid = self._frames[-1]
        keys = grid.selected_keys
        refs = self._back_refs.get(spec.name, ())
        if not keys or not refs:
            return
        multi = self._multi_col_sources(refs)
        menu = QMenu(self)
        for src, fk_col in refs:
            label = f'{src} ({fk_col})' if src in multi else src
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, s=src, c=fk_col, k=set(keys):
                self._goto(s, c, k))
        menu.exec(self._goto_btn.mapToGlobal(self._goto_btn.rect().bottomLeft()))

    def _goto(self, src: str, fk_col: str, keys: set) -> None:
        self._push(
            self._specs[src],
            apply=lambda t: t.apply_fk_lookup(fk_col, keys),
            mark_col=fk_col,
        )

    @staticmethod
    def _multi_col_sources(
        refs: 'tuple[tuple[str, str], ...]',
    ) -> set[str]:
        """Source tables that reference this PK via more than one column (so the
        menu disambiguates them by column). None do today, but the rule is safe."""
        seen: set[str] = set()
        multi: set[str] = set()
        for src, _ in refs:
            if src in seen:
                multi.add(src)
            seen.add(src)
        return multi

    # ----- chrome -----

    def _update_chrome(self) -> None:
        self._back_btn.setVisible(len(self._frames) > 1)
        if not self._frames:
            self._goto_btn.hide()
            return
        spec, grid = self._frames[-1]
        has_refs = bool(self._back_refs.get(spec.name))
        self._goto_btn.setVisible(has_refs and bool(grid.selected_keys))


class PrettyViewPage(QWidget):
    """Placeholder for the planner-specific pretty view (a later phase)."""

    def __init__(self, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        label = QLabel('Pretty view — not yet implemented.')
        label.setObjectName('message')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
