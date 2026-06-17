from dataclasses import dataclass
from typing import Any, Literal, Mapping

Role = Literal['writer', 'reader']

DEFAULT_HOST: str
DEFAULT_PORT: int


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
    role: Role,
    env: Mapping[str, str] | None = ...,
) -> ConnConfig: ...
