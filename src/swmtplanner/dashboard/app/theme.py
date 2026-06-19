#!/usr/bin/env python

"""The dashboard's app-wide visual theme — a light, colorful, friendly Qt
stylesheet. See `swmtplanner/dashboard/app/DESIGN.md` (Phase 2 — Theme)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication

__all__ = ['apply_theme']

_STYLESHEET = """
* { font-size: 13px; color: #1f2933; }

QWidget { background-color: #f0efec; }    /* soft off-white/grey, not pure white */

/* Sidebar navigation. `show-decoration-selected: 1` makes hover/selection span
   the whole row (branch column included) instead of just the item, so there's no
   square-on-the-left + rounded-item gap. Flat (no radius) for a clean bar. */
QTreeWidget {
    background-color: #5192a5;
    border: none;
    outline: 0;
    font-size: 14px;
    color: #f0f0f0;
    show-decoration-selected: 1;
}
QTreeWidget::item { padding: 8px 6px; }
QTreeWidget::item:hover { background-color: #73a7b7; }
QTreeWidget::item:selected {
    background-color: #f0f0f0;
    color: #488394;
    border-right: 1px solid #5192a5;
}

/* Content header */
QLabel#headerLabel {
    font-size: 20px;
    font-weight: bold;
    color: #3c3c3c;
    padding: 10px 4px;
    background-color: #f0f0f0;
    border-bottom: 1px solid #c0c0c0;
}
QLabel#message { font-size: 16px; color: #52606d; }

/* Data grid */
QTableView {
    background-color: #eef9fb;
    alternate-background-color: #d6f0f6;
    gridline-color: #ade2ee;
    border: 1px solid #b5e4ef;
}
QHeaderView::section {
    background-color: #9bcbd6;
    font-weight: bold;
    padding: 5px;
    border: none;
}

/* Paging buttons */
QToolButton {
    background-color: #ffae78;
    border: 1px solid #ff791f;
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 15px;
    color: #66300c;
}
QToolButton:hover { background-color: #ff934b; }
QToolButton:disabled { color: #644631; background-color: #d6a17e; }

/* Run-selection cards */
QFrame#runButton {
    background-color: #ffc9a5;
    border: 1px solid #ffa162;
    border-radius: 10px;
    padding: 4px;
}
QFrame#runButton:hover { background-color: #e59c6c; }
QFrame#runButton[selected="true"] {
    background-color: #ff934b;
    border: 2px solid #66300c;
}
QFrame#runButton QLabel { background: transparent; }
QLabel#runTitle { font-size: 16px; font-weight: bold; color: #4c2409; }
QLabel#runDetails { color: #6f4f3a; }
QFrame#runButton QLabel#runTitle[selected="true"] { color: #fff6f1; }
QFrame#runButton QLabel#runDetails[selected="true"] { color: #ffd6bb; }

/* Filter popup — a soft, rounded off-white card */
QFrame#filterCard {
    background-color: #e8e6e1;
    border: 1px solid #b9b4ac;
    border-radius: 12px;
}
QFrame#filterCard QLabel { background: transparent; }
QFrame#filterCard QLineEdit,
QFrame#filterCard QComboBox,
QFrame#filterCard QDateTimeEdit,
QFrame#filterCard QScrollArea {
    background-color: #faf9f6;
    border: 1px solid #cbc6bd;
    border-radius: 6px;
    padding: 3px 6px;
}
QFrame#filterCard QScrollArea { padding: 0; }
QFrame#filterCard QCheckBox { padding: 4px 6px; border-radius: 4px; }
QFrame#filterCard QCheckBox:hover { background-color: #5192a5; color: #ffffff; }
QFrame#filterCard QPushButton {
    background-color: #ffae78;
    border: 1px solid #ff791f;
    border-radius: 6px;
    padding: 5px 12px;
    color: #66300c;
}
QFrame#filterCard QPushButton:hover { background-color: #ff934b; }
QFrame#filterCard QPushButton:disabled { color: #9a8f86; background-color: #ddd8d1; }

/* Combo dropdown lists (filter kind, range bound) — blue hover */
QFrame#filterCard QComboBox {
    background-color: #faf9f6;
    border: 1px solid #cbc6bd;
    selection-background-color: #5192a5;
    selection-color: #ffffff;
    outline: 0;
}
QFrame#filterCard QComboBox QListView::item { padding: 4px 6px; }
QFrame#filterCard QComboBox QListView::item:hover { background-color: #5192a5; color: #ffffff; }
"""


def apply_theme(app: 'QApplication') -> None:
    """Install the dashboard stylesheet on the `QApplication`."""
    app.setStyleSheet(_STYLESHEET)
