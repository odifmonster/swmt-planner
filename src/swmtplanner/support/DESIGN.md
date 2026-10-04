# `swmtplanner.support`

Miscellaneous standalone helper functions and classes with no dependence on
planning domain concepts.

## Overview

`support` holds the small, general-purpose building blocks the rest of the
package is built on. Nothing here knows about yarn, fabric, machines, or
demand; the objects are reusable utilities that happen to be needed by the
planner. Every other module in the package may depend on `support`, and
`support` depends on nothing else in the package.

`support` currently introduces the following capabilities:

- **Identity by id** – a lightweight base class, `HasID[T]`, for objects
  that are identified by an `id` and should compare equal whenever their
  ids are equal, even if they were constructed separately.

Further helpers will be added as later designs call for them. A `WorkCal`
class for date math against a work calendar is anticipated but not yet
specified.

## Core objects

```python
T = TypeVar("T")

class HasID(Generic[T]):
    id: T

    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
```

## `HasID`

`HasID[T]` is a lightweight generic base class for objects identified by an
`id` of type `T`. Its purpose is to let the same logical object be
reconstructed many times, from different sources, and still be recognized as
the same object. The motivating cases are `core.products` classes such as
`Yarn` and `BeamSetDesc`, which are translated from many distinct database
variants into one master item: every variant that resolves to the same id
must produce an object equal to every other.

A subclass declares what its `id` is, either as a dataclass field or as a
property computed from other fields. `HasID` provides nothing else.

| Member                                  | Description |
|-----------------------------------------|-------------|
| `id: T`                                 | The identifying value. Declared by the subclass. |
| `__eq__(self, other: object) -> bool`   | `True` if and only if `other` is an instance of the same class as `self` and `other.id == self.id`. |
| `__hash__(self) -> int`                 | `hash(self.id)`, so that equal objects hash equally and instances can be used as dict keys and set members. |

Equality requires the same class, not merely any `HasID` with an equal id,
so that two unrelated kinds of object that happen to share an id value (for
example a `str` id used by two different classes) are never considered
equal.

**Use with dataclasses.** Subclasses that are dataclasses must be declared
with `eq=False` (e.g. `@dataclass(frozen=True, eq=False)`) so that the
dataclass machinery does not generate its own field-wise `__eq__` and
`__hash__` and override the id-based ones inherited from `HasID`.
