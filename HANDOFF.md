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
- **core/DESIGN.md** — `core`'s five submodules and what each owns: `product`
  (static style definitions), `materials` (physical quantities, in inventory and
  on the schedule), `demand` (order fulfillment status), `schedule` (machines +
  job-placement logic), `debuglog` (self-contained decision-log architecture as
  linked tables). Each defines abstract concepts + concrete planner-specific
  subclasses and gets its own `DESIGN.md`; only `product`'s is written so far.
- **core/product/DESIGN.md** — design complete for both submodules: `greige`
  (`Greige` style implementing `HasID[str]` + the `BeamConfig` frozen dataclass)
  and `fabric` (`Fabric` implementing `HasID[str]`, the `Color` frozen dataclass,
  and the shade-rating int constants `EXTRA_LIGHT`/`LIGHT`/`MEDIUM`/`BLACK`/
  `SD_BLACK`, values intentionally undefined for now). `yds_per_lb` is computed
  in the `Fabric` constructor as `36 * 16 / (oz_sq_yd * width) * yld_pct`.
  `Color.get_needed_strip` will take a `JetState` (deferred — not yet defined).
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

- **support/workcal/tests/** — `COVERAGE.md` (Section 1 `holiday`, Section 2
  `WorkCal`) plus `holiday_tests.py` and `workcal_tests.py`. Full suite passes
  (40 tests: 10 holiday + 30 WorkCal). Test method docstrings cite their
  COVERAGE numbers.

`support/workcal/` is **complete** through design → code → coverage → test (the
first step of Phase 1's internals). `support/__init__` now surfaces `workcal`
(plus flattened `WorkCal`/`holiday`).

Run the suite with:
`PYTHONPATH=src python3 -m unittest src/swmtplanner/support/workcal/tests/holiday_tests.py src/swmtplanner/support/workcal/tests/workcal_tests.py`

Next up: implement `core/product/` (the `greige` and `fabric` submodules) from
the reviewed design, following code → coverage → test. Remaining `core`
submodules (`materials`, `demand`, `schedule`, `debuglog`) are not yet designed.

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

### Code & stub layout

The package uses a `src/` layout (`src/swmtplanner/...`) and ships type stubs.
Conventions:

- **Per-module stubs.** Each implementation `.py` file has a sibling `.pyi` stub
  of the same name (e.g. `counters.py` → `counters.pyi`) that carries the type
  signatures and docstrings. Implementation `.py` files are kept lean — no
  docstrings; the docstrings live in the stub.
- **Package `__init__` files re-export.** A package's `__init__.py` imports and
  re-exports the names from its submodules (and may flatten / re-expose
  sub-package names), with an explicit `__all__`.
- **`__init__.pyi` mirrors `__init__.py`.** Each `__init__.pyi` is an import
  aggregator that mirrors its `__init__.py` exactly — same imports and same
  `__all__` — pulling the names through from the per-module `.pyi` stubs. When the
  `__init__.py` exports change, update the matching `__init__.pyi` to match.
- **Tests** live in a `tests/` subpackage of the module they cover and need no
  stubs.
