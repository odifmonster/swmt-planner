from typing import Hashable
from swmtplanner.support import HasID, SwmtBase, Viewer

__all__ = ['Data', 'DataView', 'match_props', 'repr_props']

def match_props[T: Hashable](data: Data[T], prop_names: tuple[str, ...],
                             prop_vals: tuple) -> bool: ...

def repr_props(prop_names: tuple[str, ...], prop_vals: tuple,
               indent: str = '  ') -> str: ...

class Data[T: Hashable](SwmtBase, HasID[T]):
    """
    A base class for objects that can be added to Grouped
    objects. Should not be directly instantiated.
    """
    def __init_subclass__(cls, mut_in_group: bool,
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None:
        """
        Initialize a new Data subclass.

          mut_in_group:
            Whether or not objects of this type should be mutable
            while in a group.
          read_only:
            Names to be passed to the SwmtBase subclass initializer.
            'prefix' and 'id' are added automatically.
          priv:
            Names to be passed to the SwmtBase subclass initializer.
            'view' and 'in_group' are added automatically.
        """
        ...
    def __init__(self, prefix: str, id: T, view: DataView[T], **kwargs) -> None:
        """
        Initialize a new Data object.

          prefix:
            The name that distinguishes this object from other Data
            subclasses.
          id:
            The unique, hashable id of this object.
          view:
            The view object attached to this Data.
          **kwargs:
            Additional keyword arguments to pass to the SwmtBase
            initializer.
        """
        ...
    def view(self) -> DataView[T]:
        """Returns a live, read-only view of this object."""
        ...

class DataView[T: Hashable](Viewer[Data[T]]):
    """
    A base class for views of Data objects. Should not be
    directly instantiated.
    """
    def __init_subclass__(cls, dunders: tuple[str, ...] = tuple(),
                          attrs: tuple[str, ...] = tuple(),
                          funcs: tuple[str, ...] = tuple(), 
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None:
        """
        Initialize a new DataView subclass.

          dunders:
            Dunder names to be passed to the Viewer subclass
            initializer. 'hash', 'eq', and 'repr' are added
            automatically.
          attrs:
            Attribute names to be passed to the Viewer subclass
            initializer. 'prefix' and 'id' are added automatically.
          funcs:
            Function names to be passed to the Viewer subclass
            initializer.
          read_only:
            Names to be passed to the Viewer subclass initializer.
          priv:
            Names to be passed to the Viewer subclass initializer.
        """
        ...