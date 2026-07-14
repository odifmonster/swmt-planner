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
  subclasses and gets its own `DESIGN.md`; `product`'s and `materials`' are
  written so far.
- **core/product/DESIGN.md** — design complete for both submodules: `greige`
  (`Greige` style implementing `HasID[str]` + the `BeamConfig` frozen dataclass)
  and `fabric` (`Fabric` implementing `HasID[str]`, the `Color` frozen dataclass,
  and the shade-rating int constants `EXTRA_LIGHT`/`LIGHT`/`MEDIUM`/`BLACK`/
  `SD_BLACK` = 0–4). `yds_per_lb` is computed in the `Fabric` constructor as
  `36 * 16 / (oz_sq_yd * width) * yld_pct`. `Color.get_needed_strip` will take a
  `JetState` (deferred — not yet defined). Each submodule also owns cross-system
  name translations (in `translation.py`): `greige` has variant→master and
  alt-greige→`Greige`; `fabric` has ply1→`Fabric`. Lookups return `None` on a
  missing key (convention local to these translation functions).
- **core/materials/DESIGN.md** & **core/materials/inventory/DESIGN.md** — design
  complete. `materials` tracks physical raw-material quantities and has two
  submodules:
  - `rawmat` — abstract `RawMat(HasID[str | int])` (concrete `id`/`sku`/
    `avail_date` (a `datetime`)/`qty`/`unit`), concrete `GreigeRoll` (str `id`;
    `unit='lbs'`; adds `plant`/`variant`/`yarn_merge`/`greige`; computed
    `single_target`, `size` (`SMALL`/`STANDARD`/`LARGE`), `n_ports`,
    `avg_port_wt`; `split`/`combine`), and `DyeLot` (groups same-`sku`/`plant`
    rolls; `sku`/`plant`/`avail_date`/`total_lbs`/`n_ports`/`avg_port_wt`;
    `add`/`remove`/`__iter__`).
  - `inventory` (own `DESIGN.md`) — `Condition` alias (frozen `Exactly`/
    `NotExactly`/`Greater`/`Less`/`InRange`, each with `to_func()`);
    `Inventory[T: RawMat]` (`__init__(grouped, sorted)`, `add`/`remove`/
    `select_where`); the `group` sub-submodule (abstract `Group[T: RawMat]` +
    `ValGroup`/`SortedGroup`, plus `GreigeGroup`: `skus`, `prepare_dye_pool` via
    greedy sweep, `dye_lots`, `has_cached_lots`); and `GreigeInv` (grouped
    size/plant/variant/yarn_merge, sorted qty/avail_date, `sku` via a
    `GreigeGroup`; owns `transform_rolls` — remove→transform→add — and delegates
    the other dye-lot ops; `create_roll` mints `FSNEW-`/`WVNEW-` ids). Machine
    limits are constants (`MIN_PORT_LBS`/`MAX_PORT_LBS`/`PORT_EVEN_TOL`/
    `MAX_TRIM_LBS` in `group`; `DEFAULT_ROLL_WT`/`SINGLE_PORT_MAX`/`STD_SIZE_TOL`
    in `rawmat`).
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

- **core/product/greige/** & **core/product/fabric/** — implemented: classes in
  `greige.py`/`fabric.py`, translation functions in each `translation.py`, with
  sibling `.pyi` stubs and `__init__` re-export pairs. Each `.py` has its own
  `.pyi` per the Code & stub layout convention.
- **core/product/tests/** — `COVERAGE.md` (Section 1 `greige`, Section 2
  `fabric`) plus `greige_tests.py` and `fabric_tests.py` (17 tests). Docstrings
  cite their COVERAGE numbers.
- **core/materials/** — implemented. `rawmat/` (`rawmat.py` `RawMat`,
  `greigeroll.py` `GreigeRoll` + size/classification constants + public
  `single_target`, `dyelot.py` `DyeLot`) and `inventory/` (`condition.py`,
  `inventory.py` `Inventory`, `greigeinv.py` `GreigeInv`, and the `group/`
  sub-submodule: `group.py` `Group`/`ValGroup`/`SortedGroup`, `greigegroup.py`
  `GreigeGroup` + port constants). Each `.py` has a sibling `.pyi`.
  `ValGroup`/`SortedGroup` `remove` and `Inventory.remove` raise on a missing id
  (broken-grouping guard); `Inventory.add` raises on a duplicate id.
  - Two behaviors were changed while writing tests: (a) `SortedGroup` now
    **snapshots each element's key at `add` time** (stores `(key, mat)` pairs) so
    a mutated sort-key is caught by the `remove` guard, matching `ValGroup`;
    (b) `GreigeGroup.prepare_dye_pool` now **partitions dye lots by `plant`**
    (bucket by plant, then greedy-sweep `avg_port_wt` within each), consistent
    with `DyeLot`'s and `transform_rolls`' plant invariant.
- **core/materials/tests/** — `COVERAGE.md` (Section 1 `RawMat`, Section 2
  `GreigeRoll`, Section 3 `DyeLot`) + `rawmat_tests.py`, `greigeroll_tests.py`,
  `dyelot_tests.py`.
- **core/materials/inventory/tests/** — `COVERAGE.md` (Section 1 `Condition`s,
  Section 2 `ValGroup`/`SortedGroup`, Section 3 `Inventory`, Section 4
  `GreigeGroup`/`GreigeInv`) + `condition_tests.py`, `group_tests.py`,
  `inventory_tests.py`, `greigegroup_tests.py`, `greigeinv_tests.py`.

`support/workcal/`, `core/product/`, and `core/materials/` are all **complete**
through design → code → coverage → test. Full test suite passes (119 tests).
`support/__init__` surfaces `workcal` (plus flattened `WorkCal`/`holiday`);
`core/product/__init__` surfaces `greige` (plus flattened `Greige`); `core/__init__`
surfaces `product` + `materials`. `materials/__init__` surfaces `rawmat` +
`inventory` (plus flattened `RawMat`/`GreigeRoll`/`DyeLot`).
`swmtplanner/__init__` still exposes only `support` (not `core`) — left for the
user to curate.

Run the full suite with:
`PYTHONPATH=src python3 -m unittest $(find src -name '*_tests.py' | sort)`

Next up: design the next `core` submodule. `demand`, `schedule`, and `debuglog`
are still undesigned; `demand` (order fulfillment) or `schedule` (machines +
job placement) is the natural next piece toward the Phase 1 dyeing planner.

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
