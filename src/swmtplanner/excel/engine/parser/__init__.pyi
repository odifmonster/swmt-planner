from typing import Protocol, NamedTuple, Literal
from enum import Enum
from swmtplanner.excel.engine.lexer import Token, Lexer

__all__ = ['Exp', 'Stmt', 'Empty', 'AtomType', 'Binop', 'ExpType', 'StmtType',
           'Atom', 'RngExp', 'AccessExp', 'CallExp', 'ListExp', 'UnpackExp',
           'BinopExp', 'PatternExp', 'UseStmt', 'AssignStmt', 'BlockStmt',
           'parse']

def parse(lex: Lexer) -> list[Stmt]: ...

class AtomType(Enum):
    INT = ...
    FLOAT = ...
    STRING = ...
    NAME = ...
    REF = ...

class Binop(Enum):
    MULT = ...
    DIV = ...
    MOD = ...
    ADD = ...
    SUB = ...

class ExpType(Enum):
    Rng = ...
    Access = ...
    Call = ...
    List = ...
    Unpack = ...
    Binop = ...
    Pattern = ...

class StmtType(Enum):
    Use = ...
    Assign = ...
    Block = ...

class Empty:
    ...

class Exp(Protocol):
    @property
    def kind(self) -> ExpType: ...

class Stmt(Protocol):
    @property
    def kind(self) -> StmtType: ...

class Atom(NamedTuple):
    kind: AtomType
    token: Token

class _IntAtom(Atom):
    kind: Literal[AtomType.INT]
    token: Token

class RngExp(Exp, NamedTuple):
    start: _IntAtom
    stop: _IntAtom
    kind: Literal[ExpType.Rng] = ExpType.Rng

class _RefAtom(Atom):
    kind: Literal[AtomType.REF]
    token: Token

class _NameAtom(Atom):
    kind: Literal[AtomType.NAME]
    token: Token

class AccessExp(Exp, NamedTuple):
    owner: AccessExp | _RefAtom
    member: _NameAtom
    kind: Literal[ExpType.Access] = ExpType.Access

class CallExp(Exp, NamedTuple):
    func: CallExp | _NameAtom
    args: list[Exp]
    kind: Literal[ExpType.Call] = ExpType.Call

class ListExp(Exp, NamedTuple):
    exps: list[Exp]
    kind: Literal[ExpType.List] = ExpType.List

class UnpackExp(Exp, NamedTuple):
    child: Exp
    kind: Literal[ExpType.Unpack] = ExpType.Unpack

class BinopExp(Exp, NamedTuple):
    op: Binop
    left: Exp
    right: Exp
    kind: Literal[ExpType.Binop] = ExpType.Binop

class PatternExp(Exp, NamedTuple):
    var: _NameAtom
    pattern: Exp
    kind: Literal[ExpType.Pattern] = ExpType.Pattern

class UseStmt(Stmt, NamedTuple):
    funcs: list[_NameAtom]
    source: _NameAtom
    kind: Literal[StmtType.Use] = StmtType.Use

class AssignStmt(Stmt, NamedTuple):
    dest: _NameAtom
    source: Exp
    kind: Literal[StmtType.Assign] = StmtType.Assign

class BlockStmt(Stmt, NamedTuple):
    dtype: _NameAtom | Empty
    name: _NameAtom
    stmts: list[Stmt]
    kind: Literal[StmtType.Block] = StmtType.Block