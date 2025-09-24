#!/usr/bin/env python

from collections import namedtuple
from enum import Enum, auto

class Empty:
    pass

class AtomType(Enum):
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    NAME = auto()

Atom = namedtuple('Atom', ['kind', 'value', 'token'])

class ExpType(Enum):
    Access = auto()
    Call = auto()
    Unpack = auto()
    Binop = auto()
    Pattern = auto()
    Rng = auto()
    List = auto()

AccessExp = namedtuple('AccessExp', ['owner', 'member', 'kind'],
                       defaults=[ExpType.Access])
CallExp = namedtuple('CallExp', ['func', 'args', 'kind'],
                     defaults=[ExpType.Call])
UnpackExp = namedtuple('UnpackExp', ['child', 'kind'],
                       defaults=[ExpType.Unpack])

class Binop(Enum):
    MULT = auto()
    DIV = auto()
    MOD = auto()
    ADD = auto()
    SUB = auto()

BinopExp = namedtuple('BinopExp', ['op', 'left', 'right', 'kind'],
                      defaults=[ExpType.Binop])

PatternExp = namedtuple('PatternExp', ['var', 'exp', 'kind'],
                        defaults=[ExpType.Pattern])
RngExp = namedtuple('RngExp', ['start', 'stop', 'kind'],
                    defaults=[ExpType.Rng])
ListExp = namedtuple('ListExp', ['exps', 'kind'],
                     defaults=[ExpType.List])

class Exp:
    pass

class StmtType(Enum):
    Use = auto()
    Assign = auto()
    Block = auto()

UseStmt = namedtuple('UseStmt', ['names', 'source', 'kind'],
                     defaults=[StmtType.Use])
AssignStmt = namedtuple('AssignStmt', ['name', 'value', 'kind'],
                        defaults=[StmtType.Assign])
BlockStmt = namedtuple('BlockStmt', ['dtype', 'name', 'stmts', 'kind'],
                       defaults=[StmtType.Block])

class Stmt:
    pass