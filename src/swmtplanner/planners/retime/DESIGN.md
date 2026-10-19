# Retiming a schedule — Design

Source of truth for `planners/retime`: carrying an existing plan forward to
the plant's current position without re-deciding it. The sequence of jobs
and rolls on every machine stays what the prior plan said; the times move
to where the floor actually is, and the beam sets are re-drawn from the
current inventory.

## Purpose

The greedy planner (`planners/infinite`) produces a plan once. Days later
the floor has doffed some of its rolls, run some beams out, and received new
sets, and the plant wants the *same* plan with its clock corrected: what is
left on each machine, when it now lands, and which real sets go on at each
hang. Re-running the greedy would make new decisions; the manual planner
(`planners/manual`) can replay decisions but needs someone to write the
steps. The retimer writes those steps from the prior plan and the doff
tickets, replays them through the manual planner, and writes the normal
outputs.

## Inputs

```
plan retime <config> <prior plan JSON> <tickets JSON> -o <dir> [--keep-sets]
```

`--keep-sets` keeps the prior plan's set assignments where they still
hold and fills only its `NEW…` placeholders (see "Two passes over the
sets"); without it every hang's set is re-decided in runout order.

- **The run config** (`master.json`), loaded exactly as `plan infinite`
  and `plan manual` load it (`run.load_config`): its `start_date` and
  `change_date` are the **new** ones, its `machines` file is the new
  machine status (built by `plan machines` from the runtime export), its
  `beam_sets` the new inventory export. Every machine is run up to
  `change_date` on its current item as usual.
- **The prior plan** — the schedule JSON `plan infinite` (or a previous
  retime) wrote: per machine, jobs in order, each with its item, its
  `tgt_order`, its target order's `due_date` (carried on `PriorJob` so a
  run starting from this plan can match the job to today's order — see
  "Sticking to the prior plan" in `planners/infinite/DESIGN.md`), its
  rolls and the sets its hangs mounted. Its times are
  UTC like all schedule JSON; the retimer converts them to the planner's
  clock. Its first job(s) on a machine are the run-up the prior load made
  to the prior change date; they are rolls like any other.
- **The doffed rolls** (`doffed-rolls.json`) — the rolls doffed on the
  floor since the prior plan's start, keyed by machine:

  ```json
  {"N03": [{"ticket_no": "N03-3885", "style": "AU3426H-AH/15",
            "lbs": 743.72, "doff_ts": "2026-10-06T12:10:46-04:00"}, ...],
   ...}
  ```

  The machine id is normalised like the machines file's (`O2`, not
  `O02`); machines the config does not have are ignored. `doff_ts` carries
  its UTC offset and is converted to the planner's clock. The style is the
  plant's variant name and resolves to a planner master through
  `variant_masters`, as a machine's `init_item` does; one that resolves to
  nothing is reported and treated as a wrong style (below). `lbs` is not
  used — a ticket is one whole roll. A flat list of the same records, the
  machine read off the ticket's `<machine>-` prefix, is accepted too, and
  key names are taken loosely (`ticket_no` / `ticket`; `doff_ts` /
  `scan_ts` / `ts` / `time`; `style` / `item`).

## Mechanism

### 1. Where each machine is

For each machine in the config, the prior plan's rolls are listed in
order (job by job, roll by roll, each roll with its job's item and
`tgt_order`), and the machine's tickets are sorted by time and walked
against that list:

```
next = the first scheduled roll
for each ticket in time order:
    if ticket.item == next.item:          consume next (the roll was doffed as planned)
    elif ticket.item == the item of the roll just consumed:
                                          an EXTRA roll of the style the machine was on:
                                          insert one roll of that item before `next`
                                          (the style change shifts past it), consume
                                          it, and record a deviation
    elif ticket.item == the item of the NEXT job (the one after next's job):
                                          the machine CHANGED EARLY: the rest of next's
                                          job is dropped, the walk goes on from that
                                          next job (this ticket consumes its first roll),
                                          and the dropped rolls are recorded
    else:                                 the machine is on a style the plan never put
                                          there: record a deviation and stop — the
                                          machine keeps its status and is not replayed
```

An early change is the floor answering a customer need the plan did not
know about; the rolls it skipped are **dropped, not re-added** — if the
machine did not need to run more of the previous item, the retimer has no
reason to put those rolls back — and the demand sheet shows whatever
shortfall that leaves. Only the very next job is checked: a machine found
on a style two or more jobs ahead has left the plan and is a wrong style.

What is left after the walk is the machine's **remaining rolls**, grouped
back into jobs: consecutive rolls of one item with one `tgt_order` form a
job, so an inserted extra roll joins the job it extends. The machine
status then says where in the first remaining roll the machine is:
`init_roll_lbs > 0` means that roll is in progress, and it is not counted
again — the machine model's run-up finishes it (`plan_production` always
completes a roll in progress). The status's item must be the first
remaining roll's item, or the style the machine just finished (an extra
roll in progress), or the next job's item — the early change again, seen
through the status rather than a ticket, with the same dropping of the
unfinished job's rolls; anything else is the wrong-style deviation above
(the status is authoritative, the plan is not replayed on that machine). A machine with no remaining rolls — the floor got through
everything the plan had for it — is reported and left at its status.

One mismatch is the plan's own doing, not the floor's: a machine the
planner found idle, or on a style it had no more use for, gets a plan that
**opens with a changeover** — its first job is on another item, and the
status still says the item the machine was on when the plan was made.
Nothing is accounted for on such a machine (no ticket, no run-up roll), so
the mismatch is read as the plan's own opening change, and the machine is
at its first roll with every job remaining, when either the plan is being
retimed from its own start (`prior_start` is not before the status
snapshot — a hand-edited plan replayed on the morning it was made) or the
first job's changeover activity records the status item as the item it
changed *from* (`PriorJob.opens_from`, the `from_item` of the job's first
`StyleChange` / `RunnerChange` / `PatternChange`; the plan knew the machine
was there). `Position.opening_change` marks it and the report lists it
under deviations. A plan retimed days later whose machine still shows the
old item but whose first job does not record it is the wrong style it
always was, and so is one whose run-up made a roll the plan never had.

Tickets older than the prior plan's start are ignored (they belong to the
run before it), and so are tickets scanned **after** the config's
`start_date` — the status snapshot — since the status already describes
that future; both counts are on the report. A machine with no tickets is
simply at its first roll.

### 2. Steps

Each remaining job becomes one manual step, `Step(machine, item, rolls,
'schedule_tail', top, btm, order)`:

- `rolls` is the job's remaining whole rolls, less the one in progress for
  the first job; a first job reduced to the roll in progress alone
  contributes no step (the run-up covers it) and its order is noted on
  the report.
- `at` is always `'schedule_tail'`: the machine runs continuously. The
  prior plan's carrying-avoidance idles and slot waits are not carried
  over; slot waits re-arise only where the ration forces them.
- `order` is the prior job's `tgt_order`, so the new jobs register
  against the same orders (a new field on `Step`, `None` for the prior
  plan's run-up jobs; `Step` / `ManualSchedule.rolls` pass it to
  `plan_production(tgt_order=)`). A job that filled a slot wait in the
  prior plan (`fill: true`, see the planner's "Filling a slot wait") is
  an ordinary job with an order: it replays as a continuation of its
  item at the tail, which is what it was. The replay itself never fills
  — it reproduces the prior plan's jobs, and a wait it meets is idle, as
  the prior plan's would have been without the fill.
- `top` / `btm` are empty in the first round: the prior plan's set
  choices are **not followed**. Which real set goes on which bar is
  decided afterwards, in runout order (below), so a long job replayed
  early no longer takes the sets a sooner hang on another machine needs
  today; the later rounds then name the sets so assigned, to time the
  schedule on their pounds. With `--keep-sets`
  they instead name the prior plan's sets, in hang order, **when the
  prior set is still usable**: it is in the new inventory under the bar's
  requirement, the machine accepts it (a large beam fits only a new
  machine — `schedule/DESIGN.md` "Large beams") and it is not already
  named by an earlier step. A prior `NEW…`
  placeholder, a set the new export no longer has (taken by the load's
  run-up, or gone), and one an earlier step already named become `None`
  — a placeholder for the second pass to fill — and the reason is noted
  on the hang's record. A name the manual planner refuses at staging (a
  set received after its hang, say) is dropped the same way and the step
  re-staged without it.

Steps are ordered by the prior plan's start time of the job they come
from, across machines, and each is staged and committed in that order —
so an earlier tape-out claims its ration slot before a later one.

**Two passes over the sets.** The replay runs through a `ManualSchedule`
in a restricted stock mode (`planners/manual/DESIGN.md`, "Stock modes"):
`stock='none'` by default, so every hang the steps need invents a
placeholder set with the default pounds (`fresh_beam_lbs`), the plant's
queued sets aside — they are real, staged at the machine, and hung as
the queue dictates (or passed over when they do not fit); `stock='named'`
with `--keep-sets`, so a step hangs exactly the prior sets it names and
invents a placeholder for every other hang. That first pass fixes the
schedule's timing — on default pounds, or on the kept sets' real pounds
where a prior set was kept. The second pass is `schedule.assign_sets`
over the committed machines with what is left of the config's inventory
after pass one: every placeholder hang across the plant, in time order,
takes the set the walk would have picked at that moment — stock by
receipt and the sets earlier hangs tape out again, `choose_stock` for
continuity with the set coming off the bar — and the machine's schedule
is relabelled with it under the plan's pounds (see "Assigning sets after
planning" in `schedule/DESIGN.md`). A hang stock has nothing for keeps
its placeholder. With `--keep-sets` the
long-job problem the default mode solves is back by choice: a kept set
goes where the prior plan put it even if a sooner hang elsewhere could
use it — the flag is for carrying a plan the floor has already pulled
sets for.

**Re-timing on the real pounds.** Those two passes leave the timing on
the placeholders' default pounds: a 2,200-lb set standing in for an
1,800-lb placeholder would show the placeholder's rolls, and a lighter
set would be flagged short rather than running out sooner. The floor
needs to know how many rolls to expect off the set it is given, so the
retime **repeats** the two passes until the schedule is timed on the sets
it names, in **rounds**:

1. Round one is the two passes above: a replay on placeholders (or the
   kept prior sets) and an `assign_sets` over the placeholders.
2. Every later round replays the same steps with every set the previous
   round assigned **named** at its hang (the `'named'` stock mode, as
   `--keep-sets` names the prior sets), so each hang mounts its real set
   at its real pounds: the machine's runouts move — later with a heavier
   set, sooner with a lighter one — and the hangs after it move with
   them. The names are carried per job and bar in hang order (the step's
   `runouts` rows against the assignment by machine, bar and hang
   time). A step with more names than hangs under the new timing (a
   heavier set has removed a hang) is re-staged with the surplus names
   dropped from the end, and those sets go back to the pool; a name the
   planner refuses for another reason — the set is no longer available
   at the hang because the tape-out that returns it moved later, or an
   earlier step now takes it — is dropped the same way and the reason
   noted. The round ends with `assign_sets` over whatever placeholders
   the new timing left (a lighter set's extra hang, a dropped name).
3. The rounds stop when a round assigns nothing more, so every hang
   either names a real set the schedule is timed on or is a placeholder
   stock has nothing for; `MAX_ROUNDS` (6) caps the loop, the last round
   standing, and the report says how many rounds it took. Each round
   rebuilds the state from the config (fresh machines and stock) and
   replays the same positions; the tickets are read once.

After the last round an assigned set's `HangRecord` has `plan_lbs ==
set_lbs` and `short_by` 0 — the plan now draws the real pounds — and
carries `rolls`, the whole rolls the schedule doffs from that set on
that bar (the rolls whose last knit names it — a roll that straddles a
swap counts for the set it finishes on), which is the figure the floor
wants. A hang still invented keeps the default pounds and `rolls` on
them. `assign_sets` and the manual planner are unchanged; the loop is
the retimer's.

### 3. Outputs

After the last commit the state is reported exactly as `plan infinite`
reports its own: `PlanReport` from the state (`loop.plan.build_report`,
the existing `_build_report` made public), `write_plan_report_xlsx` and
`write_schedule_json` to `knit_plan_<start date>.xlsx` / `.json` in the
output directory (the `_<n>` suffix rule when the name is taken). The
costing is loaded from the config so the report carries a score, as a
manual schedule otherwise would not. The late-orders, demand and
changeovers sheets therefore all describe the retimed plan, and the Gantt
script reads the JSON unchanged.

Beside them, `retime_<start date>.txt` — the retime report:

- per machine: rolls doffed since the prior start, where the machine
  stood (job / roll, roll in progress), steps replayed;
- **deviations**: extra rolls inserted (machine, item, ticket), early
  changes (machine, the rolls dropped with their item and order, and the
  ticket or status that showed the change), machines on a wrong style
  (machine, status item, the item the plan expected, the ticket that
  first showed it) and machines that finished their plan;
- **set assignments**: every hang of the retimed plan in time order —
  machine, bar, hang time, the requirement, the set hung and its source
  (`queued` by the plant, `assigned` when `--keep-sets` kept the prior
  plan's set, `stock` from the assignment rounds, `new` when stock had
  nothing), the pounds on the set the schedule is timed on, the **rolls**
  the schedule knits from it on that bar, and a **short by** figure
  should the plan still draw more from the bar than the set holds (it
  does not after the re-timing rounds). The header says how many rounds
  the re-timing took. Beside each, the set the prior plan had at the same hang
  (matched by order on the bar within the job; `no prior hang` for a
  surplus one), so what moved is visible, and with `--keep-sets` the
  reason a prior set was not kept (invented; named by an earlier step;
  not in the new inventory; the planner's refusal). Hangs still invented
  are listed apart, as the bars stock has nothing for;
- **assigned sets passed over**: machine, bar, hang time, the plant-staged
  set a hang dropped from the bar's queue because its yarn did not fit or
  its merge is blacklisted, the requirement it failed and the reason
  (`Machine.queue_passed_over`, see schedule/DESIGN.md "Assigned sets and
  bar queues" and "Blacklisted merges");
- steps that failed to replay (`ValueError` from the manual planner —
  an item that no longer runs on the machine, say): the machine is left
  where the failure found it and the rest of its steps are skipped.

## Interfaces touched outside this module

- `planners/manual`: `Step.order: str | None = None` (JSON `order`),
  `ManualSchedule.rolls(..., order=None)`, and `_stage` passing
  `tgt_order=step.order` to `plan_production`. The step file gains the
  optional key; existing files read unchanged. `ManualSchedule(state,
  stock=)` — the `'none'` / `'named'` stock modes the retimer plans in.
- `schedule`: `assign_sets` / `SetAssignment` (the second pass),
  `Machine.rebind_sets`, `Status.rebind_sets`, `BeamSet.relabelled`, and
  `Knit.top_beam` / `btm_beam` — the sets each knit ran on, carried into
  the schedule JSON and the xlsx `desc` so the floor reads set numbers
  and merges off every knit.
- `planners/infinite/loop/plan.py`: `build_report(state, costing)` public.
- `planners/cli.py`: the `retime` command (`retime_cmd.py`, like
  `manual_cmd.py`).

## The retimed plan as the next run's prior plan

The retimer realigns a plan with reality; it does not hold anything to
it. `plan infinite` does that: given the retimed plan as its
`prior_plan`, it recommits the plan's jobs that fill urgent demand before
planning the rest — see "Sticking to the prior plan" in
`planners/infinite/DESIGN.md`. The planner reads the retimed JSON with
this module's `prior_jobs`, which is why a job carries its order's
`due_date`.

## Out of scope (for now)

- Re-deciding anything: no new moves, no re-ordering, no re-scoring of
  alternatives. A plan that has drifted badly is re-run, not retimed.
- Demand changes: the config's `demand` is read as usual, but the retimer
  neither checks nor repairs the prior plan against it.
- Partial tickets (a roll doffed short) — a ticket is one whole roll.
- Re-choosing sets under the re-timed order: a later round keeps the
  sets the earlier one assigned and only fills what the new timing
  opened, so a set is not moved to a hang that the re-timing made sooner
  than the one it was given. The rounds converge on a plan timed on its
  sets, not on the pull order a from-scratch assignment under that
  timing would give.
