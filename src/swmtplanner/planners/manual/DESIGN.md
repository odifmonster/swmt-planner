# Manual scheduling — Design

Source of truth for `planners/manual`: building a machine schedule by hand
— "N rolls of this item on that machine, with these beam sets at the
runout" — and producing it in the same schedule-JSON format the greedy
planner writes. The machine model still does the arithmetic: when the
current beams run out, what the changeover needs, how long each roll takes.

## Purpose

The greedy planner (`planners/infinite`) chooses *what* to run; the plant's
scheduler sometimes needs to choose it themselves and only wants the
consequences computed. The manual scheduler therefore exposes the same
building blocks the greedy loop uses — `Machine.plan_production` against the
shared `State` (machines, beam-set inventory, demand) and
`State.commit_move` — behind a small API that is usable interactively (a
notebook, `python -i`) and replayable from a **step file**. It writes the
schedule JSON only (timestamps in UTC, like the greedy planner's JSON;
the API itself — `pending()`, `runouts()` — reports planner-local times);
the xlsx report is the greedy planner's.

## API

```
Step                                      # one committed manual move
  machine: str
  item: str                               # greige id
  rolls: int                              # whole rolls of `item`
  at: 'schedule_tail' | 'next_runout'     # plan_production's start_at
  top: tuple[str | None, ...] = ()        # set numbers queued for top hangs
  btm: tuple[str | None, ...] = ()        # … and bottom hangs
  order: str | None = None                # the order the step serves: the new
                                          # job's tgt_order (JSON `order`)
  to_json() -> dict ; from_json(d) -> Step

ManualSchedule(state, stock='all' | 'named' | 'none')
                                               # what automatic picks may draw on —
                                               # see "Stock modes"
  from_config(config_path) -> ManualSchedule   # loads the run-config exactly as
                                               # `plan infinite` does (run.load_config)
  machines: Mapping[str, Machine]
  inventory: Inventory
  steps: tuple[Step, ...]                      # committed so far, in order
  staged: Mapping[str, ProductionPlan]         # staged plans by machine, in
                                               # staging order
  pending() -> list[dict]                      # per machine: item, schedule_tail,
                                               # next_tape_out_slot (under the ration,
                                               # None when unrationed),
                                               # next_runout, rolls_before_runout
                                               # (Machine.whole_rolls_before_runout),
                                               # roll_lbs_remaining, per-bar set +
                                               # lbs remaining + threaded (False for
                                               # a bar hung but not threaded) +
                                               # queue (each entry with its
                                               # location: staged / inventory),
                                               # whether a plan is staged
  stock(desc: str, at: datetime | None = None) -> list[BeamSet]
                                               # sets fitting a beam-set label,
                                               # available at `at` (default: start),
                                               # not hung by a staged plan; oldest
                                               # received first (the pull order)
  rolls(machine, item, n, at='schedule_tail', top=(), btm=(), order=None) -> ProductionPlan
                                               # plan (not commit) a step for
                                               # `machine`, replacing that machine's
                                               # earlier staging; other machines'
                                               # stagings stay
  runouts(machine=None) -> list[dict]          # hang points of one staged plan (hang
                                               # order) or of all (chronological):
                                               # machine, bar, at, desc, the set
                                               # coming off, the set going on and
                                               # where it came from, whether it is
                                               # locked, queue_idx, stock options,
                                               # waited_from (a slot wait that
                                               # delayed this preamble)
  assignments(machine=None, *, all_hangs=False) -> {'top': [...], 'btm': [...]}
                                               # a staged machine's set numbers per
                                               # bar in hang order: the hand
                                               # assignments (None = automatic), or
                                               # with all_hangs every hang's set
  assign(top=(), btm=(), *, machine=None, replace=False) -> ProductionPlan
                                               # re-stage one machine's step with
                                               # set numbers appended to (or, with
                                               # replace, redefining) its per-bar
                                               # assignment lists
  commit(machine=None) -> list[Step]           # commit one staged plan, or all in
                                               # staging order
  discard(machine=None) -> None                # drop one staged plan, or all
  replay(steps: Iterable[Step]) -> None        # rolls+commit each, in order
  schedule_json() -> list[dict]                # same shape as the greedy output
  write_json(path) -> None
  save_steps(path) -> None ; load_steps(path) -> list[Step]   (static)
```

`rolls` calls `machine.plan_production(item, n * item.tgt_wt, start_at=at,
tgt_order=order, inventory=<stock view>, assign={'top': top, 'btm': btm})`
and stages
the resulting `Move` under that machine; nothing changes until `commit`,
which goes through `State.commit_move` so activities, jobs (including the
previous job's recreation with its tape-out), the inventory and the demand
items are all updated the way the greedy planner updates them. Staging then
committing is what makes the tool interactive: look at the plan (its
activities, which sets it hung, where the runout fell), then keep or discard
it.

### Plan first, then assign

The intended rhythm is two-phase. `rolls(...)` stages the move with the
automatic picks, so the machine model has already found *where* the sets
change: the changeover re-thread and any mid-run runouts. `runouts()` lists
those hang points — for each, the machine, the bar, the time, the
requirement, the set **coming off** that bar (`prev_set` / `prev_merge` /
`prev_vendor`: what was on the bar just before the hang, so the operator
can see what merge and vendor the bar is changing *from*), the set going on
(`auto`, with its `lbs`, `vendor` and `source`: `queued` at the machine by
the plant, `assigned` from stock by name, `stock` picked automatically, or
`new` when stock had nothing), `assigned` — whether this step named the set
in `assign`, which is also True for a plant-queued set the step confirmed
by its own number — whether that hang is `locked`, its position in the bar's queue
(`queue_idx`), and the stock sets that fit and are available at that moment
(less anything a staged plan hangs earlier), each as `(set_no, lbs, merge,
vendor)`. `assign(top=[...], btm=[...])` then re-stages the same step with
set numbers queued in that order; a bar left out keeps what it had, and a
bad assignment raises while the previous staging stays put. `commit()`
records the `Step` *with* the assignments, so a replayed step file
reproduces the choices.

**Pull order.** Stock is listed — by `stock()` and in each runout's
`options` — oldest received first, then by set number: the order in which
the warehouse wants sets pulled (the longest-held set is the easiest to
reach, and goes first). The scheduler's job is to hand those sets out in
that order to the runouts as they come, plant-wide. So `runouts()` with no
machine lists every staged plan's hangs **chronologically across
machines**, and `assign` **appends** by default: walking down the list,
`assign(btm=['X'], machine='N2')` then `assign(top=['Y'], machine='M3')`
then `assign(btm=['Z'], machine='N2')` gives N2's bottom bar `['X', 'Z']`
for its first two hangs without restating `X`. `replace=True` redefines
the bar lists outright (a bar passed nothing becomes automatic again).
Each `assign` re-stages just that machine, and the other stagings' options
drop the set it now hangs.

### Set assignment

`top` / `btm` are the set numbers to hang on that bar, in the order the
plan's hangs occur — the changeover re-thread first, then any mid-run
re-threads (the order `runouts()` lists them in). A `None` entry (`null` in
the step file) leaves that hang to the machine's own queue — the set the
plant already staged there — or to stock, so `top=[None, '3-0625']` keeps
the staged set for the first top hang and names the second. They flow
straight into `plan_production`'s `assign` (see `schedule/DESIGN.md`,
"Manual assignment"): a set that is not in stock for the bar's requirement,
not yet available, already hung in a staged plan, or never needed raises
`ValueError` from `rolls`, so a mistaken assignment is caught before
anything is committed. Bars with no assignment get the automatic most-lbs
pick, and a bar whose queue runs out mid-plan falls back to it too.
`stock(desc)` lists what can be assigned.

**Stock modes.** `ManualSchedule(state, stock='all')` is the default: a
staging's automatic picks draw on the committed inventory as described
above. Two restricted modes serve the retimer, which hands stock out in
runout order *after* planning (`schedule.assign_sets`): `stock='none'`
plans every automatic pick as a placeholder (`NEW…`, `source: 'new'` in
`runouts()`) — a step naming a set raises, as there is nothing to name
from — and `stock='named'` lets a step hang exactly the sets it names (a
named set must still be in the committed inventory under the bar's
requirement, available, and not held by hand elsewhere) while every
unnamed hang invents a placeholder. In both modes the plant's queued sets
are hung as usual, since the queue precedes stock. `stock()` and
`runouts()`' `options` still list the committed inventory in every mode.

**Locked hangs.** A set the plant has assigned to a machine bar (the bar's
queue) is locked in: when it is next up for a hang — it fits the
requirement and has been received — that hang takes it, and a manual
assignment naming a *different* set for that hang raises. The assignment
for a locked hang is `None` or the queued set's own number; `runouts()`
marks such a row `locked: True` with `source: 'queued'` and lists only that
set as its option.

### Staging several machines

Plans can be staged on any number of machines at once — one per machine —
and committed together or one at a time. Each staging is planned against
the committed inventory **less the sets every other staged plan hangs**, so
two staged machines never claim the same stock set. Re-staging a machine
(`assign`, or `rolls` again) plans against the current committed state and
the *other* stagings and keeps the machine's place in the staging order, so
a staging never depends on the commit order: `commit()` commits all of them
in staging order, `commit(machine)` just the one, and the rest remain valid
either way. Each machine's `at='next_runout'` is its own computed runout,
so the staged plans' *times* are independent of one another — except
through the changeover ration: each staging is laid out against the
committed tape-out and pattern-change bookings **plus the slots the other
stagings take** (a `CapacityView`, see `schedule/DESIGN.md` "Changeover
capacity"), so two staged tape-outs never share a day's last unit, and the
second one staged waits for the next period. Re-staging re-plans against
the current overlay like the inventory. `runouts()` reports a slot wait on
the hang it delayed (`waited_from`), and `pending()` shows each machine's
next free tape-out period.

**A hand beats an automatic pick.** The exception to "less what the others
hang" is a set the step names itself. If another staging picked that set
**automatically**, the manual assignment takes it: the step is staged with
the set, then the displaced staging is re-planned against the stock that
now remains, so its automatic pick simply moves on to the next set (the
whole re-staging is atomic — if anything fails, every staging is left as it
was). This is what lets the scheduler hand sets out in pull order across
machines without first discarding whatever the automatic picks grabbed.
Only automatic picks give way: naming a set another staging assigned **by
hand** raises with that machine's name, since two deliberate assignments
of one set are a real conflict. Accordingly `stock()` and each runout's
`options` list sets other stagings hold automatically (a runout row's
`held_elsewhere` maps those set numbers to the machine holding them) and
leave out only sets held by hand.

### Ordering

Steps are committed in the order given (and, when several plans are
staged, in staging order). Inventory is consumed in that order too: a set
staged for machine A first is gone for machine B even if B's hang would
happen earlier in time. That is deliberate — it mirrors how a scheduler
works through the machines — and `at='next_runout'` still places each
machine's changeover at its own computed runout, so the *times* stay right
regardless of step order.

## Step file

A JSON list of `Step.to_json()` objects:

```json
[
  {"machine": "J8", "item": "AU8084A", "rolls": 3, "at": "next_runout",
   "top": ["2-3757"], "btm": ["308288"]},
  {"machine": "E7", "item": "AU7538B", "rolls": 5, "at": "schedule_tail"}
]
```

`save_steps` writes the committed steps of a session; `plan manual <config>
<steps.json> -o <dir>` (`planners/cli.py`) rebuilds a schedule from one and
writes `manual_schedule_<start date>.json`. A step file is therefore the
reproducible form of an interactive session, and can be edited by hand.

## Out of scope (for now)

- Costing / scoring the manual schedule.
- Undoing a committed step (discard the staged plan instead; a committed
  mistake means editing the step file and replaying).
- A prompt-driven REPL or GUI — both would sit on this class.
