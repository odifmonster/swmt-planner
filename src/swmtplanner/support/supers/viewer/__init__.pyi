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
            A list of read-only attributes (if any). These names
            will refer to properties without setters, and instances
            must have corresponding "private" attributes with a
            preceding '_'.
          priv:
            A list of additional attributes (if any) to be required
            for initialization that should not be publicly
            accessible. Instances must have corresponding "private"
            attributes with a preceding '_'.
        """
        ...
    def __init__(self, link: T, **kwargs) -> None:
        """
        Initialize a new Viewer object.

          link:
            The object to link the properties to.
          **kwargs:
            Every keyword will become an attribute of the instance,
            and the value will be used as the initial value. If any
            names provided to the initializer are not present as
            keywords (preceded by '_'), a ValueError is raised. If
            any keyword is the name of a read-only attribute, a
            ValueError is raised.
        """
        ...