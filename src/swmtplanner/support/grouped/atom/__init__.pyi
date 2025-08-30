from typing import Hashable, Generator
from swmtplanner.support import SwmtBase, Viewer
from swmtplanner.support.grouped import Data, DataView

class Atom[T: Hashable](SwmtBase, priv=('prop_names','prop_vals','data','view')):
    """
    A class for Atom objects. These are Grouped-like containers
    for individual Data objects.
    """
    def __init__(self, **kwargs) -> None:
        """
        Initialize a new Atom object.

          **kwargs:
            Every keyword must be an attribute on the object this
            Atom will store. The value is the required value of the
            attribute. If 'id' is not a keyword, a ValueError is
            raised.
        """
        ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Generator[tuple[()]]:
        """Generates the keys in this object."""
        ...
    def __contains__(self, key: tuple[()]) -> bool:
        """Returns True iff this object contains the given key."""
        ...
    def __getitem__(self, key: tuple[()]) -> AtomView[T]: ...
    @property
    def depth(self) -> int:
        """The number of axes this object has."""
        ...
    @property
    def n_items(self) -> int:
        """The flat total number of items this object holds."""
        ...
    @property
    def data(self) -> DataView[T] | None:
        """A view of the data stored in this Atom."""
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
    def iterkeys(self) -> Generator[tuple[()]]:
        """
        Generates the full-length keys of this object. Each key
        corresponds to an individual item.
        """
        ...
    def itervalues(self) -> Generator[DataView[T]]:
        """Generates the individual items in this object."""
        ...
    def view(self) -> AtomView[T]:
        """Returns a live, read-only view of this object."""
        ...

class AtomView[T: Hashable](Viewer[Atom[T]],
                            dunders=('len','iter','contains','getitem','repr'),
                            attrs=('depth','n_items','data'),
                            funcs=('get','iterkeys','itervalues')):
    """
    A class for views of Atom objects.
    """
    def __len__(self) -> int: ...
    def __iter__(self) -> Generator[tuple[()]]:
        """Generates the keys in this object."""
        ...
    def __contains__(self, key: tuple[()]) -> bool:
        """Returns True iff this object contains the given key."""
        ...
    def __getitem__(self, key: tuple[()]) -> 'AtomView[T]': ...
    @property
    def depth(self) -> int:
        """The number of axes this object has."""
        ...
    @property
    def n_items(self) -> int:
        """The flat total number of items this object holds."""
        ...
    @property
    def data(self) -> DataView[T] | None:
        """A view of the data stored in this Atom."""
        ...
    def get(self, id: T) -> DataView[T]:
        """
        Gets an item (view) from this object by its id. Raises a
        KeyError if 'id' does not point to one of the items.
        """
        ...
    def iterkeys(self) -> Generator[tuple[()]]:
        """
        Generates the full-length keys of this object. Each key
        corresponds to an individual item.
        """
        ...
    def itervalues(self) -> Generator[DataView[T]]:
        """Generates the individual items in this object."""
        ...