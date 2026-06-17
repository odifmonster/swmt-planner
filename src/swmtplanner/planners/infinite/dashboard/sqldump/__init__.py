#!/usr/bin/env python

"""`sqldump` — the write path: persist a populated `DebugLog` to the MySQL store
(run-tagged by an auto-incremented `run_id`). Uses the shared `..manifest` (DB
layout / insert order) and `..config` (writer connection). See ../DESIGN.md."""

from .persistence import PersistenceError, persist_run

__all__ = ['PersistenceError', 'persist_run']
