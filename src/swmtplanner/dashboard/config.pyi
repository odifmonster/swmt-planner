from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_HOST: str
DEFAULT_PORT: int
DEFAULT_DRIVER: str
DEFAULT_ENCRYPT: str
DEFAULT_TRUST_SERVER_CERTIFICATE: str
DASHBOARD_CONFIG_ENV: str


class DatabaseConfigError(ValueError): ...


@dataclass(frozen=True)
class ConnConfig:
    host: str
    port: int
    database: str
    user: str
    password: str | None
    driver: str = ...
    encrypt: str = ...
    trust_server_certificate: str = ...


def resolve_conn_config(
    block: Mapping[str, Any] | None,
    env: Mapping[str, str] | None = ...,
    *,
    prefix: str = ...,
) -> ConnConfig: ...
def connection_string(cfg: ConnConfig) -> str: ...
def connect(cfg: ConnConfig, *, autocommit: bool = ...) -> Any: ...
def read_reader_config(env: Mapping[str, str] | None = ...) -> ConnConfig: ...
