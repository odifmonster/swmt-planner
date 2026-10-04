# swmt-planner: Project Plan

A planning and scheduling tool for an automotive textile supply chain. This
document holds the high-level plan for completing the project. Detailed
designs live in per-module `DESIGN.md` files; test coverage lives in
per-module `COVERAGE.md` files.

## Purpose

The company produces automotive textiles in four stages, each at its own
plant(s):

1. **Warping** – yarn is warped from packages onto beam sets.
2. **Knitting** – yarn from beam sets is knit into greige fabric.
3. **Dyeing and finishing** – greige fabric is dyed and finished.
4. **Lamination** – foam backings are laminated to finished fabric, which is
   then delivered to the OEM.

There is one plant for warping and knitting, one plant for dyeing and
finishing, and several plants for lamination (demand is concentrated in three
of them).

The app suggests schedules for each plant based on:

- incoming demand,
- current inventory levels, and
- safety stock targets.

Reporting on productivity and quality fallout at the various locations may be
added, but planning is the primary focus.

## Development workflow

Development is gated per section of the project. Each step begins only when
explicitly approved:

1. **Design** – create or edit the relevant `DESIGN.md` files until the
   design is finalized.
2. **Implementation** – implement the design in reviewable chunks.
3. **Coverage** – create or update the relevant `COVERAGE.md` document.
4. **Testing** – write and run the tests.

Design documents are generally per-module. Modules small enough to be
described within their parent's design are folded into that document rather
than given their own.

Design documents follow a common layout:

- a short description at the top,
- **Overview** – purpose relative to the larger project and the capabilities
  the module introduces,
- **Core objects** – all constants, classes, and functions in the module,
  plus any folded-in submodules and their core objects,
- detailed sections for core objects as needed (constants generally do not
  need one).

## Branches

- `master` holds the finished project and is developed intentionally and
  slowly following the workflow above.
- A separate live branch holds a temporary working solution. Its history and
  approach are not carried over; this project is a fresh start.

## Phases

### Phase 1: Dyeing and knitting planners (current)

Deliverable: a CLI app containing a dyeing planner and a knitting planner.
Warping is out of scope (it will get its own planner in phase 2).

Steps, in order:

1. **Products** – define all products except laminated material. Includes
   both the class structures and the I/O functionality needed to read them
   in.
2. **Demand** – define demand structures: how demand gets filled, what is
   tracked, and the I/O functions to read it in.
3. **Inventory and raw materials** – structures for stock at each stage.
4. **Machines and activities** – definitions for the equipment at each
   plant, and what a machine is doing and when.
5. Remaining steps TBD.

Remaining known pieces of work, not yet placed in the sequence above:

- **Planning algorithms** – the logic that produces suggested schedules.
- **Entry points** – the CLI surface into the app.
- **Debug mode** – a detailed log of every planner decision at each step, so
  disagreeable decisions can be analyzed after the fact.
- **I/O module** – formats inputs and outputs. Data will eventually come
  entirely from a SQL database; today some of it lives in manually edited
  Excel files, and both sources must be supported. I/O for each data type
  is built alongside that type in the steps above.

### Phase 2: Warping scheduler

Introduce a scheduler for the warping plant.

### Phase 3: Linked planners and yarn ordering

Link the planners directly to one another so that each plant's schedule
informs the others, and add yarn ordering to the planning tools.

### Future phases

Further phases are likely (for example, expanded reporting) but are not
planned here.
