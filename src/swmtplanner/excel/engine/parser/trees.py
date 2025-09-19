#!/usr/bin/env python

from typing import Protocol
from collections import namedtuple
from enum import Enum, auto

class Exp(Protocol):

    @property
    def kind(self):
        raise NotImplementedError()

class Stmt(Protocol):

    @property
    def kind(self):
        raise NotImplementedError()
    
class Empty:
    pass

class AtomType(Enum):
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    NAME = auto()
    REF = auto()

class Binop(Enum):
    MULT = auto()
    DIV = auto()
    MOD = auto()
    ADD = auto()
    SUB = auto()

class ExpType(Enum):
    Rng = auto()
    Access = auto()
    Call = auto()
    List = auto()
    Unpack = auto()
    Binop = auto()
    Pattern = auto()

class StmtType(Enum):
    Use = auto()
    Assign = auto()
    Block = auto()

Atom = namedtuple('Atom', ['kind', 'token'])
RngExp = namedtuple('RngExp', ['start', 'stop', 'kind'], defaults=[ExpType.Rng])
AccessExp = namedtuple('AccessExp', ['owner', 'member', 'kind'],
                       defaults=[ExpType.Access])
CallExp = namedtuple('CallExp', ['func', 'args', 'kind'], defaults=[ExpType.Call])
ListExp = namedtuple('ListExp', ['exps', 'kind'], defaults=[ExpType.List])
UnpackExp = namedtuple('UnpackExp', ['child', 'kind'], defaults=[ExpType.Unpack])
BinopExp = namedtuple('BinopExp', ['op', 'left', 'right', 'kind'],
                      defaults=[ExpType.Binop])
PatternExp = namedtuple('PatternExp', ['var', 'pattern', 'kind'],
                        defaults=[ExpType.Pattern])
UseStmt = namedtuple('UseStmt', ['funcs', 'source', 'kind'],
                     defaults=[StmtType.Use])
AssignStmt = namedtuple('AssignStmt', ['dest', 'source', 'kind'],
                        defaults=[StmtType.Assign])
BlockStmt = namedtuple('BlockStmt', ['dtype', 'name', 'stmts', 'kind'],
                       defaults=[StmtType.Block])