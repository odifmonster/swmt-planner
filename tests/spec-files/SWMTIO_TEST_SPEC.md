# Specification of coverage of swmtio tests

Covers `planners/infinite/swmtio` (`tests/swmtio_tests.py`): the **translation
classes** (`translate.py`), the **loaders** (`loaders.py` — the connection
config, by-name column matching, `run_query` against a stand-in connection,
`read_csv`, `get_file_name`), **`SQLQuery`** (`queries.py`) and the **declared
queries and tables** (`queries.py` / `tables.py` — the pairing, the column kinds
and their converters, the file-borne tables). Everything is pure: `run_query`
is proven with a stand-in `_connect` (no driver, no server), files through
`tempfile`. `loadinputs` is not yet designed and has no coverage here. Design:
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

## 8. The declared queries and tables (`queries.py` / `tables.py`)

### 8.1 Pairing

1. **Every query has its table** — for each of `ACTIVE`, `ASSIGNED`,
   `DOFFED`, `THREADED`, `LAST_TKT`, `SCANNED`, `ALL_VARIANTS`, `queries.X`
   is a `SQLQuery` and `tables.X` a `Table` named `X`.
2. **Columns match the SELECT list** — each table's `names` equal, in order,
   the `AS "…"` aliases of the query's final SELECT list (parsed from
   `raw_str`).
3. **Date arguments** — `DOFFED` and `SCANNED` take one argument and render
   it into `DATETIMEFROMPARTS(YYYY, MM, DD, HH, MM, SS, 0)`; the other five
   take none and contain no `{}` placeholder.

### 8.2 Kinds and converters

4. **Four kinds only** — every column of every table is one of: string
   (`to_string`, dtype `string`), count (`to_number`, dtype `Int64`), number
   (`to_number`, dtype `float64`), timestamp (`utc_to_plant`, no dtype).
5. **Consistent across tables** — a column name (per-bar prefix stripped)
   has one kind everywhere, with the one stated exception of `bar` in
   `FLOOR_STATUS` (text, since a note can cover `2/3`); the timestamp
   columns are exactly `rcv_date`, `assign_date`, `assn_ts`, `start_ts`,
   `end_ts`, `scan_ts`; the count columns exactly `bar`, `beams`, `nbeams`,
   `ends`.
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
    objects), so a TSV in the skill's layout — `None` for nulls, UTC
    timestamps — loads with the same kinds and converted times.
13. **`RACKS`** — source names `MC` / `Racks` land as `machine` (normalised)
    / `racks` (float); an empty `Racks` is `NaN`.
