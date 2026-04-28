from typing import NamedTuple

__all__ = ['EOF', 'Pos', 'File']

EOF: str = ...

class Pos(NamedTuple):
    line: int
    col: int

class File:
    """A custom class for handling file reading with convenience methods
    for backing up and outputting the current file position.
    """
    def __init__(self, path: str) -> None:
        """Initialize a new File object from a path to an existing file."""
        ...
    @property
    def has_ended(self) -> bool:
        """Indicates whether the current position is after the end of the file."""
        ...
    def read(self) -> str:
        """Read and return the next character in the file.

        Returns:
            A single character or the EOF constant.
        
        Raises:
            EOFError: Raises an exception if read() is called after the end of the file.
        """
        ...
    def backup(self, n: int) -> None:
        """Backup n characters in the file, enabling those characters to be read
        again. Resets has_ended when n > 0, does nothing when n = 0.

        Args:
            n: The number of characters to backup by. Must be non-negative.
        
        Returns:
            None
        
        Raises:
            ValueError: Raises an exception if n < 0.
        """
        ...
    def tell(self) -> Pos:
        """Return the current read position as a 1-indexed (line, col) Pos.
        The position reflects where the next call to read() will read from.
        """
        ...