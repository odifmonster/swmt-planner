# core — Design

`core` holds the abstract classes and concrete implementations for the
planning-related objects and functions: static product definitions, the physical
quantities of those products, the demand they fulfill, and the machine schedules
they run on.

Each submodule defines the **abstract** version of the concept it owns plus the
**concrete, planner-specific** subclasses. Each has its own `DESIGN.md` for the
details.

## Overview

The submodules build on one another:

- `product` provides static product/style definitions (what a thing *is*).
- `materials` tracks physical quantities of those products — both sitting in
  inventory and assigned within the schedule (what physical stock *exists* and
  *where*).
- `demand` tracks how well the current plan fulfills incoming orders.
- `schedule` defines the machines and the logic for placing new jobs onto the
  plant's schedule.
- `debuglog` records the calculations and decisions behind a given schedule as a
  set of linked tables.

The `planners` module (outside `core`) drives these pieces to build a plan; the
`app` module handles I/O around them.

## Core objects

`core` defines no module-level constants, functions, or classes of its own. Each
concept lives in a submodule, and each submodule has its own `DESIGN.md`
documenting its core objects.

## Submodules

### `product`
Static product/style definitions — greige (knitted, undyed) styles and finished
fabric styles. A style is a description only; it holds no mutable planning state.

See `src/swmtplanner/core/product/DESIGN.md`.

### `materials`
Tracks physical quantities of products, both in inventory and within the
schedule. For example, a `GreigeRoll` is raw material available in inventory to
be dyed, or assigned as part of a dye lot on a schedule — whereas a `Greige`
style (in `product`) is simply a description of the style such a roll might be.

See `src/swmtplanner/core/materials/DESIGN.md`. *(Not yet written.)*

### `demand`
Tracks the fulfillment status of orders: how much is left of hard requirements,
whether additional safety stock replenishment is needed, and whether the current
schedule is late, on time, or early relative to the incoming demand.

See `src/swmtplanner/core/demand/DESIGN.md`. *(Not yet written.)*

### `schedule`
Defines the properties of the various machines and the logic for adding new jobs
to the plant's schedule.

See `src/swmtplanner/core/schedule/DESIGN.md`. *(Not yet written.)*

### `debuglog`
A self-contained module holding only the debug / decision log architecture: a
general class for "logging" the calculations and decisions that went into
producing a given schedule, captured as a set of linked tables. (The data
structures for describing SQL tables remain in `support`.)

See `src/swmtplanner/core/debuglog/DESIGN.md`. *(Not yet written.)*
