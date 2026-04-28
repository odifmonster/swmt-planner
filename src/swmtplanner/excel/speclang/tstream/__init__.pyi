from typing import Generator, Any

from swmtplanner.excel import file
from . import tokens

__all__ = ['tokens', 'tokenize', 'TStream', 'Token']

def tokenize(f: file.File) -> Generator[tokens.Token, Any, None]:
    """Converts a File object into a Token generator."""
    ...

Token = tokens.Token

class TStream:
    """Reads a file as a stream of tokens."""
    def __init__(self, f: file.File) -> None: ...
    @property
    def has_ended(self) -> bool:
        """Whether the cursor is currently at the end of the stream."""
        ...
    @property
    def last_token(self) -> tokens.Token:
        """The last token processed from the file, regardless of where
        the current cursor position is."""
        ...
    def advance(self) -> tokens.Token:
        """Return the next token in the stream and advance the cursor's
        position by 1."""
        ...
    def backup(self, n: int) -> None:
        """Back the cursor up by n tokens."""
        ...