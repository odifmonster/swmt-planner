from typing import NamedTuple, Callable
from enum import Enum

from . import file, tokenized, parser

__all__ = ['file', 'tokenized', 'parser', 'ValType', 'Value', 'interpret']

class ValType(Enum):
    INT = ...
    FLOAT = ...
    STRING = ...
    FUNC = ...

class Value(NamedTuple):
    dtype: ValType
    data: int | str | float | Callable

type _Context = dict[str, Value | list[Value] | _Context]

def interpret(file: list[parser.trees.Stmt], **kwargs) -> _Context: ...