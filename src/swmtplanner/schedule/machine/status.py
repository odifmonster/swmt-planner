#!/usr/bin/env python

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, TYPE_CHECKING

from swmtplanner.schedule.activity import (
    Activity, Knit, Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle, BEAM_FLOOR_LBS,
)

if TYPE_CHECKING:
    from swmtplanner.products import Greige, BeamSet

Bar = Literal['top', 'btm']


@dataclass(frozen=True)
class _BarState:
    """Per-bar slice of a `Status`: the mounted beam, its remaining lbs, and
    whether the set is threaded (routed) and ready to knit. Internal to
    `Status` — read it through the bar accessors."""
    beam: 'BeamSet | None'
    lbs_remaining: float
    threaded: bool


@dataclass(frozen=True)
class Status:
    """Snapshot of a machine's state at a moment in time. Derived from
    `Machine.initial_status` plus the machine's activity sequence; never
    mutated directly.

    Per-bar values are read through the `beam(bar)`, `lbs_remaining(bar)`, and
    `threaded(bar)` accessors (`bar` is `'top'` or `'btm'`) rather than
    separate top_*/btm_* fields; the underlying per-bar state (`_bars`) is
    private.

    `current_item` is non-nullable — a machine is always programmed to
    produce *something*. `beam(bar)` can be `None` after a `TapeOut`/`Waste`,
    before the matching re-thread. A beam swap moves a bar through threaded ->
    removed -> hung (loaded, not threaded) -> threaded; the `apply_activity`
    guards keep those steps in order.

    `is_idle` reports whether an activity is in progress at `as_of`. It is
    informational only — the planner does not consult it when deciding on
    changeovers, since yarn stays threaded across idle gaps."""
    as_of: datetime
    _bars: 'dict[str, _BarState]'
    current_item: 'Greige'
    is_idle: bool

    # ----- construction -------------------------------------------------

    @classmethod
    def create(
        cls, *, as_of: datetime, current_item: 'Greige', is_idle: bool,
        top_beam: 'BeamSet | None', top_lbs_remaining: float, top_threaded: bool,
        btm_beam: 'BeamSet | None', btm_lbs_remaining: float, btm_threaded: bool,
    ) -> 'Status':
        """Build a `Status` from per-bar primitives, without callers having to
        know the private per-bar storage. The accessors (`beam`, etc.) are the
        read API; this is the matching write/construct API."""
        return cls(
            as_of=as_of,
            _bars={
                'top': _BarState(top_beam, top_lbs_remaining, top_threaded),
                'btm': _BarState(btm_beam, btm_lbs_remaining, btm_threaded),
            },
            current_item=current_item, is_idle=is_idle,
        )

    # ----- per-bar accessors --------------------------------------------

    def beam(self, bar: Bar) -> 'BeamSet | None':
        """Mounted beam SKU on `bar` (None after a remove, before re-thread)."""
        return self._bars[bar].beam

    def lbs_remaining(self, bar: Bar) -> float:
        """Yarn remaining on `bar`'s beam."""
        return self._bars[bar].lbs_remaining

    def threaded(self, bar: Bar) -> bool:
        """Whether `bar`'s set is threaded (routed) and ready to knit."""
        return self._bars[bar].threaded

    @property
    def current_family(self) -> str:
        """Family of `current_item`. Derived rather than stored so the record
        cannot be constructed in an inconsistent state where `current_family`
        contradicts `current_item.family`."""
        return self.current_item.family

    # ----- guard predicates ---------------------------------------------

    def _removed(self, bar: Bar) -> bool:
        """A bar is 'removed' (old set gone or spent, ready to hang) when its
        beam has been taken off (`beam(bar) is None`, via TapeOut/Waste) or
        knit down to the floor (`lbs_remaining(bar) <= BEAM_FLOOR_LBS`)."""
        return self.beam(bar) is None or self.lbs_remaining(bar) <= BEAM_FLOOR_LBS

    def _hung(self, bar: Bar) -> bool:
        """A bar is 'hung' (a fresh set loaded but not yet threaded) when it is
        not removed and not threaded — exactly the post-`Hanging` state."""
        return (not self._removed(bar)) and (not self.threaded(bar))

    # ----- evolution ----------------------------------------------------

    def _evolve(
        self, as_of: datetime, *,
        current_item: 'Greige | None' = None, is_idle: bool = True,
        top: 'dict | None' = None, btm: 'dict | None' = None,
    ) -> 'Status':
        """Build the next Status at `as_of`. `top` / `btm`, when given, are
        dicts of `_BarState` field overrides for that bar (an omitted bar
        carries over unchanged). Pure — `self` is untouched."""
        bars = dict(self._bars)
        if top is not None:
            bars['top'] = replace(self._bars['top'], **top)
        if btm is not None:
            bars['btm'] = replace(self._bars['btm'], **btm)
        return Status(
            as_of=as_of, _bars=bars, is_idle=is_idle,
            current_item=(self.current_item if current_item is None
                          else current_item),
        )

    def apply_activity(self, activity: Activity) -> 'Status':
        """Return the Status that results from completing `activity` against
        `self`. Pure: `self` is not mutated. The returned status's `as_of`
        is `activity.end` and `is_idle` is True (the activity just finished;
        nothing is in progress at exactly `activity.end`).

        Beam-swap activities are guarded to keep the remove -> hang -> thread
        sequence in order (see "Beam-swap sequencing" in DESIGN.md): a
        `Hanging` onto a bar that still holds a usable set, or a `Threading`
        of a bar that hasn't been hung, raises `ValueError`."""
        if isinstance(activity, Knit):
            # Continuous run: consumes yarn from each bar in proportion to the
            # item's pcts and sets current_item. Beam/threaded state unchanged.
            cfg = activity.item.configuration
            return self._evolve(
                activity.end, current_item=activity.item,
                top={'lbs_remaining':
                     self.lbs_remaining('top') - activity.lbs * cfg.top_pct},
                btm={'lbs_remaining':
                     self.lbs_remaining('btm') - activity.lbs * cfg.btm_pct},
            )
        if isinstance(activity, Waste):
            # Discards a beam's usable residue unknit, emptying the named bar;
            # current_item unchanged. A paired re-thread refills it.
            return self._evolve(activity.end, **{
                activity.bar: {'beam': None, 'lbs_remaining': 0.0,
                               'threaded': False},
            })
        if isinstance(activity, Doff):
            # Takes one completed roll off the machine: machine time only.
            return self._evolve(activity.end)
        if isinstance(activity, TapeOut):
            # Removes the set on the named bar(s).
            gone = {'beam': None, 'lbs_remaining': 0.0, 'threaded': False}
            return self._evolve(
                activity.end,
                top=gone if activity.bars in ('top', 'both') else None,
                btm=gone if activity.bars in ('btm', 'both') else None,
            )
        if isinstance(activity, Hanging):
            # Loads a fresh set onto the named bar(s): sets beam + lbs and
            # leaves the bar un-threaded. Requires the bar already removed.
            top = btm = None
            if activity.bars in ('top', 'both'):
                if not self._removed('top'):
                    raise ValueError(
                        'cannot hang top: it still holds a usable set — '
                        'remove the old set first'
                    )
                top = {'beam': activity.top_beam,
                       'lbs_remaining': activity.top_lbs, 'threaded': False}
            if activity.bars in ('btm', 'both'):
                if not self._removed('btm'):
                    raise ValueError(
                        'cannot hang btm: it still holds a usable set — '
                        'remove the old set first'
                    )
                btm = {'beam': activity.btm_beam,
                       'lbs_remaining': activity.btm_lbs, 'threaded': False}
            return self._evolve(activity.end, top=top, btm=btm)
        if isinstance(activity, Threading):
            # Routes the loaded yarn: flips the named bar(s) to threaded and
            # nothing else. Requires the bar already hung (loaded, unthreaded).
            top = btm = None
            if activity.bars in ('top', 'both'):
                if not self._hung('top'):
                    raise ValueError(
                        'cannot thread top: it is not hung — hang a fresh '
                        'set first'
                    )
                top = {'threaded': True}
            if activity.bars in ('btm', 'both'):
                if not self._hung('btm'):
                    raise ValueError(
                        'cannot thread btm: it is not hung — hang a fresh '
                        'set first'
                    )
                btm = {'threaded': True}
            return self._evolve(activity.end, top=top, btm=btm)
        if isinstance(activity, (StyleChange, RunnerChange, PatternChange)):
            # Changeover: switches the item being run. No yarn, beam, or
            # threaded change — the three types differ only in duration/cost.
            return self._evolve(activity.end, current_item=activity.to_item)
        if isinstance(activity, Idle):
            # Beams, lbs, current_item, threaded all unchanged; advance as_of.
            return self._evolve(activity.end)
        raise TypeError(f'unknown activity type: {type(activity).__name__}')
