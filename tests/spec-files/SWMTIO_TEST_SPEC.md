# Specification of coverage of swmtio tests

Covers `planners/infinite/swmtio` (`tests/swmtio_tests.py`): the **translation
classes** (`translate.py`), the **loaders** (`loaders.py` — the connection
config, by-name column matching, `run_query` against a stand-in connection,
`read_csv`, `get_file_name`), **`SQLQuery`** (`queries.py`) and the **declared
queries and tables** (`queries.py` / `tables.py` — the pairing, the column kinds
and their converters, the file-borne tables), and **`loadinputs`** (the shared
conventions, `gen_inventory`, `gen_doffed`, `compute_runout`, `gen_machines`,
and the entry point `make_input_file` / `plan inputs`). Everything is pure:
`run_query` is proven with a stand-in `_connect` (no driver, no server), files
through `tempfile`, and `make_input_file` with `run_query` patched by a
recorder that serves empty tables. The `loadinputs` fixtures are small
dataframes built in plant-local time with hand-computed expectations. Design:
`planners/infinite/swmtio/DESIGN.md`.

## 1. Translations (`translate.py`)

### 1.1 `Column` — the value pipeline (`apply`)

1. **Null replacement, default** — `None`, `float('nan')`, `numpy.nan`,
   `pd.NA` and `pd.NaT` all become `None` before anything else, as a
   recording converter observes; in the resulting series they are null
   (pandas may re-infer the stand-in, e.g. to `NaN` in a string column).
2. **Null replacement, custom** — with `read_na_as=0`, every null becomes
   `0` and non-nulls are untouched.
3. **Converter sees the replacement** — with `read_na_as=''` and a converter
   that records its inputs, the converter is called once per value and
   receives `''` (never `None`) for the null.
4. **Cast after conversion** — `converter=int` + `dtype='int64'` on text
   values yields an `int64` series; the converter runs first (text would not
   cast directly).
5. **No dtype → inference** — with no `dtype`, a column of ints infers an
   integer dtype; the series is named `name`.
6. **`source`** — `src_name` when set, else `name`.

### 1.2 `Table.from_tuples`

7. **Shape** — the frame's columns are the declared `name`s in order, one
   row per tuple, positions matching the declared order; `names` /
   `sources` list the result / source names in order.
8. **Length check** — a tuple shorter or longer than `len(columns)` raises
   `ValueError` naming the table and the row index; nothing else is
   validated up front.
9. **Empty data** — no tuples yield an empty frame that still has the
   declared columns.
10. **Errors propagate** — a converter that raises on one value propagates
    its exception (not wrapped); so does a failing cast (`astype`).

## 2. The connection config (`loaders.py`)

### 2.1 `parse_sql_config`

1. **Pairs** — `KEY=value` lines land as `{'KEY': 'value'}`; keys are kept
   as written (case-sensitive: `Encrypt` ≠ `ENCRYPT`).
2. **Comments and blanks** — a line whose first non-blank character is `#`
   and a blank / whitespace-only line are skipped.
3. **Whitespace** — spaces around the key and around the value are stripped.
4. **First `=` splits** — an unquoted `a=b=c` gives key `a`, value `b=c`
   (the quote rule is required for readability, not enforced).
5. **Quoted values** — `"p=w"` and `'p=w'` both yield `p=w`; a lone or
   mismatched quote is kept verbatim.
6. **Malformed** — a line with no `=` raises `SQLConfigError` naming the
   source and line number; an empty key (`=v`) raises too.

### 2.2 `load_sql_config`

7. **Explicit path** — reads the file and returns its pairs, optional and
   unknown keys included untouched.
8. **`SQLCONFIG`** — with no `fpath`, the file named by the environment
   variable is read.
9. **Nothing named** — no `fpath` and `SQLCONFIG` unset (or empty) raises
   `SQLConfigError`.
10. **Missing file** — a path that does not exist raises `SQLConfigError`.
11. **Required keys** — a missing required key, and a present-but-empty one,
    raise `SQLConfigError` naming every offender (`HOST`, `PORT`, `DATABASE`,
    `UID`, `PWD`).
12. **Optional keys have no default** — a config without
    `TrustServerCertificate` / `Encrypt` returns without them.

### 2.3 `connection_string`

13. **Exact text** — renders `DRIVER={ODBC Driver 17 for SQL Server};SERVER=
    <HOST>,<PORT>;DATABASE=<DATABASE>;UID=<UID>;PWD=<PWD>;` with no optional
    segments when none are configured.
14. **Optional segments** — `TrustServerCertificate=…;` and `Encrypt=…;` are
    appended, in that order, only for the keys present; an unknown key is
    never rendered.

## 3. Matching a source to a table (`align_rows`)

1. **Reorder by name** — source columns in a different order than the table
   come back in declared order, picked by `source` (`src_name` else `name`).
2. **Extras dropped** — a source column no table column names is dropped.
3. **Missing** — a declared column absent from the source raises
   `SourceColumnError` naming the column, the table and the source label.

## 4. `run_query` (stand-in connection)

`loaders._connect` is patched with a factory returning a fake connection
whose cursor records the statement and serves a fixed `description` /
`fetchall`.

1. **Wiring** — `_connect` receives `connection_string(load_sql_config(
   cfgpath))`; the cursor executes `query_str` **verbatim** (nothing
   substituted); the frame is the table's, rows reordered by name.
2. **Closed on success** — the connection is closed after the fetch.
3. **Closed on failure** — when `execute` raises, the exception propagates
   and the connection is still closed.
4. **Missing column** — a result set lacking a declared column raises
   `SourceColumnError` (and the connection is closed).

## 5. `read_csv`

1. **Header match, order free** — a file whose header is in a different
   order than the table, with an extra column, loads in declared order.
2. **Separator** — `sep='\t'` reads a TSV; the default is `,`.
3. **No inference** — with a pass-through table, cells arrive as the file's
   strings (`'1'` stays `'1'`).
4. **Default nulls** — an empty cell and the literal `None` both become a
   null; a custom `na_values` replaces the default set (so `None` is then a
   string and `NA` a null).
5. **BOM and blank tail** — a UTF-8 BOM before the header is ignored, as is
   a trailing empty line.
6. **No header** — an empty file has no columns: a table with any column
   raises `SourceColumnError`.
7. **Missing file** — `FileNotFoundError`.

## 6. `get_file_name`

1. **Dated** — `('machine_status', 'tsv', date(2026, 10, 14))` →
   `machine_status_20261014.tsv`.
2. **Undated** — `is_dated=False` → `<stem>.<ext>`, `dt` ignored.
3. **Default today** — with no `dt`, the stamp is `date.today()` at call
   time (checked against a patched `date`).

## 7. `SQLQuery` (`queries.py`)

1. **Rendering** — two placeholders and two dates render in the order
   passed, each with `date_fmt` (quoting included in the format).
2. **Date or datetime** — a `datetime` keeps its time parts in a format that
   uses them; a `date` renders them as zeros.
3. **No arguments** — `num_args=0` renders `raw_str` as is.
4. **Wrong count** — too few or too many arguments raise
   `QueryArgumentError`.
5. **Literal braces** — doubled braces in `raw_str` render as single braces.
6. **Definition-time checks** — `num_args > 0` with `date_fmt=None`,
   `num_args == 0` with a format, and a negative `num_args` each raise
   `ValueError` on construction.
7. **Unpadded directives** (`render_date`) — `%-m, %-d, %-H, %-M, %-S` on
   2026-01-07 06:05:04 give `1, 7, 6, 5, 4` while `%m` beside them stays
   `01`; `%%` renders a literal `%` and `%%-d` the text `%-d`; `%-b` (not
   numeric) raises `ValueError`; a `SQLQuery` whose `date_fmt` uses them
   renders through the same path.

## 8. The declared queries and tables (`queries.py` / `tables.py`)

### 8.1 Pairing

1. **Every query has its table** — for each of `ACTIVE`, `ASSIGNED`,
   `DOFFED`, `THREADED`, `LAST_TKT`, `TKTS_SINCE`, `THREADINGS_SINCE`,
   `SCANNED`, `ALL_VARIANTS`, `queries.X` is a `SQLQuery` and `tables.X` a
   `Table` named `X`; `TKTS_SINCE` shares `DOFFED`'s column declarations
   (same objects).
2. **Columns match the SELECT list** — each table's `names` equal, in order,
   the `AS "…"` aliases of the query's final SELECT list (parsed from
   `raw_str`; every query's final list aliases each column explicitly, with
   no `*`, so the check is complete).
3. **Date arguments** — `DOFFED`, `TKTS_SINCE`, `THREADINGS_SINCE` and
   `SCANNED` take one argument and render it into `DATETIMEFROMPARTS(YYYY,
   M, D, H, M, S, 0)` with unpadded parts (`2026, 10, 7, 0, 0, 0`); the
   other five take none and contain no `{}` placeholder.

### 8.2 Kinds and converters

4. **Four kinds only** — every column of every table is one of: string
   (`to_string`, dtype `string`), count (`to_number`, dtype `Int64`), number
   (`to_number`, dtype `float64`), timestamp (`utc_to_plant`, no dtype).
5. **Consistent across tables** — a column name (per-bar prefix stripped)
   has one kind everywhere, with the one stated exception of `bar` in
   `FLOOR_STATUS` (text, since a note can cover `2/3`); the timestamp
   columns are exactly `rcv_date`, `assign_date`, `assn_ts`, `start_ts`,
   `end_ts`, `scan_ts`; the count columns exactly `bar`, `beams`, `nbeams`,
   `ends`, `denier`.
6. **`utc_to_plant`** — a naive `datetime` is taken as UTC and lands on the
   plant clock, naive (summer −4 h, winter −5 h); an aware `datetime` is
   converted from its own zone; an ISO string of either parses; `None`
   passes through.
7. **`to_number`** — `int`, `Decimal`, a numeric `str` → `float`; `None`
   passes; a non-numeric string raises `ValueError`.
8. **`to_string`** — `int` → digits, an integral `float` → digits with no
   `.0`, a non-integral float keeps its text, `str` unchanged, `None`
   passes.
9. **`norm_machine`** — `b8` / `B8` / `B08` / ` B8 ` → `B08`; `None` passes;
   `B`, `B123`, `BB8`, `8` raise `ValueError`.
10. **Same frame from both sources** — `THREADED.from_tuples` over
    pyodbc-style rows (`int`, `Decimal`, `str`, `None`) and over the same
    rows as CSV text gives equal frames with the expected dtypes; a
    non-integral count fails the `Int64` cast.

### 8.3 The file-borne tables

11. **`FLOOR_STATUS`** — columns `machine` / `bar` / `status`, all string;
    `machine` normalised (`b8` → `B08`); `bar` keeps `2/3`.
12. **`MACHINE_STATUS`** — its columns are `LAST_TKT.columns` (same
    objects) followed by one string `status`, so a TSV in the skill's
    layout — `None` for nulls, UTC timestamps, a trailing status — loads
    with the same kinds and converted times, and `status` as text.
13. **`RACKS`** — source names `MC` / `Racks` land as `machine` (normalised)
    / `racks` (float); an empty `Racks` is `NaN`.

## 9. Conventions (`loadinputs/common.py`)

1. **`planner_machine_id`** — `B08` / `b8` / ` B08 ` → `B8`; `N1` stays;
   `K10` stays `K10` (only leading zeros go); `8`, `B`, `` raise
   `ValueError`.
2. **`is_null`** — `None`, `float('nan')`, `pd.NA`, `pd.NaT` are null; `0`,
   `''`, `'None'` and a timestamp are not.
3. **`iso_plant`** — a naive `datetime` renders with the plant's offset
   (`-04:00` in October, `-05:00` in January) to the second (microseconds
   dropped); a `pd.Timestamp` the same; an aware time in another zone is
   converted; a null → `None`; a non-timestamp raises `TypeError`.
4. **`from_iso_plant`** — inverts `iso_plant` (round trip is identity); text
   carrying another offset lands on the plant clock, naive.
5. **Cell conversions** — `as_int` / `as_float` / `as_str` map every null to
   `None`; otherwise `as_int(2.0)` is `2`, `as_float(Decimal('1.5'))` is
   `1.5`, `as_str(5)` is `'5'`; `to_plant_naive` turns a `pd.Timestamp` into
   a `datetime` and a null into `None`.

## 10. `gen_inventory`

Frames carry the `ACTIVE` / `ASSIGNED` / `FLOOR_STATUS` column names
(machines padded, timestamps naive plant-local).

1. **Filter** — a set with non-null `comments` is dropped, so is one with a
   null `beams`; the rest are kept in `active`'s order.
2. **Inventory record** — the keys are exactly `set_no, received, assigned,
   merge, vendor, lbs, beams, ends, denier, luster, desc, size`; `received`
   is `rcv_date` as ISO text with the plant offset; `assigned` is `True` iff
   `assign_date` is not null; `desc` is `yarn_type`, `size` is `beam_size`;
   counts are `int`, `lbs` `float`; a null `denier` / `size` is `None`.
3. **Queue order** — the assigned records are every `assigned` row sorted by
   machine, bar, then `assn_ts` (stable), machine in the planner's form,
   `bar` an `int`, `assigned` the ISO time; keys exactly `set_no, assigned,
   merge, vendor, lbs, beams, ends, luster, desc, machine, bar, status,
   size`.
4. **Status join** — the floor note for `(machine, bar)` is the record's
   `status`; a bar with no note is `inventory`; a note whose `bar` is `2/3`
   applies to bars 2 and 3; a padded floor machine (`B08`) matches.
5. **`floor_status_map`** — a note with a null machine, bar or status is
   skipped.
6. **Empty** — empty frames give `([], [])`.

## 11. `gen_doffed`

Rolls are given by `(machine, ticket, start, end, style, rack_wt, racks)`.
The scanned rolls on `B08` are `A` 08:00–10:00 and `B` 10:00–open; the
plant has `rack_wt` 1200, so a roll's pounds are `racks × 12`.

1. **Record** — keys exactly `ticket_no, style, racks, lbs, doff_ts`; `lbs`
   = `racks × rack_wt / 100`; `doff_ts` = `end_ts` as ISO text.
2. **Open rolls** — a roll with a null `end_ts` is not written; a machine
   whose only roll is open is absent from the result.
3. **Order** — machines sorted; each machine's rolls by start.
4. **Splice inside** — an unscanned `tkts_since` roll `X` 08:30–09:00 lands
   after `A`: `A`'s doff is 08:30, `X` keeps its own end, `B`'s doff is
   unchanged; order `A, X, B`. Hosts are matched on the scanned rolls'
   **original** spans: a second roll 09:30–09:45 also joins `A`'s group
   (`A, X, X2, B`), not `B`'s.
5. **Two in one span** — `E3` 08:10–08:20 and `E4` 08:40–08:50 inside a
   closed `P` 08:00–10:00 followed by `Q`: `P` ends 08:10, `Q` starts 08:50,
   order `P, E3, E4, Q`.
6. **After the last** — `Y` 11:00–12:00 after the open `B`: `B` is doffed at
   11:00 and `Y` follows with its own end; `Y` with a null end is appended
   but not written (still closes `B`).
7. **No scans** — a machine only in `tkts_since` takes those rolls as its
   list, in start order.
8. **Unplaceable** — a roll before the first scanned roll, and one
   straddling two, are each reported (`WARNING` naming the ticket) and left
   out; the scanned rolls are untouched.
9. **Already scanned** — a `tkts_since` ticket that is also in `doffed` is
   ignored (no duplicate, no re-splice).
10. **Missing weight** — a roll with a null `racks` or `rack_wt` is written
    with `lbs` `None` and reported.
11. **Null start** — a row with a null `start_ts` in either frame is skipped.

## 12. `compute_runout`

Style `S` has `rack_wt` 1200 (12 lbs per rack) and bar shares 40 / 30 / 30
/ — ; so bar 1 takes 4.8 lbs per rack, bars 2 and 3 take 3.6. Machine
`B08` was threaded at T = 2026-10-10 08:00 with set `47999` on bar 1
(`init_lbs` 2000) and set `2-3813` on bars `2-3` (`init_lbs` 3000), the
roll then in progress at 100 racks; its doffed rolls (`gen_doffed`
records) are 500 racks doffed before T, 300 racks doffed 10-11, 50 racks
doffed 10-12; the racks file shows 25 racks wound now; the last ticket
says style `S` with sets on bars 1, 2, 3 and none on bar 4.

1. **Shape** — `{machine: {bar: {set_no, merge, vendor, lbs}}}`, machines in
   the planner's form, bars `int`; the machines are `last_tkt`'s and the
   bars those with a non-null `bar<n>_set_no` (bar 4 absent); a machine
   with nothing on any bar maps to `{}`.
2. **Single bar** — bar 1: `2000 − (300−100 + 50 + 25) × 4.8 = 680.0`, with
   the threading's `set_no` / `merge` / `vendor`.
3. **Split lease** — bars 2 and 3 each: `3000/2 − 275 × 3.6 = 510.0`, both
   carrying set `2-3813`.
4. **Latest threading wins** — an older threading of bar 1 (set `OLD`,
   10-01) changes nothing.
5. **Rolls before the threading are ignored** — the 500-rack roll doffed
   10-09 is not deducted (implicit in 2; checked by removing it).
6. **Racks at run-out beyond the roll** — with the threading's `racks` 400 >
   the in-progress roll's 300, the whole roll counts: bar 1 is
   `2000 − (300 + 50 + 25) × 4.8 = 200.0`.
7. **Current roll** — a machine with no doffed rolls and 100 racks on the
   roll: `1000 − 100 × 4.8 = 520.0`; one absent from the racks file, or
   whose `last_tkt` style is null, deducts nothing for the current roll.
8. **Fallback** — a bar with no threading in the window takes `set_no` /
   `merge` / `vendor` from `last_tkt`'s `bar<n>_*` and `lbs` from
   `threaded`'s `rem_lbs` for that machine and bar; with no `threaded` row
   either, `0.0`; both reported (`WARNING` naming machine and bar).
9. **Ran out** — a set whose deductions exceed its share is written `0.0`
   and reported.
10. **Unknown style** — a roll (or the current roll) whose style is not in
    `variants` raises `KeyError` naming the style.
11. **`parse_bars`** — `'1'` → `[1]`, `'2-3'` → `[2, 3]`, `' 1-2 '` → `[1,
    2]`.

## 13. `gen_machines`

The status frame carries `MACHINE_STATUS`'s names (machines padded); `S`
is the style of section 12 (bar 1 merge `2609`; bars 2 and 3 merge
`A716B`; bar 4 no ends).

1. **One record per row** — in the status file's order; keys exactly `id,
   is_new, init_item, status, init_top_lbs, init_btm_lbs, init_roll_lbs,
   init_btm_set, init_top_set`; `id` in the planner's form; `is_new` `True`
   for `M`/`N`/`O`/`P` and `False` otherwise; `init_item` the row's
   `style`; `status` verbatim, and `running` for a null.
2. **Grouping** — for `S`: bottom `(1,)`, top `(2, 3)`; `init_btm_lbs` is
   `runout` bar 1's lbs, `init_top_lbs` the sum of bars 2 and 3;
   `init_btm_set` / `init_top_set` are the `runout` identities of bars 1
   and 2.
3. **Identity fallback** — a group whose first bar is missing from
   `runout` but whose second is there takes the second's entry silently;
   a group with no `runout` entry on any bar takes the status row's
   `bar<n>_set_no` / `_merge` / `_vendor` (reported); one with none
   anywhere is `null`.
4. **Ungroupable** — a style not in `variants`, one whose bars form one
   merge, or three, falls back to bottom `(1,)` / top `(2, 3, 4)` with a
   report; a `runout` entry on bar 4 is then summed into the top.
5. **Roll** — `init_roll_lbs` = racks × `rack_wt` / 100 (`40 × 1200 / 100
   = 480.0`); `0.0` when the machine is not in the racks file or its
   `rack_wt` is null.
6. **Missing machine** — a status row for a machine `runout` lacks is
   written with both lbs `0.0` and identities from the status row.
7. **`bar_groups`** — `None` for an unknown or null style, for one or three
   merges, and when bar 1 carries no ends; `((1,), (2, 3))` for `S`.

## 14. `make_input_file` / `plan inputs`

`make_input.run_query` is patched with a recorder returning the table's
empty frame (or fixed rows); the TSVs are written to a temporary
directory under `get_file_name`'s names.

1. **Name → loads** — per name, the queries run (by table name) and the
   files read are exactly the design's table: `machines` runs
   `THREADINGS_SINCE, DOFFED, TKTS_SINCE, ALL_VARIANTS, LAST_TKT, THREADED`
   and reads `racks` and `machine_status`; `runout` the same queries and
   `racks` only; `doffed-rolls` runs `DOFFED, TKTS_SINCE` and reads nothing;
   `beam-sets` / `assigned-sets` run `ACTIVE, ASSIGNED` and read
   `floor_status`. Each query and file loads **once** per call.
2. **Dates and config** — the dated queries' statements carry `since`
   rendered as `DATETIMEFROMPARTS(2026, 10, 1, 0, 0, 0` (unpadded, as
   `DATETIMEFROMPARTS_FMT` writes it) and the others no rendered date;
   `dt` picks the TSVs' stamp (`racks_20260101.tsv`); `cfgpath` reaches
   `run_query`.
3. **Output** — the file holds the builder's result as indented JSON with a
   trailing newline and non-ASCII kept (`ensure_ascii=False`); the two
   inventory names write the first and second list respectively; `runout`
   writes bar keys as strings (JSON).
4. **Name forms** — the enum member and its value string both work; a
   string that is no member raises `ValueError`.
5. **Errors** — a missing TSV and a `KeyError` from a builder surface as
   `typer.BadParameter`.
6. **Reporting** — a builder's `WARNING` is emitted on
   `swmtplanner.swmtio.loadinputs`; with no handler configured anywhere,
   the call installs one stderr handler on that logger, and a second call
   does not add another.
7. **Command** — `plan inputs` is registered on the planner app: `--help`
   lists the five names; invoking `inputs doffed-rolls OUT --since
   2026-10-01 --files-dir DIR` writes the file and exits 0; an unknown name
   exits non-zero.
