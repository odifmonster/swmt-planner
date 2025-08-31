from typing import NamedTuple
from io import TextIOBase

__all__ = ['FilePos', 'CharStream']

class FilePos(NamedTuple):
    line: int
    line_offset: int
    file_offset: int

class CharStream:
    def __init__(self, buffer: TextIOBase) -> None: ...
    def read(self) -> str: ...
    def backup(self) -> None: ...
    def get_pos(self) -> FilePos: ...