#!/usr/bin/env python

"""Filter-popup body widgets — the per-kind input areas: a membership checkbox
list (selection / exclusion), range bounds, and a pattern entry. Each exposes a
`changed` signal, an `is_valid()` gate for the Apply button, and accessors the
`FilterPopup` reads to build the rule. See `../DESIGN.md` (Phase 3)."""

from typing import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..formatting import format_cell

__all__ = ['MembershipBody', 'RangeBody', 'PatternBody']


class MembershipBody(QWidget):
    """Selection / exclusion: a search box over a scrollable checkbox list of the
    column's distinct values (or an 'unavailable' message when there are too
    many)."""

    changed = pyqtSignal()

    def __init__(self, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        self._loaded = False
        self._available = False
        self._checks: list[QCheckBox] = []

        self._search = QLineEdit()
        self._search.setPlaceholderText('Search…')
        self._search.textChanged.connect(self._apply_search)

        self._listw = QWidget()
        self._list_layout = QVBoxLayout(self._listw)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._listw)

        self._msg = QLabel()
        self._msg.setObjectName('message')
        self._msg.setWordWrap(True)
        self._msg.hide()

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._scroll)
        layout.addWidget(self._msg)

    def load(self, getter: Callable[[], list | None]) -> None:
        """Populate from `getter()` (the column's distinct values) once."""
        if self._loaded:
            return
        self._loaded = True
        values = getter()
        if values is None:
            self._available = False
            self._search.setEnabled(False)
            self._scroll.hide()
            self._msg.setText('(Selection/exclusion) unavailable: too many values')
            self._msg.show()
            return
        self._available = True
        for value in sorted(values, key=format_cell):
            box = QCheckBox(format_cell(value))
            box.setProperty('_value', value)
            box.stateChanged.connect(lambda _s: self.changed.emit())
            self._checks.append(box)
            self._list_layout.addWidget(box)
        self._list_layout.addStretch(1)

    def _apply_search(self, text: str) -> None:
        needle = text.lower()
        for box in self._checks:
            box.setVisible(needle in box.text().lower())

    def selected_values(self) -> set:
        return {box.property('_value') for box in self._checks if box.isChecked()}

    def is_valid(self) -> bool:
        return self._available and any(b.isChecked() for b in self._checks)


class RangeBody(QWidget):
    """A lower and an upper bound, each a No-bound/Bound dropdown plus a
    type-matched editor (disabled when 'No bound')."""

    changed = pyqtSignal()

    def __init__(self, col_type: str, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        self._col_type = col_type
        layout = QVBoxLayout(self)
        self._low_combo, self._low_edit = self._make_row('Lower bound', layout)
        self._high_combo, self._high_edit = self._make_row('Upper bound', layout)

    def _make_row(self, label: str, parent_layout: QVBoxLayout):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        combo = QComboBox()
        combo.addItems(['No bound', 'Bound'])
        editor = self._make_editor()
        editor.setEnabled(False)
        combo.currentIndexChanged.connect(
            lambda i, e=editor: (e.setEnabled(i == 1), self.changed.emit())
        )
        row.addWidget(combo)
        row.addWidget(editor, 1)
        parent_layout.addLayout(row)
        return combo, editor

    def _make_editor(self) -> QWidget:
        if self._col_type == 'datetime':
            edit = QDateTimeEdit()
            edit.setCalendarPopup(True)
            edit.dateTimeChanged.connect(lambda _v: self.changed.emit())
            return edit
        edit = QLineEdit()
        if self._col_type == 'int':
            edit.setValidator(QIntValidator())
        elif self._col_type == 'float':
            edit.setValidator(QDoubleValidator())
        edit.textChanged.connect(lambda _v: self.changed.emit())
        return edit

    def _bound(self, combo: QComboBox, editor: QWidget):
        """`(active, valid, value)` for one bound row."""
        if combo.currentIndex() != 1:
            return False, True, None
        if self._col_type == 'datetime':
            return True, True, editor.dateTime().toPyDateTime()
        text = editor.text().strip()
        if not text or not editor.hasAcceptableInput():
            return True, False, None
        if self._col_type == 'int':
            return True, True, int(text)
        if self._col_type == 'float':
            return True, True, float(text)
        return True, True, text

    def bounds(self) -> tuple:
        _la, _lv, low = self._bound(self._low_combo, self._low_edit)
        _ha, _hv, high = self._bound(self._high_combo, self._high_edit)
        return (low, high)

    def is_valid(self) -> bool:
        low_active, low_valid, _l = self._bound(self._low_combo, self._low_edit)
        high_active, high_valid, _h = self._bound(self._high_combo, self._high_edit)
        return (low_active or high_active) and low_valid and high_valid


class PatternBody(QWidget):
    """A single text entry for starts-with / ends-with / contains."""

    changed = pyqtSignal()

    def __init__(self, parent: 'QWidget | None' = None) -> None:
        super().__init__(parent)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText('Text…')
        self._edit.textChanged.connect(lambda _v: self.changed.emit())
        layout = QVBoxLayout(self)
        layout.addWidget(self._edit)

    def text(self) -> str:
        return self._edit.text()

    def is_valid(self) -> bool:
        return bool(self._edit.text())
