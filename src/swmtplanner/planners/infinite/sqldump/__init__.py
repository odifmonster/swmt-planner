#!/usr/bin/env python

"""`sqldump` — the write path: persist a populated `DebugLog` to the MySQL store
(run-tagged by an auto-incremented `run_id`). Uses the planner's concrete
`..manifest` (DB layout / insert order) and the writer `ConnConfig` from the
top-level `swmtplanner.dashboard.config`. See `planners/infinite/DESIGN.md`."""

from .persistence import PersistenceError, persist_run

__all__ = ['PersistenceError', 'persist_run']
