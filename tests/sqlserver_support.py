#!/usr/bin/env python

"""Shared SQL Server test-connection scaffolding for the persistence (planner)
and read-layer (dashboard) suites — connection details from `SWMT_TEST_*` env
vars, a `_connect` helper (pyodbc, via the dashboard's `config.connect`), and a
`_clean_slate` that empties the store's tables in FK-safe order. Not a
`*_tests.py` module, so test discovery skips it.

**No SQL Server test database exists yet.** The gated suites probe reachability
in `setUpClass` and **skip** when the driver or server is unavailable, so until
one is provisioned the translation is exercised by the pure tests (storage
mapping, `insert_sql`/`project_rows`, `Query.build`'s SQL text) and confirmed by
a manual run against the real database.
"""

import os

from swmtplanner.dashboard.config import ConnConfig, connect

_HOST = os.environ.get('SWMT_TEST_DB_HOST', '127.0.0.1')
_PORT = int(os.environ.get('SWMT_TEST_DB_PORT', '1433'))
_DB = os.environ.get('SWMT_TEST_DB_NAME', 'swmtinftest')
_DRIVER = os.environ.get('SWMT_TEST_DB_DRIVER', 'ODBC Driver 17 for SQL Server')
_WRITER = (os.environ.get('SWMT_TEST_WRITER_USER', 'knitwritetest'),
           os.environ.get('SWMT_TEST_WRITER_PASSWORD', 'testpass'))
_READER = (os.environ.get('SWMT_TEST_READER_USER', 'knitreadtest'),
           os.environ.get('SWMT_TEST_READER_PASSWORD', 'testpass'))
_ADMIN = (os.environ.get('SWMT_TEST_ADMIN_USER', 'ktroot'),
          os.environ.get('SWMT_TEST_ADMIN_PASSWORD', 'InfTestRoot'))


def _config(creds) -> ConnConfig:
    """The test `ConnConfig` for a `(user, password)` role pair."""
    user, password = creds
    return ConnConfig(_HOST, _PORT, _DB, user, password, driver=_DRIVER)


def _connect(creds, autocommit=True):
    """A pyodbc connection as `creds`. Raises if the driver is missing or the
    server is unreachable — the gated suites turn that into a skip."""
    return connect(_config(creds), autocommit=autocommit)


def _clean_slate(specs) -> None:
    """Empty every table in `specs` as the admin role, **children first**.
    `specs` is the manifest's parents-first insert order (`ALL_TABLES`), so it is
    walked in reverse: T-SQL has no FK-checks toggle and `TRUNCATE` refuses an
    FK-referenced table, so ordered `DELETE`s keep the constraints satisfied.
    Physical (`db_name`) table names throughout."""
    conn = _connect(_ADMIN, autocommit=False)
    try:
        cur = conn.cursor()
        try:
            for spec in reversed(list(specs)):
                cur.execute(f'DELETE FROM [{spec.db_name}]')
        finally:
            cur.close()
        conn.commit()
    finally:
        conn.close()
