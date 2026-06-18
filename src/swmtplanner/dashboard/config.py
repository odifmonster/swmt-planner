#!/usr/bin/env python

"""Resolve MySQL connection settings into a `ConnConfig`.

One flat shape serves both sides: `{host, port, name, user, password}`. The
planner's writer resolves from its run-config `database` block; the dashboard
reader resolves from its own JSON file pointed to by `SWMT_DASHBOARD_CONFIG`.
The two stay separate processes pointing at different MySQL users (writer:
`SELECT,INSERT,UPDATE`; reader: `SELECT`), so read-only is enforced at the grant
level. Their env namespaces are distinct (`SWMT_DB_*` for the writer,
`SWMT_DASHBOARD_*` for the reader) so neither picks up the other's credentials.
The environment wins over the file, so a committed config can hold non-secret
defaults and leave the password to the environment.

See `swmtplanner/dashboard/DESIGN.md`.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 3306

# Environment variable naming the dashboard reader's JSON config file.
DASHBOARD_CONFIG_ENV = 'SWMT_DASHBOARD_CONFIG'


class DatabaseConfigError(ValueError):
    """A required connection setting could not be resolved (a missing database
    name / user, an unparseable port, or an unreadable dashboard config file)."""


@dataclass(frozen=True)
class ConnConfig:
    """A resolved MySQL connection. `password` may be `None` (e.g. a passwordless
    local user); everything else is required."""
    host: str
    port: int
    database: str
    user: str
    password: str | None


def resolve_conn_config(
    block: Mapping[str, Any] | None,
    env: Mapping[str, str] | None = None,
    *,
    prefix: str = 'SWMT_DB',
) -> ConnConfig:
    """Resolve a `ConnConfig` from a connection `block` (a flat mapping with
    `host` / `port` / `name` / `user` / `password`, or `None`) and `env`
    (defaults to `os.environ`).

    Resolution per field: the environment variable wins when set (non-empty),
    else the file value, else a default where one exists. Env keys are
    `{prefix}_HOST` / `_PORT` / `_NAME` / `_USER` / `_PASSWORD` — `prefix` is
    `SWMT_DB` for the planner's writer and `SWMT_DASHBOARD` for the reader, so
    the two never share credentials by accident.

    Raises `DatabaseConfigError` on an unparseable port or a missing database
    name / user (the password may legitimately be `None`).
    """
    env = os.environ if env is None else env
    block = block or {}

    def pick(field: str, file_val: Any) -> Any:
        """Environment value (when set and non-empty) else the file value."""
        v = env.get(f'{prefix}_{field}')
        return v if v not in (None, '') else file_val

    host = pick('HOST', block.get('host')) or DEFAULT_HOST

    port_val = pick('PORT', block.get('port'))
    if port_val is None:
        port = DEFAULT_PORT
    else:
        try:
            port = int(port_val)
        except (TypeError, ValueError):
            raise DatabaseConfigError(f'invalid database port: {port_val!r}')

    database = pick('NAME', block.get('name'))
    user = pick('USER', block.get('user'))
    password = pick('PASSWORD', block.get('password'))

    missing = [
        label for label, val in (('name', database), ('user', user)) if not val
    ]
    if missing:
        raise DatabaseConfigError(
            f'missing database config: {", ".join(missing)} — set it in the '
            f'connection block or via the {prefix}_* environment variables'
        )

    return ConnConfig(
        host=host, port=port, database=database, user=user, password=password,
    )


def read_reader_config(env: Mapping[str, str] | None = None) -> ConnConfig:
    """The dashboard reader's `ConnConfig`: read the JSON file named by
    `SWMT_DASHBOARD_CONFIG` (when set) as the connection block, then resolve it
    against the `SWMT_DASHBOARD_*` env vars (which override individual fields).
    With the variable unset, the block is empty and everything must come from
    `SWMT_DASHBOARD_*`. The reader's `SWMT_DASHBOARD_*` namespace is distinct from
    the writer's `SWMT_DB_*`, so the two can't pick up each other's credentials.

    Raises `DatabaseConfigError` if the file can't be read / isn't a JSON object,
    or if a required field is still missing after resolution.
    """
    env = os.environ if env is None else env
    path = env.get(DASHBOARD_CONFIG_ENV)
    if path:
        try:
            with open(path) as fh:
                block = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise DatabaseConfigError(
                f'could not read dashboard config {path!r} '
                f'(${DASHBOARD_CONFIG_ENV}): {exc}'
            )
        if not isinstance(block, dict):
            raise DatabaseConfigError(
                f'dashboard config {path!r} must be a JSON object'
            )
    else:
        block = {}
    return resolve_conn_config(block, env, prefix='SWMT_DASHBOARD')
