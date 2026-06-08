#!/usr/bin/env python

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.schedule.activity import (
    Activity, Knit, Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle, BEAM_FLOOR_LBS,
)

if TYPE_CHECKING:
    from swmtplanner.products import Greige, BeamSet


def _removed(beam: 'BeamSet | None', lbs: float) -> bool:
    """A bar is 'removed' (old set gone or spent, ready to hang) when its beam
    has been taken off (`beam is None`, via TapeOut/Waste) or it's been knit
    down to the floor (`lbs <= BEAM_FLOOR_LBS`, a run-out)."""
    return beam is None or lbs <= BEAM_FLOOR_LBS


def _hung(beam: 'BeamSet | None', lbs: float, threaded: bool) -> bool:
    """A bar is 'hung' (a fresh set is loaded but not yet threaded) when it is
    not removed and not threaded — exactly the post-`Hanging` state."""
    return (not _removed(beam, lbs)) and (not threaded)


@dataclass(frozen=True)
class Status:
    """Snapshot of a machine's state at a moment in time. Derived from
    `Machine.initial_status` plus the machine's activity sequence; never
    mutated directly.

    `current_item` is non-nullable — a machine is always programmed to
    produce *something*; changing items only ever swaps that program, never
    clears it. `top_beam` / `btm_beam` can be `None` after a `TapeOut`/`Waste`
    before the matching re-thread.

    `top_threaded` / `btm_threaded` report whether each bar's loaded set has
    its yarn routed and is ready to knit. A beam swap moves a bar through
    threaded -> removed -> hung (loaded, not threaded) -> threaded; see
    `apply_activity` for the guard rails that keep those steps in order.

    `is_idle` reports whether an activity is in progress at `as_of`. It is
    informational only — the planner does not consult it when deciding on
    changeovers, since yarn stays threaded across idle gaps."""
    as_of: datetime
    top_beam: 'BeamSet | None'
    btm_beam: 'BeamSet | None'
    top_lbs_remaining: float
    btm_lbs_remaining: float
    top_threaded: bool
    btm_threaded: bool
    current_item: 'Greige'
    is_idle: bool

    @property
    def current_family(self) -> str:
        """Family of `current_item`. Derived rather than stored so the
        record cannot be constructed in an inconsistent state where
        `current_family` contradicts `current_item.family`."""
        return self.current_item.family

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
            return replace(
                self,
                as_of=activity.end,
                top_lbs_remaining=self.top_lbs_remaining - activity.lbs * cfg.top_pct,
                btm_lbs_remaining=self.btm_lbs_remaining - activity.lbs * cfg.btm_pct,
                current_item=activity.item,
                is_idle=True,
            )
        if isinstance(activity, Waste):
            # Discards a beam's usable residue unknit, emptying the named bar
            # (beam -> None, lbs -> 0, un-threaded); a paired re-thread refills
            # it. current_item is unchanged — the yarn was dropped, never knit.
            if activity.bar == 'top':
                return replace(
                    self, as_of=activity.end,
                    top_beam=None, top_lbs_remaining=0.0, top_threaded=False,
                    is_idle=True,
                )
            return replace(
                self, as_of=activity.end,
                btm_beam=None, btm_lbs_remaining=0.0, btm_threaded=False,
                is_idle=True,
            )
        if isinstance(activity, Doff):
            # Takes one completed roll off the machine. No beam/lbs/item or
            # threaded change — only machine time (advancing as_of).
            return replace(self, as_of=activity.end, is_idle=True)
        if isinstance(activity, TapeOut):
            # Removes the set on the named bar(s): beam -> None, lbs -> 0,
            # un-threaded. current_item unchanged.
            changes: dict = {'as_of': activity.end, 'is_idle': True}
            if activity.bars in ('top', 'both'):
                changes.update(top_beam=None, top_lbs_remaining=0.0,
                               top_threaded=False)
            if activity.bars in ('btm', 'both'):
                changes.update(btm_beam=None, btm_lbs_remaining=0.0,
                               btm_threaded=False)
            return replace(self, **changes)
        if isinstance(activity, Hanging):
            # Loads a fresh set onto the named bar(s): sets beam + lbs and
            # leaves the bar un-threaded. Requires the bar already removed.
            changes = {'as_of': activity.end, 'is_idle': True}
            if activity.bars in ('top', 'both'):
                if not _removed(self.top_beam, self.top_lbs_remaining):
                    raise ValueError(
                        'cannot hang top: it still holds a usable set — '
                        'remove the old set first'
                    )
                changes.update(top_beam=activity.top_beam,
                               top_lbs_remaining=activity.top_lbs,
                               top_threaded=False)
            if activity.bars in ('btm', 'both'):
                if not _removed(self.btm_beam, self.btm_lbs_remaining):
                    raise ValueError(
                        'cannot hang btm: it still holds a usable set — '
                        'remove the old set first'
                    )
                changes.update(btm_beam=activity.btm_beam,
                               btm_lbs_remaining=activity.btm_lbs,
                               btm_threaded=False)
            return replace(self, **changes)
        if isinstance(activity, Threading):
            # Routes the loaded yarn: flips the named bar(s) to threaded and
            # nothing else. Requires the bar already hung (loaded, unthreaded).
            changes = {'as_of': activity.end, 'is_idle': True}
            if activity.bars in ('top', 'both'):
                if not _hung(self.top_beam, self.top_lbs_remaining,
                             self.top_threaded):
                    raise ValueError(
                        'cannot thread top: it is not hung — hang a fresh '
                        'set first'
                    )
                changes.update(top_threaded=True)
            if activity.bars in ('btm', 'both'):
                if not _hung(self.btm_beam, self.btm_lbs_remaining,
                             self.btm_threaded):
                    raise ValueError(
                        'cannot thread btm: it is not hung — hang a fresh '
                        'set first'
                    )
                changes.update(btm_threaded=True)
            return replace(self, **changes)
        if isinstance(activity, (StyleChange, RunnerChange, PatternChange)):
            # Changeover: switches the item being run. No yarn, beam, or
            # threaded change — the three types differ only in duration/cost.
            return replace(
                self, as_of=activity.end,
                current_item=activity.to_item, is_idle=True,
            )
        if isinstance(activity, Idle):
            # Beams, lbs, current_item, threaded all unchanged; advance as_of.
            return replace(self, as_of=activity.end, is_idle=True)
        raise TypeError(f'unknown activity type: {type(activity).__name__}')
