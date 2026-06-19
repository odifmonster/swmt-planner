#!/usr/bin/env python

"""The `FilterHeader` — a `QHeaderView` that draws a per-column filter button (a
small rounded square with a funnel-ish ▾ when unfiltered, an accent ✕ when
filtered) and turns clicks on it into `filter_requested` / `filter_cleared`
signals. See `../DESIGN.md` (Phase 3)."""

from typing import Any

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHeaderView, QWidget

__all__ = ['FilterHeader']

_ACCENT = '#ff791f'        # the applied-filter ✕ color
_BTN_BORDER = '#b9b4ac'
_BTN_FILL = '#faf9f6'      # off-white, softer than pure white
_GLYPH = '#3a3a3a'


class FilterHeader(QHeaderView):
    """Horizontal header with a per-column filter button. Clicks in the button
    emit `filter_requested` / `filter_cleared`; clicks elsewhere behave
    normally."""

    filter_requested = pyqtSignal(int)
    filter_cleared = pyqtSignal(int)

    _BTN_W = 22

    def __init__(self, parent: 'QWidget | None' = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._filtered: set[int] = set()
        self._skip = 0
        self.setSectionsClickable(True)

    def set_filtered(self, col: int, on: bool) -> None:
        if on:
            self._filtered.add(col)
        else:
            self._filtered.discard(col)
        self.updateSection(col)

    def set_skip_leading(self, n: int) -> None:
        """Leading sections (e.g. a checkbox column) that carry no filter button:
        they reserve no button width and ignore button clicks."""
        self._skip = n

    def sectionSizeFromContents(self, logicalIndex: int):
        # Reserve room for the filter button so the column name still fits
        # (except the skipped leading sections, which have no button).
        size = super().sectionSizeFromContents(logicalIndex)
        if logicalIndex >= self._skip:
            size.setWidth(size.width() + self._BTN_W + 6)
        return size

    def paintSection(self, painter, rect: QRect, logicalIndex: int) -> None:
        super().paintSection(painter, rect, logicalIndex)
        if logicalIndex < self._skip:
            return
        filtered = logicalIndex in self._filtered
        side = min(self._BTN_W, rect.height() - 6)
        btn = QRect(rect.right() - self._BTN_W,
                    rect.top() + (rect.height() - side) // 2,
                    self._BTN_W, side)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(_BTN_BORDER)))
        painter.setBrush(QColor(_BTN_FILL))
        painter.drawRoundedRect(btn, 4, 4)
        painter.setPen(QColor(_ACCENT) if filtered else QColor(_GLYPH))
        painter.drawText(btn, int(Qt.AlignmentFlag.AlignCenter),
                         '✕' if filtered else '▾')
        painter.restore()

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        col = self.logicalIndexAt(pos)
        if col >= self._skip:
            right = self.sectionViewportPosition(col) + self.sectionSize(col)
            if pos.x() >= right - self._BTN_W:
                if col in self._filtered:
                    self.filter_cleared.emit(col)
                else:
                    self.filter_requested.emit(col)
                return
        super().mousePressEvent(event)
