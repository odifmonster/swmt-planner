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
  `"'%Y-%m-%d'"`). `None` exactly when `num_args` is `0`; constructing a
  `SQLQuery` that breaks that pairing (or has a negative `num_args`) is a
  `ValueError` at definition time, so a bad constant fails on import.

`get_query(*args)` takes exactly `num_args` `date` (or `datetime`)
arguments, renders each with `date_fmt`, substitutes them into `raw_str`
in the order passed, and returns the finished statement for `run_query`.
The wrong number of arguments raises `QueryArgumentError`; the arguments'
types are not checked beyond what `strftime` itself enforces.

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
(each machine's last piece ticket with its four bars), `SCANNED` (every
ticket scanned since a date, one date argument) and `ALL_VARIANTS` (the
knittable style variants). The dated queries render their argument into
`DATETIMEFROMPARTS(...)` through the shared `DATETIMEFROMPARTS_FMT`.

Each `Table` takes every column exactly as its query labels it, in the
query's order, and forces it to one of four **kinds**, so a value's type
never depends on whether the rows came from pyodbc (`str`, `int`,
`Decimal`, `datetime`) or from a CSV (all text):

- **string** (`to_string` → pandas `string`): identifiers, names and
  codes — `set_no`, `ticket`, `machine`, `style`, `variant`, `kind`,
  `merge`, `vendor`, `luster`, `yarn_type`, `desc`, `stitch`, `thread`,
  `comments`. A merge code looks numeric but is an identifier (it is the
  blacklist's key), so it is text; an integral float becomes its digits.
- **count** (`to_number` → nullable `Int64`): `bar`, `beams` / `nbeams`,
  `ends`. A non-integral value fails the cast.
- **number** (`to_number` → `float64`): weights and quantities (`lbs`,
  `rem_lbs`, `rack_wt`, `racks`), `denier`, `pct`, `gauge`, `width`, `rl`.
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
  reconcile-machine-status skill writes: exactly `LAST_TKT`'s columns (it
  reuses that table's declaration), the timestamps still UTC since the
  skill passes the database's values through.
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

*Not yet designed.* `loadinputs` holds the input-specific logic — the
joins, grouping and derivations that turn the loaders' dataframes into
the planner's JSON files. It is specified after the translation and
loading layers above are implemented and tested, since its correctness
rests on theirs.
