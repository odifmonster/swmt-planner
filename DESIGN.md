# swmtplanner

End-to-end supply chain planning tool for textile manufacturing, covering scheduling and
inventory tracking across the four production stages of warping, knitting, dyeing, and
lamination. A full planning run produces schedules for all four stages.

## Manufacturing stages

1. **Warping** — warps yarn packages into beams, which are then combined into beam sets.
2. **Knitting** — knits warped yarn into rolls of greige fabric.
3. **Dyeing** — dyes greige fabric, finishes it on a tenter frame to meet different
   specifications, and splits it into rolls.
4. **Lamination** — laminates foam backing onto dyed fabric.

## Submodules

### `materials/` - finished product and raw material data

This submodule defines data structures for all the relevant products in the
supply chain, as well as hold logic for identifying what raw materials are available
when, and how to convert from raw to finished goods at each step. It will have `product/`
and `inventory/` submodules for defining product BOMs and available raw materials
respectively.

It also defines an abstract `Product` class used to generalize shared concepts in
[`schedule/`](#schedule---work-centers-and-schedule-activities) (what a job produces
or consumes) and [`demand/`](#demand---tracking-order-fulfillment-and-inventory-levels)
(what an order is asking for), so those submodules can reason about goods without
needing to know the specifics of each production stage.

### `demand/` - tracking order fulfillment and inventory levels

This submodule defines the logic that determines how much product is needed,
which jobs on the schedule fulfill which orders, whether or not an order is on time,
and what is needed to maintain the desired safety stock levels in inventory.

### `schedule/` - work centers and schedule activities

This submodule defines different machines and their scheduling rules and the
activities that can go on each machine's work schedule. It also handles calculating
how much time it takes to produce a certain quantity of goods.

Concrete machine types defined here correspond one-to-one with the four manufacturing
stages:

- `Warper` — warping stage
- `KnitMachine` — knitting stage
- `Jet` — dyeing stage
- `LamMachine` — lamination stage

Each subclass encodes the scheduling rules, changeover constraints, and throughput
calculations specific to its work center.

### `planning/` - main planning algorithms

This submodule contains the algorithms that consume `materials/`, `demand/`, and
`schedule/` to produce a full set of work-center schedules. It is structured into
one submodule per production stage:

- `planning/warping/`
- `planning/knitting/`
- `planning/dyeing/`
- `planning/lamination/`

Each per-process submodule owns the planning logic for its stage. On top of these,
`planning/` exposes the main schedule-building functions that compose the per-stage
planners into an end-to-end run, and provides the CLI entry point that the user
invokes to execute a planning run.

### `input/` - reading and formatting inputs to the program

This submodule is the data-loading layer for the program. Initially it provides
convenience methods for reading the required inputs from Excel files (the current
source of truth for planning data). The eventual target is to load everything
directly from a SQL database, with the Excel readers serving as a stopgap until
that integration is in place.

This submodule will also eventually host a GUI for running the program and adjusting
tunable parameters, so non-technical users can launch planning runs without going
through the CLI.

## End-to-end workflow

### User entry points

There are two supported entry points into the program, both of which are
responsible for collecting the planning-run inputs, converting them into the data
structures expected by the core planning functions, and invoking those functions.

1. **CLI app** — lives in [`planning/`](#planning---main-planning-algorithms).
   Takes a path to a `config.json` file that provides all the inputs needed for a
   run. Exposes a sub-command per production stage for running an individual
   planner, plus one sub-command for running the full end-to-end pipeline.
2. **GUI dashboard** — lives in [`input/`](#input---reading-and-formatting-inputs-to-the-program).
   Collects the same inputs as the `config.json` through interactive forms instead
   of a file. Provides a separate menu/layout for configuring each per-stage
   planning run and one for configuring the complete end-to-end run.

Both entry points delegate to the same underlying planning functions, so the choice
of entry point only affects how inputs are gathered, not how the schedule is built.

### Main script

The main-script behavior differs between individual-planner runs and the
end-to-end run.

**Individual planners.** For a single-stage run, the workflow is straightforward:
invoke the planning function for the selected stage with the inputs gathered by
the entry point, and return its schedule report.

**End-to-end run.** Because the demand at each stage is determined by the schedule
of the stage that immediately follows it (knitting demand comes from the dyeing
schedule, dyeing demand comes from the lamination schedule, and so on), the
end-to-end run is structured as a cascade running backward through the production
sequence:

1. Call the planning function for the **last** stage in the process using the
   initial inputs.
2. Use that stage's schedule report to build the demand for the **previous**
   stage.
3. Pass that demand — along with any other initial inputs relevant to the
   previous stage — into the previous stage's planning function.
4. Repeat back through the pipeline until the first stage has been planned.

The main script is also responsible for dispatching the right slice of the
complete configuration to each planning function. The per-stage planners do not
all consume the same inputs and are designed to run without a full end-to-end
configuration, so the main script picks out the subset each function needs and
passes only that.

### Outputs

The default output of any planning run is a set of Excel files. Each file holds,
for one production stage:

- the schedule for each work center at that stage,
- any demand at that stage that the schedule did not meet, and
- any orders the planner could not fill on time.

On an end-to-end run, each per-stage planner produces its own output file.

Responsibility is split between the main script and the entry points:

- The **main script** returns the output data as data frames — one per Excel
  sheet, grouped by planner — and does not write any files itself.
- The **entry points** (CLI app and GUI dashboard) are responsible for writing
  those data frames to disk. The destination folder is one of the inputs they
  collect, so file I/O naturally lives with them.

Both entry points also expose flags/options for emitting extra metrics beyond the
default set — for example, inventory used, production broken out by item, and the
internal program decision log. These additional outputs are written alongside the
default Excel files at the same destination.

## Development phases

### MVP

The MVP is a project-level milestone. The capabilities listed here describe the
state of the project as a whole at that point; individual modules may go through
intermediate steps or improvements on the way that don't advance the overall
project to the next iteration, and those finer-grained steps are not described
here.

At the MVP milestone, the project covers:

- **Process coverage.** Only the knitting and dyeing stages are linked together.
  Warping and lamination are not yet in scope.
- **Inputs.** No Excel input-formatting capabilities. Every input is provided as
  a nicely-formatted JSON string. This is a deliberate choice for end-to-end
  testing: the real Excel sources span a large OneDrive directory tree and are
  frequently changed, so reconstructing them for tests is prohibitively tedious.
- **Scheduling algorithm.** Each in-scope planner uses a basic greedy scheduling
  algorithm, with implementation details specific to its process. No post-pass
  optimization step.
- **Entry points.** The CLI app is available. The GUI dashboard is not yet
  implemented.

Everything else described above in this document (the submodule structure, the
main-script cascade behavior, the output format and metric flags, etc.) is
expected to be in place at the MVP milestone for the two in-scope stages.

### Future iterations

Extend the pipeline to cover all four stages end-to-end (warping → knitting → dyeing →
lamination).

_Specific capabilities: TBD._
