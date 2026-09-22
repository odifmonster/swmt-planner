from datetime import datetime

from swmtplanner.support import HasID

__all__ = ['BeamSetDesc', 'BeamSet']

class BeamSetDesc(HasID[str]):
    """A beam set as the planner describes it — the label string a greige
    style's `beam_cfg` names, e.g. `40D WHT 1172X4 S/L`."""
    def __init__(self, id: str) -> None:
        """Initialize from the label, which the constructor parses for the
        denier, yarn description, construction and split-lease marker."""
        ...
    @property
    def denier(self) -> int: ...
    @property
    def ends(self) -> int:
        """Number of yarn ends on each beam."""
        ...
    @property
    def spools(self) -> int:
        """Number of beams in this set."""
        ...
    @property
    def split_lease(self) -> bool: ...
    @property
    def yarn_desc(self) -> str:
        """Additional descriptive information for the yarn."""
        ...
    @property
    def physical(self) -> BeamSetDesc:
        """The description of the physical set this label calls for: `S/L`
        stripped and the denier folded to its planner class. The inventory
        key."""
        ...
    def same_set(self, other: BeamSetDesc) -> bool:
        """True when the two describe the same physical beam set — everything
        but split lease, which is how the set is threaded, not what it is."""
        ...


class BeamSet(HasID[str]):
    """A physical beam set: the plant's set number, the yarn merge on it (or
    `None` for a set the planner invented), the vendor that supplied the
    yarn, the pounds on it, when it is available, and its planner
    description (never split-lease). Immutable; equality is by id."""
    def __init__(
        self, set_no: str, merge: str | None, lbs: float, desc: BeamSetDesc,
        avail_date: datetime, *, vendor: str | None = ...,
        denier: int | None = ..., luster: str = ...,
        ytype: str = ..., known_merge: bool = ..., assigned: bool = ...,
    ) -> None: ...
    @classmethod
    def new(cls, desc: BeamSetDesc, lbs: float, avail_date: datetime) -> BeamSet:
        """A set the planner invents: ids `NEW000001`, …, no merge."""
        ...
    def returned(self, lbs: float, at: datetime) -> BeamSet:
        """This set as it comes back off a machine: same id and merge, `lbs`
        now the pounds left on it, available again from `at`."""
        ...
    @property
    def set_no(self) -> str: ...
    @property
    def merge(self) -> str | None: ...
    @property
    def vendor(self) -> str | None:
        """The supplier of the yarn on this set; `None` for an invented set
        or when no input named one."""
        ...
    def same_vendor(self, vendor: str | None) -> bool:
        """Whether a record naming `vendor` can be this set: True when either
        side names no vendor, else when they agree."""
        ...
    @property
    def lbs(self) -> float: ...
    @property
    def avail_date(self) -> datetime: ...
    @property
    def desc(self) -> BeamSetDesc: ...
    @property
    def denier(self) -> int:
        """The plant's denier (unfolded; `desc.denier` is the planner class)."""
        ...
    @property
    def luster(self) -> str: ...
    @property
    def ytype(self) -> str: ...
    @property
    def known_merge(self) -> bool:
        """Whether some variant of ours uses this merge. False for an
        invented set."""
        ...
    @property
    def is_new(self) -> bool:
        """An invented set (see `new`)."""
        ...
    @property
    def assigned(self) -> bool:
        """Reserved for a specific machine and bar (export flag): not free
        stock; the next set that bar hangs."""
        ...
    def fits(self, desc: BeamSetDesc) -> bool:
        """Whether this set can serve a style's beam-set requirement, split
        lease or not."""
        ...
    def available_at(self, t: datetime) -> bool: ...
