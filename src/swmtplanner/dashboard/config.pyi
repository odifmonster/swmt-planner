from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_HOST: str
DEFAULT_PORT: int
DASHBOARD_CONFIG_ENV: str


class DatabaseConfigError(ValueError): ...


@dataclass(frozen=True)
class ConnConfig:
    host: str
    port: int
    database: str
    user: str
    password: str | None


def resolve_conn_config(
    block: Mapping[str, Any] | None,
    env: Mapping[str, str] | None = ...,
    *,
    prefix: str = ...,
) -> ConnConfig: ...
def read_reader_config(env: Mapping[str, str] | None = ...) -> ConnConfig: ...
