#!/usr/bin/env python

"""`debuglog` — the planner's optional audit log and (eventually) dashboard.

Defines `DebugLog`, an in-memory object threaded through the planner so its
methods can record *why* the schedule came out the way it did, plus the logic
that renders a populated log. Built up over four phases — see DESIGN.md. Phase
1 is in progress: the `DebugLog` class is complete (schema construction via
`set_pk` / `set_fk`; row population / export via `add_row`, `update_row`,
`get_last_pk_val`, `get_df`). The simplified iteration-log + cost-summary
wiring into the planner follows.
"""

from .debuglog import DebugLog, TableSchema, ForeignKey

__all__ = ['DebugLog', 'TableSchema', 'ForeignKey']
