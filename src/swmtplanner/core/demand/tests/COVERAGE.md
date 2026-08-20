# demand — Test Coverage

Test coverage for the `core/demand/` submodules (`unittest`).

## Section 1 — `requirement`

The `Requirement` hierarchy is lightweight: construction plus the one computed
property (`remaining`). The "abstract" classes are abstract only in their `id`,
so the tests use small concrete subclasses. `FabReq` is a `Requirement` whose
`item` is a `Fabric` and whose `id` is just the fabric's id.

Note: testing `Requirement` (via `FabReq`) effectively tests `Safety` as well —
`Safety` adds nothing beyond its `id` format (`'S@<item id>'`), so its `remaining`
/ `allocated_qty` behavior is identical and only the `id` needs a separate,
trivial check.

### 1.1 `Requirement` (via `FabReq`)

The only interesting behavior is the computed
`remaining = max(0.0, init_qty - covered_on_hand - allocated_qty)`, so these
cases walk different initial values and confirm it tracks `allocated_qty` updates
correctly. `allocated_qty` starts at `0.0` and is settable.

1. **All zeros** — `init_qty = 0`, `covered_on_hand = 0` (empty requirement,
   nothing on hand). `remaining` starts at `0`; increasing `allocated_qty` keeps
   it at `0`.
2. **Zero init, positive on-hand** — `init_qty = 0`, `covered_on_hand > 0`.
   `remaining` starts at `0` and stays `0` as `allocated_qty` increases.
3. **Positive init, zero on-hand** — `init_qty > 0`, `covered_on_hand = 0`.
   `remaining` starts at the full `init_qty` and goes down by the amount
   allocated as `allocated_qty` increases, with a floor of `0` (once the
   allocation meets or exceeds `init_qty`).
4. **Positive init, on-hand < init** — `init_qty > 0`,
   `0 < covered_on_hand < init_qty`. `remaining` starts at
   `init_qty - covered_on_hand` and goes down by the allocated amount as
   `allocated_qty` increases (floor of `0`).
5. **Positive init, on-hand > init** — `init_qty > 0`,
   `covered_on_hand > init_qty`. `remaining` starts at `0` and stays `0` as
   `allocated_qty` increases.

### 1.2 `Order` and `RawOrder`

Both are built directly with a `Fabric` item — no concrete subclass needed.
`RawOrder` extends `Order` with late-arrival tracking. `remaining` is already
covered by 1.1, so these tests exercise the id / week-offset and late-calculation
logic.

#### 1.2.1 `Order.id` and `Order.week_offset`

These tests focus on `id` and `week_offset`, which depend on the ISO-calendar
relationship between `first_week` (an `(ISO year, ISO week)` pair) and `due_date`.
`id` is `f'P{week_offset}-{iso_weekday}@{item.id}'` (`iso_weekday` = Mon 1 … Sun
7); `week_offset` is the count of whole ISO weeks from `first_week` to the
`due_date`'s ISO week.

For each `first_week` scenario below, verify the full matrix of outcomes —
offset ∈ {0, 2, −1} × iso_weekday ∈ {1, 3, 6} — checking **both** the `id`
string (e.g. `'P2-3@<fabric id>'`) and the `week_offset` value:

- `P0-1`, `P0-3`, `P0-6` — due in the `first_week` itself (offset 0);
- `P2-1`, `P2-3`, `P2-6` — due two weeks later (offset 2);
- `P-1-1`, `P-1-3`, `P-1-6` — due one week earlier, i.e. past due by a week
  (offset −1).

The three `first_week` scenarios stress different calendar quirks:

1. **Mid-year `first_week`** — a week comfortably inside the year; baseline, no
   year-boundary effects.
2. **Year-crossing `first_week`** — a week whose Monday and Friday fall in
   different calendar years (an ISO week straddling Dec–Jan). The `P0` outcomes
   then include due dates whose *calendar* year differs from their ISO year,
   confirming `id` / `week_offset` key off the ISO week, not the calendar year.
3. **Near-year-end `first_week`** — a week roughly one week before year-end, so
   the `P2` outcomes land in the following ISO year; confirms `week_offset`
   counts correctly across the year boundary (including 52- vs 53-week years).

#### 1.2.2 `RawOrder` late calculations

`RawOrder` sorts each added chunk into on-time (`avail_date <= due_date`) or late
(`avail_date > due_date`) and reports over the late ones: `late_qty` (total late
quantity), `late_fill_date` (latest late `avail_date`, or `None`), and
`late_table()` (`(avail_date - due_date, qty)` pairs, sorted by `avail_date`).
These tests only add/clear chunks — they do **not** touch `allocated_qty` in
parallel, since `remaining` is covered by 1.1 and is independent of the late
calculations.

1. **Empty after construction** — a fresh `RawOrder` (no chunks): `late_table()`
   is `[]`, `late_qty` is `0`, `late_fill_date` is `None`.
2. **All on-time chunks** — add several chunks all with `avail_date <= due_date`
   (out of chronological order): the late values stay empty (`late_table() ==
   []`, `late_qty == 0`, `late_fill_date is None`).
3. **One late chunk** — add a single chunk with `avail_date > due_date`:
   `late_qty` equals that chunk's `qty`, `late_fill_date` equals its
   `avail_date`, and `late_table()` is `[(avail_date - due_date, qty)]`.
4. **Multiple late chunks, out of order** — add several late chunks in
   non-chronological order: `late_qty` is their total, `late_fill_date` is the
   latest `avail_date`, and `late_table()` lists all of them as `(lag, qty)`
   sorted by `avail_date` ascending.
5. **Mixed late + on-time, out of order** — add a mix of on-time and late chunks
   in non-chronological order: only the late chunks contribute (correct split) —
   `late_qty` / `late_fill_date` reflect just the late ones, and `late_table()`
   contains only the late chunks, sorted by `avail_date`.
6. **Clear resets** — after populating with late (and on-time) chunks,
   `clear_chunks()` returns everything to the construction state (`late_table()
   == []`, `late_qty == 0`, `late_fill_date is None`).

## Section 2 — `view`

Covers `DemandView` and its concrete subclasses. The `DemandView` base is very
light (item / orders holders + an abstract `recompute`) and is left untested
directly; `SafetyOrder` adds nothing to `Order` and is likewise left alone.

### 2.1 `RawView`

Shared setup: a `RawView` over six `RawOrder`s built with a `Fabric` item and
`covered_on_hand = 0` (netting happens at the `RlsItem` level), one per
consecutive week so their ids are `P0-2` … `P5-2` — each due on the Tuesday
(iso_weekday 2) of week offsets 0–5 from a common `first_week`. Each order has a
positive `init_qty`; chunk quantities are chosen to fill or split them as each
case requires.

Each test drives the view the way `RlsItem` will: keep a running list of chunks,
**append chunks in chronological order** (by `avail_date`, as `recompute`
expects) and call `recompute(chunks)` after each append. After *every* append
verify:

- every order's `remaining`;
- every order's `late_table()`, `late_fill_date`, and `late_qty`;
- the view's `lateness`.

#### 2.1.1 Whole-order fills (no splitting)

1. **One early chunk fills everything** — a single chunk available before the
   first order's due date, sized for all six orders. Every order fully filled
   (`remaining == 0`) and on time (empty late tables, `late_qty == 0`,
   `late_fill_date is None`); `lateness == 0`.
2. **One late chunk fills everything** — a single chunk available one day after
   the last order's due date, sized for all six orders. Every order fully filled
   but late — each order's late table holds its portion at its own lag,
   `late_qty == init_qty`, `late_fill_date` is the chunk's `avail_date`;
   `lateness` is the summed penalty.
3. **One on-time chunk per order** — six chunks (appended earliest first), the
   i-th available on/before the i-th order's due date and sized exactly to that
   order. After each append the just-covered order reaches `remaining == 0` on
   time (no late entries) while later orders remain unfilled; `lateness` stays
   `0` throughout.
4. **One late chunk per order** — six chunks, the i-th available one day after
   the i-th order's due date, sized exactly to that order. After each append the
   corresponding order is fully filled but one day late (single late-table entry,
   `late_qty == init_qty`, `late_fill_date == avail_date`); `lateness` grows by
   that order's penalty at each step.

#### 2.1.2 Split fills (a chunk spanning orders / an order spanning chunks)

1. **Late first, then forward on-time** —
   - chunk 1 (after the first order's due, on/before the second's): fills the
     whole first order (late) and part of the second (on time);
   - chunk 2 (after the second order's due): fills the remainder of the second
     order (late);
   - chunk 3 (before the third order's due): fills all remaining orders (third …
     sixth) on time.
2. **First order split across two late chunks** —
   - chunk 1 (after the first order's due, on/before the second's): fills part of
     the first order (late);
   - chunk 2 (after chunk 1, still on/before the second order's due): fills the
     remainder of the first order (late) and the whole second order (on time);
   - chunk 3 (on/before the third order's due): fills the remaining orders on
     time. (The first order ends with two late-table entries.)
3. **Several chunks mid-sequence, splitting both ways** —
   - chunks A (two or more, after the second order's due but before the third's):
     together fill the first and second orders (late) and part of the third (on
     time);
   - chunk B (before the third order's due, after chunks A): fills the remainder
     of the third order and part of the fourth (both on time);
   - chunk C (a final chunk on/before the fourth order's due): fills the
     remainder of the fourth order and the fifth and sixth orders on time.
4. **Back-fill from after the last due date** — multiple chunks, all available
   after the last order's due date, back-filling the orders starting from the
   first (each filled in due order across the chunks); every filled portion is
   late, so late tables / `late_fill_date` / `late_qty` and `lateness` accumulate
   as chunks are appended.

### 2.2 `SafetyView`

Shared setup: a `SafetyView` over the same six orders as 2.1 — `SafetyOrder`s
`P0-2` … `P5-2` (Tuesdays of consecutive weeks). Unlike 2.1, these tests **set
the netted starting state directly** — the orders' `covered_on_hand`, plus the
view's `safety_tgt` / `safety_on_hand` / `on_hand` / `today` — since netting is
external to the view. As in 2.1, drive the view by appending chunks in
chronological order and calling `recompute(chunks)` after each. After every step
verify: each order's `remaining`, the `safety` requirement's `allocated_qty` and
`remaining`, and the view's `carrying`, `drainage`, and `excess`.

Recall the three penalties: **carrying** accrues when a chunk fills an order
whose due date is more than `lead_time` after the chunk's `avail_date` (supply
produced "early"); **drainage** accrues while the physical pool (starting at
`on_hand`, drained by each order's full `init_qty` at its due date, refilled by
chunks) sits below `safety_tgt`; **excess** is supply beyond all demand plus the
safety target. A short `lead_time` (less than the one-week order spacing) is used
where "early" fills are needed.

The tests split into targeted cases (2.2.1 — no penalties, or exactly one of the
three activated) and mixed cases (2.2.2).

#### 2.2.1 Targeted penalties (one type at a time)

**No penalties**

1. P0 and safety start fully covered (`P0.covered_on_hand == P0.init_qty`,
   `safety_on_hand == safety_tgt`, `on_hand == P0.init_qty + safety_tgt`). Each
   subsequent chunk arrives within `lead_time` before its order's due date, sized
   exactly to that order (P1 … P5). Every order ends filled on time, safety stays
   full, and `carrying == drainage == excess == 0` at every step.

**Excess only**

2. Same setup as (1), but the chunk filling P5 is larger than P5's requirement.
   With safety already full and no later orders, the surplus lands in `excess`;
   `carrying == drainage == 0`.

**Carrying only** (P0 + safety covered; short `lead_time` so filling a later
week's order counts as "early")

3. **One chunk covers P1 and P2** — the first chunk (arriving near P1's due)
   fills all of P1 (on time) and all of P2 (early → carrying); the remaining
   chunks fill P3–P5 within lead. Only `carrying > 0`.
4. **One chunk covers P1, P2, and P3** — the first chunk (arriving near P1's due)
   fills all of P1 (on time) and all of P2 and P3 (both early → carrying); the
   remaining chunks incur no costs. Only `carrying > 0`.
5. **One chunk covers P1 and part of P2** — the first chunk fills all of P1 (on
   time) and part of P2 (early → carrying); a later chunk fills the rest of P2
   (and beyond) on time. Only `carrying > 0`.
6. **Carrying across two chunks** — chunk 1 fills P1 on time and part of P2
   (early → carrying); chunk 2 fills the remainder of P2 on time and part of P3
   (early → carrying); the remaining chunks fill on time. `carrying` accumulates
   over the two early portions; `drainage == excess == 0`.
7. **All up front** — a single chunk before P1's due fills every remaining order
   (P1 on time, P2–P5 all early → carrying on each). Large `carrying`, no
   drainage or excess.

**Drainage only** (chunks fill near-term demand / safety only — no early fills,
no leftover)

8. **P1 from safety, safety unrefilled until the end** — `on_hand` covers P0 +
   safety; nothing is produced before P1's due, so P1 is met out of safety and
   the pool drops below target at P1's due. Later chunks meet subsequent demand
   but leave safety short until a final chunk (after P5's due) restores it;
   `drainage` accrues over that whole below-target span. `carrying == excess == 0`.
9. **Rebuild safety over the first chunks** — `on_hand` covers only P0
   (`safety_on_hand == 0`, so safety starts drained). Chunk 1 fills P1; chunk 2
   fills P2 and half the safety target; chunk 3 fills P3 and the remaining half;
   later chunks fill P4/P5 on time. The pool sits below target until safety is
   fully rebuilt (chunk 3), where `drainage` stops. `carrying == excess == 0`.
10. **Safety drained across two orders, then restored** — `on_hand` covers P0 +
    safety. Chunk 1 fills only part of P1, the rest drawn from safety (pool below
    target); chunk 2 fills only part of P2, drawing the remaining safety (pool
    further below); then the schedule catches up fully before P3 (demand and
    safety both restored) and the remaining chunks fill on time. `drainage`
    accrues over the drawn-down span; `carrying == excess == 0`.

#### 2.2.2 Mixed penalties

Same setup and drive as 2.2.1; each case activates two or three penalties at
once. Keeping a penalty *off*: no carrying ⟺ no chunk fills an order more than
`lead_time` early; no drainage ⟺ the pool never dips below `safety_tgt`; no
excess ⟺ total supply equals demand + safety exactly. The cases deliberately mix
orders filled by several chunks and chunks spanning several orders.

**Carrying + excess** (safety stays covered, so no drainage)

1. **One over-large early chunk** — P0 + safety covered; a single chunk arriving
   before P1's due, larger than the total remaining demand: fills P1 on time and
   P2–P5 early (carrying) and overshoots (excess). [one chunk → many orders]
2. **Split order plus a tail overshoot** — P0 + safety covered; chunk 1 (near
   P1's due) fills P1 on time and part of P2 early (carrying); chunk 2 (near P2's
   due) fills the rest of P2 on time; P3/P4 on time; a final chunk before P5's
   due fills P5 and overshoots (excess). [P2 filled by two chunks + tail excess]
3. **Two early multi-order chunks plus overshoot** — P0 + safety covered; chunk 1
   (before P1's due) fills P1 + P2 (P2 early → carrying); chunk 2 fills P3 + P4
   (P4 early → carrying); an over-large chunk before P5's due fills P5 and
   overshoots (excess).

**Drainage + excess** (no early fills, so no carrying)

4. **P1 from safety, tail overshoot** — P0 + safety covered; nothing before P1's
   due, so P1 is met from safety (drainage) and safety is replenished before P2's
   due; P2–P5 filled on time; one extra chunk before P5's due exceeds P5's demand
   (excess).
5. **Partial P1 draw, rebuilt, then overshoot** — P0 + safety covered; chunk 1
   fills part of P1 with the rest from safety (drainage); chunk 2 fills the
   remainder of P1 and refills safety before P2; P2–P5 on time; an over-large
   final chunk overshoots (excess). [P1 filled by two chunks]
6. **Safety uncovered at start, later overshoot** — `on_hand` covers only P0
   (`safety_on_hand == 0`); safety is rebuilt over the first couple of chunks
   (drainage until then) with all orders filled on time; a later oversized chunk
   overshoots total demand (excess).

**Drainage + carrying** (supply equals demand + safety exactly, so no excess)

7. **Safety fills P1–P2, then an early catch-up chunk** — P0 + safety covered;
   nothing before P1/P2's dues, so both are met from safety (drainage); then a
   single large chunk before P3's due replenishes safety, fills P3 on time, and
   fills P4 early (carrying). P5 on time. Sizes exact (no overshoot).
8. **Partial draw plus a multi-order early chunk** — P0 + safety covered; chunk 1
   fills part of P1, the rest from safety (drainage); chunk 2 (before P2's due)
   refills safety, fills P2 on time, and fills P3 + P4 early (carrying); the rest
   on time, exact sizes. [chunk spanning safety + several orders]
9. **Safety uncovered plus early over-provision to a future order** — `on_hand`
   covers only P0 (`safety_on_hand == 0`, drainage until rebuilt); an early chunk
   rebuilds safety and fills a later order (e.g. P3) ahead of its lead window
   (carrying) while nearer orders are covered on time; sizes exact (no excess).

**All three**

10. **Catch-up chunk that overshoots** — the 2.2.2.7 scenario (safety fills P1–P2
    → drainage; catch-up before P3 replenishes safety and fills P3), plus a chunk
    before P4's due larger than P4 + P5 combined: it fills P4 on time, P5 early
    (carrying), and overshoots (excess). Drainage + carrying + excess.
11. **Partial draw, split order, early fill, overshoot** — P0 + safety covered;
    chunk 1 fills part of P1, the rest from safety (drainage); chunk 2 refills
    safety and fills the rest of P1 and all of P2 on time; an early chunk fills P3
    on time and P4 early (carrying); a final over-large chunk before P5 fills P5
    and overshoots (excess).
12. **Safety uncovered, early multi-order chunk, overshoot** — `on_hand` covers
    only P0 (`safety_on_hand == 0`, drainage until rebuilt); an early over-large
    chunk rebuilds safety, fills the near order on time and a later order early
    (carrying), and overshoots total demand (excess).

#### 2.2.3 Chunk pairing — single chunk

`recompute` returns the `(chunk, first-fill priority)` pairs. These cases
register **exactly one chunk**; the surrounding state is created entirely by
the initial `covered_on_hand` values (and `safety_on_hand`). Terminology: a
chunk is *early* for an order when the order is due beyond the chunk's horizon
(`due > avail_date + lead_time` — future demand, step 3), *on time* when the
order falls within the horizon (step 1), and *late* when
`avail_date > due_date` (still step 1 — a past-due order is always near-term);
safety (step 2) sits between the two steps.

1. **On-time fill** — one open order due inside the chunk's horizon, chunk
   arriving before the due date: one pair, the order's `week_offset`.
2. **Late fill** — the chunk's `avail_date` is past the open order's
   `due_date`: still pairs with the order's `week_offset` (lateness itself is
   `RawView`'s concern, not the pairing's).
3. **Early fill, safety pre-covered** — safety fully covered
   (`safety_on_hand == safety_tgt`); the only open order is due beyond the
   chunk's horizon: the chunk skips to future demand and pairs with that
   order's `week_offset`.
4. **Early fill, safety short** — same, but safety has `remaining`: the
   chunk's first quantity goes to safety, so the pair is `'S'` (the remainder
   fills the future order).
5. **Safety only** — all orders covered on hand, safety short: the pair is
   `'S'`.
6. **Order fill without touching safety** — safety short, chunk exactly
   consumed by a near-term order (`qty <= remaining`): the order's
   `week_offset`, and the safety allocation is unchanged.
7. **One chunk, multiple orders** — the chunk spans the tail of order A and
   part of order B (both near-term): exactly one pair, with A's `week_offset`
   (the first order to use part of the chunk).
8. **One chunk, order + safety** — the chunk finishes the last near-term
   order and the overflow goes to safety: the order's `week_offset`, not
   `'S'`.
9. **Fully covered → no pair** — every order *and* safety covered on hand:
   the chunk allocates nothing (pure excess) and `recompute` returns no
   pairs.

#### 2.2.4 Chunk pairing — multiple chunks

The same target scenarios as 2.2.3, but the surrounding requirements are
covered by **other chunks** in the same `recompute` rather than by
`covered_on_hand`; every chunk's pairing is asserted.

1. **On-time fill** — chunk A fills the earlier order (pair: its
   `week_offset`); chunk B fills its own order on time (pair: its
   `week_offset`).
2. **Late fill** — chunk A covers the earlier order; chunk B arrives past the
   second order's due date: pair is the second order's `week_offset`.
3. **Early fill, safety covered mid-pass** — chunk A tops up safety (pair:
   `'S'`); chunk B, early for the remaining order, pairs with that order's
   `week_offset` — the pairing reacts to safety state as it evolves within
   one pass, not just to the initial netting.
4. **Early fill, safety short** — chunk A fills all near-term demand (pair:
   its `week_offset`); chunk B, early for the last order with safety still
   short: pair is `'S'`.
5. **Safety only** — earlier chunks fill every order (pairs asserted); the
   last chunk goes entirely to safety: `'S'`.
6. **Order fill without touching safety** — chunk A fills the earlier order;
   chunk B is exactly consumed by the later near-term order with safety still
   short: that order's `week_offset`, and the safety allocation is unchanged.
7. **Multiple chunks, one order** — two chunks each partially fill the same
   order: two pairs, both carrying that order's `week_offset`.
8. **Trailing excess → no pair** — earlier chunks fill everything (pairs
   asserted); a trailing chunk allocates nothing and produces no pair.
9. **Ordering and shape** — a mixed scenario asserting the pairs come back in
   chunk (`avail_date`) order, with at most one pair per chunk.

## Section 3 — `RlsItem`

The view computations are covered by Section 2, so `RlsItem`'s tests focus on
what it adds: the **initial netting** of on-hand into each view's
`covered_on_hand` (raw = sequential by due date; safety = near-term demand →
safety → future), that the full pipeline — construction/netting +
`register_chunks` + `recompute` — drives the views correctly end to end, and
the **chunk → job map / priority push** (3.3). Tests use a concrete
`FabRlsItem(RlsItem[Fabric])`; 3.1/3.2 leave its `register_job` unused, while
3.3 gives it the job → `Chunk` conversion described there. Both views' order lists
are sorted by due date, so index `i` is the same demand in each. Setups place
`today` / `lead_time` so the first order is within the safety-side near-term
horizon (`first_due <= today + lead_time < second_due`), isolating the
near-term / safety / future split.

### 3.1 Initial netting

Build a `FabRlsItem` and verify the netted `covered_on_hand` on the raw orders,
the safety orders, and the `Safety`.

1. **`safety_tgt == 0` — raw and safety net identically.** With no safety to
   absorb on-hand, the safety side reduces to filling demand in due order, so it
   matches the raw side. For each on-hand amount, confirm every raw order and its
   matching safety order get the same `covered_on_hand`, and the `Safety` gets 0.
   On-hand amounts:
   - part of the first order (`on_hand < first init_qty`);
   - exactly the first order (`on_hand == first init_qty`);
   - spanning multiple orders (covers the first order and part/all of later ones).
2. **`safety_tgt > 0`, `on_hand <= first order` — first orders match.** The
   on-hand is absorbed entirely by the first order in both views (near-term on
   the safety side), so the first `RawOrder` and first `SafetyOrder` get the same
   `covered_on_hand` (`== on_hand`) and the `Safety` gets 0. Cover a couple of
   on-hand values (a fraction of, and exactly, the first order).
3. **`safety_tgt > 0`, `on_hand >= first order` — the excess diverges.** Both
   first orders are fully covered; the leftover (`on_hand - first init_qty`) goes
   to the **second `RawOrder`** on the raw side but to the **`Safety`** on the
   safety side. Cover multiple leftover sizes:
   - leftover `< safety_tgt` (safety partly filled; the safety side's later orders
     stay 0);
   - leftover `== safety_tgt` (safety exactly filled);
   - leftover `> safety_tgt` (safety filled to target, the remainder spilling to
     the safety side's future orders) — while the raw side just keeps covering its
     orders sequentially.

### 3.2 End to end through `RlsItem`

Pick five Section-2 scenarios, construct a `FabRlsItem` whose netting reproduces
that scenario's initial state, `register_chunks` with the scenario's chunks, call
`recompute`, and confirm the view values match Section 2:

- a couple of **`RawView`** scenarios via `on_hand == 0` (every order nets to
  `covered_on_hand == 0`), checking the `raw_view` orders' final states and
  `lateness`;
- a few **`SafetyView`** "P0 + safety covered" scenarios via
  `on_hand == first init_qty + safety_tgt` (netting yields the first safety order
  covered and the `Safety` covered to target), checking the `safety_view`
  `carrying` / `drainage` / `excess`.

### 3.3 `register_job` and the priority push

`FabRlsItem.register_job(job)` converts a `core.schedule` `Job` into chunks:
each job produces **50-unit chunks at 10 units/hour** — one `Chunk` per 5
hours of runtime, available at its completion time (a 10-hour job yields two
50-unit chunks at `start + 5h` and `start + 10h`) — registered via
`register_chunks(chunks, job)` so the map records the source. Jobs are built
with `Priority(None)`; after each `recompute`, assert every job's
`priority.value`.

1. **Job → chunk conversion** — `register_job` on a job spanning N hours
   produces the right number of 50-unit chunks at the right `avail_date`s,
   verified through the view allocations after `recompute` (the chunk list
   itself is private).
2. **Late job** — the job runs past the earliest unfilled order's due date:
   its chunks fill that earliest unfilled order, and the job's priority
   becomes that order's `week_offset`.
3. **On-time job** — the job completes within `lead_time` of its order's due
   date, safety short: it fills the order *before* safety and is assigned the
   on-time order's `week_offset`.
4. **Early job** — the job completes more than `lead_time` before every open
   order's due date, safety short: it fills safety first and is assigned
   `'S'`.
5. **Pure excess job** — all orders and safety already covered: after
   `recompute` the job's priority is still `None`.
6. **Multiple jobs, same priority** — two jobs whose chunks all land in one
   large order: both end up with that order's `week_offset`.
7. **One job spanning requirements (first write wins)** — a single job whose
   earlier chunk fills an order and whose later chunk tops up safety: the
   job's priority is the order's `week_offset` (from its earliest paired
   chunk), not `'S'`.
8. **Insertion, no change** — a new job is registered covering a different
   requirement than the existing jobs'; after `recompute`, every existing
   job's priority is unchanged.
9. **Insertion, moving down** — a new job running earlier takes over the
   order an existing job used to fill; on `recompute` the existing job now
   fills a later order and its priority moves down (a larger `week_offset`).
10. **Insertion, non-safety → safety** — the new earlier job fills the
    near-term order the existing job used to fill; the existing job's first
    fill becomes the safety top-up, so its priority changes from a
    `week_offset` to `'S'`.
11. **Insertion, safety → non-safety** — the existing early job was `'S'`
    (topping safety); the new earlier job replenishes safety instead; on
    `recompute` the existing job's first fill becomes a future order, so its
    priority changes from `'S'` to that order's `week_offset`.
