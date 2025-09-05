from typing import NamedTuple, Literal
from enum import Enum
from io import TextIOBase

__all__ = ['Empty', 'AtomType', 'Atom', 'VarType', 'Variable',
           'Attribute', 'Block', 'parse']

class Empty:
    ...

class AtomType(Enum):
    VARNAME = ...
    NAME = ...
    NUMBER = ...
    FILE = ...
    STRING = ...

class Atom(NamedTuple):
    kind: AtomType
    data: str

class VarType(Enum):
    NORMAL = ...
    LIST = ...

class _NormVar(NamedTuple):
    name: str
    kind: Literal[VarType.NORMAL]
    value: Atom

class _ListVar(NamedTuple):
    name: str
    kind: Literal[VarType.LIST]
    value: list[Atom]

type Variable = _NormVar | _ListVar

class Attribute(NamedTuple):
    name: str
    value: list[Atom]

class Block(NamedTuple):
    name: str
    attrs: list[Attribute]

type _Tree = list[Block | Variable]

def parse(buffer: TextIOBase) -> _Tree:
    """Parse a file buffer as an excel info AST."""
    ...