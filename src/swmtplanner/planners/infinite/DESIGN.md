# Infinite Plant — Knitting Planner — Design

Top-level planner for the Infinite Knitting plant. Composes `schedule/`
(per-machine scheduling) and `demand/` (per-item fulfillment costing) into
a global optimizer that decides which greige to produce on which machine,
in what quantity, and in what order across the 4-week planning horizon.

This planner targets the knitting plant only. The broader project's end
goal is an end-to-end supply-chain planner; downstream (dyeing,
finishing) lives in separate future submodules.

## Purpose

Given:

- A set of knitting machines, each with its initial threading and
  schedule (`Machine` instances).
- A set of released greige items, each with weekly demand, on-hand
  inventory, and lead time (`RlsItem` instances).
- A cost-weighting configuration.

Produce:

- A committed schedule on each `Machine` (its `activities` populated via
  `add_activities`).
- Matching `Job` registrations on each `RlsItem` (`register_jobs`).
- A summary of the resulting cost components and any unmet demand.

The planner introduces no new physical concepts. Its job is to choose
*placements* — `(machine, item, lbs, start_at, idle_for)` tuples — by
composing the existing `schedule/` and `demand/` operations.

## Inputs

The planner is invoked against:

- `machines: dict[str, Machine]` — keyed by machine id, already
  constructed with their initial state.
- `rls_items: dict[str, RlsItem]` — keyed by greige id, already
  constructed with weekly demand and on-hand inventory.
- `start_date: datetime` — the planning anchor; matches each
  `RlsItem.start_date`.
- `weights` — cost-weighting config that the costing module consumes
  (see below).

Constructing these from spreadsheets is a separate concern; the planner
takes them ready-made.

## High-level structure

Three modules under `infinite/`. Each has a single, well-defined
responsibility, and the main loop only knows the surface of each rather
than the internals.

### `state/`

The plant-wide state. A bag of data plus its mutation operations.

```
State
  machines: dict[str, Machine]
  rls_items: dict[str, RlsItem]
  start_date: datetime
  # query helpers as needed (e.g. eligible machines for an item,
  # remaining unmet demand for an rls_item/week, etc.)
  commit_move(move) -> None
```

`State` is a thin container. Its primary purpose is to let any function
take `state` as a single argument rather than threading a half-dozen
dicts through call signatures. It also owns `commit_move`, the
incremental-update operation that mutates both `Machine` and `RlsItem`
in lockstep when a placement is accepted. Keeping that update logic in
`state/` rather than in the main loop keeps the loop short and gives us
a single point of truth for "what does it mean to commit a move".

### `costing/`

Scores any `State` as a single scalar. Three ingredients combined into
one number:

1. **Weighted sum of per-item demand costs.** For each `RlsItem`, read
   the four `CostComponents` (`lateness`, `drainage`, `carrying`,
   `excess`) from its raw and safety views and multiply by their
   respective weights. Sum across all rls_items.

2. **Per-occurrence changeover penalties.** Fixed costs added once per
   occurrence of expensive changeover activities anywhere in the
   committed plant schedule. Captures "we'd rather not do this even if
   the time fits". Phase-1 set:
   - One cost per `TapeOut(bars='top')` / `TapeOut(bars='btm')`
     (single tape-out).
   - One cost per `TapeOut(bars='both')` (double tape-out).
   - One small cost per `StyleChange(is_family_change=True)`
     (family change).

   The time these activities consume is *already* reflected in
   downstream activity start times — these weights are extra
   discouragement on top of that.

3. **Cross-cutting aggregates** (Phase 2+). Penalties on plant-wide
   state metrics that can't be captured by any single item's view in
   isolation — e.g. overproducing one item while another goes unmet, or
   piling work onto one machine while others sit idle. Likely terms:
   - Plant-wide total excess across all items.
   - Machine-utilization imbalance (variance across machines).
   - Aggregate changeover time.

   The exact set evolves with the phasing (see below).

```
CostWeights
  # per-item demand weights (Phase 1)
  lateness, drainage, carrying, excess: float
  # per-occurrence changeover weights (Phase 1)
  tape_out_single, tape_out_both, family_change: float
  # plant-wide aggregate weights (Phase 2+)
  total_excess, util_imbalance, changeover_total: float

Costing
  score(state) -> float                          # current state's score
  score_after_move(state, move) -> float         # post-commit score, pure
```

`score_after_move` is the loop's hot path. It computes what `score`
would return if `move` were committed, without actually mutating
anything — built on `RlsItem.cost_if(jobs)` for the demand-side
contributions and on inspecting `move.plan` for the schedule-side
changeover contributions.

### `loop/`

The main iteration. Greedy: at each step, score every candidate move
and commit the one with the lowest resulting state score.

```
Move
  machine_id: str
  item: Greige
  lbs: float
  start_at: Literal['next_job_end', 'next_runout']
  idle_for: timedelta
  plan: list[Activity]    # cached output of machine.plan_production

plan(state, costing) -> PlanReport
```

`plan` is the entrypoint. It iterates:

1. **Enumerate** candidate `Move`s from the current state — for each
   `(rls_item, week_idx)` with unmet demand, propose a move on each
   eligible machine.
2. **Score** each candidate via `costing.score_after_move(state, move)`.
3. **Commit** the lowest-scoring move via `state.commit_move(move)`.
4. **Repeat** until no candidate is producible (`producible_lbs == 0`
   everywhere) or no candidate would improve the score.

`PlanReport` is the artifact the operator actually consumes. Returned at
the end of `plan`:

```
PlanReport
  # the planned schedule — the headline output of the planning tool
  schedules: dict[str, tuple[Activity, ...]]    # machine_id -> activities
  jobs_by_item: dict[str, tuple[Job, ...]]      # greige_id -> jobs registered
  # final cost picture
  total_score: float
  cost_components_by_item: dict[str, CostComponents]
  # what couldn't be placed
  unmet_lbs_by_item_week: dict[tuple[str, int], float]
```

The full schedules also remain on the `Machine` instances inside
`state`; the report bundles them into a self-contained snapshot so
callers can persist or render without holding the mutable `State`
around.

## End-to-end workflow

```
state = State(machines, rls_items, start_date)
costing = Costing(weights)
report = plan(state, costing)
# state has been mutated; report summarizes the result
```

The post-call `state` is the deliverable — machines now carry the
committed activities, rls_items now carry the registered jobs.

## Phases

Like the `schedule/` rollout, the planner is built up in phases. Each
phase produces a working end-to-end planner; later phases improve
optimization breadth and quality rather than adding new capabilities.

### Phase 1 — basic greedy

The minimum viable planner.

- `state/`: `State` data class with machines, rls_items, start_date,
  and `commit_move`. No undo / no snapshots — the loop is monotonic.
- `costing/`: `CostWeights` with the four per-item demand weights
  (`lateness`, `drainage`, `carrying`, `excess`) and the three
  per-occurrence changeover weights (`tape_out_single`,
  `tape_out_both`, `family_change`). `score` is the weighted sum of
  per-item `CostComponents` plus a count-weighted sum of changeover
  activities in the schedule. No cross-cutting aggregates yet.
- `loop/`: greedy `plan` as described above. For each
  `(eligible_machine, item, week_idx)` with `producible_lbs > 0`,
  propose one move sized at `min(unmet_lbs, producible_lbs)` — the
  unmet gap for the week, capped by what the machine can actually
  produce. `start_at` and `idle_for` use defaults (`'next_job_end'`,
  `timedelta(0)`); finer control comes in later phases.
- Termination: no candidate has `producible_lbs > 0`, or the best
  candidate doesn't decrease the score.

Delivers: a planner that produces feasible end-to-end schedules.

### Phase 2 — cross-cutting cost aggregates

- Extend `CostWeights` and `Costing.score` with plant-wide penalty
  terms (total excess, util imbalance, changeover total).
- Avoids globally-bad-but-locally-fine decisions that Phase 1 can't
  see (e.g., committing every cycle to one machine while others idle).

### Phase 3 — multi-machine parallel placement for high-volume items

- Some items demand more lbs per week than any single machine can
  produce. Phase 1's per-machine greedy can stumble into this by
  loading sequential cycles onto one machine, but Phase 3 makes
  *coordinated splits* explicit.
- Enumerator gains "allocation moves" — proposals to split one
  `(item, week)` demand across multiple machines simultaneously.
- Candidate space could explode if any subset of machines is fair game;
  restrict to natural patterns (even split across all eligible
  machines with available capacity in that week).

### Phase 4 — local search post-pass

- After Phase 1–3 produce a greedy baseline, run a local-search pass
  that tries swap/replace operations on already-committed moves to
  reduce the total score.
- Requires either reversible state updates (undo) or operating on
  state snapshots. Probably introduces a `state.snapshot()` method or
  a copy-on-write variant of `commit_move`.

## Out of scope

- **Downstream supply chain.** Dyeing and finishing are handled by
  future separate planners. This planner stops at greige production.
- **Input construction.** Building `Machine` / `RlsItem` instances from
  spreadsheets or other operational inputs is a separate concern; the
  planner consumes them ready-made.
- **Output formatting.** The planner returns data (a `PlanReport` and a
  mutated `State`); rendering for human consumption is downstream.
- **Mid-plan demand changes.** The planner assumes demand and on-hand
  inventory are fixed for the duration of a single `plan` call.
- **Multi-week look-ahead beyond greedy.** Phase 4's local search is
  the deepest non-greedy optimization in scope; full
  dynamic-programming or solver-based optimization is out.
