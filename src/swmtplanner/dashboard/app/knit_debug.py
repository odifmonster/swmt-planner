#!/usr/bin/env python

"""The `knit-debug` launcher: open the dashboard shell on the knitting planner's
debug database (SQL Server), connecting as the reader (`SWMT_DASHBOARD_CONFIG`).
See `swmtplanner/dashboard/app/DESIGN.md`.

This is the planner-specific binding — it supplies the knit planner's manifest
(viewable tables/views + the run registry) to the otherwise-generic dashboard.
"""

import sys

from swmtplanner.planners.infinite import manifest

from ..config import DatabaseConfigError, connect, read_reader_config

__all__ = ['main']


def main() -> None:
    """Entry point for the `knit-debug` console script."""
    from PyQt6.QtWidgets import QApplication

    from .theme import apply_theme
    from .window import DashboardWindow

    try:
        cfg = read_reader_config()
        # The reader only SELECTs; autocommit avoids holding a transaction open
        # across the app's lifetime. pyodbc errors are plain `Exception`s.
        conn = connect(cfg, autocommit=True)
    except (DatabaseConfigError, Exception) as exc:
        print(
            f'knit-debug: cannot connect to the dashboard database: {exc}',
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        app = QApplication(sys.argv)
        apply_theme(app)
        window = DashboardWindow(
            conn.cursor(),
            table_specs=list(manifest.TABLES) + list(manifest.VIEWS),
            runs_spec=manifest.RUNS,
        )
        window.setWindowTitle('knit-debug')
        window.show()
        code = app.exec()
    finally:
        conn.close()
    sys.exit(code)
