# swmtplanner — Handoff

Running notes for picking work back up across sessions: development workflow,
project/development norms, and current progress.

## Current Status

Working from a clean slate on branch `combined-planners`; prior code was
hard-reset, so ignore the git history. The only code that exists is the generic
`support/` utilities: `hasid` (`HasID[T]` protocol), `counters` (`Counters`,
`mk_counter`), and `observable` (`Observer` / `Observable`). Python 3.12+
(uses native generic syntax).

Done so far:

- **PLAN.md** — whole-project plan: five phases, plus Phase 1 deliverables and
  the development order within Phase 1.
- **DESIGN.md** (top level) — the four modules (`support`, `core`, `planners`,
  `app`) and what each owns.
- **support/workcal/DESIGN.md** — design complete: the `holiday` submodule
  (`Holiday`/`FixedDate`/`FlexDate` frozen dataclasses + `load_holidays`) and the
  `WorkCal` class, including per-method details.
- **support/workcal/holiday/** — implemented (`holiday.py` + `__init__` re-export
  + `__init__.pyi` stub). Reviewed.
- **support/workcal/workcal.py** — `WorkCal` fully implemented and reviewed: the
  constructor + read-only properties, `is_workday` (with lazy holiday-ordinal
  caching), `offset_work_days`, `offset_work_hours`, `get_work_hours_between`, and
  `avail_hours_before_weekend`. The hour-based methods apply `cal_shift` by
  transforming into "aligned" coordinates (`aligned = real - cal_shift`), running
  the calendar there, then transforming back. Stub in `workcal/__init__.pyi`.

`support/workcal/` is code-complete (the first step of Phase 1's internals).
Note: `workcal/__init__` re-exports the `workcal`/`holiday` names but `support/
__init__.py` does not yet surface `workcal`.

Next up: the `workcal` COVERAGE.md test spec, then the `unittest` tests.

## Development Workflow

A **plan** is written only for sufficiently-large pieces of work (e.g. major
additions or refactors). The plan lays out the high-level steps. Development
then proceeds in several iterations through the design → code → coverage → test
cycle to complete those steps:

1. **Design** — Design the structures and algorithms before writing code.
2. **Code** — Implement the design in reviewable chunks.
3. **Coverage** — Write the test coverage spec.
4. **Test** — Implement and run the tests (using the `unittest` framework).

### How to work with me

- **Don't take initiative unless explicitly told to.** I choose the project
  direction, data structures, and algorithms. Don't add scope, make project-level
  decisions, or run ahead — ask or wait when in doubt.
- **Pause after each step for review.** When work is broken into steps, complete
  one step and then stop for my review, unless I explicitly say to complete
  multiple steps at once.
- **Wait for design approval before implementing.** Don't start writing code
  until I've approved the design.
- **Keep the design documents consistent with the code.** When I want to make a
  change, update all relevant design documents so the design stays consistent
  with the code base.

### Where things live (markdown documents)

- **PLAN.md** — Project-level plan and development phases for the whole project.
- **DESIGN.md** — Design of the structures and algorithms. Package/phase-level
  design documents describe the intended shape of the code before it is written.
- **COVERAGE.md** — Test coverage specs describing what the tests should cover.
- **HANDOFF.md** — This document. Development workflow, project/development
  norms, and progress tracking so work can resume in a new session.

### DESIGN.md document layout

Each `DESIGN.md` follows this structure:

1. **Header** — A brief description of what the document covers: the module and
   its purpose (or, for the top-level document, the project description).
2. **Overview** (if necessary) — Explains the overall layout: how the elements
   are broken down and how they connect to one another.
3. **Core objects** — Lists the module-level constants (if any) with their types
   and purposes, plus the type signatures for all module-level functions and
   classes. Does the same for each sub-module that does not have its own
   dedicated `DESIGN.md`.
4. **Detail sections** — Dedicated sections describing the module-level functions
   and classes in more detail: their purpose, the purpose of each attribute /
   method, and possibly specific details or pseudo-code for certain functions /
   methods. Plus a dedicated section for each sub-module; if a sub-module has its
   own `DESIGN.md`, that section's body just points to that document.

Additional sections are added per-document where necessary.
