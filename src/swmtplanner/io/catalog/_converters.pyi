from typing import Any

def _strip(v: Any) -> str:
    """Return ``str(v)`` with surrounding whitespace removed. Used on
    text columns, whose blanks are read as ``""`` first so this never
    sees a null."""
    ...

def _is_x(v: Any) -> bool:
    """Whether a flag cell holds an ``X`` (case-insensitive, after
    stripping). A blank cell, read as ``""``, is ``False``."""
    ...

def _is_active(v: Any) -> bool:
    """Whether a status cell marks an active row: anything but ``I``
    (case-insensitive, after stripping), so a blank status counts as
    active."""
    ...
