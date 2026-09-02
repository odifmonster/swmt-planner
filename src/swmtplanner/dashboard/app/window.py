#!/usr/bin/env python

"""The dashboard shell: a sidebar (Run selection / Raw view ▸ tables / Pretty
view) beside a header + stacked content. Run selection sets the run; the raw view
then pages any chosen table. See `swmtplanner/dashboard/app/DESIGN.md` (Phase 2).
"""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..manifest import referencing_fks
from .pages import PrettyViewPage, RawViewPage, message_page
from .run_select import RunSelectionPage

if TYPE_CHECKING:
    from ..manifest import TableSpec

__all__ = ['DashboardWindow']

_ROLE = Qt.ItemDataRole.UserRole
_NO_RUN = 'Please select a run to investigate.'


class DashboardWindow(QWidget):
    """The application shell. Constructed with the reader `cursor`, the ordered
    viewable `table_specs` (tables + views, not the run registry), and the
    `runs_spec` registry for the run-selection page."""

    def __init__(
        self, cursor: Any, table_specs: 'list[TableSpec]',
        runs_spec: 'TableSpec', parent: 'QWidget | None' = None,
    ) -> None:
        super().__init__(parent)
        self._specs = {s.name: s for s in table_specs}
        self.selected_run_id: int | None = None

        # ----- sidebar -----
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(170)
        self._tree.setMaximumWidth(240)

        run_item = QTreeWidgetItem(['Run selection'])
        run_item.setData(0, _ROLE, ('run',))
        raw_item = QTreeWidgetItem(['Raw view'])
        raw_item.setData(0, _ROLE, ('raw_root',))
        for spec in table_specs:
            child = QTreeWidgetItem([spec.disp_name])     # readable name, not the DB name
            child.setData(0, _ROLE, ('raw', spec.name))
            raw_item.addChild(child)
        pretty_item = QTreeWidgetItem(['Pretty view'])
        pretty_item.setData(0, _ROLE, ('pretty',))
        self._tree.addTopLevelItem(run_item)
        self._tree.addTopLevelItem(raw_item)
        self._tree.addTopLevelItem(pretty_item)
        raw_item.setExpanded(True)
        self._tree.itemClicked.connect(self._on_nav)

        # ----- content -----
        self._header = QLabel('')
        self._header.setContentsMargins(10, 10, 10, 2)
        self._header.setObjectName('headerLabel')
        # A small description under the header (the table's `desc`); hidden when
        # there's nothing to describe (run-selection / pretty pages).
        self._desc = QLabel('')
        self._desc.setContentsMargins(12, 0, 10, 8)
        self._desc.setObjectName('descLabel')
        self._desc.setWordWrap(True)
        self._desc.hide()
        self._run_page = RunSelectionPage(cursor, runs_spec)
        self._run_page.run_chosen.connect(self._on_run_chosen)
        self._raw_page = RawViewPage(
            cursor, self._specs, referencing_fks(table_specs),
        )
        self._raw_page.current_table_changed.connect(self._on_table_changed)
        self._pretty_page = PrettyViewPage()
        self._placeholder = message_page(_NO_RUN)

        self._stack = QStackedWidget()
        self._stack.setContentsMargins(15, 15, 15, 15)
        self._stack.addWidget(self._run_page)
        self._stack.addWidget(self._raw_page)
        self._stack.addWidget(self._pretty_page)
        self._stack.addWidget(self._placeholder)

        # Header + description share one bar (so its bottom border sits below
        # whichever is the last visible line, desc shown or not).
        header_box = QWidget()
        header_box.setObjectName('headerBox')
        header_layout = QVBoxLayout(header_box)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(self._header)
        header_layout.addWidget(self._desc)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(header_box)
        content_layout.addWidget(self._stack)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._tree)
        outer.addWidget(content, 1)

        self._show_run_selection()
        self.resize(1000, 660)

    # ----- navigation -----

    def _on_nav(self, item: QTreeWidgetItem, _column: int) -> None:
        kind = item.data(0, _ROLE)
        if kind is None:
            return
        tag = kind[0]
        if tag == 'run':
            self._show_run_selection()
        elif tag == 'raw_root':
            item.setExpanded(not item.isExpanded())
        elif tag == 'raw':
            self._show_raw(kind[1])
        elif tag == 'pretty':
            self._show_pretty()

    def _set_header(self, title: str, desc: str = '') -> None:
        """Set the content header to `title` and the description line to `desc`
        (the description is hidden when empty)."""
        self._header.setText(title)
        self._desc.setText(desc)
        self._desc.setVisible(bool(desc))

    def _on_table_changed(self, name: str) -> None:
        """Header follows the raw view's current table — its readable `disp_name`
        with the `desc` underneath."""
        spec = self._specs[name]
        self._set_header(spec.disp_name, spec.desc)

    def _show_run_selection(self) -> None:
        self._set_header('Run selection')
        self._stack.setCurrentWidget(self._run_page)

    def _show_raw(self, name: str) -> None:
        spec = self._specs[name]
        self._set_header(spec.disp_name, spec.desc)
        if self.selected_run_id is None:
            self._stack.setCurrentWidget(self._placeholder)
            return
        # Show the raw page (its "Loading…") first so the new header/placeholder
        # appear immediately, before the table's blocking build.
        self._stack.setCurrentWidget(self._raw_page)
        self._raw_page.show_table(self._specs[name], self.selected_run_id)

    def _show_pretty(self) -> None:
        self._set_header('Pretty view')
        if self.selected_run_id is None:
            self._stack.setCurrentWidget(self._placeholder)
            return
        self._stack.setCurrentWidget(self._pretty_page)

    def _on_run_chosen(self, run_id: int) -> None:
        self.selected_run_id = run_id
