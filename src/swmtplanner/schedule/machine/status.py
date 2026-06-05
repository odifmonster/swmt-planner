#!/usr/bin/env python

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.schedule.activity import (
    Activity, Knit, Waste, TapeOut, BeamLoad, StyleChange, Idle,
)

if TYPE_CHECKING:
    from swmtplanner.products import Greige, BeamSet


@dataclass(frozen=True)
class Status:
    """Snapshot of a machine's state at a moment in time. Derived from
    `Machine.initial_status` plus the machine's activity sequence; never
    mutated directly.

    `current_item` is non-nullable — a machine is always programmed to
    produce *something*; changing items only ever swaps that program, never
    clears it. `top_beam` / `btm_beam` can be `None` after a `TapeOut`
    before the matching `BeamLoad`.

    `is_idle` reports whether an activity is in progress at `as_of`. It is
    informational only — the planner does not consult it when deciding on
    changeovers, since yarn stays threaded across idle gaps."""
    as_of: datetime
    top_beam: 'BeamSet | None'
    btm_beam: 'BeamSet | None'
    top_lbs_remaining: float
    btm_lbs_remaining: float
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
        nothing is in progress at exactly `activity.end`)."""
        if isinstance(activity, Knit):
            cfg = activity.item.configuration
            return Status(
                as_of=activity.end,
                top_beam=self.top_beam,
                btm_beam=self.btm_beam,
                top_lbs_remaining=self.top_lbs_remaining - activity.lbs * cfg.top_pct,
                btm_lbs_remaining=self.btm_lbs_remaining - activity.lbs * cfg.btm_pct,
                current_item=activity.item,
                is_idle=True,
            )
        if isinstance(activity, Waste):
            # Waste discards a beam's usable residue unknit before an early
            # swap, so it empties the named bar (beam -> None, lbs -> 0); a
            # paired BeamLoad refills it. current_item is unchanged — the
            # yarn was dropped, never knit into anything new.
            if activity.bar == 'top':
                return Status(
                    as_of=activity.end,
                    top_beam=None,
                    btm_beam=self.btm_beam,
                    top_lbs_remaining=0.0,
                    btm_lbs_remaining=self.btm_lbs_remaining,
                    current_item=self.current_item,
                    is_idle=True,
                )
            # bar == 'btm'
            return Status(
                as_of=activity.end,
                top_beam=self.top_beam,
                btm_beam=None,
                top_lbs_remaining=self.top_lbs_remaining,
                btm_lbs_remaining=0.0,
                current_item=self.current_item,
                is_idle=True,
            )
        if isinstance(activity, TapeOut):
            top_beam = self.top_beam
            btm_beam = self.btm_beam
            top_lbs = self.top_lbs_remaining
            btm_lbs = self.btm_lbs_remaining
            if activity.bars in ('top', 'both'):
                top_beam = None
                top_lbs = 0.0
            if activity.bars in ('btm', 'both'):
                btm_beam = None
                btm_lbs = 0.0
            return Status(
                as_of=activity.end,
                top_beam=top_beam,
                btm_beam=btm_beam,
                top_lbs_remaining=top_lbs,
                btm_lbs_remaining=btm_lbs,
                current_item=self.current_item,
                is_idle=True,
            )
        if isinstance(activity, BeamLoad):
            if activity.bar == 'top':
                return Status(
                    as_of=activity.end,
                    top_beam=activity.beam,
                    btm_beam=self.btm_beam,
                    top_lbs_remaining=activity.lbs,
                    btm_lbs_remaining=self.btm_lbs_remaining,
                    current_item=self.current_item,
                    is_idle=True,
                )
            # bar == 'btm'
            return Status(
                as_of=activity.end,
                top_beam=self.top_beam,
                btm_beam=activity.beam,
                top_lbs_remaining=self.top_lbs_remaining,
                btm_lbs_remaining=activity.lbs,
                current_item=self.current_item,
                is_idle=True,
            )
        if isinstance(activity, StyleChange):
            # Style change does not consume yarn or swap beams; just switches
            # what item is being run.
            return Status(
                as_of=activity.end,
                top_beam=self.top_beam,
                btm_beam=self.btm_beam,
                top_lbs_remaining=self.top_lbs_remaining,
                btm_lbs_remaining=self.btm_lbs_remaining,
                current_item=activity.to_item,
                is_idle=True,
            )
        if isinstance(activity, Idle):
            # Beams, lbs, current_item all unchanged. Just advance as_of.
            return replace(self, as_of=activity.end, is_idle=True)
        raise TypeError(f'unknown activity type: {type(activity).__name__}')
