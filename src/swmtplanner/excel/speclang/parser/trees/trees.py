#!/usr/bin/env python

from collections import namedtuple
from enum import Enum, auto

Empty = namedtuple('Empty', ['token'])

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

AccessExp = namedtuple('AccessExp', ['owner', 'r_dot', 'member', 'kind'],
                       defaults=[ExpType.Access])
CallExp = namedtuple('CallExp', ['func', 'args', 'kind'],
                     defaults=[ExpType.Call])
UnpackExp = namedtuple('UnpackExp', ['r_star', 'child', 'kind'],
                       defaults=[ExpType.Unpack])

class BinopType(Enum):
    MULT = auto()
    DIV = auto()
    MOD = auto()
    ADD = auto()
    SUB = auto()

Binop = namedtuple('Binop', ['kind', 'token'])
BinopExp = namedtuple('BinopExp', ['op', 'left', 'right', 'kind'],
                      defaults=[ExpType.Binop])

PatternExp = namedtuple('PatternExp', ['var', 'r_arrow', 'exp', 'kind'],
                        defaults=[ExpType.Pattern])
RngExp = namedtuple('RngExp', ['start', 'r_to', 'stop', 'kind'],
                    defaults=[ExpType.Rng])
ListExp = namedtuple('ListExp', ['exps', 'kind'],
                     defaults=[ExpType.List])

class Exp:
    pass

class StmtType(Enum):
    Assign = auto()
    Block = auto()

AssignStmt = namedtuple('AssignStmt', ['name', 'r_eq', 'value', 'kind'],
                        defaults=[StmtType.Assign])
BlockStmt = namedtuple('BlockStmt', ['dtype', 'name', 'stmts', 'kind'],
                       defaults=[StmtType.Block])

class Stmt:
    pass