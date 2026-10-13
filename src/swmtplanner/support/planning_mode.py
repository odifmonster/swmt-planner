#!/usr/bin/env python

"""Planning mode — a coarse plan instead of exact runout and doff times.

In planning mode the planner answers "how many rolls of what on each
machine, and when to switch it to a different style", not "when does each
beam run out and each roll come off". Three things change, all plant-wide:

- doffing, hanging and threading take `HANDLING_HOURS` (0.01 h) each instead
  of their real durations — they still happen and still order the schedule,
  but no longer shape the timeline;
- there is no beam-set stock: the run-config's `beam_sets` and
  `assigned_sets` are not loaded, a taped-out set is never returned to
  stock (`worth_stocking` is False), and every set a changeover needs is
  invented (`BeamSet.new`); every set — mounted or invented — starts with
  `BEAM_LBS` (a million pounds), so a set is only ever taken off a machine
  because a changeover needs different yarn (a tape-out), never because it
  ran out;
- machines run at `EFFICIENCY` (65 %) of their nominal rate instead of the
  planner's `RUNNING_EFFICIENCY` (76.5 %, `schedule.machine`).

The mode is a process-wide switch set from the run-config (`"mode":
"planning"`, see `planners/infinite/DESIGN.md`) before any input is loaded;
the accessors below are what the loaders and the machine model consult.
Off by default, so the tests' fixtures see the real constants."""

__all__ = ['HANDLING_HOURS', 'BEAM_LBS', 'EFFICIENCY', 'enable', 'enabled',
           'handling_hours', 'beam_lbs', 'efficiency']

HANDLING_HOURS: float = 0.01        # work-hours for a doff / hang / thread
BEAM_LBS: float = 1_000_000.0       # lbs every beam set starts with
OLD_EFFICIENCY: float = 0.75            # running efficiency applied to old machine rates
NEW_EFFICIENCY: float = 0.7

_enabled: bool = False


def enable(on: bool = True) -> None:
    """Turn planning mode on (or off with `on=False`)."""
    global _enabled
    _enabled = bool(on)


def enabled() -> bool:
    return _enabled


def handling_hours(actual: float) -> float:
    """The duration to use for a doff, hang or thread: `actual` normally,
    `HANDLING_HOURS` in planning mode."""
    return HANDLING_HOURS if _enabled else actual


def beam_lbs(actual: float) -> float:
    """The lbs a beam set starts with: `actual` normally, `BEAM_LBS` in
    planning mode."""
    return BEAM_LBS if _enabled else actual


def efficiency(actual: float, mtype: str) -> float:
    """The running-efficiency factor on machine rates: `actual` normally,
    `EFFICIENCY` in planning mode."""
    plan_eff = NEW_EFFICIENCY if mtype == 'new' else OLD_EFFICIENCY
    return plan_eff if _enabled else actual