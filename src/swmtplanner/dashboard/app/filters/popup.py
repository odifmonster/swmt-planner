#!/usr/bin/env python

"""The `FilterPopup` — the filter menu box for one column: a kind selector, a
body that follows the kind (from `bodies`), and an Apply-filter button. It emits
only valid `(kind, rule)` pairs (Apply is disabled otherwise), matching
`sqlload.Filter`. See `../DESIGN.md` (Phase 3)."""

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .bodies import MembershipBody, PatternBody, RangeBody

__all__ = ['FilterPopup']

# Kind options (label, mode). The three pattern modes are text-only.
_BASE_KINDS = [('Selection', 'selection'), ('Exclusion', 'exclusion'),
               ('Range', 'range')]
_PATTERN_KINDS = [('Starts with', 'starts'), ('Ends with', 'ends'),
                  ('Contains', 'contains')]


def _kinds_for(col_type: str) -> list[tuple[str, str]]:
    return _BASE_KINDS + _PATTERN_KINDS if col_type == 'str' else _BASE_KINDS


def _like_escape(text: str) -> str:
    """Escape MySQL `LIKE` metacharacters so the user's text matches literally
    once the affix `%` is added (backslash first)."""
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class FilterPopup(QWidget):
    """The filter menu box for one column. On apply it calls `on_apply(kind, rule)`
    and closes."""

    def __init__(
        self, column: str, col_type: str,
        unique_getter: Callable[[], list | None],
        on_apply: Callable[[str, Any], None],
        parent: 'QWidget | None' = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        # Transparent window so only the rounded card shows (no square corners).
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._col_type = col_type
        self._unique_getter = unique_getter
        self._on_apply = on_apply
        self._kinds = _kinds_for(col_type)

        self._combo = QComboBox()
        self._combo.addItem('')                       # empty initial selection
        self._combo.addItems([label for label, _m in self._kinds])
        self._combo.currentIndexChanged.connect(self._on_kind_changed)

        self._prompt = QLabel('Please select a filter method.')
        self._prompt.setObjectName('message')
        self._prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prompt.setWordWrap(True)
        self._membership = MembershipBody()
        self._range = RangeBody(col_type)
        self._pattern = PatternBody()
        for body in (self._membership, self._range, self._pattern):
            body.changed.connect(self._update_apply)
        self._body = QStackedWidget()
        self._body.addWidget(self._prompt)
        self._body.addWidget(self._membership)
        self._body.addWidget(self._range)
        self._body.addWidget(self._pattern)

        self._apply = QPushButton('Apply filter')
        self._apply.clicked.connect(self._do_apply)

        card = QFrame()
        card.setObjectName('filterCard')
        inner = QVBoxLayout(card)
        inner.addWidget(QLabel(column))
        inner.addWidget(self._combo)
        inner.addWidget(self._body)
        inner.addWidget(self._apply)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self.setMinimumWidth(260)
        self._on_kind_changed(0)

    def _mode(self) -> 'str | None':
        idx = self._combo.currentIndex()
        return None if idx <= 0 else self._kinds[idx - 1][1]

    def _on_kind_changed(self, _index: int) -> None:
        mode = self._mode()
        if mode is None:
            self._body.setCurrentWidget(self._prompt)
        elif mode in ('selection', 'exclusion'):
            self._body.setCurrentWidget(self._membership)
            self._membership.load(self._unique_getter)
        elif mode == 'range':
            self._body.setCurrentWidget(self._range)
        else:
            self._body.setCurrentWidget(self._pattern)
        self._update_apply()

    def _active_body(self) -> Any:
        mode = self._mode()
        if mode in ('selection', 'exclusion'):
            return self._membership
        if mode == 'range':
            return self._range
        return self._pattern

    def _update_apply(self) -> None:
        mode = self._mode()
        self._apply.setEnabled(mode is not None and self._active_body().is_valid())

    def _do_apply(self) -> None:
        mode = self._mode()
        if mode is None:
            return
        if mode in ('selection', 'exclusion'):
            self._on_apply(mode, self._membership.selected_values())
        elif mode == 'range':
            self._on_apply('range', self._range.bounds())
        else:
            value = _like_escape(self._pattern.text())
            pattern = {'starts': value + '%', 'ends': '%' + value,
                       'contains': '%' + value + '%'}[mode]
            self._on_apply('pattern', pattern)
        self.close()
