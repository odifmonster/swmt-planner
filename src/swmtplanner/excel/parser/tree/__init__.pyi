from typing import NamedTuple, Literal
from io import TextIOBase
from swmtplanner.excel.parser.lexer import TokType

__all__ = ['Atom', 'KWArg', 'Info', 'Empty', 'InfoFile', 'parse']

class Atom(NamedTuple):
    kind: Literal[TokType.NAME, TokType.NUM, TokType.STRING, TokType.FILE]
    value: str

class KWArg(NamedTuple):
    name: str
    value: Atom | list[Atom]

class Info(NamedTuple):
    name: str
    kwargs: list[KWArg]

class Empty:
    ...

type InfoFile = list[Info]

def parse(buffer: TextIOBase) -> InfoFile: ...