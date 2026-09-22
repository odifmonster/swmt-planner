#!/usr/bin/env python

from datetime import datetime

from ...support import HasID


def _denier_class(denier: int) -> int:
    """The planner's denier classes (kept in step with
    `products.variants.denier_class`)."""
    if denier in (70, 75):
        return 75
    if denier in (40, 45):
        return 40
    return denier


class BeamSetDesc(HasID[str]):
    """A beam set as the planner describes it — the label string a greige
    style's `beam_cfg` names, e.g. `40D WHT 1172X4 S/L`."""

    def __init__(self, id):
        self._id = id

        parts = id.split()
        if parts[-1] == 'S/L':
            self._split_lease = True
            parts = parts[:-1]
        else:
            self._split_lease = False

        self._denier = int(parts[0].removesuffix('D'))
        ends_str, spools_str = parts[-1].split('X')
        self._ends = int(ends_str)
        self._spools = int(spools_str)
        self._yarn_desc = ' '.join(parts[1:-1])

    @property
    def id(self):
        return self._id

    @property
    def denier(self) -> int:
        return self._denier

    @property
    def ends(self) -> int:
        return self._ends

    @property
    def spools(self) -> int:
        return self._spools

    @property
    def split_lease(self) -> bool:
        return self._split_lease

    @property
    def yarn_desc(self) -> str:
        return self._yarn_desc

    @property
    def physical(self) -> 'BeamSetDesc':
        """The description of the *physical* set this label calls for: the
        split-lease marker stripped (split lease is how a set is threaded, not
        what it is) and the denier folded to its planner class. Two labels
        with the same `physical` are satisfied by the same stock — it is the
        inventory key."""
        return BeamSetDesc(
            f'{_denier_class(self._denier)}D {self._yarn_desc} '
            f'{self._ends}X{self._spools}'
        )

    def same_set(self, other: 'BeamSetDesc') -> bool:
        """True when the two describe the same physical beam set — everything
        but split lease, which is how the set is threaded, not what it is.
        Deniers compare by planner class (70/75 -> 75, 40/45 -> 40), so a
        label written with the plant's denier still matches."""
        return (_denier_class(self.denier) == _denier_class(other.denier)
                and self.yarn_desc == other.yarn_desc
                and self.ends == other.ends and self.spools == other.spools)


def _make_id_counter():
    ctr = 0
    def _next():
        nonlocal ctr
        ctr += 1
        return ctr
    return _next


_NEW_SET_ID = _make_id_counter()


class BeamSet(HasID[str]):
    """A physical beam set: the plant's set number, the yarn merge on it (or
    `None` for a set the planner invented), the vendor that supplied the
    yarn, the pounds on it, when it is available, and its planner
    description (never split-lease — that is decided when the set is
    threaded).

    Immutable. A set that comes off a machine is represented by a *new*
    `BeamSet` with the same id, merge and vendor (`returned`), so planning
    stays pure. Equality is by id, so the returned set matches the original
    in a stock list."""

    def __init__(self, set_no: str, merge: 'str | None', lbs: float,
                 desc: BeamSetDesc, avail_date: datetime, *,
                 vendor: 'str | None' = None,
                 denier: 'int | None' = None, luster: str = '', ytype: str = '',
                 known_merge: bool = False, assigned: bool = False):
        if desc.split_lease:
            raise ValueError(f'a physical beam set cannot be split lease: {desc.id!r}')
        self._id = set_no
        self._merge = merge
        self._vendor = vendor
        self._lbs = float(lbs)
        self._desc = desc
        self._avail_date = avail_date
        self._denier = desc.denier if denier is None else int(denier)
        self._luster = luster
        self._ytype = ytype
        self._known_merge = known_merge
        self._assigned = assigned

    @classmethod
    def new(cls, desc: BeamSetDesc, lbs: float, avail_date: datetime) -> 'BeamSet':
        """A set the planner invents because nothing suitable is in stock:
        ids `NEW000001`, `NEW000002`, … from a module counter, no merge,
        `known_merge` False. `desc` may carry `S/L`; the set takes its
        physical description."""
        return cls(f'NEW{_NEW_SET_ID():06}', None, lbs, desc.physical, avail_date)

    def returned(self, lbs: float, at: datetime) -> 'BeamSet':
        """This set as it comes back off a machine: same id and merge, `lbs`
        now the pounds left on it, available again from `at`."""
        return BeamSet(self._id, self._merge, lbs, self._desc, at,
                       vendor=self._vendor, denier=self._denier,
                       luster=self._luster, ytype=self._ytype,
                       known_merge=self._known_merge)
        # (a returned set is no longer assigned to anything)

    @property
    def id(self):
        return self._id

    @property
    def set_no(self) -> str:
        return self._id

    @property
    def merge(self) -> 'str | None':
        """The plant's merge code, or `None` for an invented set."""
        return self._merge

    @property
    def vendor(self) -> 'str | None':
        """The supplier the plant records for the yarn on this set (set
        numbers are the vendors' own numbering, so set number + vendor is
        how the floor identifies a set). `None` for an invented set or when
        no input named one."""
        return self._vendor

    def same_vendor(self, vendor: 'str | None') -> bool:
        """Whether a record naming `vendor` can be this set: True when either
        side names no vendor, else when they agree."""
        return self._vendor is None or vendor is None or self._vendor == vendor

    @property
    def lbs(self) -> float:
        return self._lbs

    @property
    def avail_date(self) -> datetime:
        """When the set can next be hung: the planner start for stock, a
        tape-out's end for a returned set."""
        return self._avail_date

    @property
    def desc(self) -> BeamSetDesc:
        return self._desc

    @property
    def denier(self) -> int:
        """The plant's denier (unfolded; `desc.denier` is the planner class)."""
        return self._denier

    @property
    def luster(self) -> str:
        return self._luster

    @property
    def ytype(self) -> str:
        return self._ytype

    @property
    def known_merge(self) -> bool:
        """Whether some variant of ours uses this merge — i.e. whether knitting
        from this set can be tied to a specific variant. Always False for an
        invented set."""
        return self._known_merge

    @property
    def is_new(self) -> bool:
        """An invented set (see `new`)."""
        return self._merge is None

    @property
    def assigned(self) -> bool:
        """Reserved by the plant for a specific machine and bar (the
        inventory export's `assigned` flag): not free stock, but the next set
        that bar will hang — see the machines' bar queues."""
        return self._assigned

    def fits(self, desc: BeamSetDesc) -> bool:
        """Whether this set can serve a style's beam-set requirement, split
        lease or not."""
        return self._desc.same_set(desc)

    def available_at(self, t: datetime) -> bool:
        return self._avail_date <= t
