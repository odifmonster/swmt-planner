#!/usr/bin/env python

"""`swmtplanner.dashboard` — the PyQt6 debug-log viewer, planner-agnostic at the
data layer. A planner persists a run-tagged debug log to a local MySQL store; the
dashboard reads it, driven by a `manifest` of `TableSpec`s the planner hands in.

Layout: the generic `manifest` dataclasses + reader `config` (the `ConnConfig`
connection + its resolution) at the top; the read/pagination data layer in
`sqlload`; the GUI in `app` (later). See DESIGN.md."""

from . import manifest
from .config import ConnConfig, DatabaseConfigError, resolve_conn_config

__all__ = [
    'manifest',
    'ConnConfig', 'DatabaseConfigError', 'resolve_conn_config',
]
