from typing import Hashable
from swmtplanner.support import HasID, SwmtBase, Viewer

__all__ = ['Data', 'DataView']

class Data[T: Hashable](SwmtBase, HasID[T]):
    def __init_subclass__(cls, mut_in_group: bool,
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None: ...
    def __init__(self, prefix: str, id: T, view: DataView[T], **kwargs) -> None: ...
    def view(self) -> DataView[T]: ...

class DataView[T: Hashable](Viewer[Data[T]]):
    def __init_subclass__(cls, dunders: tuple[str, ...] = tuple(),
                          attrs: tuple[str, ...] = tuple(),
                          funcs: tuple[str, ...] = tuple(), 
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None: ...