#!/usr/bin/env python

"""Shared MySQL test-connection scaffolding for the persistence (planner) and
read-layer (dashboard) suites — connection details from env vars with the
project's local test defaults, plus a `_connect` helper. Not a `*_tests.py`
module, so test discovery skips it."""

import os

_HOST = os.environ.get('SWMT_TEST_DB_HOST', '35.188.224.154')
_PORT = int(os.environ.get('SWMT_TEST_DB_PORT', '3306'))
_DB = os.environ.get('SWMT_TEST_DB_NAME', 'swmtinftest')
_WRITER = (os.environ.get('SWMT_TEST_WRITER_USER', 'debuglogtest'),
           os.environ.get('SWMT_TEST_WRITER_PASSWORD', 'TestWriter!'))
_READER = (os.environ.get('SWMT_TEST_READER_USER', 'dashboardtest'),
           os.environ.get('SWMT_TEST_READER_PASSWORD', 'TestReader!'))
_ADMIN = (os.environ.get('SWMT_TEST_ADMIN_USER', 'testroot'),
          os.environ.get('SWMT_TEST_ADMIN_PASSWORD', 'W@rp-Kn!tt!ng-Rul3s'))


def _connect(creds, autocommit=True):
    import pymysql
    user, password = creds
    return pymysql.connect(
        host=_HOST, port=_PORT, user=user, password=password,
        database=_DB, autocommit=autocommit,
    )
