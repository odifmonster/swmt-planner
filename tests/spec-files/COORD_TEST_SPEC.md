# Specification of coverage of coordination submodule tests

These tests target `planners/infinite/coordination/`. The submodule
exposes the order-identity types (`OrderKey`, `RegularOrder`,
`SafetyOrder`), the `ScoringContext` bundle, and four cross-candidate
functions: `eligible_orders`, `assign_priorities`,
`build_new_machine_avail`, and `build_context`.

The dataclasses are simple data containers tested transitively through
the function tests below — no logic worth covering directly.
`eligible_orders` is already covered by `INF_PLAN_TEST_SPEC.md` section
1.3.2; this file focuses on the three Phase 2 functions that don't yet
have coverage.

## Phase 2 coordination functions

### 1.1 `assign_priorities`

Builds `{OrderKey: rank}` from the eligible orders, with rank 1 the
highest priority. Three buckets in order: urgent regulars
(`week_idx <= state.reference_week_idx`), safety orders, future
regulars (`week_idx > state.reference_week_idx`). Urgent and future
regulars share an intra-bucket sort of `(due_date asc, safety_ratio
asc)`; safety orders sort by `safety_pool / safety_target` ascending.

1. **Empty state** — `state.rls_items == {}`. Output: `{}`.

2. **Single bucket — only urgent regulars** — several items with unmet
   regular orders at `week_idx <= state.reference_week_idx`; all
   safety pools at-or-above target. Verify ranks reflect the
   `(due_date asc, safety_ratio asc)` sort.

3. **Single bucket — only safety orders** — all items have demand
   fully met but `safety_pool < safety_target`. Verify ranks reflect
   ascending `safety_pool / safety_target` (largest relative depletion
   first).

4. **Single bucket — only future regulars** — items have unmet orders
   only at `week_idx > state.reference_week_idx`; safety pools at-or-
   above target. Verify ranks reflect the same `(due_date asc,
   safety_ratio asc)` sort as urgent.

5. **All three buckets together** — state contains items spanning all
   three buckets simultaneously. Verify global ordering: every urgent
   rank < every safety rank < every future rank. Intra-bucket ordering
   matches the single-bucket cases.

6. **Tie-breaker — equal due_date in the regular bucket** — two urgent
   regulars with the same `due_date` but different
   `safety_pool / safety_target` ratios. The one with the lower ratio
   ranks first.

7. **Tie-breaker — equal absolute safety gap, different targets** —
   two safety orders with the same `safety_target - safety_pool` but
   different `safety_target`. The one with the smaller relative ratio
   (`safety_pool / safety_target`) ranks first, confirming the sort is
   on the ratio rather than the absolute gap.

8. **`safety_target == 0` corner case** — an item whose Greige has
   `safety == 0`. Its relative-safety ratio resolves to `0.0` (the
   convention to avoid divide-by-zero), so its regular orders sort
   first in their bucket on the ratio tie-breaker. Safety orders never
   appear for such items (the gap is always 0).

9. **Ranks are contiguous starting at 1** — for `N` eligible orders,
   the returned values are exactly `{1, 2, …, N}`. No gaps, no
   duplicates.

10. **Reference-week advance shifts the regular/safety boundary** —
    same `rls_items` evaluated through `assign_priorities` multiple
    times with different `state.reference_week_idx` values. One item
    has a `RegularOrder` at week 2; another item has a `SafetyOrder`.
    - At `reference_week_idx == 1` (default) the week-2 regular is
      *future* → `safety_rank < regular_rank`.
    - At `reference_week_idx == 2` the week-2 regular is now
      *urgent* → `regular_rank < safety_rank`.
    Confirms `reference_week_idx` is the lever that controls bucket
    membership: the same eligible-orders set yields different
    rankings purely via the reference week.

11. **Reference-week advance promotes multiple futures at once** — a
    state with regulars at weeks 1, 2, and 3 (each on a different
    item) plus a safety order on a fourth item. Run
    `assign_priorities` three times:
    - `reference_week_idx == 1` — only the week-1 regular is urgent;
      weeks 2 and 3 sit in the future bucket *after* the safety
      order.
    - `reference_week_idx == 2` — weeks 1 and 2 are urgent (both
      ahead of safety); week 3 remains future (behind safety).
    - `reference_week_idx == 3` — all three regulars are urgent;
      they rank ahead of safety, and the future bucket is empty.
    Verify each step shifts exactly one regular across the safety
    boundary, confirming the lever's monotonic behavior.

### 1.2 `build_new_machine_avail`

Maps each `Greige` appearing in `candidates` to `True` iff at least one
of its candidate moves targets a `Machine.is_new` machine. Items not in
the candidate pool are absent from the dict.

1. **Empty candidate list** — `build_new_machine_avail(state, [])`.
   Output: `{}`.

2. **Single new-machine candidate** — one move for item `A` on a
   `Machine.is_new` machine. Output: `{A: True}`.

3. **Single old-machine candidate** — one move for item `A` on a
   legacy machine. Output: `{A: False}`.

4. **Mixed candidates for one item — True wins** — two moves for item
   `A`: one on a new machine, one on an old. Output: `{A: True}`. A
   sub-case lists the old-machine move first in `candidates` to
   confirm the result doesn't depend on iteration order.

5. **Multiple items, mixed availability** — three items: `A` has both
   new and old candidates, `B` has only old, `C` has only new. Output:
   `{A: True, B: False, C: True}`.

6. **Items absent from candidate pool** — state has rls_items `D` and
   `E`, but no candidates reference `D`. `D` is NOT a key in the
   output dict; callers using `.get(item, False)` fall through to
   `False` naturally.

### 1.3 `build_context`

Bundles the per-iteration `ScoringContext` from `state` and
`candidates`. Composition: `priorities` from `assign_priorities(state)`;
`new_machine_avail` from `build_new_machine_avail(state, candidates)`;
`earliest_dp_time` from `min(dp_time(c) for c in candidates)`, where
`dp_time` is `machine.next_job_end` for `start_at='next_job_end'` and
`machine.next_runout` otherwise — i.e., the bare DP time *before* any
carrying-avoidance idle.

1. **Standard composition** — non-empty candidates spanning multiple
   items and machines. Verify `ctx.priorities ==
   assign_priorities(state)`, `ctx.new_machine_avail ==
   build_new_machine_avail(state, candidates)`, and
   `ctx.earliest_dp_time == min(dp_time(c) for c in candidates)`.

2. **`dp_time` resolution per `start_at`** — two candidates on the
   same machine, one with `start_at='next_job_end'` (dp_time =
   `machine.next_job_end`) and one with `start_at='next_runout'`
   (dp_time = `machine.next_runout`, generally later). Verify each
   branch picks the right time.

3. **Earliest DP across multiple machines** — three candidates on
   three distinct machines with distinct DP times. Verify
   `earliest_dp_time` equals the minimum across them.

4. **Carrying-avoidance idle ignored in DP time** — a candidate whose
   `idle_for > 0` doesn't shift its DP time; `dp_time` is the
   machine's bare `next_job_end` / `next_runout`, not the post-idle
   effective start. Confirms idle isn't double-counted between
   `level_loading` and `idle_time`.

5. **Empty candidate list raises** — `build_context(state, [])` raises
   `ValueError` (via `min(...)` on an empty sequence). The main loop
   never calls `build_context` with an empty pool, so this is a
   programmer-error contract.
