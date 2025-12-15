from . import trees

from swmtplanner.excel.engine.tokenized import Tokenized

__all__ = ['trees', 'parse']

def parse(tstream: Tokenized) -> list[trees.Stmt]: ...