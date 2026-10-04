# swmt-planner: Project Design

High-level design for the `swmtplanner` package: the modules it is divided
into, what each is responsible for, and how they depend on one another.
Per-module details live in each module's own `DESIGN.md`.

## Overview

`swmtplanner` is a planning and scheduling tool for an automotive textile
supply chain (see `PLAN.md` for the project's purpose and phases). It reads
demand, inventory, and machine data from external sources, runs planning
algorithms that suggest schedules for each plant, and presents the results
through a CLI (and, in the future, a PyQt6 GUI).

The package is divided into five modules, each with a narrow responsibility:

| Module     | Responsibility                                                   |
|------------|------------------------------------------------------------------|
| `support`  | Miscellaneous standalone helper functions and classes            |
| `core`     | Core structures used by the planners; rules and restrictions     |
| `planners` | Planning algorithms and main planning loops; debug mode          |
| `io`       | Input and output formatting                                      |
| `app`      | CLI entry points for running planners and reports; future GUI    |

## Modules

### `support`

Miscellaneous helper functions and classes that stand on their own and have
no dependence on planning domain concepts. Examples: a `WorkCal` class that
makes date math against a work calendar easy, and a `HasID[T]` protocol for
objects identified (and compared) by an `id` of type `T`.

### `core`

The core structures used by the planners. Objects in `core` define the rules
and restrictions that planning must respect, but contain no optimization
algorithms.

`core` is the shared vocabulary of the package. It describes what the supply
chain produces and consumes, how much of it exists and where, what is being
asked for and by when, and what equipment is available to do the work. It
introduces the following capabilities:

- **Product definitions** – bill-of-materials style descriptions of every
  product produced in the supply chain and every material consumed, so that
  the relationship between a finished item and its inputs is explicit.
- **Physical quantities and inventory** – representations of actual
  quantities of those products, and tools for selecting the correct raw
  materials from inventory when building a schedule.
- **Demand and fulfillment** – requirements placed on an item, the rules for
  how they get fulfilled, and reporting on whether an order will be filled
  late or safety stock will be drained.
- **Machines and activities** – definitions of the machines at each plant,
  the activities that run on them, and what those activities produce.

`core` has no top-level constants, classes, or functions of its own. It is
composed of the following submodules, each with its own `DESIGN.md`:

| Submodule   | Responsibility                                                 |
|-------------|----------------------------------------------------------------|
| `products`  | Class structures equivalent to product BOMs, for all products produced in the supply chain and all materials consumed. Carries the rules for what can be made from what; does not track quantities. |
| `materials` | Structures representing physical quantities of products: what exists, how much, and where. Contains the `inventory` submodule, which helps a planner select the correct raw materials from available inventory when creating a schedule. |
| `demand`    | Objects that define requirements on an item and how they get fulfilled. Reports whether an order will be filled late or safety stock will be drained. |
| `schedule`  | Definitions of machines, the activities that run on them, and what those activities produce. Together these describe the capacity and constraints the planners schedule against. |

### `planners`

The optimization algorithms and main planning loops, along with any other
planning-specific structures they need. This includes the "debug mode"
structures and functions that record a detailed log of every planner
decision at each step.

Planners expect easily readable JSON objects as input and do not format
their output; both concerns belong to `io`.

### `io`

Input and output formatting. On the input side, `io` reads from the
project's data sources (eventually a SQL database; today partly manually
edited Excel files) and produces the JSON objects the planners expect. On
the output side, it formats planner results for presentation and storage.

### `app`

The user-facing surface of the package. Contains the main CLI commands for
running the planners and reports. In the future, it will also contain the
PyQt6 GUI.

## Dependencies

Dependencies flow in one direction:

```
app ──► planners ──► core ──► support
 │                             ▲
 └─────► io ───────────────────┘
```

- `app` calls `io` to load inputs and format outputs, and `planners` to run
  the planning algorithms.
- `planners` builds on the structures in `core`.
- `core` and `io` may use helpers from `support`.
- `support` depends on nothing else in the package.
