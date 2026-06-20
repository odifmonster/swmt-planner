# swmtplanner — Project Plan

End-to-end supply chain planning tool for textile manufacturing. The pipeline
runs: order yarn → warp into beam sets → knit beam sets into greige fabric →
dye and finish the fabric → laminate foam backings onto the finished fabric.
The end goal is an all-in-one planning and reporting tool with both a desktop
GUI app and a CLI app.

## Development Phases

### Phase 1 — Dyeing planner (CLI)
Implement only the dyeing planner, delivered as a command-line tool. Abstract
and generalize wherever possible so that later pipeline stages can slot in
without rework.

By the end of Phase 1, the planner will:

- Expect input as nicely-formatted JSON files, so it is easy to wire up to the
  later dashboard version.
- Include abstract structures as well as concrete implementations for:
  - machine schedules,
  - product BOMs / SKUs,
  - inventory tracking, and
  - demand / order fulfillment.
- Run a main planning algorithm / loop that writes the final schedule to an
  Excel file.
- Dump the full decision-making log to a (local, for now) MySQL database, so
  questionable decisions can be investigated and tweaks made as necessary.

Development order within Phase 1:

1. Implement the internals: product information, demand tracking, inventory, and
   machines / schedules.
2. Implement the full planning algorithm along with I/O — reading from JSON and
   writing to Excel.
3. Thread through the debug / decision log and write it to the MySQL database.

### Phase 2 — Knitting planner (CLI)
Link in a knitting planner, also delivered as a command-line tool.

### Phase 3 — UI dashboard
Design a UI dashboard covering the dyeing and knitting planners.

### Phase 4 — Reporting
Add reporting capabilities to both the CLI and the GUI-based app.

### Phase 5+ — TBD
Most urgent next steps to be determined by the end users.
