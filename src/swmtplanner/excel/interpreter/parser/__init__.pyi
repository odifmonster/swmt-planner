from typing import NamedTuple
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

class Variable(NamedTuple):
    name: str
    kind: VarType
    value: Atom | list[Atom]

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