#!/usr/bin/env python

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str
    src_name: str | None = None
    converter: Callable[[Any], Any] | None = None
    read_na_as: Any | None = None
