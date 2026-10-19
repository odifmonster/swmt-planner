# Specification of coverage of `planners/retime` tests

Covers `planners/retime/retime.py` (see `planners/retime/DESIGN.md`): the
ticket and prior-plan readers, the per-machine walk (`locate`), the step
derivation and replay in `retime`, and the retime report. The CLI command
(`retime_cmd.py`) is a thin wrapper and is exercised by manual runs, like
`plan infinite` and `plan manual`.

Fixtures are the in-memory kind the planner tests already use (`_make_machine`,
`_make_rls_item` from `inf_plan_tests.py`, a 24/7 calendar, items with a
100-lb target roll). Where a test needs a run-config, it writes a minimal
one to a temporary directory: two machines, two styles, a small beam-set
export, no demand beyond what the steps need, no ration.

## 1. `read_tickets`

1. **Grouping and order** — an object keyed by machine (`"N03"`, `"02"`)
   whose lists are out of time order comes back per normalised machine
   (`N3`, `O2`) sorted by doff time; a flat list of records groups by the
   ticket's prefix the same way.
2. **Other machines are dropped and counted** — a key (or ticket prefix)
   for a machine not in the list is left out and the second return value
   counts its records; a machine with no tickets has an empty list; an
   empty or null list under a key is fine.
3. **Style resolution** — a plant variant resolves to its master through
   `variant_masters`; a style that is itself a master id resolves to
   itself; an unknown style gives `item = None`.
4. **Loose keys** — the ticket is read from `ticket_no` or `ticket`, the
   time from the first of `doff_ts` / `scan_ts` / `ts` / `time` and the
   style from the first of `style` / `item` / `variant`; a record without
   a ticket, a time or a style raises `ValueError`, as does a file that is
   neither an object nor a list. `lbs` is ignored.
5. **Times are converted to the planner's clock** — a `doff_ts` with a
   UTC offset (`2026-10-06T12:10:46-04:00`) becomes the naive plant-local
   time; a naive stamp stays as is.

## 2. `prior_jobs`

1. **Jobs in order with their rolls and order** — a schedule-JSON machine
   with two jobs out of chronological order yields `PriorJob`s sorted by
   start, each with `item`, `tgt_order` as `order`, `rolls = len(rolls)`
   and `start` converted from the JSON's UTC stamp to plant local.
2. **Hang sets per bar in hang order** — a job whose activities hold a
   both-bar `Hanging` then a top-only one gives `top = (s1, s3)`,
   `btm = (s2,)`; a set numbered `NEW…` becomes `None`; non-hang
   activities and non-job entries (an orphaned `Idle`) are ignored.
3. **Machines** — only the machines asked for are returned; one the plan
   lacks gets an empty list; the plan's ids are normalised like the
   tickets'.

## 3. `locate`

A prior plan of three jobs on one machine: `A` × 2 (order `P1@A`),
`B` × 2 (`P1@B`), `A` × 1 (`P2@A`). Tickets are built with a helper
`_t(ticket, time, item)`; `prior_start` is the plan's first start.

1. **No tickets, no run-up** — the machine on `A`: nothing consumed,
   `remaining` is the three jobs unchanged, `replayable`, no deviation.
2. **Tickets consume in order** — two `A` tickets then one `B`:
   `consumed = 3`, `tickets = 3`, remaining `B × 1`, `A × 1`, with the
   first job gone and the second job's `rolls` reduced to 1 (its `order`,
   `start` and hang sets kept).
3. **Tickets before the prior start** — a ticket earlier than
   `prior_start` is skipped and not counted.
4. **Tickets after the status** — a ticket later than `status_at` is
   skipped, `after_status` counts it, and nothing is consumed by it.
5. **Extra roll of the style just finished** — tickets `A`, `A`, `A`
   (three where the plan had two): the third is recorded in `extra`,
   consumes nothing, `consumed = 2`, and the walk continues (a following
   `B` ticket consumes job 2's first roll).
6. **Wrong style stops the walk** — tickets `A`, `C` (an item the plan
   never had on this machine): `wrong_style` names the ticket and the
   expected item, `consumed = 1`, `remaining` is empty, not `replayable`,
   and later tickets are not walked (`tickets` counts up to the bad one).
7. **An unresolved style is a wrong style** — a ticket with `item None`
   is treated as in 6.
7a. **Early change by ticket** — tickets `A`, `B` (the plan had `A × 2`):
    the `B` ticket is accepted as an early change, the unfinished `A`
    roll is dropped and described in `early` (count, item, order, the
    ticket), `consumed` counts the `A` roll and the `B` roll, and
    remaining is `B × 1`, `A × 1`. A ticket for an item two jobs ahead
    (a four-job plan `A, B, C, A` with tickets `A`, `C`) is a wrong
    style, not an early change.
7b. **Early change per the status** — no tickets, status on `B`
    (the plan expected `A`, nothing consumed): the `A` job's rolls are
    dropped with `early` saying `per the status`, the run-up then
    consumes `B` rolls as in 9, and the machine is replayable; a status
    on `C` two jobs ahead is a wrong style.
8. **The status must match** — with no tickets, a status item `C` (the
   plan expected `A` first, and `C` is not the next job either) is a
   wrong style with the status named in the message.
9. **Run-up rolls consume scheduled rolls** — status on `A`,
   `run_up_rolls = 2` (the load's run-up finished the roll in progress and
   ran one more), `roll_in_progress = True`: both `A` rolls are consumed,
   `in_progress_order = 'P1@A'` (the order of the roll the run-up
   finished), remaining `B × 2`, `A × 1`.
10. **Run-up overrunning the style** — status on `A`, `run_up_rolls = 3`
    with only two `A` rolls scheduled: two are consumed, the loop stops
    at the `B` roll, and the machine is not marked finished (`B × 2`,
    `A × 1` remain).
11. **Extra roll in progress** — tickets `A`, `A`, status on `A`, the plan
    expecting `B` next, `run_up_rolls = 1`, `roll_in_progress = True`:
    `extra_in_progress` is set, nothing more is consumed, remaining is
    `B × 2`, `A × 1`; with `run_up_rolls = 2` the surplus whole roll is
    also listed in `extra`.
12. **Finished** — tickets for every scheduled roll: `finished`, remaining
    empty, not `replayable`; the status item is not checked.
13. **Remaining jobs keep their identity** — a partially consumed job
    keeps `job_id`, `order`, `start`, `top` and `btm`.

## 4. `retime` — steps and replay

A temporary run-config with two machines, `M1` on `A` with plenty of yarn
and `M2` on `B`, both bars full; a beam-set export holding one stock set
for `A`'s top yarn (`S1`) and nothing else; a prior plan JSON written by
the test (built with `schedule_json`-shaped dicts) placing `A × 2` then
`B × 1` on `M1` and `B × 2` on `M2`; an empty tickets file unless stated.

1. **Same sequence, new times** — the result's `report.schedules['M1']`
   holds a run-up job (if any), then jobs `A × 2` and `B × 1` with the
   prior orders as `tgt_order`; `steps` lists `(M1, A, 2, order)`,
   `(M1, B, 1, order)`, `(M2, B, 2, order)` in prior-start order across
   machines; every job starts at or after the config's change date.
2. **Tickets shorten the first job** — a tickets file with one `A` roll
   on `M1` (between the prior start and the status): the replayed `A`
   step has 1 roll; `positions['M1'].consumed` counts it.
3. **A wrong-style machine is left alone** — a ticket for `C` on `M2`:
   no step is replayed on `M2`, its schedule is only the load's run-up,
   `positions['M2'].wrong_style` is set, and `M1` replays normally.
4. **Sets go to the earliest hang, not the earliest step** — both
   machines on `A`; the prior plan has `M1` run `A × 3` then `B × 1`
   (its `B` hang named `S1`) and `M2` run `A × 1` then `B × 1` (no set
   named); the export holds only `S1`. `M1`'s `B` step is staged first
   (earlier prior start) but its hang comes later in time: `M2`'s hang
   mounts `S1`, `M1`'s stays `NEW…`; `hangs` records `M2`'s as `stock`
   with `prior None` and `M1`'s as `new` with `prior 'S1'`.
5. **Re-timed on the real pounds** — `M1` runs `A × 1` then `B × 2` and
   the export's only `B` set holds 80 lbs: the schedule's `Hanging`
   mounts it at 80 lbs, its `HangRecord` has `plan_lbs 80`, `set_lbs 80`,
   `short_by 0` and `rolls 1` (one roll above the floor), and the second
   roll hangs again — a placeholder, `rolls 1`; the result took at least
   two rounds. A 2,000-lb set gives one hang, `rolls 2`, `short_by 0`,
   and nothing `withheld`.
5a. **Rounds** — the same plan with the 2,000-lb set takes two rounds
    (one assigns, the next confirms); with an empty export one round,
    every hang `new`.
6. **A taped-out set comes back in time order** — `M1` runs `A × 1`,
   `B × 1`, `A × 1` (its `B` set is taped out at the change back) and
   `M2` runs `A × 6` then `B × 1`; the export holds one `B` set: both
   `B` hangs mount it, `M1`'s `TapeOut` carries it, and `M2`'s record
   shows `set_lbs` less what `M1`'s roll drew (1950).
7. **Knits carry their sets** — after the retime every `Knit` on `M1`
   names a set on each bar, the `B` knits' `top_beam` is the assigned
   set, and the schedule JSON's knit objects carry `top_beam` /
   `btm_beam` with that set number.
8. **A step that cannot replay stops its machine** — a prior job for an
   item the machine cannot run: `failures` has one entry naming the
   machine and item, that machine's later steps are skipped, and the
   other machine replays.
9. **Machines not in the prior plan** — a config machine the plan lacks
   is listed in `not_in_plan` and left at its status.
10. **Tickets of other machines** — a ticket for `X9` is ignored and
    `tickets_ignored = 1`.
11. **The report is the state's** — `report.jobs_by_item['A']` holds the
    replayed `A` jobs and `late_orders` / `unmet_lbs_by_item_week` are
    present (zero-demand config: empty), and `start_date` is the
    config's.

12. **`keep_sets` keeps the prior plan's sets** — the same two-machine
    plan as 4, run with `keep_sets=True` and the export holding `S1` and
    `S2`: `M1`'s `B` hang mounts `S1` (its prior name; `source
    'assigned'`, no note) even though `M2`'s hang comes first in time, and
    `M2`'s hang, which named nothing, gets `S2` from the second pass. A
    prior name the export lacks (`S9`) gives a placeholder the second pass
    fills, with `note 'not in the new inventory'`; a prior `NEW…` gives
    `note 'invented'`; two steps naming `S1` leave the second with `note
    'named by an earlier step'`; a prior name that is the plant's queued
    set on that bar is kept with `source 'queued'` and no note; a prior
    set received after its hang is dropped with a note starting
    `assignment refused` and the step still replays. Without `keep_sets`
    every note is empty. (This also covers the manual planner's `'named'`
    and `'none'` stock modes, which have no tests of their own.)
12a. **A prior set the machine cannot take** — with `keep_sets`, a prior
    name for a large (40 in) set on an old machine is not kept: the hang
    gets a placeholder and the record's note reads `too large for the
    machine`; on a new machine it is kept.
13. **Placeholders are never stock** — a placeholder a step's tape-out
    returned to the inventory is not handed to a later hang by the second
    pass: with no real set for `B`, both machines' `B` hangs stay `NEW…`.

## 5. `retime_text` and `write_outputs`

1. **Sections** — the text has `POSITIONS`, `DEVIATIONS`, `SET
   ASSIGNMENTS`, `STILL INVENTED`, `ASSIGNED SETS PASSED OVER`, `STEPS
   REPLAYED` and `FAILURES` sections; a position line per machine in the
   plan, `none` under empty deviation / assignment / passed-over /
   failure sections.
2. **Deviations are spelled out** — a wrong-style machine, an extra roll,
   an extra roll in progress, an early change (with the dropped rolls), a
   finished machine and a run-up roll with an order each produce their
   own line.
3. **Assignments and still-invented hangs** — a `stock` hang is listed
   under `SET ASSIGNMENTS` (whose header gives the re-timing rounds) with
   its pounds, its `rolls`, a `SHORT BY` note when short, and the prior
   plan's set; a `new` hang appears only under `STILL INVENTED`, with its
   requirement and `rolls`; sets held back from assignment are named
   under the header.
4. **Files** — `write_outputs` writes `knit_plan_<date>.xlsx`, `.json` and
   `retime_<date>.txt` to the directory, taking the `_<n>` suffix when the
   stem is already there; the JSON parses as a schedule list.
5. **Passed-over sets listed** — a result whose report maps a machine to
   one `PassedOver` prints it under `ASSIGNED SETS PASSED OVER` with the
   set, its description and merge and the requirement; a result with no
   report (the text tests' fixtures) prints `none` there.
