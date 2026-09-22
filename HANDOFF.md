# swmtplanner — Handoff

Running notes for picking work back up across sessions: development workflow,
project/development norms, and current progress.

## Current Status

Clean slate on branch `combined-planners`; prior code was hard-reset — ignore
git history. Python 3.12+ (native generic syntax). `support/` holds the generic
utilities (`hasid`, `counters`, `observable`); the rest of the tree is being
built out module by module.

See `PLAN.md` for the five project phases. We are in **Phase 1** (dyeing planner,
CLI), **step 1** — building the internals: product info, demand, inventory, and
machines/schedules. This section tracks **status only**; the per-module
`DESIGN.md` files are the source of truth for structure and algorithms (top-level
`DESIGN.md` covers `support`/`core`/`planners`/`app`; `core/DESIGN.md` covers
core's five submodules). Each piece runs through the design → code → coverage →
test cycle (see Development Workflow below); "complete" means it has been through
all four.

Progress by module:

- **`support/workcal/`** — complete. `holiday` submodule + the `WorkCal` class.
- **`core/product/`** — `fabric` complete. **Mid-refactor** of the greige side to
  match how styles are actually defined in the company database (see "Greige
  restructure" below): now three submodules, `yarn` + `greige` + `fabric`.
  - `yarn` (new) — **designed and implemented** (code + stubs): `Yarn` and
    `BeamSetItem`, both `HasID[str]` with ids built from their other properties,
    plus the `LUSTER_CODES` / `MATERIAL_CODES` / `ATTR_CODES` maps that the ids
    are coded from. Coverage + tests pending.
  - `greige` — **designed, not yet implemented.** `BarConfig` replaces
    `BeamConfig` in `greige.py` (`bset` / `pct` / `stitch` / `thread`), and
    `Greige` swaps `top` / `bottom` for `n_bars` + 1-based `bar(i)`, keeping
    `id` / `tgt_wt` / `safety` / `pattern` / `alt_names`. `translation.py` is
    unaffected. Coverage + tests pending.
  - `Product` now includes `BeamSetItem` (the warping plant plans against beam
    sets); `Yarn` is deliberately excluded as an ingredient rather than a
    planned product.
- **`core/materials/`** — complete. `rawmat` + `inventory` submodules (`inventory`
  has its own `DESIGN.md`). `DyeLot.freeze()` added (through all four phases):
  once frozen, `add` / `remove` / setting `fabric` raise `RuntimeError`.
- **`core/demand/`** — complete. `requirement` + `view` submodules, plus
  module-level `Chunk` and the top-level `RlsItem`. All generic on `Product`.
  Now also pushes priorities back onto the schedule: `Chunk` implements
  `HasID[int]`, `RlsItem` keeps a chunk → source-`Job` map
  (`register_chunk(chunk, job=None)`), and each `recompute` clears every
  mapped job's `priority` and rewrites it from the `(chunk, priority)` pairs
  `SafetyView.recompute` now returns (covered in 2.2.3 / 2.2.4 / 3.3).
- **`core/schedule/`** — fully **designed**: the `activity` submodule in
  `schedule/DESIGN.md`, the `machine` submodule in its own
  `machine/DESIGN.md` (`State` / `Machine` bases, `JetState`, `JetUpdate`,
  `ShadeSeq`, `Jet`). The `activity` submodule is **implemented** (code +
  stubs: `Priority`, `Activity`, `Idle`, `DyeCycle` / `EmptyCycle` /
  `StripCycle`, `Job` / `DyeJob`, cycle-time constant/function) — it was
  implemented early so `demand` could use `Job` / `Priority`; its own
  coverage + tests are deliberately still pending. `machine` is not
  implemented.
- **`core/debuglog/`** — not started (undesigned).

Cross-cutting notes:

- **Deferred types, updated.** `Job` now exists (`schedule.activity`) and
  `demand` uses it; `RlsItem.register_job` remains the abstract job → `Chunk`
  hook (a test-only conversion lives on the tests' `FabRlsItem`). `JetState`
  is designed (`machine/DESIGN.md`) but not implemented;
  `Color.get_needed_strip` still references only its documented interface.
- **`__init__` curation.** `core/__init__` surfaces `product` + `materials` +
  `demand`; `product/__init__` now surfaces `yarn` + `Yarn` + `BeamSetItem`
  alongside `greige` / `fabric`; `schedule/__init__` re-exports `activity`, but
  `schedule` is not yet surfaced in `core/__init__`; `swmtplanner/__init__`
  still exposes only `support`. Left for the user to curate as modules finish.
- **Greige restructure — source data.** The greige styles are now derived from a
  SQL export of the company database (`greige_variants.tsv` in
  `../plan-input-files/`, one row per style *variant*) plus `greige-targets.json`
  (the master style list, with `alt_names` / `tgt_wt` / `safety`) and
  `knit-machine-master.json`. The old `greige-styles.json` is **superseded and no
  longer used** — it was not derived from the database, and where the two
  disagree the TSV wins. Deriving one master style from its many variants needs a
  specific set of normalisation and resolution rules (yarn-spec normalisation,
  construction matching, dominant-stitch filtering, averaging of measured
  values); those rules are settled but **not yet written into any design
  document** — they belong with the loader at the `app` layer, which is
  undesigned. A working reference implementation lives outside the repo in the
  session scratchpad, so this needs writing up before the loader is built.
  Unresolvable styles should warn and be skipped, not abort the run.
- **Parked design question.** `Priority.value` is currently
  `int | str | None` (`None` = cleared / entirely-excess). The user started
  to refine this (restrict `value` to `int | str`, with `Job.priority` itself
  becoming `None`-able) and set it aside — revisit before implementing
  `machine`'s priority comparisons.
- Full suite passes (**213 tests**). Test-method docstrings cite their
  `COVERAGE.md` numbers.

Run the full suite:
`PYTHONPATH=src python3 -m unittest $(find src -name '*_tests.py' | sort)`

Next up: finish the greige restructure — implement `greige.py` / `.pyi`
(`BarConfig` + the new `Greige`), update the `greige` `__init__` pair, then write
coverage + tests for the new `yarn` submodule and the reworked `greige`. After
that: implement `core/schedule`'s `machine` submodule (design complete), write
the `activity` submodule's coverage + tests, and write up the greige loader rules
noted above; later `core/debuglog`.

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
