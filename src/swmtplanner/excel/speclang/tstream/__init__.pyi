from typing import Generator, Any

from swmtplanner.excel import file
from . import tokens

__all__ = ['tokens', 'tokenize']

def tokenize(f: file.File) -> Generator[tokens.Token, Any, None]:
    """Converts a File object into a Token generator."""
    ...