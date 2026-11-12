#!/usr/bin/env python

import pyodbc

_REQUIRED = ('HOST', 'PORT', 'DATABASE', 'UID', 'PWD')
_DEFAULT_DRIVER = '{ODBC Driver 17 for SQL Server}'


def conn_str(cfg: dict) -> str:
    sql = cfg['sql']
    missing = [k for k in _REQUIRED if k not in sql]
    if missing:
        raise KeyError(f'sql config is missing required keys {missing!r}')
    parts = {
        'DRIVER': sql.get('DRIVER', _DEFAULT_DRIVER),
        'SERVER': f"{sql['HOST']},{sql['PORT']}",
    }
    for key, value in sql.items():
        if key in ('HOST', 'PORT', 'DRIVER'):
            continue
        parts[key] = value
    return ';'.join(f'{k}={v}' for k, v in parts.items())


def connect(cfg: dict) -> pyodbc.Connection:
    return pyodbc.connect(conn_str(cfg))
