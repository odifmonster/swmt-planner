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
- **`core/product/`** — complete. `greige` + `fabric` submodules.
- **`core/materials/`** — complete. `rawmat` + `inventory` submodules (`inventory`
  has its own `DESIGN.md`).
- **`core/demand/`** — complete. `requirement` + `view` submodules, plus
  module-level `Chunk` and the top-level `RlsItem`. All generic on `Product`.
- **`core/schedule/`** and **`core/debuglog/`** — not started (undesigned).

Cross-cutting notes:

- **Deferred types.** `JetState` (read by `Color.get_needed_strip`) and `Job`
  (converted by `RlsItem.register_job`) both belong to `core/schedule`; `product`
  and `demand` reference only their documented interfaces until it is designed.
- **`__init__` curation.** `core/__init__` now surfaces `product` + `materials`
  + `demand`; `swmtplanner/__init__` still exposes only `support`, left for the
  user to curate as modules finish.
- Full suite passes (**184 tests**). Test-method docstrings cite their
  `COVERAGE.md` numbers.

Run the full suite:
`PYTHONPATH=src python3 -m unittest $(find src -name '*_tests.py' | sort)`

Next up: design `core/schedule` (machines + job placement), which brings in the
deferred `JetState` (read by `Color.get_needed_strip`) and `Job` (converted by
`RlsItem.register_job`); later `core/debuglog`.

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
