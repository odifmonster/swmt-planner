#!/usr/bin/env python

"""Debug-investigation feature: persist a run's `DebugLog` to a local MySQL
store and investigate it through the `knit-debug` PyQt6 app. See DESIGN.md.

Phase 1 (in progress): the `manifest` (DebugLog -> MySQL mapping, FK graph,
insert order) and `config` (connection resolution for the writer / reader
roles). The PyMySQL writer, `run.py` wiring, and the app follow."""

from . import manifest
from .config import ConnConfig, DatabaseConfigError, resolve_conn_config
from .persistence import PersistenceError, persist_run

__all__ = [
    'manifest',
    'ConnConfig', 'DatabaseConfigError', 'resolve_conn_config',
    'PersistenceError', 'persist_run',
]
