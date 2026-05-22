#!/usr/bin/env python

import bisect
import operator
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from ..rawmat import RawMat
from .groupkey import GroupKey

if TYPE_CHECKING:
    from collections.abc import Iterable


class InvGroup[T: RawMat]:
    """Per-attribute index used by `Inventory`.

    Buckets `RawMat` instances by their value for a single key
    attribute (`attr_name`), keeping the distinct values in
    `sorted_keys` in ascending order so range queries can use
    `bisect`. The group also snapshots each item's attribute value at
    insertion time and is responsible for detecting subsequent
    mutations of that attribute on items it holds.

    Concrete inventories may subclass this to add per-bucket
    bookkeeping or construction-time behavior.
    """

    def __init__(self, attr_name: str) -> None:
        self.attr_name = attr_name
        self.sorted_keys: list[Any] = []
        self.mapping: dict[Any, set[T]] = {}
        self.snapshots: dict[str, Any] = {}

    def add(self, item: T) -> None:
        """Add `item` to the bucket determined by `item.<attr_name>`.

        Reads the live attribute value off the item, snapshots it for
        later mutation-detection, and inserts the item into the
        corresponding bucket (creating the bucket and inserting the
        key into `sorted_keys` at the position dictated by ascending
        order if it's not already present).
        """
        val = getattr(item, self.attr_name)
        if val not in self.mapping:
            self.mapping[val] = set()
            bisect.insort(self.sorted_keys, val)
        self.mapping[val].add(item)
        self.snapshots[item.id] = val

    def remove(self, item: T) -> None:
        """Remove `item` from the group.

        Verifies first that `item.<attr_name>` still equals the
        snapshot taken at `add` time; raises `RuntimeError` if it has
        been mutated. On success, removes the item from its bucket
        (dropping the bucket and the key from `sorted_keys` if the
        bucket becomes empty) and drops the snapshot.
        """
        self.verify(item)
        snap = self.snapshots[item.id]
        bucket = self.mapping[snap]
        bucket.discard(item)
        if not bucket:
            del self.mapping[snap]
            self.sorted_keys.remove(snap)
        del self.snapshots[item.id]

    def verify(self, item: T) -> None:
        """Check that `item.<attr_name>` still matches the snapshot.

        Raises `RuntimeError` if the live attribute value differs from
        the snapshot taken when `item` was added. No-op if `item` is
        not currently in this group.
        """
        snap = self.snapshots.get(item.id)
        if snap is None:
            return
        live = getattr(item, self.attr_name)
        if live != snap:
            raise RuntimeError(
                f'inventory item {item.id!r}: key attribute '
                f'{self.attr_name!r} was mutated after insertion '
                f'(snapshot={snap!r}, current={live!r})'
            )

    def get_group(self, group_key: GroupKey) -> set[T]:
        """Return the set of items whose value for `attr_name` satisfies
        the predicate represented by `group_key`.

        Iterates `sorted_keys` and unions the buckets whose key
        satisfies `group_key(...)`. Walks the keys (not the items) so
        the membership test is run once per distinct value rather than
        once per item.

        Each item that would join the result set is passed through
        `self.verify(...)` first, so a mutated item in a matched
        bucket raises `RuntimeError` rather than being returned with
        stale data.
        """
        result: set[T] = set()
        for val in self.sorted_keys:
            if group_key(val):
                for item in self.mapping[val]:
                    self.verify(item)
                    result.add(item)
        return result


class Inventory[T: RawMat](ABC):
    """Abstract generic container for raw-goods inventories.

    Indexes `RawMat` instances by their physical-inventory ID (a flat
    `_items` map) and by a fixed set of attribute keys declared at
    construction (one `InvGroup` per key attribute, stored in
    `_groups`). Per-attribute mutation detection is delegated to the
    individual `InvGroup`s; this class orchestrates calls across them.

    Concrete subclasses must implement `new_group` to choose which
    `InvGroup` variant (and with what construction-time behavior) is
    used for each per-attribute index.
    """

    def __init__(self, key_attrs: 'Iterable[str]', **kwargs: Any) -> None:
        self._key_attrs: tuple[str, ...] = tuple(key_attrs)
        self._items: dict[str, T] = {}
        self._groups: dict[str, InvGroup[T]] = {
            attr: self.new_group(attr_name=attr, **kwargs)
            for attr in self._key_attrs
        }

    @abstractmethod
    def new_group(self, **kwargs: Any) -> InvGroup[T]:
        """Create a new `InvGroup` (or subclass) for one key attribute.

        Called once per `key_attrs` entry during `__init__`. The
        `Inventory` constructor injects ``attr_name=<name>`` into the
        kwargs in addition to any kwargs the caller passed to
        `Inventory.__init__`, so subclasses can dispatch on the
        attribute name or pass it through to the constructed group.
        """
        raise NotImplementedError()

    def get(self, id_: str) -> T | None:
        """Return the item with the given ID, or `None` if absent.

        Asks every group to verify the item before returning, so a
        mutation of any key attribute since insertion raises rather
        than returning a stale view.
        """
        item = self._items.get(id_)
        if item is None:
            return None
        for group in self._groups.values():
            group.verify(item)
        return item

    def add(self, x: T) -> None:
        """Add `x` to the inventory.

        Raises `ValueError` if an item with the same `id` is already
        present, or if `x` is missing any of the configured key
        attributes. Each group snapshots `x`'s value for its own
        attribute at this point for later mutation detection.
        """
        if x.id in self._items:
            raise ValueError(
                f'item with id {x.id!r} is already in the inventory'
            )
        for attr in self._key_attrs:
            if not hasattr(x, attr):
                raise ValueError(
                    f'item {x.id!r} is missing key attribute {attr!r}'
                )
        for group in self._groups.values():
            group.add(x)
        self._items[x.id] = x

    def remove(self, id_: str) -> T:
        """Remove and return the item with the given ID.

        Raises `KeyError` if no item with that ID is present. Asks
        every group to verify the item before any state is modified;
        if any key attribute was mutated since insertion the
        offending group raises and the inventory is left untouched.
        """
        if id_ not in self._items:
            raise KeyError(id_)
        item = self._items[id_]
        # Verify pass: raise before touching state if any attribute mutated.
        for group in self._groups.values():
            group.verify(item)
        # Mutation pass: every verify already succeeded.
        for group in self._groups.values():
            group.remove(item)
        del self._items[id_]
        return item

    def get_group(self, **kwargs: GroupKey | Any) -> set[T]:
        """Return the set of items satisfying every supplied predicate.

        Each keyword argument names a key attribute (one of the
        configured `key_attrs`). The value is either a `GroupKey`
        describing the predicate to apply to that attribute, or any
        non-`GroupKey` value `x`, in which case it is interpreted as
        the shorthand `GroupKey(operator.eq, x)` — i.e., "attribute
        equals `x`". Predicates across keyword arguments are combined
        with logical AND.

        Raises `KeyError` if any keyword name is not a configured key
        attribute (the inventory has no index for it). Calling with no
        keyword arguments returns every item currently in the
        inventory.
        """
        if not kwargs:
            return set(self._items.values())
        for attr in kwargs:
            if attr not in self._groups:
                raise KeyError(attr)
        per_attr_sets = [
            self._groups[attr].get_group(
                gk if isinstance(gk, GroupKey)
                else GroupKey(operator.eq, gk)
            )
            for attr, gk in kwargs.items()
        ]
        return set.intersection(*per_attr_sets)
