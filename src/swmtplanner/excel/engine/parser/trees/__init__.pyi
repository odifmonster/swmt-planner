from typing import NamedTuple, Literal
from enum import Enum
from swmtplanner.excel.engine.tokenized import Token

__all__ = ['Empty', 'AtomType', 'Atom', 'ExpType', 'AccessExp', 'CallExp',
           'UnpackExp', 'Binop', 'BinopExp', 'PatternExp', 'RngExp',
           'ListExp', 'Exp', 'StmtType', 'UseStmt', 'AssignStmt', 'BlockStmt',
           'Stmt']

class Empty:
    ...

class AtomType(Enum):
    INT = ...
    FLOAT = ...
    STRING = ...
    NAME = ...

class Atom(NamedTuple):
    kind: AtomType
    value: int | float | str
    token: Token

class ExpType(Enum):
    Access = ...
    Call = ...
    Unpack = ...
    Binop = ...
    Pattern = ...
    Rng = ...
    List = ...

class AccessExp(NamedTuple):
    owner: Exp
    member: Atom
    kind: Literal[ExpType.Access] = ExpType.Access

class CallExp(NamedTuple):
    func: Exp
    args: list[Exp]
    kind: Literal[ExpType.Call] = ExpType.Call

class UnpackExp(NamedTuple):
    child: Exp
    kind: Literal[ExpType.Unpack] = ExpType.Unpack

class Binop(Enum):
    MULT = ...
    DIV = ...
    MOD = ...
    ADD = ...
    SUB = ...

class BinopExp(NamedTuple):
    op: Binop
    left: Exp
    right: Exp
    kind: Literal[ExpType.Binop] = ExpType.Binop

class PatternExp(NamedTuple):
    var: Atom
    exp: Exp
    kind: Literal[ExpType.Pattern] = ExpType.Pattern

class RngExp(NamedTuple):
    start: Exp
    stop: Exp
    kind: Literal[ExpType.Rng] = ExpType.Rng

class ListExp(NamedTuple):
    exps: Exp
    kind: Literal[ExpType.List] = ExpType.List

type Exp = Atom | AccessExp | CallExp | UnpackExp | BinopExp | PatternExp \
    | RngExp | ListExp

class StmtType(Enum):
    Use = ...
    Assign = ...
    Block = ...

class UseStmt(NamedTuple):
    names: list[Atom]
    source: Atom
    kind: Literal[StmtType.Use] = StmtType.Use

class AssignStmt(NamedTuple):
    name: Atom
    value: Exp
    kind: Literal[StmtType.Assign] = StmtType.Assign

class BlockStmt(NamedTuple):
    dtype: Atom
    name: Atom
    stmts: list[Stmt]
    kind: Literal[StmtType.Block] = StmtType.Block

type Stmt = UseStmt | AssignStmt | BlockStmt