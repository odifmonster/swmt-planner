from typing import NamedTuple
from io import TextIOBase

__all__ = ['Pos', 'File']

class Pos(NamedTuple):
    line: int
    column: int
    file_offset: int

class File:
    """
    A wrapper class for file buffers that tracks current line
    and column numbers. Moves one character at a time.
    """
    def __init__(self, buffer: TextIOBase) -> None:
        """Initialize a new CharStream using a file buffer."""
        ...
    def read(self) -> str:
        """
        Read and return one character from the stream. Returns an
        empty string if the buffer has reached the end of the
        stream.
        """
        ...
    def backup(self) -> None:
        """Back up by one character."""
        ...
    def tell(self) -> Pos:
        """Get the current position in the file."""
        ...