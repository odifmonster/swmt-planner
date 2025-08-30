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
                          priv: tuple[str, ...] = tuple()) -> None:
        """
        Initialize a new Viewer subclass.

          dunders:
            The dunder functions (without leading and trailing '_')
            to copy from the linked object.
          attrs:
            The attributes to view on the linked object. These will
            be live and read-only.
          funcs:
            The functions to copy from the linked object.
          read_only:
            Names to be passed to the SwmtBase subclass initializer.
          priv:
            Names to be passed to the SwmtBase subclass initializer.
            'link' is added automatically.
        """
        ...
    def __init__(self, link: T, **kwargs) -> None:
        """
        Initialize a new Viewer object.

          link:
            The object to link the properties to.
          **kwargs:
            Additional keyword arguments to pass to the SwmtBase
            initializer.
        """
        ...