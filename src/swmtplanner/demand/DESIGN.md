# Demand / Order Tracking — Design

Source of truth for the structure of `RlsItem`, `Order`, and the two fulfillment
views. Captures decisions made before implementation so the code stays small
and the math lives in one place.

## Purpose

For each released item (`RlsItem`), track weekly demand fulfillment under two
parallel accountings:

- **Raw view** — what will actually happen on the floor. The plant ships
  whatever it has, including safety stock if needed. Measures actual shipment
  lateness.
- **Safety-aware view** — what the schedule *should* be doing. Treats safety
  stock as a reserve we don't want to plan to drain. Measures how much the
  schedule would force us to draw safety down, and for how long.

The two views are kept separate because their allocation rules and cost shapes
differ enough that combining them would obscure rather than clarify.

## Inputs

`RlsItem` is constructed with:

- `greige` — product reference, source of `safety` target (scalar lbs).
- `start_date` — anchor for week 0's `due_date`. Week N's `due_date` is
  `start_date + N * 7 days`, so week 0 is due at `start_date` itself and
  the four-week horizon ends at `start_date + 21 days` (week 3).
- `on_hand_lbs` — inventory available at `start_date`.
- `lead_time` — the carry duration before which early lbs are not penalized.
- `weekly_demand` — 4 `WeeklyDemand` records (one per week, fixed horizon).

Jobs are added via `register_jobs(jobs)`. The list form exists because the
schedule layer's `plan_production` can emit multiple `Job`s from one
decision — beam exhaustion mid-production splits a single logical run into
back-to-back `Job`s separated by a `BeamLoad`, and `'next_runout'` mode
prepends `Job`s of the current item ahead of the new one. The scheduler
groups emitted `Job`s by `job.item` and registers each batch with its
`RlsItem`.

Jobs are append-only — never removed — but may be added in non-chronological
order. The internal job list is kept sorted by `job.end`, with new jobs
inserted in the correct position (e.g. via `bisect.insort`). `recompute` can
iterate the list directly without sorting.

## Core objects

```
WeeklyDemand          # plain data
  week_idx            # 0..3
  due_date
  qty_lbs

Order (HasID)         # one week's slice of one view's accounting
  rls_item
  week: WeeklyDemand
  allocated_lbs       # lbs from jobs assigned to this order by the view
  remaining_lbs       # week.qty_lbs - allocated_lbs
  is_fulfilled

SafetyAwareOrder(Order)
  # No extra attributes; allocation logic lives on SafetyAwareView.

RawOrder(Order)
  late_lbs: float                # subset of `allocated_lbs` that came
                                 # from chunks arriving past
                                 # `week.due_date`
  late_fill_date: datetime|None  # latest chunk-arrival time across the
                                 # chunks that fed `allocated_lbs` —
                                 # i.e., when the order became whole,
                                 # or (when recompute ends with
                                 # `remaining_lbs > 0`) the time of
                                 # the last job that made progress on
                                 # it. `None` when nothing was
                                 # allocated to the order at all.
  # Allocation logic still lives on RawView; `recompute` writes all
  # three per-order attributes (allocated_lbs, late_lbs,
  # late_fill_date) during the FIFO walk.

FulfillmentView (abstract)
  orders: list[Order]              # length 4, week-ordered
  recompute(jobs, on_hand, start_date, safety_target, lead_time)
  # cost components reported separately and unweighted — see Costs section

  RawView(FulfillmentView)
    lateness                       # exponential-shape scalar

  SafetyAwareView(FulfillmentView)
    drainage                       # linear lb-day scalar
    carrying                       # linear lb-day scalar
    excess                         # linear lbs scalar

RlsItem (HasID)
  start_date, greige, on_hand_lbs, lead_time
  weekly_demand: list[WeeklyDemand]  # length 4
  jobs: list[Job]                    # kept sorted by job.end on insert
  safety_view: SafetyAwareView
  raw_view: RawView
  register_jobs(jobs)
  cost_if(jobs) -> CostComponents    # pure, no mutation
  excess_lbs, replenishment_need_lbs, ...

CostComponents                       # plain named record returned by cost_if
  lateness, drainage, carrying, excess
```

`register_jobs` inserts each job into `self.jobs` (in `job.end`-sorted
order) then re-runs both views' `recompute` once after the batch.
`cost_if(jobs)` runs both views with `self.jobs + jobs` against fresh order
arrays without binding the results — gives a price-out without state change.
This is the supported way to "test" a placement; we do not expose
`unregister`.

Both methods accept a list; a single-job decision is just `[job]`. An
empty list is a no-op for `register_jobs` and yields current state's cost
for `cost_if([])`.

## Allocation — Raw view

Build a FIFO stream of lb chunks by availability time:
```
[(start_date, on_hand_lbs)] + [(job.end, job.lbs) for job in jobs sorted by end]
```

Walk weeks 0..3 in order. For each week, pull from the stream until the week's
`qty_lbs` is satisfied or the stream is empty. Each pulled lb is stamped with
its `availability_time`; if `availability_time > week.due_date`, that lb is
late by `availability_time - week.due_date`.

`RawOrder.allocated_lbs` includes both on-time and late lbs (per
"the plant ships whatever it has"). The same walk also writes two
per-order late-reporting attributes:

- `RawOrder.late_lbs` — the subset of `allocated_lbs` whose
  `availability_time > week.due_date`. The view-level `lateness`
  scalar still aggregates the exponential lb-day cost; `late_lbs` is
  the raw lbs view that the scheduler turns into an operator-facing
  table.
- `RawOrder.late_fill_date` — the latest `availability_time` across
  the chunks that contributed to `allocated_lbs`. When the order is
  fully filled, this is the moment it became whole; when recompute
  ends with `remaining_lbs > 0`, it's the time the last contributing
  job made progress on it (so the scheduler can still report a
  meaningful "filled by" date even for orders with unmet demand).
  Stays `None` for orders with `allocated_lbs == 0`.

Anything left in the stream after week 3 is fully covered = excess. The raw
view ignores excess and carrying — it only cares about lateness.

## Allocation — Safety-aware view

Process jobs in `job.end` ascending order. Treat `on_hand` as a pseudo-job at
`t = start_date` and feed it through the same rule.

For each job, let `O` = the earliest order whose `due_date >= job.end`
(the nearest on-time order). The job's lbs are distributed by this priority:

1. **Cumulative unfilled demand across orders `0..O`**, filling earliest week
   first. If earlier orders are unfilled, the job pays them down *late* before
   touching `O`. This matches reality: late material catches up missed
   shipments before it backs further-out work.
2. **Refill the safety pool** toward `safety_target`.
3. **Later on-time orders** — orders after `O`, in week order.
4. **Excess** — any remainder.

If a job is late to all 4 orders (no `O` exists), bucket 1 spans all four
orders (earliest-first), and bucket 3 is empty.

## Safety pool dynamics

`safety_pool(t)` is a step function:

- **Increases** at `t = job.end` when bucket 2 receives lbs (jobs filling the
  pool toward target).
- **Increases** at `t = job.end` when bucket 1 receives lbs that fill a
  *late* order — those lbs effectively refund the safety drained earlier to
  cover that order.
- **Decreases** at `t = order.due_date` by the order's on-time gap
  (`week.qty_lbs - on_time_job_lbs_assigned_to_this_order`). This is reality
  draining safety to ship on time.

The pool's initial value at `t = start_date` follows from feeding `on_hand`
through the per-job rule: it goes to week 0's demand first, then safety, then
later weeks. So safety only starts "full" if `on_hand > week_0.qty + target`.

## Costs

The demand layer defines the *shape* of each cost (linear vs. exponential,
lb-day vs. lb) and produces an **unweighted** scalar for each. The scheduling
program owns the weights (and any other shape parameters that need to be
tunable, e.g. the exponential rate for lateness) and combines the scalars into
whatever objective it wants. Keeping the weights out of this layer means the
tunable knobs live in one place — the scheduler's config — rather than being
hard-coded inside `demand/`.

Each cost is exposed as its own attribute on the relevant view, and `cost_if`
returns all four components separately rather than pre-combined.

### Raw view

**`lateness`** — exponential-shape lb-day quantity. Each lb assigned to an
order has an `availability_time`; if it's past `due_date`, that lb accrues
contribution for each day it stays past due, weighted by **`2 ** days_late`**
(the cost doubles for each additional day). This approximates the real-world
tiered shape (expedite → supply-chain disruption → customer loss) while
keeping the curve monotonically increasing past the last real tier. The
doubling factor is hard-coded in the view for now; if it needs to change we
revisit then. The raw view reports nothing else — no carrying, no excess.

### Safety-aware view

**`drainage`** — linear lb-day integral of `max(0, safety_target -
safety_pool(t))`. Integrated from `start_date` to `min(last_due_date,
time_pool_returns_to_target)`. Drainage that persists past the last due date
is not modeled further — at that point the raw view's `lateness` takes over
conceptually.

**`carrying`** — linear lb-day quantity. Per lb-day past `lead_time` for lbs
sitting in bucket 3 before their target order's due date.

For `X` lbs assigned to a later on-time order with due date `D` from a job
ending at `T`, the contribution is:
```
X * max(0, (D - T) - lead_time)
```
Bucket 1 (nearest cumulative demand) and bucket 2 (safety) never contribute
to `carrying` — refilling safety should not be discouraged.

**`excess`** — linear lbs quantity. Total lbs in bucket 4 (beyond all demand
and a full safety pool). The scheduler weights this more aggressively than
`carrying`: the plant has limited warehouse space and is currently renting
overflow storage, so a schedule that plans excess is actively bad.

## Order-level reporting in the safety view

This is the key non-obvious behavior:

- `SafetyAwareOrder.remaining_lbs = week.qty_lbs - lbs_filled_by_jobs`
  (jobs, whether on-time or late, count — those lbs are now on the schedule).
- An order with on-time-job-gap covered only by safety drainage **still
  reports a positive `remaining_lbs`**, because those lbs are not yet on the
  schedule. The drainage is a cost, not a fulfillment.
- The same gap becomes `remaining_lbs == 0` only after a job is added that
  assigns lbs to that order (late or on-time).

This is what tells the scheduler "you still need to plan to produce this,
even though reality would limp through on safety."

## RlsItem aggregates

Derived from the two views and the job list:

- `scheduled_lbs` — sum of `job.lbs` for `self.jobs`.
- `total_demand_lbs` — sum of `week.qty_lbs` over the 4 weeks.
- `excess_lbs` — `max(0, scheduled_lbs - total_demand_lbs)`. Useful as a
  fast scalar; the safety view's `excess` cost component is the authoritative
  penalty quantity.
- `replenishment_need_lbs` — sum of `safety_view.orders[i].remaining_lbs`
  plus any safety shortfall at horizon end. This is "what the scheduler still
  has to place."
- No `total_cost` here. Cost components are exposed separately via the views
  and via `cost_if`; the scheduler combines them.

## File I/O

The demand submodule owns its own input format — the planner's CLI
doesn't know how a demand spreadsheet is structured. Exported reader:

```
read_rls_items(
    path: Path, *, start_date: datetime,
    greige_by_id: dict[str, Greige],
) -> dict[str, RlsItem]
```

`path` points to an Excel (.xlsx) workbook with one row per released
item. Per-row fields: greige id (looked up in `greige_by_id` for the
`Greige` instance), on-hand lbs, lead time, and the weekly demand
series. Item-side fields (yarn, tgt_wt, safety, machines) come from
the resolved `Greige`, not from the demand file — those are products-
submodule data.

No writer is exported from `demand/`: the human-readable output of a
planning run is the `PlanReport`'s per-item job snapshot, written by
the top-level CLI in `planners/infinite/`.

## Test-placement contract

```
rls_item.cost_if(hypothetical_jobs) -> CostComponents(lateness, drainage,
                                                      carrying, excess)
```

Internally runs each view's `recompute` against `self.jobs + hypothetical_jobs`
on throwaway order arrays. Pure; does not touch `self.jobs` or
`self.{raw,safety}_view.orders`. Cheap because recompute is O(jobs × weeks)
with weeks fixed at 4. All four scalars are unweighted — the scheduler
applies its weights to compare placements.

## Out of scope

- **Substitution** — using a different SKU to fulfill demand. Happens
  occasionally in reality (decided at the dyeing facility, requires testing
  and approval) but we do not plan for it. `RlsItem` stays the sole owner of
  jobs of its item.
- **Job removal / rollback** — jobs are append-only. The test-placement
  contract above covers "what-if" without needing an unregister path.
- **Cross-item interactions** — no shared resources modeled at the RlsItem
  level. Sequence-dependent costs on machines are the scheduler's concern,
  not the order's.
