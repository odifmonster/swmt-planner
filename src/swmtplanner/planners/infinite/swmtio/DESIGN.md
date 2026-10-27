# Planner inputs from the plant — Design

Source of truth for `planners/infinite/swmtio`: pulling the planner's inputs
straight from the plant's SQL Server database and the locally kept files,
and writing the JSON input files the planner reads. It replaces the
scattered convenience scripts that did this by hand.

## Purpose

`plan infinite` and `plan retime` read a set of JSON inputs (the machine
status, the beam-set inventory, the assigned sets, the demand, the
blacklist, the variant map and the masters). Until now those were produced
by exporting from the plant's systems, running one-off scripts over the
exports, and editing the results. `swmtio` formalises that path: the data
that lives in the plant database is queried directly over `pyodbc`, the
data that only exists in local files is read from those files, both land as
pandas dataframes of a declared shape, and one module combines them into
the JSON the planner expects.

## Layout

```
planners/infinite/swmtio/
    translate.py    the shared Column / Table declarations (source → dataframe)
    loaders.py      load_sql_config / run_query (the plant database),
                    read_csv (local files), get_file_name — every source
                    into a dataframe
    queries.py      SQLQuery (SQL text + its date arguments) and every
                    query as a named SQLQuery constant
    tables.py       the Table declaration paired with each query / file
    loadinputs/     joining the dataframes and writing the planner's JSON inputs
```

Both loaders share one contract: each input is declared once as a `Table`
(below) and a loader's job is only to fetch the rows of its source, line
them up with the declaration's columns, and hand them to it. Everything
that crosses sources — joins, grouping, the derivations the planner's
inputs need — lives in `loadinputs`, never in a loader or a declaration.

## Translations (`translate.py`)

A **translation** describes how one source — a SQL table or query, or a
local file — becomes a dataframe. It is purely columnar: every source row
becomes one dataframe row, and the only work is naming the columns and
converting their values. Two classes carry it.

### `Column`

```python
Column(name: str,
       src_name: str | None = None,
       dtype: str | None = None,
       converter: Callable | None = None,
       read_na_as: Any = None)
```

- **`name`** — the column's name in the resulting dataframe.
- **`src_name`** — the column's name in the source, when it differs from
  `name`. `None` means the source uses `name` as well. The loaders use it
  to pick the column out of the source (the SELECT list, the file's
  header); the translation itself never sees source names.
- **`dtype`** — the pandas dtype the column is forced to (`astype`), or
  `None` to leave pandas' default inference alone.
- **`converter`** — a function applied to every value of the column, or
  `None` for none.
- **`read_na_as`** — the value every null in the source (`None` or `NaN`)
  is replaced with before anything else happens. The default `None`
  normalises `NaN` to `None`; a column may name any other stand-in (`0`,
  `""`, a sentinel date).

A column's values go through a fixed pipeline, in this order:

1. **Null replacement** — every null becomes `read_na_as`.
2. **Conversion** — `converter` is applied to every value, replacements
   included. A converter therefore always sees the stand-in rather than a
   raw `None`/`NaN`, and may rely on it.
3. **Casting** — `astype(dtype)` when `dtype` is set. The converter's
   output has to be castable to it.

A column with neither a converter nor a dtype still has its nulls
normalised by step 1.

### `Table`

```python
Table(name: str, columns: tuple[Column, ...])

Table.from_tuples(self, data: Iterable[tuple]) -> pd.DataFrame
```

- **`name`** — the label the loaders key on to find the declaration for an
  input. It is *not* required to be the physical SQL table or file name;
  the loaders own that mapping.
- **`columns`** — the declared columns, in dataframe order.

`from_tuples` builds the dataframe: each tuple is one row, its positions
matching `columns` in declared order, and every tuple must have exactly
`len(columns)` entries. The result has the columns' `name`s as its header,
and each column has been run through its pipeline above.

**Errors are not scanned for up front.** A conversion or cast that fails
raises from wherever it is hit, with pandas' or the converter's own
exception; `from_tuples` does no validation pass of its own beyond the
tuple-length requirement. The loaders are responsible for handing rows in
the declared order — `from_tuples` is positional and cannot tell a
reordered tuple from a correct one.

## Loading sources (`loaders.py`)

One module turns every source into a dataframe: the plant's SQL Server,
reached over `pyodbc` (`load_sql_config` + `run_query`), and local CSV
files (`read_csv`). Each loader ends the same way — it hands rows to a
`Table.from_tuples` — and each matches its source to the table the same
way:

**Columns are matched by name, not by position.** A loader reads the
source's column names (a result set's cursor description, a CSV's header
row) and, for each `Column` of the table, picks the source column named by
its `src_name` (or its `name` when `src_name` is unset). The rows are
reordered into the table's declared order before `from_tuples` sees them,
so a query's SELECT list or a file's header may be in any order and may
carry extra columns, which are dropped. A declared column the source does
not contain raises `SourceColumnError` naming the column and the source.

### The connection config

Connection details live in a small text file, never in code. Its layout is
one `<key>=<value>` pair per line:

```
# plant database — reader login
HOST=sql.plant.local
PORT=1433
DATABASE=Production
UID=planner_ro
PWD="s3cret=with=equals"
TrustServerCertificate=yes
```

- A line whose first non-blank character is `#` is a comment. Blank lines
  are ignored. Whitespace around the key and around the value is stripped.
- A value is everything after the first `=`. A value that itself contains
  `=` must be wrapped in quotes; the quotes are stripped and the inside is
  taken verbatim.
- Keys are case-sensitive and kept as written.

```python
load_sql_config(fpath: str | None = None) -> dict[str, str]
```

reads that file and returns its pairs. With no `fpath` it reads the file
named by the environment variable **`SQLCONFIG`**. It then verifies the
keys the connection string needs:

- **Required:** `HOST`, `PORT`, `DATABASE`, `UID`, `PWD` — every one must
  be present with a non-empty value.
- **Optional, no default:** `TrustServerCertificate`, `Encrypt`. When
  present they are passed through to the connection string; when absent
  they are simply not set, and the driver's own behaviour applies. The
  loader never invents a value for them.

A missing file, no `fpath` with `SQLCONFIG` unset, a malformed line (no
`=`), or a required key missing or empty raises `SQLConfigError` naming
the problem. Keys beyond the ones above are returned untouched and
ignored by the connection string.

### Running a query

```python
run_query(query_str: str, tbl: Table, cfgpath: str | None = None) -> pd.DataFrame
```

builds the connection string from `load_sql_config(cfgpath)`, opens a
`pyodbc` connection, executes `query_str` as given — a complete statement,
with any date arguments already rendered into it by `SQLQuery.get_query`
(below); `run_query` substitutes nothing itself — fetches every row,
closes the connection, matches the result's columns to `tbl` by name
(above), and returns `tbl.from_tuples(...)` over the reordered rows.
Driver and database errors (`pyodbc.Error`) propagate as they are.

### Reading a CSV

```python
read_csv(fpath: str, tbl: Table, sep: str = ',',
         na_values: Sequence[str] = ('', 'None')) -> pd.DataFrame
```

reads the file at `fpath` with `sep` as the delimiter (`'\t'` for the
plant's TSVs), taking its first row as the header, matches the header to
`tbl` by name (above), and returns `tbl.from_tuples(...)` over the
remaining rows in file order. The file is read with **no type inference of
its own**: every cell reaches the table as the string the file holds,
except a cell equal to one of `na_values`, which becomes a null. The
default covers the empty cell and the literal text `None`, which is how
the reconcile skill's status files write a missing value. So a column's
`read_na_as` / `converter` / `dtype` are the only things deciding a
value's type. Reading the same file through `read_csv` and through a
query returning the same text therefore gives the same dataframe. A
missing file raises the usual `FileNotFoundError`.

### Dated file names

```python
get_file_name(stem: str, ext: str, dt: date | None = None, is_dated: bool = True) -> str
```

names a local file the way the planner's outputs are named: `<stem>_<dt
as YYYYMMDD>.<ext>` when `is_dated`, else plain `<stem>.<ext>`. `dt`
`None` means today (resolved at call time, not import time), so the
usual call names today's export. `ext` is given
without its dot. The helper only builds the name — it joins no directory
and touches no file — so callers combine it with whatever folder the
inputs live in.

### Queries with date arguments (`queries.py`)

Some queries are bounded by a date — the demand due after a day, the
tickets printed since one. Rather than a loose `str`, every query is a
`SQLQuery`:

```python
SQLQuery(raw_str: str, num_args: int, date_fmt: str | None)

SQLQuery.get_query(self, *args) -> str
```

- **`raw_str`** — the complete SQL text with one positional placeholder,
  `{}`, per argument, in the order the arguments are passed. Any literal
  brace in the SQL is written doubled (`{{`, `}}`), as for `str.format`.
- **`num_args`** — how many arguments the query takes; `0` for a query
  that takes none.
- **`date_fmt`** — the `strftime` format each date argument is rendered
  with, including whatever quoting the SQL needs around it (for example
  `"'%Y-%m-%d'"`). On top of `strftime`'s directives it accepts the
  **unpadded** forms `%-d`, `%-m`, `%-H`, `%-M`, `%-S` (any numeric
  directive with a `-` after the `%`): `strftime` only knows these on
  some platforms, so the module's `render_date(value, fmt)` renders them
  itself and hands the rest to `strftime`; `%%` stays a literal percent,
  and `%-` before a non-numeric directive is a `ValueError`. `None`
  exactly when `num_args` is `0`; constructing a `SQLQuery` that breaks
  that pairing (or has a negative `num_args`) is a `ValueError` at
  definition time, so a bad constant fails on import.

`get_query(*args)` takes exactly `num_args` `date` (or `datetime`)
arguments, renders each with `date_fmt` through `render_date`,
substitutes them into `raw_str` in the order passed, and returns the
finished statement for `run_query`. The wrong number of arguments raises
`QueryArgumentError`; the arguments' types are not checked beyond what
`strftime` itself enforces.

### The queries and their tables

Every query the planner's inputs need is a **named `SQLQuery` constant**
in `queries.py`, and its shape is a **matching `Table` constant** in
`tables.py`, named for the same input. The tables of the file-borne
inputs live in `tables.py` as well, so it is the one place every input's
shape is declared. The pairing of a query with its table is by name
convention and by the `loadinputs` call that uses them together; there is
no registry. Adding a database input means adding one constant to each
file; adding a file input means adding its `Table`.

The current inputs are `ACTIVE` (the beam-set inventory), `ASSIGNED`
(sets assigned to bars, not yet threaded), `DOFFED` (piece tickets since a
date, one date argument), `THREADED` (the set on each bar), `LAST_TKT`
(each machine's last piece ticket with its four bars), `TKTS_SINCE`
(every ticket whose doff started since a date, one date argument — read
from the tickets table rather than the scans, so it also catches rolls
on **dummy tickets**, which cannot be scanned and only appear once the
shipping warehouse has processed them; its table shares `DOFFED`'s
columns), `THREADINGS_SINCE` (every threading ticket scanned since a
date, one date argument — the ticket's text names the machine, item, set
and bars, which the query splits apart; with the racks on the machine's
roll at the time and the set's initial weight, merge and vendor),
`SCANNED` (every ticket
scanned since a date, one date argument) and `ALL_VARIANTS` (the
knittable style variants). The dated queries render their argument into
`DATETIMEFROMPARTS(...)` through the shared `DATETIMEFROMPARTS_FMT`, its
parts unpadded (`2026, 10, 7, 0, 0, 0`).
Every query's final SELECT list aliases each column explicitly (no `*`),
so a table can be checked against its query.

Each `Table` takes every column exactly as its query labels it, in the
query's order, and forces it to one of four **kinds**, so a value's type
never depends on whether the rows came from pyodbc (`str`, `int`,
`Decimal`, `datetime`) or from a CSV (all text):

- **string** (`to_string` → pandas `string`): identifiers, names and
  codes — `set_no`, `ticket`, `machine`, `style`, `variant`, `kind`,
  `merge`, `vendor`, `luster`, `yarn_type`, `desc`, `stitch`, `thread`,
  `comments`, `beam_size`, `item`, `bars` (a threading ticket can name
  more than one bar). A merge code looks numeric but is an identifier (it is the
  blacklist's key), so it is text; an integral float becomes its digits.
- **count** (`to_number` → nullable `Int64`): `bar`, `beams` / `nbeams`,
  `ends`, `denier`. A non-integral value fails the cast.
- **number** (`to_number` → `float64`): weights and quantities (`lbs`,
  `rem_lbs`, `init_lbs`, `rack_wt`, `racks`), `pct`, `gauge`, `width`,
  `rl`.
- **timestamp** (`utc_to_plant`): the plant's systems store timestamps in
  **UTC** and the planner's clock is plant-local, so `rcv_date`,
  `assign_date`, `assn_ts`, `start_ts`, `end_ts` and `scan_ts` become the
  same instant on `PLANT_TZ` (the zone `schedule_json` already defines),
  left naive, as the retimer does for doff times. A naive `datetime` is
  taken as UTC; an aware one or an ISO string of either is accepted too.

Nulls stay null in every kind (`<NA>`, `NaN`, `NaT`); the converters pass
`None` through. A column name has the same kind in every table it appears
in, with one exception called out below (`bar` in `FLOOR_STATUS`). The
per-bar groups (`bar1_… bar4_`) take their kind from the field suffix.

**The file-borne inputs** are three dated TSVs (named by `get_file_name`
with `ext='tsv'`, read with `sep='\t'`), each with its `Table`:

- **`FLOOR_STATUS`** — the floor's per-bar notes: `machine`, `bar`,
  `status`, all strings. `machine` is normalised by `norm_machine` as the
  racks file's is (below); `bar` is text, not a count, because one note
  can cover two bars (`1/2`).
- **`MACHINE_STATUS`** — the reconciled machine status the
  reconcile-machine-status skill writes: one row per machine on the
  floor, in `LAST_TKT`'s columns (it reuses that table's declaration)
  **plus a final `status`** string — `running`, `standing` or
  `overhaul`, the values the planner's machine loader accepts. The
  timestamps are still UTC since the skill passes the database's values
  through. This file is the floor list: `gen_machines` writes exactly
  its machines.
- **`RACKS`** — rack counts per machine. The source headers are `MC` and
  `Racks` (`src_name`), landing as `machine` (string) and `racks`
  (number); the machine id is normalised by `norm_machine` to the
  database's form — one upper-case letter plus a zero-padded two-digit
  number (`b8` → `B08`) — so it joins to the query results. A value that
  is not a letter and one or two digits raises `ValueError`.

> **Open:** the ODBC driver name is not among the config keys. The
> connection string needs one; the design assumes a fixed driver constant
> in `loaders.py` (the dashboard's reader config uses `ODBC Driver 17 for
> SQL Server`). Say if it should instead be a config key.

## Producing the planner's inputs (`loadinputs/`)

`loadinputs` is a set of functions, one per planner input, each taking
the dataframes it needs (already loaded through the tables above) and
returning the JSON-ready Python structure the planner's loaders read.
The joins, grouping and derivations live here and nowhere else. Each
function is documented by its inputs, its output record, and the rules
that produce one from the other. Writing the structures to files is
covered after the functions.

Two conventions run through every function:

- **Machine ids** come in from the database padded (`B08`) and go out in
  the planner's form (`B8`): the letter and the number with no leading
  zero, as `plan machines` already normalises them. This holds for every
  output — the machines file and the assigned sets alike.
- **Timestamps** come in naive plant-local (the tables' `utc_to_plant`)
  and go out as ISO-8601 text carrying the plant's UTC offset
  (`2026-10-13T12:14:38-04:00`), as the existing input files show.

### `gen_machines(runout, machine_status, racks, variants) -> list[dict]`

The machines file: one record per machine **on the floor**, describing
where the machine stands right now. The floor list is the
**machine status** (`MACHINE_STATUS`): the reconcile-machine-status
skill writes one row per machine on the knit-machine master, so every
row is written, in the file's order, whether or not anything else knows
the machine. The record builds on `compute_runout` (below) for the sets
and their pounds, on the machine status for what is running, the
machine's status and the sets' fallback identities, and on `variants`
for how a style's bars pair up.

```json
{"id": "B8", "is_new": false, "init_item": "AU5429D-HASH/16", "status": "running",
 "init_top_lbs": 0.0, "init_btm_lbs": 2714.07, "init_roll_lbs": 481.53,
 "init_btm_set": {"set_no": "47999", "merge": "2609", "vendor": "Ashfar Enterprises, Inc."},
 "init_top_set": {"set_no": "2-3813", "merge": "A716B", "vendor": "Hyosung Holdings USA, Inc."}}
```

- **`id`** — the machine, in the planner's form.
- **`is_new`** — `true` for the new line: the machines whose letter is
  `M`, `N`, `O` or `P`.
- **`init_item`** — the machine status's `style`.
- **`status`** — the machine status's `status` column, carried
  verbatim (`running` / `standing` / `overhaul`, the values the
  planner's loader accepts). A null status means **`running`**, the
  file's own default for a machine nothing lists as standing.
- **The two sets.** Which bars belong together comes from the **style**:
  the `variants` row for `init_item` groups the bars carrying ends by
  merge, and the group holding **bar 1 is the bottom** set; the other
  group is the top set — the rule `plan machines` already applies (a
  single-bar set plus a split-lease pair on two bars). Each set's
  identity, `{set_no, merge, vendor}`, is taken from the group's **first
  bar** (the same set is on every bar of a split-lease pair), looked up
  in this order:
  1. `runout[machine][bar]`, carried verbatim;
  2. else the machine status's `bar<n>_set_no` / `bar<n>_merge` /
     `bar<n>_vendor` for that bar — the plant's last ticket is the
     fallback whenever `compute_runout` has nothing for the bar (the
     machine is missing from `runout`, or the bar is) — reported;
  3. else **`null`**: nothing is on the bar (the planner's loader takes a
     null set reference as an unnamed bar).
- **`init_btm_lbs` / `init_top_lbs`** — the pounds left on each set: the
  **sum** of `runout[machine][bar].lbs` over the group's bars, a bar
  `runout` lacks contributing `0.0`. `compute_runout` split a
  split-lease set's weight evenly across its bars, so summing the pair
  recovers the set's remaining weight.
- **When the style cannot be grouped** — `variants` has no row for
  `init_item` (a machine down for overhaul, say), or its bars do not fall
  into exactly two merges — the machine is still written (the floor list
  must be complete) with a fixed grouping: **bar 1 is the bottom set and
  bars 2–4 together are the top set** (identity from the lowest of them
  that has one). The machine is reported.
- **`init_roll_lbs`** — the pounds already wound on the roll in progress:
  the machine's `racks` from the racks file (racks wound so far) × the
  status's `rack_wt` / 100 (`rack_wt` is pounds per hundred racks, as
  `plan machines` converts it). A machine the racks file does not list,
  or whose `rack_wt` is null, has `0.0` on the roll. (This differs from
  `plan machines`, which wrote the pounds *remaining* to the target
  weight; the planner's current input carries the pounds wound.)
- **A machine with no ticket** (a status row with no `scan_ts`) is still
  written: its sets and pounds come from `runout` like any other's, and
  its roll from the racks file — typically zero on the roll.

> **Open:** `schedule/io.py` reads `init_roll_lbs` as the pounds
> *remaining* to finish the roll (`init_roll_lbs_remaining`, capped at
> the item's target weight), while this design — as agreed — writes the
> pounds *wound*. One of the two has to change; the design stands as
> written until you say which.

### `gen_inventory(active, assigned, floor_status) -> tuple[list[dict], list[dict]]`

Two lists: the **beam-set inventory** (every usable set, flagged whether
it is assigned) and the **assigned sets** (the subset sitting against a
machine's bar, with where and in what state).

**The inventory** is `active`, filtered: a set with a non-null `comments`
is dropped, and so is one with a null `beams`. Each surviving row becomes

```json
{"set_no": "1-1202", "received": "2026-09-14T21:30:42-04:00", "assigned": true,
 "merge": "6268G", "vendor": "Hyosung Holdings USA, Inc.", "lbs": 2197.0,
 "beams": 4, "ends": 1300, "denier": 75, "luster": "SDBK", "desc": "TEXT POLY",
 "size": "30 x 42"}
```

- `received` is `rcv_date`; `assigned` is `true` iff `assign_date` is not
  null; `desc` is `yarn_type`; `size` is `beam_size` (the beam-size name
  both queries join in from `new_beamsizeBase`); the rest are the row's
  columns of the same name. Order is the query's (`set_no`).

**The assigned sets** are the `assigned` table's rows — every one of
them. The query returns, per `(machine, bar)`, the sets queued against
that bar that have not yet been consumed (up to five), so each row is one
place in a bar's queue, and the queue runs in assignment-date order.
Each row is joined to `floor_status` by `(machine, bar)` for its status:

```json
{"set_no": "2-3822", "assigned": "2026-10-13T11:33:28-04:00", "merge": "A716B",
 "vendor": "Hyosung Holdings USA, Inc.", "lbs": 1864.0, "beams": 4, "ends": 1172,
 "luster": "SD", "desc": "TEXT POLY", "machine": "B8", "bar": 3,
 "status": "inventory", "size": "30 x 42"}
```

- `assigned` is the `assn_ts`; `machine` is in the planner's form (`B8`);
  `bar` is the integer bar; `desc` is `yarn_type`; `size` is `beam_size`;
  `status` is the floor's note for that machine and bar, `"inventory"`
  when the floor file has none (the three values the planner accepts are
  `inventory` / `staged` / `hung`, per the approved assigned-set status
  design). A floor note whose `bar` names two bars (`2/3`) applies to
  both. Order is by `machine`, then `bar`, then `assigned` ascending —
  the queue order. The `active` table plays no part in this list; it is
  only the source of the inventory above.

### `gen_doffed(doffed, tkts_since) -> dict[str, list[dict]]`

The doffed rolls: every roll doffed since the query date, keyed by
machine, each machine's rolls in the order they were doffed. This is the
retimer's `doffed-rolls.json`.

```json
{"A2": [{"ticket_no": "A02-2810A", "style": "3368-HYO/6", "racks": 2163.0,
         "lbs": 535.9042, "doff_ts": "2026-10-12T23:34:58-04:00"}, ...],
 ...}
```

**Two sources, one of them patchy.** `doffed` comes from the scans: a
row per piece ticket scanned on a machine, its `start_ts` the scan and
its `end_ts` the next ticket's scan on that machine. It misses rolls on
**dummy tickets**, which cannot be scanned. `tkts_since` comes from the
tickets table itself and has those rolls, with their own doff start and
end, but only once the shipping warehouse has processed them. The
function merges the second into the first:

1. **Find the gaps.** A `tkts_since` roll whose `ticket` is not in
   `doffed`, and whose `start_ts`–`end_ts` lands inside the
   `start_ts`–`end_ts` of a `doffed` roll on the same machine, is a roll
   the scans skipped.
2. **Splice it in.** The roll is inserted immediately after that `doffed`
   roll; the `doffed` roll's `end_ts` becomes the inserted roll's
   `start_ts`; and if the `doffed` roll had a successor on the machine,
   that successor's `start_ts` becomes the inserted roll's `end_ts`. The
   machine's timeline stays contiguous. Several skipped rolls inside one
   span are matched against the span **as the scans had it** and spliced
   in as a group, in start order: the host ends where the first starts,
   the successor starts where the last ends, and the skipped rolls keep
   their own times in between (a gap between two of them is left as it
   is — their doff times are real, the scans' are not).
   A skipped roll that falls **after a machine's last scanned roll** is
   appended after it in the same way (the last scanned roll's open
   `end_ts` becomes the appended roll's `start_ts`, so it is now doffed
   too); one on a **machine with no scanned rolls** starts that machine's
   list. A skipped roll that lands *before* a machine's first scanned
   roll, or straddles two, matches nothing and is reported and left out.
3. **Group and sort.** The rolls are grouped by machine (keys in the
   planner's form) and each machine's list sorted by `start_ts`.

Each roll is written as its `ticket` (`ticket_no`), `style`, its total
`racks` (kept for `compute_runout` below), `lbs` = `racks` × `rack_wt` /
100 (as the roll pounds in `gen_machines`), and
`doff_ts` = its **`end_ts`** — the scan marks a roll's start, so a roll is
doffed when the next ticket is scanned (or, for a dummy-ticket roll, at
its own doff-end time). A roll whose `end_ts` is still null after the
splice — each machine's latest, still on the machine — is not doffed and
is not written.

(The sample file keys its machines padded, `A02`; it was made by the old
scripts. This function writes the planner's form, `A2`, like every other
output here; the retimer normalises on load either way.)

### `compute_runout(threadings, doffed, racks, variants, last_tkt, threaded) -> dict[str, dict[int, dict]]`

The set on every bar in use and the pounds left on it:

```python
{"B8": {1: {"set_no": "47999", "merge": "2609",
            "vendor": "Ashfar Enterprises, Inc.", "lbs": 1357.03},
        2: {...}, 3: {...}},
 ...}
```

machines in the planner's form, bars by number. Nothing in the plant's
systems records a running set's weight directly; it is reconstructed
from what has been knit off it since it was threaded.

**Inputs.** `threadings` is the `THREADINGS_SINCE` table (each threading
ticket: machine, item, set, the bars it went on, the racks on the roll
in progress at that moment, the scan time, the set's initial weight);
`doffed` is `gen_doffed`'s output (each machine's doffed rolls in order,
with style and total racks); `racks` is the racks file (the racks wound
so far on each machine's roll in progress); `variants` is `ALL_VARIANTS`
(per style: `rack_wt`, pounds per hundred racks, and `bar<n>_pct`, the
share of each roll's weight each bar supplies); `last_tkt` is the
`LAST_TKT` table (each machine's last piece ticket: the style now
running and the set on each bar); `threaded` is the `THREADED` table
(the plant's own record of the set on each bar and the weight it has
left, `rem_lbs` — the fallback when a bar's threading is not in the
window).

**The machines and bars** are `last_tkt`'s: every machine it lists, and
on each the bars whose `bar<n>_set_no` is not null — the bars in use.

**For each such machine and bar:**

1. **The running set** is the machine's latest threading that names the
   bar (`bars` is the bar numbers joined by `-`, `1-2` for bars 1 and 2;
   a ticket naming several bars put one set across all of them). Its
   `init_lbs` is the set's weight when threaded, **split evenly** across
   the bars it names: a set on two bars starts each bar at `init_lbs /
   2`. The bar's `set_no`, `merge` and `vendor` are the threading's. A
   bar with **no threading** in `threadings` falls back to the plant's
   own record: its `set_no` / `merge` / `vendor` come from `last_tkt`'s
   `bar<n>_*` columns and its pounds are the `rem_lbs` that `threaded`
   lists for that machine and bar (the set's current weight as the
   plant tracks it). When `threaded` has no row for the bar either, the
   pounds are **`0.0`**. Either way the bar is reported: the
   window the threadings were queried over has to reach back past every
   running set's threading, and a bar it misses is one the user has to
   look at.
2. **The roll in progress at threading** is the doffed roll whose span
   contains the threading's scan — with the rolls contiguous, the first
   roll on that machine whose `doff_ts` is after the scan. The threading
   recorded `racks` already on that roll at run-out, so the racks it
   wound *off the new set* are its total `racks` − the threading's
   `racks`. Pounds off the bar = those racks × the roll's style's
   `rack_wt` / 100 × that bar's `pct` / 100.
3. **Every later doffed roll** on the machine took its whole weight off
   the set: total `racks` × its style's `rack_wt` / 100 × the bar's
   `pct` / 100.
4. **The roll in progress now**, if the racks file lists the machine,
   has taken the racks wound so far × `rack_wt` / 100 × `pct` / 100. Its
   style is the machine's `style` in `last_tkt` — the last piece ticket
   scanned is the roll on the machine.
5. **Remaining** = the bar's share of `init_lbs` − the sum of steps 2–4,
   floored at `0.0` (a negative result means the set ran out; it is
   reported).

A threading that no doffed roll spans (step 2: the machine had no roll
in progress, or the scan predates every doffed roll) takes nothing off
the set for that step; step 3 then starts from the first roll doffed
after the scan. A style that `variants` does not have raises — the
pounds cannot be computed without its weight and shares.

### `make_input_file(name, fpath, ...)` — writing an input

Every function above returns a JSON-serialisable object. One entry point
turns a name into a file:

```python
class InputName(Enum):
    MACHINES = 'machines'            # gen_machines
    BEAM_SETS = 'beam-sets'          # gen_inventory()[0]
    ASSIGNED_SETS = 'assigned-sets'  # gen_inventory()[1]
    DOFFED_ROLLS = 'doffed-rolls'    # gen_doffed
    RUNOUT = 'runout'                # compute_runout

make_input_file(name: InputName, fpath: str, *,
                since: date, files_dir: str, dt: date | None = None,
                cfgpath: str | None = None) -> None
```

`make_input_file` matches `name` to its function and to the queries and
files that function needs, loads exactly those, calls it, and writes the
result to `fpath` as JSON (indented, `ensure_ascii=False`, timestamps
already rendered as text by the functions). The mapping:

| `name` | function | queries (`run_query`) | files (`read_csv`, TSV) |
|---|---|---|---|
| `MACHINES` | `gen_machines` (via `compute_runout`) | `THREADINGS_SINCE(since)`, `DOFFED(since)`, `TKTS_SINCE(since)`, `ALL_VARIANTS`, `LAST_TKT`, `THREADED` | `racks`, `machine_status` |
| `BEAM_SETS` | `gen_inventory` → first list | `ACTIVE`, `ASSIGNED` | `floor_status` |
| `ASSIGNED_SETS` | `gen_inventory` → second list | `ACTIVE`, `ASSIGNED` | `floor_status` |
| `DOFFED_ROLLS` | `gen_doffed` | `DOFFED(since)`, `TKTS_SINCE(since)` | — |
| `RUNOUT` | `compute_runout` | `THREADINGS_SINCE(since)`, `DOFFED(since)`, `TKTS_SINCE(since)`, `ALL_VARIANTS`, `LAST_TKT`, `THREADED` | `racks` |

`RUNOUT` calls `gen_doffed` itself for the doffed rolls it needs, and
`MACHINES` calls `compute_runout` (and so `gen_doffed`) itself; neither
reads another name's file, so the outputs cannot drift apart. Within one
call every query and file is loaded **once** (`MACHINES` needs
`ALL_VARIANTS` and `racks` in two places); across calls nothing is
cached. The two inventory names each run `gen_inventory` in full and
write their half; a caller wanting both pays for the queries twice,
which is acceptable for a once-a-morning tool.

The function lives in `loadinputs/make_input.py` with `InputName`, and
`loadinputs` re-exports both.

The keyword arguments are what the loaders need beyond the name:

- **`since`** — the date the dated queries take (`DOFFED`, `TKTS_SINCE`,
  `THREADINGS_SINCE`). Required; it has no sensible default, and it must
  reach back past every running set's threading for `RUNOUT`.
- **`files_dir`** and **`dt`** — where the dated TSVs live and which
  day's: each is read from `files_dir / get_file_name(<stem>, 'tsv',
  dt)`, with the stems `racks`, `machine_status`, `floor_status`; `dt`
  `None` means today, as in `get_file_name`.
- **`cfgpath`** — passed through to `run_query`; `None` means
  `SQLCONFIG`.
A name whose files or queries are not needed ignores the corresponding
arguments. An unknown `name` is a `ValueError`.

**`make_input_file` is the module's entry point and a CLI command.**
`planners/cli.py` registers it as `plan inputs`, the way the other
`*_cmd` functions are registered, so every parameter carries a `typer`
annotation (module-level `Annotated` aliases, as `machines_cmd.py` and
`retime_cmd.py` do) and the help text comes from them:

```
plan inputs <name> <fpath> --since YYYY-MM-DD --files-dir DIR
                           [--date YYYY-MM-DD] [--db-config PATH]
```

- `name` — a `typer.Argument` over the `InputName` enum (typer offers
  its values as the choices: `machines`, `beam-sets`, …).
- `fpath` — a `typer.Argument`, the output path (`dir_okay=False`).
- `--since` — a required `typer.Option`, a date (`%Y-%m-%d`; typer
  parses dates as `datetime`, which `SQLQuery` renders like a `date`).
- `--files-dir` — a required `typer.Option`, an existing directory.
- `--date` — an optional `typer.Option`, the TSVs' day; default today.
- `--db-config` — an optional `typer.Option`, an existing file; default
  the `SQLCONFIG` environment variable.

Called from Python the same function takes the same arguments by
keyword; the annotations do not change its behaviour. Errors the user
can act on (a missing file, an unknown style, a bad config) surface as
`typer.BadParameter` from the command, as the other commands do.

### Reporting

Several functions above *report* a row they could not use — a machine
whose bars do not group into two sets, a skipped roll that fits no gap,
a bar with no threading, a set that ran out. A report never changes the
output; it tells the user what to look at. The functions emit them
through the module's `logging` logger at `WARNING`, one line each
naming the machine / bar / ticket concerned, and the CLI that drives
`loadinputs` configures logging so they reach the terminal. Nothing is
raised for a reportable condition; only an unusable input (a style
missing from `variants`, a malformed file) raises.
