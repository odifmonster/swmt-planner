#!/usr/bin/env python

from typing import NamedTuple
from enum import Enum, auto

class Empty:
    pass

class AtomType(Enum):
    VARNAME = auto()
    NAME = auto()
    NUMBER = auto()
    FILE = auto()
    STRING = auto()

class Atom(NamedTuple):
    kind: AtomType
    data: str

class VarType(Enum):
    NORMAL = auto()
    LIST = auto()

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