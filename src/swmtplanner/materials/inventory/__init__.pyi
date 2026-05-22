from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from ...product import Fabric
from ..rawmat import GreigeRoll, RawMat


__all__ = ['DyeLot', 'in_range', 'GroupKey', 'InvGroup', 'Inventory']


@dataclass(frozen=True)
class DyeLot:
    """A grouping of compatible greige rolls assigned to produce a specific Fabric item.

    Frozen record: lots are constructed by the `GreigeInv` lot-factory
    methods (`get_dye_lot`, `get_dye_lots`) and are not modified
    afterward. The class itself performs no validation; the dye-cycle
    matching constraints are enforced by the factory methods.
    """
    fabric: Fabric
    rolls: tuple[GreigeRoll, ...]

    @property
    def avail_date(self) -> date | None:
        """Earliest date at which every roll in the lot is available.

        Equal to the latest non-`None` `avail_date` among `rolls`, with
        `None` (already in inventory) treated as immediately available.
        Returns `None` if every roll has `avail_date is None` (or if the
        lot has no rolls).
        """
        ...


def in_range[T](excl_lo: bool = False, excl_hi: bool = True) -> Callable[[tuple[T, T], T], bool]:
    """Creates a function that returns True iff a value is within a supplied range."""
    ...


@dataclass(frozen=True)
class GroupKey:
    op: Callable[[Any, Any], bool]
    value: Any

    def __call__(self, val: Any) -> bool: ...


class InvGroup[T: RawMat]:
    """Per-attribute index used by `Inventory`.

    Buckets `RawMat` instances by their value for `attr_name`, keeping
    the distinct values in `sorted_keys` in ascending order so range
    queries can use `bisect`. Owns the per-attribute
    mutation-detection: snapshots each item's attribute value at
    insertion and verifies it on subsequent operations. Concrete
    inventories may subclass to add per-bucket bookkeeping or
    construction-time behavior.
    """
    attr_name: str
    sorted_keys: list[Any]
    mapping: dict[Any, set[T]]
    snapshots: dict[str, Any]

    def __init__(self, attr_name: str) -> None: ...
    def add(self, item: T) -> None:
        """Add `item` to the bucket determined by `item.<attr_name>`,
        snapshotting that value for later mutation-detection and
        inserting the key into `sorted_keys` at the correct position
        if not already present."""
        ...
    def remove(self, item: T) -> None:
        """Remove `item` from the group. Raises `RuntimeError` if
        `item.<attr_name>` has been mutated since `add` was called.
        On success, drops the bucket and the key from `sorted_keys`
        if the bucket becomes empty."""
        ...
    def verify(self, item: T) -> None:
        """Raise `RuntimeError` if `item.<attr_name>` no longer
        matches the snapshot taken at `add` time. No-op if `item` is
        not currently in this group."""
        ...
    def get_group(self, group_key: GroupKey) -> set[T]:
        """Return the set of items whose value for `attr_name`
        satisfies the predicate represented by `group_key`. Each
        item that would join the result is verified first; a mutated
        item in a matched bucket raises `RuntimeError` instead of
        being returned."""
        ...


class Inventory[T: RawMat](ABC):
    """Abstract generic container indexing `RawMat` by ID and by key attributes.

    Maintains a flat `id -> item` map and one `InvGroup` per key
    attribute (declared at construction). Concrete subclasses must
    implement `new_group` to choose which `InvGroup` variant is used.
    """
    def __init__(self, key_attrs: Iterable[str], **kwargs: Any) -> None:
        """Build an Inventory.

        `key_attrs` lists the attribute names that will be available for
        grouped lookup. Per-attribute indices are constructed via
        `self.new_group(attr_name=<name>, **kwargs)`, so any kwargs
        supplied here are forwarded to `new_group`.
        """
        ...
    @abstractmethod
    def new_group(self, **kwargs: Any) -> InvGroup[T]:
        """Create a new `InvGroup` (or subclass) for one key attribute.

        Called once per `key_attrs` entry during `__init__`. The
        `Inventory` constructor injects `attr_name=<name>` into kwargs
        alongside any kwargs the caller supplied, so subclasses can
        dispatch on the attribute name and / or forward other kwargs
        to a custom `InvGroup` constructor.
        """
        ...
    def get(self, id_: str) -> T | None:
        """Return the item with the given ID, or `None` if absent.

        Runs the mutation-detection check before returning, raising if
        any key attribute on the item has changed since insertion.
        """
        ...
    def add(self, x: T) -> None:
        """Add `x` to the inventory.

        Raises `ValueError` on duplicate `id` or missing key attribute.
        Snapshots the key-attribute values for later
        mutation-detection.
        """
        ...
    def remove(self, id_: str) -> T:
        """Remove and return the item with the given ID.

        Raises `KeyError` if absent, or a runtime error if a key
        attribute was mutated since insertion (the mutation check runs
        before any state is touched).
        """
        ...
    def get_group(self, **kwargs: GroupKey | Any) -> set[T]:
        """Return the set of items satisfying every supplied predicate.

        Each keyword argument names a configured key attribute. Its
        value is either a `GroupKey` predicate or a non-`GroupKey`
        value `x` (shorthand for `GroupKey(operator.eq, x)`).
        Predicates are AND-combined. Raises `KeyError` if any keyword
        name is not a configured key attribute. Calling with no
        keyword arguments returns every item currently in the
        inventory.
        """
        ...
