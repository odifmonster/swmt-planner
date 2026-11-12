# `swmtplanner.io.loaders` test coverage

Test cases for the `loaders` submodules. Each table row is one test case;
the test function name is given so the tests and this document can be kept
in step. File-based loaders (delimited text, Excel, and JSON) are tested
against small files written into a
temporary directory by the test's `setUp`; the SQL loader is tested
against an in-memory `sqlite3` connection, which `pd.read_sql` accepts
like any DB-API connection, so no database server is needed.

Tests live in this `tests/` package:

| Test module        | Covers                                                        |
|--------------------|---------------------------------------------------------------|
| `test_table.py`    | `Column`, `Table`                                             |
| `test_sources.py`  | `SQLQuery`, `File`, `CSVFile`, `ExcelFile`, `JSONFile`, `conn_str` |
| `test_loaders.py`  | `TableLoader` conversion, `CSVTableLoader`, `ExcelTableLoader`, `JSONTableLoader`, `SQLTableLoader` |

`connect` itself is not unit-tested, since it opens a real `pyodbc`
connection; `conn_str`, which does all the work, is.

## `table`

### `Column`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_column_init_minimal`    | `Column('width', 'int64')`                   | `name == 'width'`, `dtype == 'int64'`, `src_name is None`, `converter is None`, `read_na_as is None` |
| `test_column_init_full`       | `Column('rl', 'float64', src_name='bar1_rl', converter=float, read_na_as=0.0)` | all five fields stored as given |
| `test_column_equality`        | `Column('a', 'int64') == Column('a', 'int64')`; `Column('a', 'int64') == Column('a', 'string')` | `True`; `False` |
| `test_column_frozen`          | assign `col.dtype = 'string'`                | raises `FrozenInstanceError` |

### `Table`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_table_init`             | `Table('styles', (COL_A, COL_B))`            | `name == 'styles'`, `columns == (COL_A, COL_B)`, `index is None` |
| `test_table_init_index`       | `Table('styles', (COL_B,), index=COL_A)`     | `index is COL_A` |
| `test_table_frozen`           | assign `tbl.name = 'x'`                      | raises `FrozenInstanceError` |

## `sources`

### `SQLQuery`

Shared fixture values: `D1 = datetime(2026, 1, 1)`, `D2 = datetime(2026,
2, 1)`, `FMT = "'%Y-%m-%d'"`, and
`Q_POS = SQLQuery("WHERE d >= {0} AND d < {1}", 2, FMT, defaults=(None, lambda: D2))`,
`Q_NAMED = SQLQuery("WHERE d >= {start} AND d < {end}", ('start', 'end'), FMT, defaults=(('end', lambda: D2),))`,
`Q_NONE = SQLQuery("SELECT 1", 0)`.

**Construction**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_query_init`             | `Q_POS`                                      | `raw_str`, `date_params == 2`, `date_fmt == FMT`, `len(defaults) == 2` |
| `test_query_no_params_no_fmt` | `SQLQuery("SELECT 1", 0)`; `SQLQuery("SELECT 1", ())` | constructs; `date_fmt is None` |
| `test_query_params_need_fmt_positional` | `SQLQuery("x {0}", 1)`            | raises `ValueError` |
| `test_query_params_need_fmt_named` | `SQLQuery("x {a}", ('a',))`             | raises `ValueError` |
| `test_query_defaults_wrong_length` | `SQLQuery("x {0}", 1, FMT, defaults=(None, None))` | raises `ValueError` |
| `test_query_defaults_not_callable` | `SQLQuery("x {0}", 1, FMT, defaults=(D1,))` | raises `ValueError` (a datetime is not a zero-argument callable) |
| `test_query_defaults_unknown_name` | `SQLQuery("x {a}", ('a',), FMT, defaults=(('b', None),))` | raises `ValueError` |
| `test_query_defaults_named_bad_shape` | `SQLQuery("x {a}", ('a',), FMT, defaults=(lambda: D1,))` | raises `ValueError` (named params need `(name, default)` pairs) |
| `test_query_frozen`           | assign `Q_POS.raw_str = ''`                  | raises `FrozenInstanceError` |

**`get_query`, positional**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_pos_all_given`          | `Q_POS.get_query(D1, D2)`                    | `"WHERE d >= '2026-01-01' AND d < '2026-02-01'"` |
| `test_pos_default_omitted`    | `Q_POS.get_query(D1)`                        | second parameter from its default: `"... d < '2026-02-01'"` |
| `test_pos_default_none`       | `Q_POS.get_query(D1, None)`                  | same as omitted |
| `test_pos_default_evaluated_lazily` | query with `defaults=(lambda: calls.append(1) or D1,)`; construct, then `get_query()` | callable not invoked at construction; invoked once by `get_query` |
| `test_pos_missing_required`   | `Q_POS.get_query()`                          | raises `ValueError` |
| `test_pos_none_for_required`  | `Q_POS.get_query(None, D2)`                  | raises `ValueError` |
| `test_pos_too_many`           | `Q_POS.get_query(D1, D2, D1)`                | raises `ValueError` |
| `test_pos_rejects_keywords`   | `Q_POS.get_query(start=D1)`                  | raises `ValueError` |
| `test_pos_no_defaults`        | `SQLQuery("{0}", 1, FMT).get_query(D1)`; `.get_query()` | `"'2026-01-01'"`; raises `ValueError` |
| `test_pos_date_fmt_applied`   | `SQLQuery("{0}", 1, "%Y%m%d").get_query(D1)` | `"20260101"` |

**`get_query`, named**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_named_all_given`        | `Q_NAMED.get_query(start=D1, end=D2)`        | `"WHERE d >= '2026-01-01' AND d < '2026-02-01'"` |
| `test_named_default_omitted`  | `Q_NAMED.get_query(start=D1)`                | `end` from its default |
| `test_named_default_none`     | `Q_NAMED.get_query(start=D1, end=None)`      | same as omitted |
| `test_named_missing_required` | `Q_NAMED.get_query(end=D2)`                  | raises `ValueError` |
| `test_named_unknown_keyword`  | `Q_NAMED.get_query(start=D1, foo=D2)`        | raises `ValueError` |
| `test_named_rejects_positional` | `Q_NAMED.get_query(D1, D2)`                | raises `ValueError` |
| `test_named_order_independent` | `Q_NAMED.get_query(end=D2, start=D1)`       | same as `test_named_all_given` |

**`get_query`, no parameters and mixed forms**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_none_returns_raw`       | `Q_NONE.get_query()`                         | `"SELECT 1"` |
| `test_none_raw_braces_untouched` | `SQLQuery("SELECT '{literal}'", 0).get_query()` | `"SELECT '{literal}'"` (no formatting when there are no parameters) |
| `test_none_rejects_args`      | `Q_NONE.get_query(D1)`; `Q_NONE.get_query(a=D1)` | both raise `ValueError` |
| `test_mixed_forms`            | `Q_POS.get_query(D1, end=D2)`                | raises `ValueError` |

### `File`, `CSVFile`, `ExcelFile`, `JSONFile`

Shared fixture values: `CFG = {'inputs': '/data/in', 'exports': '/data/out'}`,
`F_PLAIN = CSVFile('inputs', 'variants', '.tsv', sep='\t')`,
`F_DATED = ExcelFile('exports', 'inv_{}', date_fmt='%Y%m%d', sheet_name='Inv')`,
`F_JSON = JSONFile('inputs', 'machines', orient='index')`.
Expected paths are built with `os.path.join` so they hold on any platform.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_file_init`              | `File('inputs', 'variants', '.tsv')`         | fields stored; `date_fmt is None` |
| `test_csv_init`               | `F_PLAIN`                                    | `sep == '\t'`, `ext == '.tsv'`; `CSVFile('a', 'b', '.csv').sep == ','` |
| `test_excel_init`             | `F_DATED`                                    | `ext == '.xlsx'`, `sheet_name == 'Inv'`, `header == 0`, `skiprows is None`, `nrows is None`, `skipfooter == 0` |
| `test_excel_ext_override`     | `ExcelFile('a', 'b', '.xls')`                | `ext == '.xls'` (default can be overridden) |
| `test_json_init`              | `JSONFile('inputs', 'styles')`; `F_JSON`     | `ext == '.json'`, `orient == 'records'`, `date_fmt is None`; `F_JSON.orient == 'index'` |
| `test_fpath_json`             | `F_JSON.get_fpath(CFG)`                      | `join('/data/in', 'machines.json')` |
| `test_fpath_json_dated`       | `JSONFile('inputs', 'm_{}', date_fmt='%Y%m%d').get_fpath(CFG, date=date(2026, 11, 4))` | `join('/data/in', 'm_20261104.json')` |
| `test_fpath_undated`          | `F_PLAIN.get_fpath(CFG)`                     | `join('/data/in', 'variants.tsv')` |
| `test_fpath_undated_ignores_date` | `F_PLAIN.get_fpath(CFG, date=date(2026, 11, 4))` | same as undated |
| `test_fpath_dated`            | `F_DATED.get_fpath(CFG, date=date(2026, 11, 4))` | `join('/data/out', 'inv_20261104.xlsx')` |
| `test_fpath_dated_default_today` | `F_DATED.get_fpath(CFG)`                  | `join('/data/out', f'inv_{date.today():%Y%m%d}.xlsx')` |
| `test_fpath_dated_stem_format` | `CSVFile('inputs', 'a_{}_b', '.csv', date_fmt='%Y').get_fpath(CFG, date=date(2026, 1, 1))` | `join('/data/in', 'a_2026_b.csv')` |
| `test_fpath_override`         | `F_PLAIN.get_fpath(CFG, override_name='old.tsv')` | `join('/data/in', 'old.tsv')` (used as-is, extension included) |
| `test_fpath_override_beats_date` | `F_DATED.get_fpath(CFG, 'x.xlsx', date(2026, 1, 1))` | `join('/data/out', 'x.xlsx')` |
| `test_fpath_missing_cfg_key`  | `F_PLAIN.get_fpath({})`                      | raises `KeyError` |
| `test_file_frozen`            | assign `F_PLAIN.stem = 'x'`                  | raises `FrozenInstanceError` |

### `conn_str`

Shared fixture value: `SQL_CFG = {'sql': {'HOST': 'db.local', 'PORT': 1433, 'DATABASE': 'plant', 'UID': 'u', 'PWD': 'secret'}}`.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_conn_str_required_only` | `conn_str(SQL_CFG)`                          | `'DRIVER={ODBC Driver 17 for SQL Server};SERVER=db.local,1433;DATABASE=plant;UID=u;PWD=secret'` |
| `test_conn_str_extra_keys`    | `SQL_CFG` plus `Encrypt='yes'`, `TrustServerCertificate='yes'` | ends with `';Encrypt=yes;TrustServerCertificate=yes'` |
| `test_conn_str_driver_override` | `SQL_CFG` plus `DRIVER='{X}'`              | starts with `'DRIVER={X};'` and contains no default driver |
| `test_conn_str_missing_required` | `SQL_CFG` without `PWD`                   | raises `KeyError` naming `PWD` |
| `test_conn_str_missing_sql_block` | `conn_str({})`                           | raises `KeyError` |
| `test_conn_str_error_hides_password` | `SQL_CFG` without `HOST`              | the `KeyError` message does not contain `'secret'` |

## `loaders`

Shared fixtures, created in `setUp` in a `tempfile.TemporaryDirectory`
whose path is `CFG['inputs']`:

```python
TBL = Table('styles', (
    Column('style', 'string', src_name='variant'),
    Column('width', 'int64'),
    Column('rl', 'float64', src_name='bar1_rl', read_na_as=0.0),
    Column('thread', 'string', src_name='bar1_thread', converter=str.upper, read_na_as='SOLID'),
))
RAW = pd.DataFrame({'variant': ['A/1', 'B'], 'width': [168, 144], 'bar1_rl': [61.5, None],
                    'bar1_thread': ['1 in, 1 out', None], 'extra': [1, 2]})
# written as styles_2026-11-04.tsv (tab-separated) and inv_20261104.xlsx (sheet "Inv")
SRC_CSV = CSVFile('inputs', 'styles_{}', '.tsv', date_fmt='%Y-%m-%d', sep='\t')
SRC_XLSX = ExcelFile('inputs', 'inv_{}', date_fmt='%Y%m%d', sheet_name='Inv')
DT = date(2026, 11, 4)
```

### `TableLoader` (conversion, via `CSVTableLoader`)

The conversion step is tested through `CSVTableLoader` since the base
class is abstract and the step is identical for every loader.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_loader_abstract`        | `TableLoader(TBL, SRC_CSV)`                  | raises `TypeError` |
| `test_convert_columns_and_rename` | `CSVTableLoader(TBL, SRC_CSV).load(CFG, DT)` | `list(df.columns) == ['style', 'width', 'rl', 'thread']`; `df['style'].tolist() == ['A/1', 'B']` |
| `test_convert_drops_unlisted`  | same                                        | `'extra' not in df.columns` |
| `test_convert_dtypes`         | same                                         | `df['style'].dtype == 'string'`, `df['width'].dtype == 'int64'`, `df['rl'].dtype == 'float64'` |
| `test_convert_read_na_as`     | same                                         | `df['rl'].tolist() == [61.5, 0.0]` |
| `test_convert_converter`      | same                                         | `df['thread'].tolist() == ['1 IN, 1 OUT', 'SOLID']` (upper-cased) |
| `test_convert_na_before_converter` | same, looking at row `B`                | `'SOLID'`: the substitute was made before `str.upper` ran, which would have failed on `NaN` |
| `test_convert_converter_without_na` | `Column('w2', 'int64', src_name='width', converter=lambda v: v * 2)` | `[336, 288]` |
| `test_convert_index`          | `Table('styles', TBL.columns[1:], index=TBL.columns[0])` | `df.index.name == 'style'`, `df.index.tolist() == ['A/1', 'B']`, `'style' not in df.columns` |
| `test_convert_index_converted` | index `Column('style', 'string', src_name='variant', converter=str.lower)` | `df.index.tolist() == ['a/1', 'b']` |
| `test_convert_missing_column` | `Table('t', (Column('nope', 'string'),))`    | raises `KeyError` whose message contains `'t'` and `'nope'` |
| `test_convert_missing_src_name` | `Table('t', (Column('x', 'string', src_name='nope'),))` | raises `KeyError` containing `'nope'` (the source name, not `'x'`) |
| `test_convert_empty_source`   | a TSV with the header row only               | an empty frame with the four columns and the right dtypes |

### `CSVTableLoader`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_csv_loader_init`        | `CSVTableLoader(TBL, SRC_CSV)`               | `tbl is TBL`, `source is SRC_CSV` |
| `test_csv_wrong_source`       | `CSVTableLoader(TBL, SRC_XLSX)`              | raises `TypeError` |
| `test_csv_load_dated`         | `.load(CFG, DT)`                             | 2 rows, columns as in `TBL` |
| `test_csv_load_override`      | `.load(CFG, override_name='styles_2026-11-04.tsv')` | same frame |
| `test_csv_load_sep`           | the same data written comma-separated as `c.csv`, `CSVFile('inputs', 'c', '.csv')` | loads with 2 rows (default `sep`) |
| `test_csv_load_missing_file`  | `.load(CFG, date(2000, 1, 1))`               | raises `FileNotFoundError` |

### `ExcelTableLoader`

The workbook has a third row `['TOTAL', 0, 0.0, '']` as a footer.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_excel_loader_init`      | `ExcelTableLoader(TBL, SRC_XLSX)`            | `tbl is TBL`, `source is SRC_XLSX` |
| `test_excel_wrong_source`     | `ExcelTableLoader(TBL, SRC_CSV)`             | raises `TypeError` |
| `test_excel_load_dated`       | `.load(CFG, DT)` with `skipfooter=0`         | 3 rows (footer included) |
| `test_excel_load_skipfooter`  | `replace(SRC_XLSX, skipfooter=1)`            | 2 rows, `['A/1', 'B']` |
| `test_excel_load_nrows`       | `replace(SRC_XLSX, nrows=1)`                 | 1 row, `['A/1']` |
| `test_excel_load_sheet_by_index` | `replace(SRC_XLSX, sheet_name=0)`         | same as by name |
| `test_excel_load_wrong_sheet` | `replace(SRC_XLSX, sheet_name='Nope')`       | raises `ValueError` (from pandas) |
| `test_excel_load_override`    | `.load(CFG, override_name='inv_20261104.xlsx')` | same as dated |

### `JSONTableLoader`

Fixtures, also written in `setUp`:

```python
# styles.json and styles_2026-11-04.json: RAW as a list of records (None written as null)
SRC_JSON = JSONFile('inputs', 'styles')
SRC_JSON_DATED = JSONFile('inputs', 'styles_{}', date_fmt='%Y-%m-%d')
# keyed.json: {"10": {"gauge": 28, "attrs": ["tall"]}, "2": {"gauge": 32, "attrs": []}}
SRC_KEYED = JSONFile('inputs', 'keyed', orient='index')
TBL_KEYED = Table('machines', (Column('gauge', 'int64'), Column('attrs', 'object', converter=tuple)),
                  index=Column('machine', 'string', src_name='index'))
```

The keys of `keyed.json` are deliberately number-like, to check they are
not converted.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_json_loader_init`       | `JSONTableLoader(TBL, SRC_JSON)`             | `tbl is TBL`, `source is SRC_JSON` |
| `test_json_wrong_source`      | `JSONTableLoader(TBL, SRC_CSV)`              | raises `TypeError` |
| `test_json_load_records`      | `JSONTableLoader(TBL, SRC_JSON).load(CFG)`   | 2 rows, converted like the CSV case (`rl == [61.5, 0.0]`, `thread == ['1 IN, 1 OUT', 'SOLID']`, `'extra'` dropped, dtypes as in `TBL`) |
| `test_json_load_dated`        | `JSONTableLoader(TBL, SRC_JSON_DATED).load(CFG, DT)` | same frame as `test_json_load_records` |
| `test_json_load_override`     | `JSONTableLoader(TBL, SRC_JSON_DATED).load(CFG, override_name='styles.json')` | same frame |
| `test_json_load_missing_file` | `JSONTableLoader(TBL, SRC_JSON_DATED).load(CFG, date(2000, 1, 1))` | raises `FileNotFoundError` |
| `test_json_load_index_orient` | `JSONTableLoader(TBL_KEYED, SRC_KEYED).load(CFG)` | `df.index.name == 'machine'`, `list(df.columns) == ['gauge', 'attrs']`, `df['gauge'].tolist() == [28, 32]` |
| `test_json_load_index_keys_stay_strings` | same                              | `df.index.tolist() == ['10', '2']` (strings, in file order; not converted to integers) |
| `test_json_load_index_key_as_column` | `Table('machines', (Column('machine', 'string', src_name='index'), Column('gauge', 'int64')))` | `df['machine'].tolist() == ['10', '2']`; default integer index |
| `test_json_load_list_values`  | `JSONTableLoader(TBL_KEYED, SRC_KEYED).load(CFG)` | `df['attrs'].tolist() == [('tall',), ()]` (lists passed through the converter) |
| `test_json_load_records_no_index_column` | `Table('t', (Column('k', 'string', src_name='index'),))` with `SRC_JSON` | raises `KeyError` naming `'index'` (the key column exists only for `orient='index'`) |

### `SQLTableLoader`

Fixture: an in-memory `sqlite3` connection with a table `styles` holding
`RAW`'s rows plus a text column `doff` with values `'2026-01-15'` and
`'2026-03-15'`, and
`Q_ALL = SQLQuery("SELECT * FROM styles", 0)`,
`Q_SINCE = SQLQuery("SELECT * FROM styles WHERE doff >= {0}", 1, "'%Y-%m-%d'")`.
`pd.read_sql` accepts the sqlite connection like any DB-API connection,
so no database server is needed.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_sql_init`               | `SQLTableLoader(TBL, Q_ALL)`                 | `tbl is TBL`, `source is Q_ALL` |
| `test_sql_wrong_source`       | `SQLTableLoader(TBL, SRC_CSV)`               | raises `TypeError` |
| `test_sql_load`               | `SQLTableLoader(TBL, Q_ALL).load(conn)`      | 2 rows, converted like the CSV case (`rl == [61.5, 0.0]`, `thread == ['1 IN, 1 OUT', 'SOLID']`, `'extra'` dropped) |
| `test_sql_load_passes_args`   | `SQLTableLoader(TBL, Q_SINCE).load(conn, datetime(2026, 2, 1))` | 1 row (`B`): the datetime was rendered and substituted into the query |
| `test_sql_load_missing_arg`   | `SQLTableLoader(TBL, Q_SINCE).load(conn)`    | raises `ValueError` (from `get_query`, before any SQL runs) |
| `test_sql_load_missing_column` | `SQLTableLoader(Table('t', (Column('nope', 'string'),)), Q_ALL).load(conn)` | raises `KeyError` |
