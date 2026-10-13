__all__ = ['HANDLING_HOURS', 'BEAM_LBS', 'OLD_EFFICIENCY', 'NEW_EFFICIENCY', 'enable', 'enabled',
           'handling_hours', 'beam_lbs', 'efficiency']

HANDLING_HOURS: float
"""Work-hours for a doff / hang / thread in planning mode (0.01)."""
BEAM_LBS: float
"""Lbs every beam set starts with in planning mode (1,000,000)."""
OLD_EFFICIENCY: float
"""Running efficiency on old machine rates in planning mode (0.75)."""
NEW_EFFICIENCY: float
"""Running efficiency on new machine rates in planning mode (0.7)."""


def enable(on: bool = ...) -> None:
    """Turn planning mode on (or off). Process-wide; set before inputs load."""
    ...
def enabled() -> bool: ...
def handling_hours(actual: float) -> float:
    """`actual` normally, `HANDLING_HOURS` in planning mode."""
    ...
def beam_lbs(actual: float) -> float:
    """`actual` normally, `BEAM_LBS` in planning mode."""
    ...
def efficiency(actual: float, mtype: str) -> float:
    """`actual` normally, `<MTYPE>_EFFICIENCY` in planning mode."""
    ...
