from typing import Callable
from swmtplanner.support.supers import SwmtBase

__all__ = ['setter_like', 'Viewer']

def setter_like[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """
    Marks a method as "setter-like" (i.e., will mutate
    attributes of the object). Prevents objects from being
    mutated in non-desired contexts.
    """
    ...

class Viewer[T](SwmtBase):
    """
    A base class for objects that "view" attributes on other
    objects. These are read-only properties whose values are
    derived from attributes of other objects.
    """
    def __init_subclass__(cls,
                          dunders: tuple[str, ...] = tuple(),
                          attrs: tuple[str, ...] = tuple(),
                          funcs: tuple[str, ...] = tuple(),
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None: ...
    def __init__(self, link: T, priv: dict[str] = {}, **kwargs) -> None: ...