from ..parser.trees import Stmt

__all__ = ['interpret']

def interpret(stmts: list[Stmt]) -> dict: ...