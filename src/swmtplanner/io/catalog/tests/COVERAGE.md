# `swmtplanner.io.catalog` test coverage

Test cases for the `catalog` modules. Each table row is one test case; the
test function name is given so the tests and this document can be kept in
step.

The catalog is mostly constants, so the tests do two things: check each
constant says what the design says (file, tab, config key, column names),
and load a small fixture file through each loader constant to check the
table definition produces the frame the design describes. The mechanics of
loading (renaming, `read_na_as`, converters, dtypes, missing files) are
covered in `loaders/tests/COVERAGE.md` and are not repeated here.

**No real plant file is read by any test.** The demand workbooks are
replaced daily and the Xref is edited by hand, so every test writes its
own small files into a `tempfile.TemporaryDirectory` in `setUp`. One
directory serves all three file config keys:
`CFG = {'pa_supply': tmp, 'inputs': tmp, 'scheduling': tmp}`. The fixture
files copy the quirks of the real ones: part numbers that are a mix of
numbers and text, padded cells, blank rows, extra columns and tabs, and
`None` written for blanks in the variants extract.

Tests live in this `tests/` package:

| Test module            | Covers                                                   |
|------------------------|----------------------------------------------------------|
| `test_package.py`      | package exports, `_converters`, `_sql.read_sql`          |
| `test_xref.py`         | `catalog.xref`                                           |
| `test_variants.py`     | `catalog.variants`                                       |
| `test_masterstyles.py` | `catalog.masterstyles`                                   |
| `test_demand.py`       | `catalog.demand`                                         |
| `test_machines.py`     | `catalog.machines`                                       |

`VARIANT_LOADER` is not run against SQL Server. Its query is checked as
text, and its table is checked against an in-memory `sqlite3` table with
the same column names (see `catalog.variants` below).

## Package and private helpers

### Exports

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_catalog_exports`        | `catalog.__all__`; `io.__all__`              | `['xref', 'variants', 'masterstyles', 'demand', 'machines']`, each an attribute of `catalog`; `'catalog' in io.__all__` |

### `_converters`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_strip_text`             | `_strip('  FF A B ')`; `_strip('')`          | `'FF A B'` (inner spaces kept); `''` |
| `test_strip_number`           | `_strip(239569)`                             | `'239569'` (non-text values become text) |
| `test_is_x_true`              | `_is_x(v)` for `'X'`, `'x'`, `' X '`         | all `True` |
| `test_is_x_false`             | `_is_x(v)` for `''`, `'Y'`, `'XX'`, `0`      | all `False` |
| `test_is_active_true`         | `_is_active(v)` for `'A'`, `''`, `' '`, `'B'` | all `True` (only `I` is inactive; blank is active) |
| `test_is_active_false`        | `_is_active(v)` for `'I'`, `'i'`, `' I '`    | all `False` |

### `_sql.read_sql`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_read_sql`               | `read_sql('si_variants.sql')`                | a non-empty `str` starting with `'WITH merges AS'` |
| `test_read_sql_missing`       | `read_sql('nope.sql')`                       | raises `FileNotFoundError` |

## `catalog.xref`

Fixture: a workbook `PA Master Xref.xlsx` with three tabs.

Tab `Xref`, with every source column named in `FABRICS` plus an unlisted
`NOTES` column. Cells not mentioned are blank.

| Row | `PLY 1 PART #` | `PA FIN ITEM` | `GREIGE ITEM` | `STATUS` | Jets and tanks | Other |
|-----|----------------|---------------|---------------|----------|----------------|-------|
| 0 | `239569` (number) | `' FF AEROKNIT D-40637-61 '` (padded) | `'AU3426H'` | `'A'` | `JET 1` `'X'`, `JET 2` `'x'`, `JET 3` `' X '` | `STYLE` `'AEROKNIT D'`, `WD` `61`, `Yield` `2.81`, `COLOR NUMBER` `40637`, `COLOR NAME` `'TINTED GRAY '`, `SHADE RATING` `0` |
| 1 | `242883` (number) | `'FF ANMUT-C-NA-40487-66'` | `'ANMUT-C'` | blank | `JET 10` `'X'`, `TANKS` `'X'` | `WD` `66`, `Yield` `2.62`, `COLOR NUMBER` `40487`, `SHADE RATING` `3` |
| 2 | `'210189A'` (text) | `'FF AURA30000-39064-63'` | `'AU9999'` | `'I'` | none | `COLOR NUMBER` `39064`, `SHADE RATING` `4` |
| 3 | blank | blank | blank | blank | none | every cell blank |
| 4 | blank | blank | blank | blank | none | every cell blank |
| 5 | `229081` (number) | `'FF HANA--59'` | `' AU3426H '` (padded) | `' i '` | none | |

Tab `Greige Styles`, with an unlisted `Notes` column:

| `GreigeAlt` | `GreigeAlt2` | `Target` |
|-------------|--------------|----------|
| `'ANMUT-C'` | `'AU7805'`   | `740`    |
| `'AU7805'`  | `'AU7805'`   | `340`    |
| `' AU3426H '` (padded) | `'AU3426H '` (padded) | `740` |

Tab `Other`, holding one unrelated cell. Two more workbooks are written by
the tests that use them: `copy.xlsx`, a copy of the workbook (the original
is then deleted, so nothing can be read from it), and `no_tanks.xlsx`, the
workbook with the `TANKS` column removed from `Xref`.

### Constants

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_xref_file`              | `XREF_FILE`                                  | `cfg_name == 'pa_supply'`, `sheet_name == 'Xref'`, `date_fmt is None`; `get_fpath(CFG) == join(tmp, 'PA Master Xref.xlsx')` |
| `test_greige_styles_sheet`    | `GREIGE_STYLES_SHEET`                        | same file as `XREF_FILE` (`get_fpath` equal); `sheet_name == 'Greige Styles'` |
| `test_fabrics_table`          | `FABRICS`                                    | `name == 'fabrics'`; `index.name == 'part_no'`; column names are `item, greige, style, width, yld, formula, color, shade, active, jet1..jet10, tanks` in that order |
| `test_fabrics_jet_sources`    | `FABRICS` columns `jet1`..`jet10`            | source names `'JET 1'`..`'JET 10'` |
| `test_greige_styles_table`    | `GREIGE_STYLES`                              | `name == 'greige_styles'`; `index.name == 'alias'`; column names `['master', 'std_wt']` |
| `test_shade_ratings`          | `SHADE_RATINGS`                              | exactly `{0: LIGHT0, 1: LIGHT1, 2: MEDIUM, 3: BLACK, 4: SD_BLACK}` |
| `test_shade_ratings_cover_shades` | `set(SHADE_RATINGS.values())`            | `== set(Shade)` (every shade has a rating, none twice) |
| `test_loader_constants`       | `GREIGE_STYLE_LOADER`; `FABRIC_LOADER`       | `GREIGE_STYLE_LOADER.tbl is GREIGE_STYLES`, `.source is GREIGE_STYLES_SHEET`; `FABRIC_LOADER` is an `XrefFabricLoader` with `tbl is FABRICS`, `source is XREF_FILE`, `aliases is GREIGE_STYLE_LOADER` |

### `GREIGE_STYLE_LOADER`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_greige_styles_load`     | `GREIGE_STYLE_LOADER.load(CFG)`              | 3 rows; `index.name == 'alias'`; `list(columns) == ['master', 'std_wt']`; `'Notes'` dropped |
| `test_greige_styles_stripped` | same                                         | `index.tolist() == ['ANMUT-C', 'AU7805', 'AU3426H']`; `master.tolist() == ['AU7805', 'AU7805', 'AU3426H']` |
| `test_greige_styles_std_wt`   | same                                         | `std_wt` is `float64`; `df.loc['AU7805', 'std_wt'] == 340.0`, `df.loc['ANMUT-C', 'std_wt'] == 740.0` (the alias row and the master's own row differ) |

### `XrefFabricLoader` and `FABRIC_LOADER`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_fabric_loader_wrong_source` | `XrefFabricLoader(FABRICS, CSVFile('pa_supply', 'x', '.csv'), GREIGE_STYLE_LOADER)` | raises `TypeError` (the source check is inherited) |
| `test_fabrics_load_shape`     | `FABRIC_LOADER.load(CFG)`                    | 6 rows (blank rows kept); `index.name == 'part_no'`; 20 columns named as in `FABRICS`; `'NOTES'` dropped |
| `test_fabrics_part_numbers`   | same                                         | `index.tolist() == ['239569', '242883', '210189A', '', '', '229081']`: numbers and text both become plain text (no `.0`), blanks become `''` |
| `test_fabrics_text_stripped`  | same, row `239569`                           | `item == 'FF AEROKNIT D-40637-61'`, `color == 'TINTED GRAY'`, `style == 'AEROKNIT D'` |
| `test_fabrics_dtypes`         | same                                         | `item`, `greige`, `style`, `color` are `string`; `width`, `yld` are `float64`; `formula`, `shade` are `Int64`; `active`, `jet1`..`jet10`, `tanks` are `bool` |
| `test_fabrics_numbers`        | same, rows `239569` and `242883`             | `width` `61.0` / `66.0`; `yld` `2.81` / `2.62`; `formula` `40637` / `40487`; `shade` `0` / `3` |
| `test_fabrics_active`         | same                                         | `active.tolist() == [True, True, False, True, True, False]`: `'A'` and blank are active; `'I'` and `' i '` are not |
| `test_fabrics_jets`           | same, row `239569`                           | `jet1`, `jet2`, `jet3` are `True` (`'X'`, `'x'`, `' X '`); `jet4`..`jet10` and `tanks` are `False` |
| `test_fabrics_tanks`          | same, row `242883`                           | `jet10` and `tanks` are `True`; `jet1`..`jet9` are `False` |
| `test_fabrics_blank_row`      | same, the two rows with index `''`           | text columns `''`; `width` and `yld` are `NaN`; `formula` and `shade` are `<NA>`; `active` is `True`; every jet and `tanks` is `False` |
| `test_fabrics_greige_converted` | same, row `242883`                         | `greige == 'AU7805'` (the `ANMUT-C` alias replaced by the name the knitters use) |
| `test_fabrics_greige_same_name` | same, rows `239569` and `229081`           | `greige == 'AU3426H'` for both (a name that maps to itself is unchanged; padding is stripped before the lookup) |
| `test_fabrics_greige_unknown` | same, row `210189A`                          | `greige == 'AU9999'` (a name with no row in `Greige Styles` is passed through, not blanked) |
| `test_fabrics_greige_blank`   | same, the rows with index `''`               | `greige == ''` (not `<NA>`) |
| `test_fabrics_greige_dtype`   | same                                         | `greige` is still `string` after the conversion and holds no missing values |
| `test_fabrics_load_override`  | `FABRIC_LOADER.load(CFG, override_name='copy.xlsx')` | same frame as `load(CFG)`: both tabs are read from the override file |
| `test_fabrics_load_ignores_date` | `FABRIC_LOADER.load(CFG, date(2000, 1, 1))` | same frame as `load(CFG)` (the workbook is undated) |
| `test_fabrics_missing_column` | `FABRIC_LOADER.load(CFG, override_name='no_tanks.xlsx')` | raises `KeyError` whose message contains `'fabrics'` and `'TANKS'` |
| `test_fabrics_missing_file`   | `FABRIC_LOADER.load({'pa_supply': join(tmp, 'nowhere')})` | raises `FileNotFoundError` |

## `catalog.variants`

Fixture values:

```python
# every source column of VARIANTS, in the query's order, plus an unlisted 'extra' column
RAW_VARIANTS = two rows:
#   'TA0799/31': width 168, rack_wt 12.51, gauge 28, beams 4,
#       bars 1-3 filled (ends 1164, merge '612VE2095S53', vendor 'NANYA', denier 40,
#       luster 'SD', desc 'POLY', pct 33.3, rl 61.5, stitch '1-0/1-2', thread 'SOLID'),
#       bar 4 entirely blank
#   'AU7805-X': width 186, rack_wt 20.0, gauge 28, beams 4, all four bars filled,
#       bar4_denier 70, bar4_thread '1 IN, 1 OUT'
```

`RAW_VARIANTS` is written to `variants.tsv` (tab-separated, blanks written
as the text `None`, as in the real extract) and into a table `variants`
in an in-memory `sqlite3` connection (blanks as `NULL`).
`Q_ALL = SQLQuery('SELECT * FROM variants', 0)`.

### Constants

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_variants_tsv`           | `VARIANTS_TSV`                               | `cfg_name == 'inputs'`, `sep == '\t'`, `date_fmt is None`; `get_fpath(CFG) == join(tmp, 'variants.tsv')` |
| `test_variants_query`         | `SI_VARIANTS_QUERY`                          | `date_params == 0`; `get_query() == read_sql('si_variants.sql')` |
| `test_variants_table`         | `VARIANTS`                                   | `name == 'variants'`; `index is None`; 45 columns; the first five are `variant, width, rack_wt, gauge, beams` |
| `test_variants_bar_columns`   | `VARIANTS` columns 5 onward                  | for each bar 1-4 in turn: `bar{i}_ends, _merge, _vendor, _denier, _luster, _desc, _pct, _rl, _stitch, _thread` |
| `test_variants_no_renames`    | every column of `VARIANTS`                   | `src_name is None` (the query's aliases are the table's names) |
| `test_query_names_every_column` | each column name of `VARIANTS`, against the query text | `AS "<name>"` appears in the query (the table and the query cannot drift apart) |
| `test_variant_loader_constants` | `VARIANT_LOADER`; `VARIANT_TSV_LOADER`     | `SQLTableLoader` with `tbl is VARIANTS`, `source is SI_VARIANTS_QUERY`; `CSVTableLoader` with `tbl is VARIANTS`, `source is VARIANTS_TSV` |

### `VARIANT_TSV_LOADER`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_variants_load_shape`    | `VARIANT_TSV_LOADER.load(CFG)`               | 2 rows; 45 columns in `VARIANTS` order; `'extra'` dropped; default integer index |
| `test_variants_dtypes`        | same                                         | `variant` and every `_merge`, `_vendor`, `_luster`, `_desc`, `_stitch`, `_thread` are `string`; `width`, `gauge`, `beams` and every `_ends`, `_denier` are `int64`; `rack_wt` and every `_pct`, `_rl` are `float64` |
| `test_variants_values`        | same, row `TA0799/31`                        | `width == 168`, `rack_wt == 12.51`, `gauge == 28`, `beams == 4`, `bar1_ends == 1164`, `bar1_merge == '612VE2095S53'`, `bar1_denier == 40`, `bar1_rl == 61.5`, `bar1_thread == 'SOLID'` |
| `test_variants_unused_bar_numbers` | same, row `TA0799/31`, bar 4            | `bar4_ends == 0`, `bar4_denier == 0`, `bar4_pct == 0.0`, `bar4_rl == 0.0` |
| `test_variants_unused_bar_text` | same, row `TA0799/31`, bar 4               | `bar4_merge`, `_vendor`, `_luster`, `_desc`, `_stitch`, `_thread` are all missing (`pd.isna`): the text `None` is read as blank, not as the string `'None'` |
| `test_variants_denier_not_normalised` | same, row `AU7805-X`                 | `bar4_denier == 70` (the 70 → 75 rule belongs to `products`, not the loader) |
| `test_variants_duplicates_kept` | a TSV with the `TA0799/31` row written twice | 2 rows (the loader does not de-duplicate variant names) |

### `VARIANTS` over a database connection

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_variants_sql_matches_tsv` | `SQLTableLoader(VARIANTS, Q_ALL).load(conn)` | a frame equal to `VARIANT_TSV_LOADER.load(CFG)` (`pd.testing.assert_frame_equal`): the table definition gives the same result from a connection's `NULL`s as from the extract's `None`s |

## `catalog.masterstyles`

Fixture: `greige-master-styles.json`, a list of records
`[{"master": "AU7805", "variant": "AU7805-X", "safety_tgt": 5000}, {"master": "AU2958G", "variant": "AU2958G-HA/2", "safety_tgt": 0}]`
(`safety_tgt` is an unlisted key).

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_master_styles_file`     | `MASTER_STYLES_FILE`                         | `cfg_name == 'inputs'`, `orient == 'records'`, `date_fmt is None`; `get_fpath(CFG) == join(tmp, 'greige-master-styles.json')` |
| `test_master_styles_table`    | `MASTER_STYLES`                              | `name == 'master_styles'`; `index.name == 'master'`; column names `['variant']` |
| `test_master_style_loader_constants` | `MASTER_STYLE_LOADER`                 | `tbl is MASTER_STYLES`, `source is MASTER_STYLES_FILE` |
| `test_master_styles_load`     | `MASTER_STYLE_LOADER.load(CFG)`              | 2 rows; `index.name == 'master'`; `index.tolist() == ['AU7805', 'AU2958G']` (file order); `list(columns) == ['variant']`; `'safety_tgt'` dropped |
| `test_master_styles_values`   | same                                         | `df.loc['AU2958G', 'variant'] == 'AU2958G-HA/2'`; `variant` and the index are `string` |

## `catalog.demand`

Fixture: a workbook with tab `Fab shortage` holding every source column
named in `PA_DEMAND` plus an unlisted `Customer` column, and a second tab
`Summary` holding one unrelated cell. Cells not mentioned are blank.

| Row | `Ply1 Item` | `PA Item` | `Bill To` | `Plant` | `Ship Day` | Requirements |
|-----|-------------|-----------|-----------|---------|------------|--------------|
| 0 | `'210189A'` (text) | `'FF AURA30000-39064-63 '` (padded) | `17191` | `20` (number) | `2` | `WK0` `3181`, `WK3` `9069.405`, `WK8` `5800` |
| 1 | `222127` (number) | `'FF TAFFETAHP-38712-60'` | `17191` | `20` (number) | `2` | `past due` `150.5` |
| 2 | `'FO000001'` (text) | `'FF HANA-40001-59'` | `30012` | `1350` (number) | `4` | none (every week blank) |

The workbook is saved as `pa_dmnd_20261104.xlsx`, and again under today's
date (`pa_dmnd_<date.today():%Y%m%d>.xlsx`). `DT = date(2026, 11, 4)`.

### Constants

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_demand_file`            | `PA_DEMAND_FILE`                             | `cfg_name == 'scheduling'`, `sheet_name == 'Fab shortage'`; `get_fpath(CFG, date=DT) == join(tmp, 'pa_dmnd_20261104.xlsx')` |
| `test_demand_table`           | `PA_DEMAND`                                  | `name == 'pa_demand'`; `index.name == 'part_no'`; column names `item, bill_to, plant, ship_day, past_due, wk0..wk8` in that order |
| `test_demand_week_sources`    | `PA_DEMAND` columns `past_due`, `wk0`..`wk8` | source names `"FAB req'd past due"`, `"FAB req'd WK0"`..`"FAB req'd WK8"` |
| `test_demand_loader_constants` | `PA_DEMAND_LOADER`                          | `tbl is PA_DEMAND`, `source is PA_DEMAND_FILE` |

### `PA_DEMAND_LOADER`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_demand_load_shape`      | `PA_DEMAND_LOADER.load(CFG, DT)`             | 3 rows; `index.name == 'part_no'`; 14 columns named as in `PA_DEMAND`; `'Customer'` dropped |
| `test_demand_part_numbers`    | same                                         | `index.tolist() == ['210189A', '222127', 'FO000001']` (text, numbers as plain text; placeholder parts kept) |
| `test_demand_dtypes`          | same                                         | `item` and `plant` are `string`; `bill_to` and `ship_day` are `int64`; `past_due` and `wk0`..`wk8` are `float64` |
| `test_demand_text`            | same                                         | `df.loc['210189A', 'item'] == 'FF AURA30000-39064-63'` (stripped); `plant.tolist() == ['20', '20', '1350']` (plant numbers as text) |
| `test_demand_quantities`      | same, row `210189A`                          | `wk0 == 3181.0`, `wk3 == 9069.405`, `wk8 == 5800.0`; every other week and `past_due` `0.0` |
| `test_demand_past_due`        | same, row `222127`                           | `past_due == 150.5`; `wk0`..`wk8` all `0.0` |
| `test_demand_blank_weeks`     | same, row `FO000001`                         | `past_due` and `wk0`..`wk8` all `0.0`, none missing |
| `test_demand_load_default_today` | `PA_DEMAND_LOADER.load(CFG)`              | same frame as `load(CFG, DT)` (today's file is read when no date is given) |
| `test_demand_load_missing_date` | `PA_DEMAND_LOADER.load(CFG, date(2000, 1, 1))` | raises `FileNotFoundError` (no file for that day) |

## `catalog.machines`

Fixture: `knit-machine-master.json`, an object keyed by machine id:

```python
{'N1': {'gauge': 28, 'is_new': True, 'width': 186, 'attrs': ['tall'], 'rpm': 2200, 'notes': 'x'},
 'B4': {'gauge': 32, 'is_new': False, 'width': 144, 'attrs': [], 'rpm': 1500, 'notes': ''},
 '12': {'gauge': 28, 'is_new': False, 'width': 168, 'attrs': ['tall', 'wide'], 'rpm': 1800, 'notes': ''}}
```

(`notes` is an unlisted key; `'12'` is a number-like id.)

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_machines_file`          | `KNIT_MACHINES_FILE`                         | `cfg_name == 'inputs'`, `orient == 'index'`, `date_fmt is None`; `get_fpath(CFG) == join(tmp, 'knit-machine-master.json')` |
| `test_machines_table`         | `KNIT_MACHINES`                              | `name == 'knit_machines'`; `index.name == 'machine'`, `index.src_name == 'index'`; column names `['gauge', 'width', 'is_new', 'rpm', 'attrs']` |
| `test_machine_loader_constants` | `KNIT_MACHINE_LOADER`                      | `tbl is KNIT_MACHINES`, `source is KNIT_MACHINES_FILE` |
| `test_new_machines_only`      | `NEW_MACHINES_ONLY`                          | a `frozenset` equal to `{'AU7992T2A'}` |
| `test_machines_load_shape`    | `KNIT_MACHINE_LOADER.load(CFG)`              | 3 rows; `index.name == 'machine'`; `index.tolist() == ['N1', 'B4', '12']` (file order; `'12'` stays text); `list(columns) == ['gauge', 'width', 'is_new', 'rpm', 'attrs']`; `'notes'` dropped |
| `test_machines_dtypes`        | same                                         | `gauge`, `width`, `rpm` are `int64`; `is_new` is `bool`; the index is `string` |
| `test_machines_values`        | same, row `N1`                               | `gauge == 28`, `width == 186`, `is_new` is `True`, `rpm == 2200` |
| `test_machines_attrs`         | same                                         | `attrs.tolist() == [('tall',), (), ('tall', 'wide')]` (tuples; no attributes is an empty tuple) |
