#!/usr/bin/env python

"""Debug-investigation feature: persist a run's `DebugLog` to a local MySQL
store and investigate it through the `knit-debug` PyQt6 app. See DESIGN.md.

Layout: shared `manifest` (DebugLog -> MySQL mapping, FK graph, insert order)
and `config` (connection resolution for the writer / reader roles) at the top;
the write path in `sqldump`; the read/pagination path in `sqlload`; the GUI
(later) in `app`."""

from . import manifest
from .config import ConnConfig, DatabaseConfigError, resolve_conn_config
from .sqldump import PersistenceError, persist_run

__all__ = [
    'manifest',
    'ConnConfig', 'DatabaseConfigError', 'resolve_conn_config',
    'PersistenceError', 'persist_run',
]
