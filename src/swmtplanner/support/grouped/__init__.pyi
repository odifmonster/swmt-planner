from .data import Data, DataView, match_props, repr_props
from .atom import Atom, AtomView

from typing import Hashable, Generator
from swmtplanner.support import SwmtBase, Viewer

__all__ = ['Data', 'DataView', 'match_props', 'repr_props', 'Atom', 'AtomView',
           'Grouped', 'GroupedView']

class Grouped[T: Hashable, U: Hashable](
    SwmtBase, priv=('prop_names','prop_vals','unbound','ids_map','subgrps','view')
    ):
    """
    A class for Grouped objects. These are mapping-like objects
    that support multi-indexing. Their contents must inherit
    from Data.
    """
    def __init__(self, *args: *tuple[str, ...], **kwargs) -> None:
        """
        Initialize a new Atom object.

          *args:
            The "unbound" attributes of the data this object will
            store. These cannot overlap with the keyword arguments.
            They will be used to organize the axes of this Grouped
            object, in the order they are listed.
          **kwargs:
            Every keyword must be an attribute on the data this
            object will store. These attributes will be "bound" to
            the provided corresponding values.
        """
        ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Generator[U]:
        """Generates the keys in this object."""
        ...
    def __contains__(self, key: U) -> bool:
        """Returns True iff this object contains the given key."""
        ...
    @property
    def depth(self) -> int:
        """The number of axes this object has."""
        ...
    @property
    def n_items(self) -> int:
        """The flat total number of items this object holds."""
        ...
    def get(self, id: T) -> DataView[T]:
        """
        Gets an item (view) from this object by its id. Raises a
        KeyError if 'id' does not point to one of the items.
        """
        ...
    def add(self, data: Data[T]) -> None:
        """
        Adds the given data to this object. Raises a ValueError if
        its properties do not match the ones passed to the
        initializer. Does nothing if the data is already present.
        """
        ...
    def remove(self, dview: DataView[T], remkey: bool = False) -> Data[T]:
        """
        Removes the data linked to the given view and returns it.
        Raises a RuntimeError if this object is empty. Raises a
        ValueError if 'dview' does not point to an item in this 
        object. When 'remkey' is True, the object will modify its
        internal grouping structure as necessary.
        """
        ...
    def view(self) -> GroupedView[T, U]:
        """Returns a live, read-only view of this object."""
        ...

class GroupedView[T: Hashable, U: Hashable](
    Viewer[Grouped[T, U]], dunders=('len','iter','contains'),
    attrs=('depth','n_items'), funcs=('get',)
    ):
    """
    A class for views of Grouped objects.
    """
    def __len__(self) -> int: ...
    def __iter__(self) -> Generator[U]:
        """Generates the keys in this object."""
        ...
    def __contains__(self, key: U) -> bool:
        """Returns True iff this object contains the given key."""
        ...
    @property
    def depth(self) -> int:
        """The number of axes this object has."""
        ...
    @property
    def n_items(self) -> int:
        """The flat total number of items this object holds."""
        ...
    def get(self, id: T) -> DataView[T]:
        """
        Gets an item (view) from this object by its id. Raises a
        KeyError if 'id' does not point to one of the items.
        """
        ...