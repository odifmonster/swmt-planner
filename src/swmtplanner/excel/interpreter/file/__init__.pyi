from typing import NamedTuple
from io import TextIOBase

__all__ = ['FilePos', 'CharStream']

class FilePos(NamedTuple):
    line: int
    column: int
    file_offset: int

class CharStream:
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
    def get_pos(self) -> FilePos:
        """Get the current position in the file."""
        ...