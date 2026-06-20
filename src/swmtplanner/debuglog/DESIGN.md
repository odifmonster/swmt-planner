# Debug Log — Design

A standalone top-level module (`swmtplanner.debuglog`). Defines **`DebugLog`**:
a generic, config-driven container of named tables — it hard-codes no schema of
its own, so any caller can declare the tables it needs. The infinite planner
uses it as an optional, in-memory audit object threaded through its methods so
they record *why* the schedule came out the way it did. It lives at the top
level (rather than under `planners/infinite/`) because it is planner-agnostic.

**Persistence and investigation are external.** `DebugLog` is only the in-memory
accumulator + its read API (`tables` / `schema` / `get_df`). Turning a populated
log into durable, browsable output — writing it to a local MySQL store and
investigating it through a PyQt6 app — is owned by the planner's dashboard
module (`planners/infinite/dashboard/`, see its DESIGN.md), which consumes this
read API. This module hard-codes nothing about MySQL, files, or UIs.

## Purpose

The planner's normal output (the Excel workbook from `report.py`) answers
*what* was scheduled. `DebugLog` answers *why*: it collects the demand /
production / cross-reference tables, the per-iteration decision trail, and the
cost attribution behind each move — so a downstream layer can persist and
investigate them.

It is the realization of Step 4's "verbose mode" (originally sketched as
`VerboseLog`): an **optional** object passed as a keyword argument into the
relevant methods — the planner loop, costing, demand views, schedule emission.
When present, each method appends its own detail records to the log as it runs;
when absent, behavior is unchanged and nothing is logged. This is intended to
**replace** the current after-the-fact reconstruction in `iterlog.py` and the
`*_detail` machinery on `PlanReport` (built up over the phases below).

This submodule owns:

- the `DebugLog` object, the table / record types it holds, and its read API
  (`tables` / `schema` / `get_df`).

It does **not** own output: persistence (→ MySQL) and the investigation UI
(→ PyQt6) live in `planners/infinite/dashboard/`.

## Phased implementation

`DebugLog` is built up over four iterations. **Each phase gets its own detailed
design (DESIGN → code → coverage spec → tests) when it begins**; the roadmap
below only fixes the scope and order of the phases.

### Phase 1 — `DebugLog` with a simplified iteration log + cost summary

`DebugLog` carries just **two tables**: a **simplified iteration log** (one row
per scored candidate per iteration) and a **cost summary**.

These two are chosen deliberately to **prove out the new mechanics**. Unlike
the regular output tables — which are built once at the end from the finished
`PlanReport` — both of these are produced **incrementally as the loop runs**.
So they exercise exactly the flow this phase exists to validate: construct a
`DebugLog`, thread it (as an optional kwarg) to the loop / costing methods, and
have those methods **write to it live**. (The output tables, built post-hoc,
wouldn't test that pass-the-object-and-write-as-you-go path at all — which is
why they're deferred to phase 2.)

No dashboard, and the iteration log is intentionally **simplified** (a small
column set, refined later): the goal is to get the plumbing right end-to-end,
not to land the final schema.

#### The `DebugLog` object — generic, config-driven tables

`DebugLog` does **not** hard-code its tables into per-table classes. It is a
generic container of named tables, each an ordered column list plus appended
rows, so new tables (phases 2–4) are added by configuration, not new types.

- **Construction** — `DebugLog(**tables)`, each keyword a
  `table_name=[(col1, default1), (col2, default2), ...]` declaration: an
  ordered list of `(column_name, default_value)` 2-tuples. The defaults let a
  row be appended before every value is known (the rest filled in later via
  `update_row`). e.g. `DebugLog(iteration_log=[('move_id', None), ...], ...)`.
- **`set_pk(table, *columns, ctr_name=None)`** — declare `columns` (one or more)
  as `table`'s primary key. A **single** column is the common case; **two or
  more** form a **composite** key (e.g. `set_pk('run_configs', 'kind',
  'label')`). The PK column **names are stored as a tuple of strings** (`()` for
  a key-less table), and a row is addressed by the **tuple of its PK column
  values**. `ctr_name` is **optional** and valid **only for a single-column
  key**: supply it to make the key **auto-incremented** (a fresh counter of that
  name is created and minted per row); a composite key is always
  caller-supplied (passing `ctr_name` with more than one column raises). A table
  may have **only one** primary key — defining a second raises.
- **`set_fk(table, column, foreign_table, foreign_column)`** — declare `column`
  as a foreign key pointing at `foreign_table.foreign_column`, which must be the
  foreign table's **single-column** primary key (a single FK column cannot carry
  a composite key's tuple — referencing a composite PK raises). The method
  internally handles the link: if the referenced key is counter-backed, this
  column rides the **same counter** so `add_row` can fill it with the current
  id; if the referenced key is non-auto, the value must be supplied at `add_row`
  time.
- **`add_row(table, **kwargs)`** — append a row and **return its primary-key
  value** — a scalar for a single-column PK, the **tuple of PK values** for a
  composite PK, or `None` if the table has no PK. Each declared column not
  supplied in `kwargs` is filled in this order of precedence: an
  **auto-incremented PK** column by **advancing** its counter (minting a fresh
  id); an **FK** column backed by a counter by that counter's **current** value
  (linking to the most-recently-minted PK); any other column by its **declared
  default**. Supplied kwargs override; unknown columns raise. A **non-auto** PK
  column (every column of a composite key, or a single key with no counter)
  must be **supplied** — it never falls back to a default (so rows stay
  addressable by `update_row`).
- **`get_last_pk_val(table)`** — return the primary-key value of the most
  recently added row of `table`: a scalar for a single-column PK (for a
  counter-backed PK this equals the counter's current value), the **tuple** of
  values for a composite PK; `None` if no row has been added yet. Requires the
  table to have a PK — **raises** otherwise. This keeps debug-side tracking
  inside the `DebugLog` rather than threading ids through caller signatures:
  e.g. `score_after_move` composes `cost_summary`'s `summary_id` from the
  current `iteration_log` `move_id` via `get_last_pk_val('iteration_log')`,
  so its only debug parameter stays the single `debuglog` object. (FK auto-link
  only ever reads a single-column referent, so it always gets a scalar.)
- **`update_row(table, pk_val, **kwargs)`** — patch the columns named in
  `kwargs` on the existing row whose primary key equals `pk_val` (a scalar for a
  single-column PK, the **tuple** for a composite PK). **Only valid on a table
  that has a primary key** — raises otherwise (there is no other way to address
  a specific row); also raises if no row matches `pk_val`, or a kwarg names an
  unknown column or **any** PK column (the key cannot be updated). This is how
  fields unknown at `add_row` time (e.g. a candidate's post-sort `rank` /
  `role`) are filled in.
- **`get_df(table, **kwargs)`** — return `pandas.DataFrame(rows,
  columns=<declared columns>, **kwargs)`; the extra kwargs are forwarded to the
  `DataFrame` constructor (e.g. `index=`, `dtype=`). Built flat — **no
  MultiIndex**. A single-column-PK table uses that PK as the (named) index; a
  **composite**-PK table keeps its PK columns as ordinary **leading columns**
  with a default integer index (since a tuple index would be a MultiIndex); a
  key-less table uses a default integer index.
- **`tables`** (property) — the names of the registered tables, in declaration
  order, as a `tuple[str, ...]`. Lets a caller enumerate the log without knowing
  its schema up front — e.g. the persistence writer walks `for name in
  log.tables: log.get_df(name)` to insert each table's rows.
- **`schema`** (property) — the inter-table link metadata, as
  `dict[str, TableSchema]` keyed by table name in declaration order. Exposes the
  PK / FK structure the persistence writer uses to lay out the run-tagged INSERTs
  and the PyQt6 investigation app ships as static metadata to drive its
  foreign-key navigation — without the caller poking at internals. Two small
  frozen value types, both exported from `swmtplanner.debuglog`:

  ```
  TableSchema
    columns: tuple[str, ...]      # declared column order (same as get_df's columns)
    pk: tuple[str, ...]           # the primary-key columns (empty for a key-less table)
    fks: tuple[ForeignKey, ...]   # one per foreign-key column, in declared order

  ForeignKey
    column: str                   # the foreign-key column in this table
    ref_table: str                # the referenced table
    ref_column: str               # the referenced table's (single-column) primary key
  ```

  `ref_table` / `ref_column` are resolved from the stored link: a foreign key
  onto a **non-auto** primary key stores the foreign table name directly; one
  onto a **counter-backed** primary key stores only the counter name, so
  `schema` maps that counter back to the table whose primary key owns it. The
  property recomputes from the current schema on each access (cheap; the schema
  is small and fixed once rows exist).

**Keys are immutable once set.** A column that is already a primary key cannot
be made a foreign key (and vice versa); a primary key cannot be redefined with
a different counter name, nor switched from counter-backed to caller-supplied or
back. `set_pk` / `set_fk` raise on all such attempts; re-declaring the identical
key is a silent no-op. The PK/FK declarations double as the **inter-table link
metadata** the `schema` property exposes — used by the MySQL persistence writer
(to lay out run-tagged tables) and the PyQt6 investigation app (to drive
foreign-key navigation). See `planners/infinite/dashboard/DESIGN.md`.

#### Counters

`DebugLog` owns a **`Counters`** (from the `support` module — `advance(name)`
mints the next int and records it as current; `counters(name)` reads the
current). Counters exist **only for auto-incremented primary keys**: `set_pk`
creates one when given a `ctr_name`, and the FK that references such a PK rides
the same counter. Phase 1 has one:

- **`move_id`** — `iteration_log`'s auto-incremented PK, with `cost_summary`'s
  `move_id` as an FK onto it. Minted once per candidate move (as its
  `iteration_log` row is added), so every `cost_summary` row written for that
  move picks it up as the current value.

`iteration_log.iteration_idx` is **not** counter-backed (it isn't a key — and
there is no per-iteration table for an FK to reference). `plan` already tracks
the main-loop iteration index, so it supplies `iteration_idx` directly on each
`add_row`.

#### Phase-1 tables

```
iteration_log                 # one row per scored candidate, per iteration
  iteration_idx               # plain column, supplied by plan each add_row
                              #   (the current main-loop iteration index)
  move_id                     # PK -> counter 'move_id' (minted per row)
  order_id                    # the order the candidate targets (its new-item
                              #   Job's tgt_order)
  order_remaining_lbs         # unfulfilled lbs on the targeted order when the
                              #   candidate is evaluated — `move.order_remaining_lbs`
                              #   (the eligible RegularOrder.lbs / SafetyOrder.lbs)
  machine                     # move.machine_id
  decision_point              # move.start_at ('schedule_tail' | 'next_runout')
  role                        # 'committed' | 'rejected' — unknown at add time;
                              #   default 'rejected', patched via update_row
  rank                        # position in the cost-sorted candidate list
                              #   (0 = lowest cost = the committed move) —
                              #   unknown at add time; patched via update_row
  total_cost                  # the candidate's total score (== sum of its
                              #   cost_summary 'cost' column == CostBreakdown.total)
                              #   — set via update_row once scored

cost_summary                  # parallel of CostBreakdown — one row per weighted
                              # component, per candidate
  summary_id                  # PK (non-auto): the caller-built composite
                              #   "{move_id}_{label}" (e.g. '10_lateness');
                              #   supplied at add_row, never defaulted
  move_id                     # FK -> iteration_log.move_id (counter 'move_id',
                              #   current); the candidate it belongs to
  label                       # the CostBreakdown attribute name, e.g.
                              #   'lateness', 'tape_out_single', 'priority'
  kind                        # 'inventory' | 'schedule' | 'other'
  raw                         # the unweighted quantity
  cost                        # the weighted contribution (raw x weight) =
                              #   the matching CostBreakdown scalar
```

`kind` partitions the fourteen `CostBreakdown` components exactly:

- **inventory** — `lateness`, `drainage`, `carrying`, `excess`
- **schedule** — `tape_out_single`, `tape_out_both`, `style_change`,
  `runner_change`, `pattern_change`, `idle_time`, `waste_lbs`
- **other** — `priority`, `level_loading`, `old_machine`

Config:
`set_pk('iteration_log', 'move_id', ctr_name='move_id')` (auto-incremented);
`set_pk('cost_summary', 'summary_id')` (**non-auto** — the caller composes
`summary_id` from `move_id` + `label`); and
`set_fk('cost_summary', 'move_id', 'iteration_log', 'move_id')`.
`iteration_idx` is a plain column (no key), supplied by `plan`.

`cost_summary` carries a primary key (rather than going key-less) so its rows
are individually addressable — the dashboard's FK links and any later
`update_row` need it. It keeps a single, caller-built `summary_id` string even
though `DebugLog` now supports **composite** primary keys (`set_pk` with several
columns): `inv_cost_detail.summary_id` is a **foreign key onto it**, and an FK
must reference a single-column PK — so `cost_summary` deliberately stays
single-keyed. Composite keys are for tables nothing references by key (e.g.
`run_configs` on `(kind, label)`).

#### Population flow

The `DebugLog` is an **optional kwarg** on the methods that populate it; absent,
behavior is unchanged. Two builders:

- **`plan`** builds `iteration_log` and drives the counters. The verbose path
  **scores and ranks the full candidate list** rather than taking the single
  lowest. It still commits the rank-0 (lowest-cost) move.
- **`Costing.score_after_move`** gains a **single** optional `debuglog` kwarg
  (no extra id parameters) and builds `cost_summary` for the candidate it is
  scoring. It reads the candidate's id from the log itself —
  `mid = debuglog.get_last_pk_val('iteration_log')` — then emits one
  `add_row('cost_summary', summary_id=f'{mid}_{label}', label=…, kind=…, raw=…,
  cost=…)` per component (the `move_id` FK auto-links to the current
  `move_id`). It delegates to its existing sub-calculations
  (demand / schedule / cross-cutting) to surface each component's raw and
  weighted values.

`update_row` resolves the ordering cleanly in a **single scoring pass** — no
recompute. Per main-loop iteration, in `plan` (which tracks the iteration
index `i`):

1. for each candidate move:
   - `mid = debuglog.add_row('iteration_log', iteration_idx=i, order_id=…,
     order_remaining_lbs=…, machine=…, decision_point=…)` — mints and returns
     the candidate's `move_id` (PK) and leaves `role` / `rank` / `total_cost`
     at their declared defaults;
   - `total = score_after_move(state, move, ctx, debuglog=debuglog)` — reads
     `mid` back via `debuglog.get_last_pk_val('iteration_log')` and appends this
     candidate's `cost_summary` rows (PK `summary_id = f'{mid}_{label}'`;
     `move_id` FK = current = `mid`); returns the scalar total;
   - capture `(mid, total, move)`;
2. sort the captured candidates by `total` ascending and, for each,
   `debuglog.update_row('iteration_log', mid, rank=position, total_cost=total,
   role='committed' if position == 0 else 'rejected')`;
3. commit the rank-0 move.

Minting `move_id` up front (step 1) makes it available to the candidate's
`cost_summary` rows immediately, while the fields that depend on the sort
(`rank`, `role`) — and the `total_cost`, known only after scoring — are filled
by `update_row` in step 2. `score_after_move` is called exactly **once per
candidate**, and the non-debug hot path is untouched.

### Phase 2 — cost-detail leaf tables + output tables

Phase 2 **lays out new tables** on the same `DebugLog` (population is a later
step). Two groups: the leaf tables that break phase-1's `cost_summary` rows
down, and the carry-over output tables.

#### Cost-detail tables

**`inv_cost_detail`** — the inventory leaf: everything the demand layer
(`RlsItem`) computes — `lateness`, `drainage`, `carrying`, `excess`. One table;
the `label` column distinguishes them. Every discrete time window is its own
row.

```
inv_cost_detail
  icost_id      # PK -> counter 'icost_id' (auto-incremented)
  summary_id    # FK -> cost_summary.summary_id (the parent component row)
  move_id       # FK -> iteration_log.move_id (the candidate; redundant with
                #   summary_id but convenient for grouping by candidate)
  label         # 'lateness' | 'drainage' | 'carrying' | 'excess'
  item          # greige id
  days          # window length / days-late; None (blank) for excess
  qty           # lbs for this row
  weight        # the component's weight
  value         # the weighted cost contribution of this row
```

Granularity by `label`:
- **lateness** — one row per late delivery of material to an order: `days` =
  days late, `qty` = lbs delivered late, `value` = `weight × qty × 2^days`.
- **drainage** — one row per stretch the pool sits at the same level **below**
  target: `days` = stretch length, `qty` = deficit lbs, `value` =
  `weight × qty × days`.
- **carrying** — one row per **fill held beyond its lead time** (the demand
  view accrues carrying per such fill, not per above-target stretch — the rows
  follow the view's actual accumulation so they reconcile): `days` = days held
  beyond lead, `qty` = lbs filled, `value` = `weight × qty × days`.
- **excess** — `days` blank; one row carrying the excess `qty`, `value` =
  `weight × qty`.

**Strict reconciliation:** detail is emitted for **every** item (each scored
candidate runs every `RlsItem` through `cost_if`, not just the ones its plan
touches), so the rows for a given `summary_id` sum (their `value`) exactly to
that `cost_summary` row's `cost`. Rows that aren't of interest (e.g. items the
move didn't affect) are filtered in the dashboard, not dropped here. Config:
`set_pk('inv_cost_detail', 'icost_id', ctr_name='icost_id')`,
`set_fk('inv_cost_detail', 'summary_id', 'cost_summary', 'summary_id')`,
`set_fk('inv_cost_detail', 'move_id', 'iteration_log', 'move_id')`.

**`sched_cost_detail`** — one row per **activity** (the schedule breakdown).

```
sched_cost_detail
  activity_id   # PK (non-auto; the Activity's own id)
  move_id       # FK -> iteration_log.move_id
  machine       # machine id
  start         # the activity's start
  end           # the activity's end
  desc          # short description (as in the schedule sheet)
  weight        # the activity's cost weight; blank for cost-free types
  cost          # weight × quantity; blank for cost-free types
```

`weight` / `cost` are **blank** for activity types that carry no cost concept
(`Knit`, `Doff`, `Hanging`, `Threading`); a weighted type whose weight happens
to be **0** shows `0` in both — distinguishing "no cost" from "zero-valued
cost". This lists every candidate's plan activities — the committed iteration's
*and* the rejected ones — so it is the complete activity ledger and the old
`schedule` **output table is dropped** (redundant). It links only by `move_id`
(no `summary_id`): it is a per-candidate activity ledger, not a per-component
leaf, so it is not expected to sum to a `cost_summary` row. Config:
`set_pk('sched_cost_detail', 'activity_id')` (non-auto), `set_fk(...,
'move_id', 'iteration_log', 'move_id')`.

**`priority_detail`** — one row per higher-priority deferred regular order the
move charges against.

```
priority_detail
  move_id        # FK -> iteration_log.move_id
  item           # greige id of the deferred order
  week_idx       # its week
  remaining_lbs  # its unfilled lbs
  late_day       # the selected late-delivery day (days_late used)
  weight         # w.priority
  cost           # weight × remaining_lbs × 2^late_day
```

Key-less — a flat leaf grouped by `move_id`. Config: `set_fk('priority_detail',
'move_id', 'iteration_log', 'move_id')`.

The remaining `cost_summary` components — **`level_loading`** and
**`old_machine`** — get **no leaf table** (each is a single scalar with no
sub-structure).

#### Output tables

**`production`** — the complete production ledger, **one row per `Knit`**
(folding the old per-job `production` and per-knit `xref` into one). It spans
**every candidate's plan — committed and rejected** — keyed by `move_id`, not
just the final schedule.

```
production
  knit_id    # PK (non-auto; the Knit activity's id, unique across all plans)
  move_id    # FK -> iteration_log.move_id (the candidate, committed or not)
  roll_id    # synthesized: f'{job_id}_{roll_index}' (a Roll has no id of its
             #   own); several knits may share one roll_id (a straddled roll)
  job_id     # the roll's job
  item       # greige id
  start      # the knit's start
  end        # the knit's end
  lbs        # the knit's lbs
```

Because it includes uncommitted rolls (never allocated to demand), it carries
**no roll→order link** — the resolved fill `order_id` the old `xref` held is
dropped.

**`demand`** — a copy of the regular Excel output's `demand` sheet (`order_id`,
`item`, `due_date`, `demand`, `covered_on_hand`, `remaining`).

**`unmet_demand`** — a copy of the regular `unmet_demand` sheet (`item`,
`week_idx`, `unmet_lbs`).

The regular **`late_orders`** sheet is **dropped** — the same lateness
information (per-delivery `days` / `qty` / `value`) is in `inv_cost_detail`'s
`lateness` rows.

### Phases 3+ — persistence & investigation (external)

Once the log is populated (phases 1–2), turning it into durable, browsable
output is owned by `planners/infinite/dashboard/` — **not** this module. That
work persists a run's tables to a local **MySQL** store (run-tagged by an
auto-incremented `run_id`) and investigates them through a **PyQt6** desktop app
(select a run → raw, run-scoped, paged grids with foreign-key navigation and
per-column filters). Those layers consume this module's `tables` / `schema` /
`get_df` read API and add no coupling back. See
`planners/infinite/dashboard/DESIGN.md` for that design and its phasing.
