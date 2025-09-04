from typing import NamedTuple
from enum import Enum
from io import TextIOBase

__all__ = ['Empty', 'AtomType', 'Atom', 'Attribute', 'Block', 'parse']

class Empty:
    ...

class AtomType(Enum):
    NAME = ...
    NUMBER = ...
    FILE = ...
    STRING = ...

class Atom(NamedTuple):
    kind: AtomType
    data: str

class Attribute(NamedTuple):
    name: str
    value: list[Atom]

class Block(NamedTuple):
    name: str
    attrs: list[Attribute]

type _Tree = list[Block]

def parse(buffer: TextIOBase) -> _Tree:
    """Parse a file buffer as an excel info AST."""
    ...