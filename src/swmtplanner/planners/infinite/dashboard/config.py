#!/usr/bin/env python

"""Resolve MySQL connection settings for the persistence writer / dashboard
reader from the run-config `database` block + environment.

The `database` block carries shared connection fields plus a `writer` and a
`reader` credential sub-block (two MySQL roles, so the dashboard is read-only at
the grant level). Either side resolves the `ConnConfig` for its role; the
environment wins over the file, so a committed config can hold non-secret
defaults and leave passwords to the environment.

See `planners/infinite/dashboard/DESIGN.md`.
"""

import os
from dataclasses import dataclass
from typing import Any, Literal, Mapping

Role = Literal['writer', 'reader']

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 3306


class DatabaseConfigError(ValueError):
    """A required connection setting could not be resolved (unknown role, or a
    missing database name / user)."""


@dataclass(frozen=True)
class ConnConfig:
    """A resolved MySQL connection for one role. `password` may be `None` (e.g.
    a passwordless local user); everything else is required."""
    host: str
    port: int
    database: str
    user: str
    password: str | None


def resolve_conn_config(
    block: Mapping[str, Any] | None,
    role: Role,
    env: Mapping[str, str] | None = None,
) -> ConnConfig:
    """Resolve the `ConnConfig` for `role` (`'writer'` or `'reader'`) from the
    run-config `database` `block` (a mapping or `None`) and `env` (defaults to
    `os.environ`).

    Resolution per field: the environment variable wins when set (non-empty),
    else the file value, else a default where one exists. Shared fields read
    `SWMT_DB_HOST` / `SWMT_DB_PORT` / `SWMT_DB_NAME`; per-role credentials read
    `SWMT_DB_{ROLE}_USER` / `SWMT_DB_{ROLE}_PASSWORD`.

    Raises `DatabaseConfigError` on an unknown `role`, an unparseable port, or a
    missing database name / role user (the password may legitimately be `None`).
    """
    if role not in ('writer', 'reader'):
        raise DatabaseConfigError(
            f"role must be 'writer' or 'reader', got {role!r}"
        )
    env = os.environ if env is None else env
    block = block or {}
    role_block = block.get(role) or {}
    role_env = role.upper()

    def pick(env_key: str, file_val: Any) -> Any:
        """Environment value (when set and non-empty) else the file value."""
        v = env.get(env_key)
        return v if v not in (None, '') else file_val

    host = pick('SWMT_DB_HOST', block.get('host')) or DEFAULT_HOST

    port_val = pick('SWMT_DB_PORT', block.get('port'))
    if port_val is None:
        port = DEFAULT_PORT
    else:
        try:
            port = int(port_val)
        except (TypeError, ValueError):
            raise DatabaseConfigError(f'invalid database port: {port_val!r}')

    database = pick('SWMT_DB_NAME', block.get('name'))
    user = pick(f'SWMT_DB_{role_env}_USER', role_block.get('user'))
    password = pick(f'SWMT_DB_{role_env}_PASSWORD', role_block.get('password'))

    missing = [
        label for label, val in (('name', database), (f'{role} user', user))
        if not val
    ]
    if missing:
        raise DatabaseConfigError(
            f'missing database config for the {role} role: '
            f'{", ".join(missing)} — set it in the run-config `database` block '
            f'or via the SWMT_DB_* environment variables'
        )

    return ConnConfig(
        host=host, port=port, database=database, user=user, password=password,
    )
