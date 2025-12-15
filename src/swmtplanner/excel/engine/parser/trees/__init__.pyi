from typing import NamedTuple, Literal
from enum import Enum
from swmtplanner.excel.engine.tokenized import Token

__all__ = ['Empty', 'AtomType', 'Atom', 'ExpType', 'AccessExp', 'CallExp',
           'UnpackExp', 'BinopType', 'Binop', 'BinopExp', 'PatternExp', 'RngExp',
           'ListExp', 'Exp', 'StmtType', 'AssignStmt', 'BlockStmt', 'Stmt']

class Empty(NamedTuple):
    token: Token

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
    r_dot: Empty
    member: Atom
    kind: Literal[ExpType.Access] = ExpType.Access

class CallExp(NamedTuple):
    func: Exp
    args: list[Exp]
    kind: Literal[ExpType.Call] = ExpType.Call

class UnpackExp(NamedTuple):
    r_star: Empty
    child: Exp
    kind: Literal[ExpType.Unpack] = ExpType.Unpack

class BinopType(Enum):
    MULT = ...
    DIV = ...
    MOD = ...
    ADD = ...
    SUB = ...

class Binop(NamedTuple):
    kind: BinopType
    token: Token

class BinopExp(NamedTuple):
    op: Binop
    left: Exp
    right: Exp
    kind: Literal[ExpType.Binop] = ExpType.Binop

class PatternExp(NamedTuple):
    var: Atom
    r_arrow: Empty
    exp: Exp
    kind: Literal[ExpType.Pattern] = ExpType.Pattern

class RngExp(NamedTuple):
    start: Exp
    r_to: Empty
    stop: Exp
    kind: Literal[ExpType.Rng] = ExpType.Rng

class ListExp(NamedTuple):
    exps: Exp
    kind: Literal[ExpType.List] = ExpType.List

type Exp = Atom | AccessExp | CallExp | UnpackExp | BinopExp | PatternExp \
    | RngExp | ListExp

class StmtType(Enum):
    Assign = ...
    Block = ...

class AssignStmt(NamedTuple):
    name: Atom
    r_eq: Empty
    value: Exp
    kind: Literal[StmtType.Assign] = StmtType.Assign

class BlockStmt(NamedTuple):
    dtype: Atom
    name: Atom
    stmts: list[Stmt]
    kind: Literal[StmtType.Block] = StmtType.Block

type Stmt = AssignStmt | BlockStmt