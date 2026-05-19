#!/usr/bin/env python

from collections import namedtuple
import json

FlexDate = namedtuple('FlexDate', ['name', 'month', 'weekday', 'n'])
FixedDate = namedtuple('FixedDate', ['name', 'month', 'day'])


def holidays_from_list(holidays, source='<holidays list>'):
    """Build a list of `FixedDate` / `FlexDate` records from an
    already-parsed list of holiday objects. Same shape as a holidays
    JSON file. `source` is woven into error messages so callers can
    point users at the file or config section where the problem is."""
    if not isinstance(holidays, list):
        raise TypeError(
            f'{source} must be a list of holiday objects'
        )
    ret = []
    for h in holidays:
        if not isinstance(h, dict):
            raise TypeError(
                f'elements of {source} must be objects'
            )
        if h['kind'] == 'fixed':
            ret.append(FixedDate(name=h['name'],
                                 month=int(h['month']),
                                 day=int(h['day'])))
        else:
            ret.append(FlexDate(name=h['name'],
                                month=int(h['month']),
                                weekday=int(h['weekday']),
                                n=int(h['n'])))
    return ret


def load_holidays(path):
    """Load holidays from a JSON file. Thin wrapper over
    `holidays_from_list`."""
    with open(path) as f:
        holidays = json.load(f)
    return holidays_from_list(holidays, source=f'holidays file at {path!r}')