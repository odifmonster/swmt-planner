#!/usr/bin/env python

"""Shared cell-value formatting for the dashboard GUI (the grid and the filter
value lists), so both render values the same way."""

import datetime
from typing import Any

__all__ = ['format_cell']


def format_cell(value: Any) -> str:
    """Render one value for display. Datetimes show as `m/d/yy h:mm` (24-hour, no
    leading zeros except the 2-digit year/minute); dates as `m/d/yy`; `None` as
    blank; everything else via `str`."""
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        return (f'{value.month}/{value.day}/{value.year % 100:02d} '
                f'{value.hour}:{value.minute:02d}')
    if isinstance(value, datetime.date):
        return f'{value.month}/{value.day}/{value.year % 100:02d}'
    return str(value)
