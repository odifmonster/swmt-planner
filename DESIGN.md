# swmtplanner — Top-Level Design

`swmtplanner` is an end-to-end supply chain planning tool for textile
manufacturing. The pipeline runs: order yarn → warp into beam sets → knit beam
sets into greige fabric → dye and finish the fabric → laminate foam backings
onto the finished fabric. The end goal is an all-in-one planning and reporting
tool with both a desktop GUI app and a CLI app.

This document lays out the major modules and what each owns, pointing to each
module's own `DESIGN.md` for the details.

## Overview

The `app` module handles how the user interacts with the tool; the remaining
modules (`support`, `core`, `planners`) handle the internal logic and
structures.

The basic flow, at least for Phase 1:

1. The user runs the app and points it to the relevant JSON files.
2. The app reads those JSONs and passes the data to the main planning function.
3. The planning function delegates to the various modules and compiles the final
   schedule / report plus the decision log.
4. These results are sent back to the outer `app` layer, which formats them for
   the Excel file and the MySQL tables and writes the output.

## Core objects

The top-level `swmtplanner` package defines no module-level constants,
functions, or classes of its own; each module is its own unit. The core objects
for `core`, `planners`, and `app` are documented in their respective
`DESIGN.md` files. `support` has no module-level `DESIGN.md` (its components are
not linked in any meaningful way); its components are documented individually
where applicable — TBD.

## Modules

### `support`
Basic, self-contained support utilities with no dependency on the planning
domain. Currently holds `hasid`, `counters`, and `observable`. A module for date
math across working holidays and working hours will be added next, and others
may be added when a need arises. `support` also owns the data structures for
describing SQL tables.

`support` has no module-level `DESIGN.md`, since its components are not linked in
any meaningful way; individual components get their own `DESIGN.md` where one is
warranted. Details TBD.

### `core`
Abstract classes and concrete implementations for planning-related objects and
functions: representations of machines / schedules, demand / orders, available
raw materials inventory, and product SKUs and BOMs. `core` also owns the
architecture for recording detailed "decision logs" on each planning run.

See `src/swmtplanner/core/DESIGN.md`.

### `planners`
The main planning algorithms and any related architecture, with a submodule for
each planner.

See `src/swmtplanner/planners/DESIGN.md`.

### `app`
I/O functionality plus the CLI (and later GUI) entry points.

See `src/swmtplanner/app/DESIGN.md`.
