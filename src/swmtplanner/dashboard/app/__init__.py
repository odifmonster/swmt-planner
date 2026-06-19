#!/usr/bin/env python

"""`swmtplanner.dashboard.app` — the PyQt6 GUI for the debug dashboard. The shell
(`DashboardWindow`) hosts a sidebar over run selection, raw paged grids, and (a
later phase) the pretty view, all driving `sqlload`. Per-planner launchers (e.g.
`knit_debug`) bind it to a planner's manifest + reader connection. Importing this
package requires PyQt6. See DESIGN.md."""

from .grid import PageModel, PagedGrid, ROWS_PER_PAGE
from .theme import apply_theme
from .window import DashboardWindow

__all__ = [
    'DashboardWindow', 'PagedGrid', 'PageModel', 'ROWS_PER_PAGE', 'apply_theme',
]
