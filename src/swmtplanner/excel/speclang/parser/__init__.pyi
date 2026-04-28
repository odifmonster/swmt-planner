from . import trees

from swmtplanner.excel.speclang.tstream import TStream

__all__ = ['trees', 'parse']

def parse(tstream: TStream) -> list[trees.Stmt]: ...