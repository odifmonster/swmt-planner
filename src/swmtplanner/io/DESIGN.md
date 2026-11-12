# `swmtplanner.io`

Input and output formatting: reading data in from the plant's sources and
producing the objects and JSON the rest of the package works with, and
formatting planner results for presentation and storage.

## Overview

`io` is the boundary between the package and the outside world. Data
arrives from a SQL database and, for now, from manually edited Excel and
TSV files; it leaves as the readable JSON the planners consume, and as
reports and formatted schedules. Nothing outside `io` reads a file or
queries a database, and nothing outside `io` knows which source a given
piece of data came from.

`io` introduces the following capabilities:

- **Loading tabular data** – a uniform way to describe a table (its
  columns, their source names, types, and conversions) and to load it into
  a pandas `DataFrame` from any supported source: a SQL query, a delimited text file,
  an Excel sheet, or a JSON file.
- **Source catalog** – one definition per plant data source: the `Table`
  that describes it, the `SQLQuery` or `File` it is read from, and the
  loader that joins the two. Everything else in the package that needs a
  source refers to these constants rather than describing the source
  itself.
- **Building product objects** – translating loaded tables into
  `core.products` objects: parsing yarn items, assembling master greige
  styles from their representative variants, deciding which machines each
  style can run on, and building dye formulas and finished fabrics from
  the cross-reference workbook.
- **Output formatting** – *(to be designed in a later round).*

Running `io` requires a **config JSON file**. Among other things, it
holds the paths to the folders containing the file-based sources and the
details needed to connect to the SQL database. A file source names the
config key its folder lives under rather than carrying a path itself, and
the SQL connection is opened from the config rather than from anything in
code, so the same source definitions work on any machine with a suitable
config. The config is passed around as a plain `dict`.

`io` depends on `swmtplanner.support` and `swmtplanner.core`, on
`pandas` (with its Excel extras) for tabular data, and on `pyodbc` for the
SQL database connection.

## Core objects

`io` has no top-level constants, classes, or functions of its own. It is
composed of the following submodules:

| Submodule | Responsibility                                                   |
|-----------|------------------------------------------------------------------|
| `loaders` | Reading data in: generic table descriptions and the loaders that fill them from each source |
| `catalog` | The concrete sources: a `Table`, source, and loader constant for each table of plant data |
| `products` | Building `core.products` objects from loaded catalog tables, one entry point per product kind plus one for everything |

Output formatting will be added as a further submodule when it is
designed.

### `loaders`

`loaders` holds the generic machinery for reading tabular data. It is
composed of two submodules and the loader classes at the `loaders` level:

- `table` describes *what* a table looks like (`Column`, `Table`);
- `sources` describes *where* data comes from (`SQLQuery`, `File` and its
  subclasses `CSVFile` and `ExcelFile`);
- the `TableLoader` classes describe *how* to fill a `Table` from a
  particular kind of source.

| Object               | Kind  | Description |
|----------------------|-------|-------------|
| `table.Column`       | class | Describes one column: its name in the resulting `DataFrame`, its name in the source, its pandas dtype, and how source values are converted |
| `table.Table`        | class | A generic table: its column set and how it is converted from its source into a pandas `DataFrame` |
| `sources.SQLQuery`   | class | A query against the SQL database, with date parameters that are filled in at load time |
| `sources.File`       | class | Base class for a file source: which config folder it lives in, its (possibly dated) name, and its extension |
| `sources.CSVFile`    | class | A delimited text file (CSV, TSV) with its separator |
| `sources.ExcelFile`  | class | A sheet of an Excel workbook, with the row-selection options passed to `pd.read_excel` |
| `sources.JSONFile`   | class | A JSON file holding a list of flat records, read with `pd.read_json` |
| `sources.conn_str`   | function | Builds the `pyodbc` connection string from the config's `sql` block |
| `sources.connect`    | function | Opens a `pyodbc.Connection` to the SQL database from the config's `sql` block |
| `TableLoader`        | class | Abstract base for loading a `Table` from a source into a `DataFrame`; owns the column conversion step |
| `SQLTableLoader`     | class | `TableLoader` for a `SQLQuery`, read through a `pyodbc` connection |
| `CSVTableLoader`     | class | `TableLoader` for a `CSVFile`, read with `pd.read_csv` |
| `ExcelTableLoader`   | class | `TableLoader` for an `ExcelFile`, read with `pd.read_excel` |
| `JSONTableLoader`    | class | `TableLoader` for a `JSONFile`, read with `pd.read_json` |

File layout: `table/` holds `column.py` and `table.py`; `sources/` holds
`sqlquery.py`, `file.py` (`File`, `CSVFile`, `ExcelFile`, `JSONFile`), and
`connect.py` (`conn_str`, `connect`); the loaders are one file each at
the `loaders` level (`tableloader.py`, `sqltableloader.py`,
`csvtableloader.py`, `exceltableloader.py`, `jsontableloader.py`).

```python
# loaders/table

@dataclass(frozen=True)
class Column:
    name: str                                   # column name in the DataFrame
    dtype: str                                  # pandas dtype name, e.g. "int64", "string"
    src_name: str | None = None                 # column name in the source; None means same as name
    converter: Callable[[Any], Any] | None = None   # applied to each source value before pandas
    read_na_as: Any | None = None               # substituted for null/NaN/None source values

@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    index: Column | None = None                 # column to use as the DataFrame index, if any

# loaders/sources

type DefaultVal = None | Callable[[], datetime]   # None: no default (parameter required)

@dataclass(frozen=True)
class SQLQuery:
    raw_str: str                                # query text; str.format placeholders {0}, {1}, … or {name}
    date_params: int | tuple[str, ...]          # number of positional params, or the name of each
    date_fmt: str | None = None                 # strftime format for rendering datetimes; required if the query has any parameters
    defaults: tuple[DefaultVal, ...] | tuple[tuple[str, DefaultVal], ...] = ()

    def get_query(self, *args: datetime | None, **kwargs: datetime | None) -> str: ...

@dataclass(frozen=True)
class File:
    cfg_name: str                               # config key holding the path to this file's folder
    stem: str                                   # file name without extension; a format string if dated
    ext: str                                    # extension, including the dot, e.g. ".tsv"
    date_fmt: str | None = None                 # strftime format for dated files; None means undated

    def get_fpath(self, cfg: dict, override_name: str | None = None,
                  date: date | None = None) -> str: ...

@dataclass(frozen=True)
class CSVFile(File):
    sep: str = ','                              # field separator; "\t" for TSV

@dataclass(frozen=True)
class ExcelFile(File):
    ext: str = '.xlsx'                          # always .xlsx
    sheet_name: str | int = 0                   # passed to pd.read_excel
    header: int | None = 0                      # passed to pd.read_excel
    skiprows: int | None = None                 # passed to pd.read_excel
    nrows: int | None = None                    # passed to pd.read_excel
    skipfooter: int = 0                         # passed to pd.read_excel

@dataclass(frozen=True)
class JSONFile(File):
    ext: str = '.json'                          # always .json
    orient: str = 'records'                     # passed to pd.read_json

def conn_str(cfg: dict) -> str: ...
def connect(cfg: dict) -> pyodbc.Connection: ...

# loaders

class TableLoader(ABC):
    tbl: Table
    source: SQLQuery | File

    @abstractmethod
    def load(self, *args, **kwargs) -> pd.DataFrame: ...

class SQLTableLoader(TableLoader):
    source: SQLQuery
    def load(self, conn: pyodbc.Connection, *args, **kwargs) -> pd.DataFrame: ...

class CSVTableLoader(TableLoader):
    source: CSVFile
    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame: ...

class ExcelTableLoader(TableLoader):
    source: ExcelFile
    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame: ...

class JSONTableLoader(TableLoader):
    source: JSONFile
    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame: ...
```

### `catalog`

`catalog` is a package with one module per plant data source. Each module
defines, as constants, the source (`SQLQuery` or `File`), the `Table`
describing the columns kept from it, the loader joining the two, and any
small lookup maps that belong with that source. The modules hold no
functions beyond private converters, and one loader subclass
(`catalog.xref.XrefFabricLoader`) for the one table that needs a second
sheet to finish loading; the translation of loaded frames into
`core.products` objects is the job of the `products` submodule.

| Module                 | Source                                                   | Constants |
|------------------------|----------------------------------------------------------|-----------|
| `catalog.xref`         | `Xref` and `Greige Styles` tabs of `PA Master Xref.xlsx` (PA Supply OneDrive folder) | `GREIGE_STYLES_SHEET`, `GREIGE_STYLES`, `GREIGE_STYLE_LOADER`, `XREF_FILE`, `FABRICS`, `XrefFabricLoader`, `FABRIC_LOADER`, `SHADE_RATINGS` |
| `catalog.variants`     | Greige style variants from the style master in the SQL database (query `si_variants.sql`); the same table from a TSV extract | `SI_VARIANTS_QUERY`, `VARIANTS_TSV`, `VARIANTS`, `VARIANT_LOADER`, `VARIANT_TSV_LOADER` |
| `catalog.masterstyles` | `greige-master-styles.json` (plan inputs folder)         | `MASTER_STYLES_FILE`, `MASTER_STYLES`, `MASTER_STYLE_LOADER` |
| `catalog.demand`       | `Fab shortage` tab of the dated `pa_dmnd_<date>.xlsx` (Scheduling folder) | `PA_DEMAND_FILE`, `PA_DEMAND`, `PA_DEMAND_LOADER` |
| `catalog.machines`     | `knit-machine-master.json` (plan inputs folder)          | `KNIT_MACHINES_FILE`, `KNIT_MACHINES`, `KNIT_MACHINE_LOADER`, `NEW_MACHINES_ONLY` |

SQL query text lives in `.sql` files under `catalog/sql/` and is read at
import time by a private helper, `catalog._sql.read_sql(name) -> str`,
through `importlib.resources`. (This needs a `package-data` entry for
`swmtplanner.io.catalog` in `pyproject.toml` so the `.sql` files ship with
the package.)

Config keys used by the catalog so far:

| Key         | Folder                                                        |
|-------------|---------------------------------------------------------------|
| `pa_supply` | The `[EXT] Supply Chain - PA Supply` OneDrive folder, holding `PA Master Xref.xlsx` |
| `inputs`    | The plan inputs folder, holding `greige-master-styles.json`, `knit-machine-master.json`, and the `variants.tsv` extract |
| `scheduling` | The `Shawmut Projects/Scheduling` folder, holding the dated `pa_dmnd_<YYYYMMDD>.xlsx` demand views |

```python
# catalog/xref.py

XREF_FILE: ExcelFile = ExcelFile('pa_supply', 'PA Master Xref', sheet_name='Xref')

FABRICS: Table = Table('fabrics', (
    Column('item',    'string',  src_name='PA FIN ITEM',  read_na_as='', converter=_strip),  # FF item code
    Column('greige',  'string',  src_name='GREIGE ITEM',  read_na_as='', converter=_strip),  # GreigeAlt; converted to GreigeAlt2 by the loader
    Column('style',   'string',  src_name='STYLE',        read_na_as='', converter=_strip),  # Fabric.master_style
    Column('width',   'float64', src_name='WD'),                                              # Fabric.width
    Column('yld',     'float64', src_name='Yield'),                                           # Fabric.yld
    Column('formula', 'Int64',   src_name='COLOR NUMBER'),                                    # DyeFormula.id
    Column('color',   'string',  src_name='COLOR NAME',   read_na_as='', converter=_strip),  # DyeFormula.name
    Column('shade',   'Int64',   src_name='SHADE RATING'),                                    # key of SHADE_RATINGS
    Column('active',  'bool',    src_name='STATUS',       read_na_as='', converter=_is_active),
    *(Column(f'jet{i}', 'bool',  src_name=f'JET {i}',     read_na_as='', converter=_is_x)
      for i in range(1, 11)),                                                                 # Fabric.jets
    Column('tanks',   'bool',    src_name='TANKS',        read_na_as='', converter=_is_x),
), index=Column('part_no', 'string', src_name='PLY 1 PART #', read_na_as='', converter=_strip))

SHADE_RATINGS: dict[int, Shade] = {   # Xref "SHADE RATING" -> Shade
    0: Shade.LIGHT0,
    1: Shade.LIGHT1,
    2: Shade.MEDIUM,
    3: Shade.BLACK,
    4: Shade.SD_BLACK,
}

GREIGE_STYLES_SHEET: ExcelFile = ExcelFile('pa_supply', 'PA Master Xref', sheet_name='Greige Styles')

GREIGE_STYLES: Table = Table('greige_styles', (
    Column('master', 'string',  src_name='GreigeAlt2', converter=_strip),   # name the knitters use
    Column('std_wt', 'float64', src_name='Target'),                         # Greige.std_wt
), index=Column('alias', 'string', src_name='GreigeAlt', converter=_strip))

GREIGE_STYLE_LOADER: ExcelTableLoader = ExcelTableLoader(GREIGE_STYLES, GREIGE_STYLES_SHEET)

@dataclass(frozen=True)
class XrefFabricLoader(ExcelTableLoader):
    aliases: ExcelTableLoader                   # loader for the greige styles table (same workbook)

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame: ...   # greige -> GreigeAlt2 name

FABRIC_LOADER: XrefFabricLoader = XrefFabricLoader(FABRICS, XREF_FILE, GREIGE_STYLE_LOADER)

# catalog/variants.py

SI_VARIANTS_QUERY: SQLQuery = SQLQuery(read_sql('si_variants.sql'), 0)
VARIANTS_TSV: CSVFile = CSVFile('inputs', 'variants', '.tsv', sep='\t')

VARIANTS: Table = Table('variants', (
    Column('variant', 'string'),
    Column('width',   'int64'),      # knitting width, inches
    Column('rack_wt', 'float64'),
    Column('gauge',   'int64'),
    Column('beams',   'int64'),
    *_bar_columns(1), *_bar_columns(2), *_bar_columns(3), *_bar_columns(4),
))
# where _bar_columns(i) is, for bar i:
#   Column(f'bar{i}_ends',   'int64',   read_na_as=0),
#   Column(f'bar{i}_merge',  'string'),
#   Column(f'bar{i}_vendor', 'string'),
#   Column(f'bar{i}_denier', 'int64',   read_na_as=0, converter=int),
#   Column(f'bar{i}_luster', 'string'),
#   Column(f'bar{i}_desc',   'string'),
#   Column(f'bar{i}_pct',    'float64', read_na_as=0.0),
#   Column(f'bar{i}_rl',     'float64', read_na_as=0.0),
#   Column(f'bar{i}_stitch', 'string'),
#   Column(f'bar{i}_thread', 'string'),

VARIANT_LOADER: SQLTableLoader = SQLTableLoader(VARIANTS, SI_VARIANTS_QUERY)
VARIANT_TSV_LOADER: CSVTableLoader = CSVTableLoader(VARIANTS, VARIANTS_TSV)

# catalog/masterstyles.py

MASTER_STYLES_FILE: JSONFile = JSONFile('inputs', 'greige-master-styles')

MASTER_STYLES: Table = Table('master_styles',
                             (Column('variant', 'string'),),
                             index=Column('master', 'string'))

MASTER_STYLE_LOADER: JSONTableLoader = JSONTableLoader(MASTER_STYLES, MASTER_STYLES_FILE)

# catalog/demand.py

PA_DEMAND_FILE: ExcelFile = ExcelFile('scheduling', 'pa_dmnd_{}', date_fmt='%Y%m%d',
                                      sheet_name='Fab shortage')

PA_DEMAND: Table = Table('pa_demand', (
    Column('item',     'string',  src_name='PA Item',  converter=_strip),   # FF item code
    Column('bill_to',  'int64',   src_name='Bill To'),
    Column('plant',    'string',  src_name='Plant',    converter=_strip),
    Column('ship_day', 'int64',   src_name='Ship Day'),
    Column('past_due', 'float64', src_name="FAB req'd past due", read_na_as=0.0),
    *(Column(f'wk{i}', 'float64', src_name=f"FAB req'd WK{i}", read_na_as=0.0)
      for i in range(0, 9)),
), index=Column('part_no', 'string', src_name='Ply1 Item', converter=_strip))

PA_DEMAND_LOADER: ExcelTableLoader = ExcelTableLoader(PA_DEMAND, PA_DEMAND_FILE)

# catalog/machines.py

KNIT_MACHINES_FILE: JSONFile = JSONFile('inputs', 'knit-machine-master', orient='index')

KNIT_MACHINES: Table = Table('knit_machines', (
    Column('gauge',  'int64'),
    Column('width',  'int64'),
    Column('is_new', 'bool'),
    Column('rpm',    'int64'),
    Column('attrs',  'object', converter=tuple),   # tuple[str, ...]
), index=Column('machine', 'string', src_name='index'))

KNIT_MACHINE_LOADER: JSONTableLoader = JSONTableLoader(KNIT_MACHINES, KNIT_MACHINES_FILE)

NEW_MACHINES_ONLY: frozenset[str] = frozenset({'AU7992T2A'})   # master styles restricted to is_new machines
```

### `products`

`products` turns loaded catalog frames into `core.products` objects. Each
builder takes already-loaded frames (and the dicts built before it) and
returns an id-keyed dict, so a caller can load and build one kind of
product on its own; `load_products` runs every catalog loader and every
builder in order and returns them bundled. Anything a builder cannot
translate is skipped with a warning through the `logging` logger
`swmtplanner.io.products`, never raised, so one bad row does not stop the
load.

| Object               | Kind     | Description |
|----------------------|----------|-------------|
| `Products`           | class    | The four product dicts bundled together |
| `build_merges`       | function | `Merge` (and its `Yarn`) for every distinct yarn item on any variant bar |
| `build_greiges`      | function | One `Greige` per master style, from its representative variant, with its machine rates |
| `build_dye_formulas` | function | One `DyeFormula` per formula number in the cross-reference |
| `build_fabrics`      | function | One `Fabric` per finished item code in the cross-reference |
| `load_products`      | function | Loads every source through the catalog and builds everything |

```python
# products

@dataclass(frozen=True)
class Products:
    merges: dict[str, Merge]          # Merge.id -> Merge
    greiges: dict[str, Greige]        # master style name -> Greige
    formulas: dict[int, DyeFormula]   # formula number -> DyeFormula
    fabrics: dict[str, Fabric]        # finished item code -> Fabric

def build_merges(variants: pd.DataFrame) -> dict[str, Merge]: ...
def build_greiges(variants: pd.DataFrame, master_styles: pd.DataFrame,
                  greige_styles: pd.DataFrame, machines: pd.DataFrame,
                  merges: dict[str, Merge]) -> dict[str, Greige]: ...
def build_dye_formulas(fabrics: pd.DataFrame) -> dict[int, DyeFormula]: ...
def build_fabrics(fabrics: pd.DataFrame, demand: pd.DataFrame,
                  greiges: dict[str, Greige], formulas: dict[int, DyeFormula]) -> dict[str, Fabric]: ...

def load_products(cfg: dict, conn: pyodbc.Connection | None = None,
                  dt: date | None = None) -> Products: ...
```

The frame arguments are the catalog tables of the same name: `variants`
is `VARIANTS`, `master_styles` is `MASTER_STYLES`, `greige_styles` is
`GREIGE_STYLES`, `machines` is `KNIT_MACHINES`, `fabrics` is `FABRICS` as returned by `FABRIC_LOADER`
(with `greige` already converted to the master name), and `demand` is
`PA_DEMAND`.

## `loaders.table`

### `Column`

`Column` – an immutable description of one column of a `Table`: where it
comes from in the source, what it is called once loaded, and how its
values are converted on the way.

| Field        | Type                           | Description |
|--------------|--------------------------------|-------------|
| `name`       | `str`                          | The column's name in the resulting pandas `DataFrame` |
| `dtype`      | `str`                          | The string name of the pandas datatype the column is converted to (e.g. `"int64"`, `"float64"`, `"string"`, `"boolean"`) |
| `src_name`   | `str \| None`                  | The column's name in the source. When `None`, the source name is assumed to be the same as `name` |
| `converter`  | `Callable[[Any], Any] \| None` | Optional single-argument function applied to each source value before it is handed to pandas |
| `read_na_as` | `Any \| None`                  | Optional value substituted for null, NaN, or `None` source values |

The fields are ordered with the two required values first (`name`,
`dtype`) so that the optional ones can take defaults.

### `Table`

`Table` – an immutable description of a generic table: its name and the
columns it is made of.

| Field     | Type                   | Description |
|-----------|------------------------|-------------|
| `name`    | `str`                  | The table's name |
| `columns` | `tuple[Column, ...]`   | The columns to load, in order |
| `index`   | `Column \| None`       | Optionally, the column to use as the `DataFrame` index. `None` means the frame keeps a default integer index |

*How a `Table` is converted from its source into a `DataFrame` is to be
detailed with `TableLoader`.*

## `loaders.sources`

### `SQLQuery`

`SQLQuery` – an immutable query against the SQL database whose text may
contain places where date parameters must be inserted before it is run.

| Field         | Type                                                               | Description |
|---------------|--------------------------------------------------------------------|-------------|
| `raw_str`     | `str`                                                              | The query text, a Python `str.format` string with a placeholder for each date parameter: `{0}`, `{1}`, … for positional parameters, `{name}` for named ones |
| `date_params` | `int \| tuple[str, ...]`                                           | The query's date parameters. An `int` gives the number of positional parameters; a tuple of strings gives the name of each parameter as it appears in the format string |
| `date_fmt`    | `str \| None`                                                      | The `strftime` format used to render each `datetime` argument into the query text (e.g. `"'%Y-%m-%d'"` to produce a quoted SQL date literal). May be omitted only for a query with no parameters; construction raises `ValueError` if `date_fmt` is `None` and the query has any date parameters, since parameters are always dates |
| `defaults`    | `tuple[DefaultVal, ...] \| tuple[tuple[str, DefaultVal], ...]`      | Optional defaults. The first form is positional, one entry per parameter in order; the second pairs parameter names with their defaults. Omitted (empty) means no parameter has a default |

`DefaultVal = None | Callable[[], datetime]`. A default is a zero-argument
callable producing the datetime to use (so that, for example, "today" is
evaluated when the query is built, not when the module is imported). A
default of `None` means the parameter has no default and must be
supplied.

| Method                                                   | Description |
|----------------------------------------------------------|-------------|
| `get_query(self, *args: datetime \| None, **kwargs: datetime \| None) -> str` | Returns the query text with every date parameter filled in, from the positional or keyword arguments provided, falling back to the parameter's default where an argument is not provided |

`get_query` renders each resolved `datetime` with `date_fmt` and
substitutes the results into `raw_str` with `str.format`. It is called with
either positional arguments (for positional `date_params`) or keyword
arguments (for named `date_params`), matching the form of the query's
parameters; mixing the forms is an error. When using positional arguments and
only some parameters should fall back to their defaults, `None` is passed
at the position where the default should be used. A keyword argument that
is omitted, or passed as `None`, likewise uses its default. A parameter
that is neither supplied nor has a default is an error.

### `File`

`File` – an immutable description of a file-based source. It does not
hold a path: it holds the name of the config parameter whose value is the
folder the file lives in, and enough to build the file's name, which for
many files includes a date. `get_fpath` is implemented here and shared by
the subclasses, which only add source-specific read options.

| Field      | Type           | Description |
|------------|----------------|-------------|
| `cfg_name` | `str`          | The name of the config parameter that holds the path to the directory holding this file |
| `stem`     | `str`          | The file's name without its extension. For a dated file it is a format string such that `stem.format(dt.strftime(date_fmt))` gives the name for date `dt` |
| `ext`      | `str`          | The file's extension, including the leading dot |
| `date_fmt` | `str \| None`  | The `strftime` format for the date embedded in the file name. `None` means the file is not dated and `stem` is used as-is |

| Method | Description |
|--------|-------------|
| `get_fpath(self, cfg: dict, override_name: str \| None = None, date: date \| None = None) -> str` | Returns the full path of the file, in the folder `cfg[cfg_name]`. If `override_name` is given (a different name for this file explicitly passed in from the command line), it is the complete file name, extension included, and is used as-is. Otherwise the name is `stem + ext` for an undated file, or `stem.format(date.strftime(date_fmt)) + ext` for a dated one, where `date` defaults to today when not given |

### `CSVFile`

`CSVFile(File)` – a delimited text file. Used for both comma- and
tab-separated files; the extension is whatever the file has (`.csv`,
`.tsv`).

| Field | Type  | Description |
|-------|-------|-------------|
| `sep` | `str` | The field separator passed to `pd.read_csv`; `"\t"` for a TSV |

### `ExcelFile`

`ExcelFile(File)` – one sheet of an Excel workbook. `ext` is always
`.xlsx`. The remaining fields are passed straight through to
`pd.read_excel` to select the sheet and the rows to read.

| Field        | Type           | Description |
|--------------|----------------|-------------|
| `sheet_name` | `str \| int`   | The sheet to read, by name or position |
| `header`     | `int \| None`  | The row holding the column names, or `None` if there is none |
| `skiprows`   | `int \| None`  | Rows to skip at the top of the sheet |
| `nrows`      | `int \| None`  | Number of rows to read |
| `skipfooter` | `int`          | Rows to skip at the bottom of the sheet |

### `JSONFile`

`JSONFile(File)` – a JSON file holding tabular data, such as a list of
flat objects with one key per column. `ext` is always `.json`.

| Field    | Type  | Description |
|----------|-------|-------------|
| `orient` | `str` | The JSON layout, passed to `pd.read_json`; `"records"` (the default) is a list of objects |

### `conn_str` and `connect`

`connect(cfg: dict) -> pyodbc.Connection` – opens a connection to the
SQL database from the config's `sql` block. The result is what
`SQLTableLoader.load` is given as `conn`. `conn_str(cfg: dict) -> str`
builds the connection string `connect` uses; it is public so the string
can be checked without a database.

The config's `sql` key maps to an object with the following keys:

| Key                    | Required | Description |
|------------------------|----------|-------------|
| `HOST`                 | yes      | The database server's host name |
| `PORT`                 | yes      | The port to connect on |
| `DATABASE`             | yes      | The database name |
| `UID`                  | yes      | The user id |
| `PWD`                  | yes      | The password |
| `DRIVER`               | no       | The ODBC driver name; defaults to `{ODBC Driver 17 for SQL Server}` |
| any other key          | no       | Passed through to the connection string as-is, e.g. `Encrypt`, `TrustServerCertificate` |

`conn_str` builds the connection string from these values, in the order
`DRIVER`, then `SERVER=<HOST>,<PORT>`, then every other key as
`<KEY>=<value>` in config order, joined with `;`. A missing required key
raises `KeyError` naming it. The password is never logged or included in
any error message.

## `loaders`

### `TableLoader`

`TableLoader` – the abstract base for loading a `Table` from a source.
All loading and conversion lives here: a loader reads the raw rows from
its source and then converts them, column by column, into the frame the
`Table` describes. The subclasses differ only in how they read the raw
rows, because each passes different attributes of its source along to the
corresponding pandas reader.

| Field    | Type               | Description |
|----------|--------------------|-------------|
| `tbl`    | `Table`            | The table to load |
| `source` | `SQLQuery \| File` | Where to load it from; narrowed by each subclass, which raises `TypeError` on construction if given the wrong kind of source |

| Method                                      | Description |
|---------------------------------------------|-------------|
| `load(self, *args, **kwargs) -> pd.DataFrame` | Abstract. Reads the raw rows from `source` and returns the converted frame |

**Conversion.** Once the raw rows are read, the loader applies the
following to produce the result, for each `Column` in `tbl.columns`:

1. Take the source column named `src_name` (or `name` if `src_name` is
   `None`) and call it `name` in the result.
2. Substitute `read_na_as` for every null, NaN, or `None` value, if
   `read_na_as` is given.
3. Apply `converter` to every value, if `converter` is given.
4. Cast the column to `dtype`.

`read_na_as` runs before `converter`, so a converter never sees a null
where a substitute was given. If `tbl.index` is set, that column is
converted in the same way and then used as the frame's index.

**Column mismatches.** Source columns not listed in `tbl.columns` (or as
`tbl.index`) are dropped silently; the result contains exactly the
`Table`'s columns. A listed column whose source name is not present in
the source raises `KeyError` naming the table and the missing column, so
a changed extract or query is caught at load time rather than later.

### `SQLTableLoader`

`SQLTableLoader(TableLoader)` – loads a `Table` from a `SQLQuery`.

| Method | Description |
|--------|-------------|
| `load(self, conn: pyodbc.Connection, *args, **kwargs) -> pd.DataFrame` | Builds the query text with `source.get_query(*args, **kwargs)` (so the date arguments and their defaults follow the `SQLQuery` rules), runs it over `conn`, and converts the result |

### `CSVTableLoader`

`CSVTableLoader(TableLoader)` – loads a `Table` from a `CSVFile` with
`pd.read_csv`, passing along the file's `sep`.

| Method | Description |
|--------|-------------|
| `load(self, cfg: dict, dt: date \| None = None, override_name: str \| None = None) -> pd.DataFrame` | Resolves the file's path with `source.get_fpath(cfg, override_name, dt)` (so a dated file defaults to today, and an `override_name` replaces the file name entirely), reads it, and converts the result |

### `ExcelTableLoader`

`ExcelTableLoader(TableLoader)` – loads a `Table` from an `ExcelFile`
with `pd.read_excel`, passing along the file's `sheet_name`, `header`,
`skiprows`, `nrows`, and `skipfooter`.

| Method | Description |
|--------|-------------|
| `load(self, cfg: dict, dt: date \| None = None, override_name: str \| None = None) -> pd.DataFrame` | Resolves the file's path with `source.get_fpath(cfg, override_name, dt)` (so a dated file defaults to today, and an `override_name` replaces the file name entirely), reads it, and converts the result |

### `JSONTableLoader`

`JSONTableLoader(TableLoader)` – loads a `Table` from a `JSONFile` with
`pd.read_json`, passing along the file's `orient`.

| Method | Description |
|--------|-------------|
| `load(self, cfg: dict, dt: date \| None = None, override_name: str \| None = None) -> pd.DataFrame` | Resolves the file's path exactly as `ExcelTableLoader.load` does, reads it, and converts the result |

When `orient` is `"index"` (a JSON object keyed by row), `pd.read_json`
returns the keys as the frame's index rather than as a column. The loader
resets that index before conversion so the keys are available as a source
column named `index`, which a `Table` can pick up with
`src_name='index'`. The file is read with `convert_axes=False`, so keys
stay the strings they are in the file rather than being guessed into
numbers or dates; any typing is left to the `Table`'s columns.

## `catalog`

Each module below is one plant data source. For each, the tables list the
columns kept, their source names, and what each is for. Anything in the
source that is not listed is dropped by the loader. Row filtering (blank
rows, inactive items, duplicates) is not done by the loader; the notes say
what the product builder must handle.

### `catalog.xref`

**Source.** The `Xref` tab of `PA Master Xref.xlsx`, an Excel workbook
maintained by hand in the `[EXT] Supply Chain - PA Supply` OneDrive
folder (config key `pa_supply`). The workbook has other tabs (`Greige
Style Translation`, `Greige Styles`, `TIER ONE X-REF`, `Reduction List`,
`EOP`) that are not read. The tab is undated and read with the default
header row. `XREF_FILE` is the `ExcelFile`; `FABRICS` the `Table`;
`FABRIC_LOADER` the loader, an `XrefFabricLoader` (below).

**Columns** (`FABRICS`). The table is indexed by `part_no`, the ply 1
part number, because that is what makes a row unique: the same finished
item code can be carried by more than one part (for instance an original
made with cationic yarn and its non-cationic replacement). The `Fabric`
object itself stays keyed by the finished item code, so the builder
collapses the rows sharing an item code into one fabric.

| Column    | Source column  | dtype     | Description |
|-----------|----------------|-----------|-------------|
| `part_no` | `PLY 1 PART #` | `string`  | Index. Finished fabric part number, unique among non-blank rows. Mixed integers and codes in the source (e.g. `239569`, `248213FR`, `RSHMOLTOBK`), so read as text |
| `item`    | `PA FIN ITEM`  | `string`  | Finished fabric item code, `FF <style>-<formula>-<width>` |
| `greige`  | `GREIGE ITEM`  | `string`  | Greige style name. The sheet holds the `GreigeAlt` name; the loader converts it to the `GreigeAlt2` name, which is the one the knitters use and the `Greige.id` |
| `style`   | `STYLE`        | `string`  | Fabric style name; becomes `Fabric.master_style` |
| `width`   | `WD`           | `float64` | Finished width, inches; fractional widths occur (`57.25`) |
| `yld`     | `Yield`        | `float64` | Yield, yards per pound |
| `formula` | `COLOR NUMBER` | `Int64`   | Dye formula number; becomes `DyeFormula.id`. Nullable integer because a few rows are blank |
| `color`   | `COLOR NAME`   | `string`  | Dye formula name; becomes `DyeFormula.name` |
| `shade`   | `SHADE RATING` | `Int64`   | Shade rating 0–4, mapped to `Shade` through `SHADE_RATINGS` |
| `active`  | `STATUS`       | `bool`    | `False` where the status is `I`; `A` and blank are `True` |
| `jet1` … `jet10` | `JET 1` … `JET 10` | `bool` | `True` where the cell holds an `X` (case-insensitive); together they give `Fabric.jets` |
| `tanks`   | `TANKS`        | `bool`    | `True` where the cell holds an `X`; whether the fabric can be dyed in a tank rather than a jet |

The text columns strip surrounding whitespace (`_strip`), since the source
has values like `" AU7389G"` and `"AU7389C "`, and read blanks as `""` so
the converter never sees a null. The flag columns use `_is_x` (`X` or `x`
after stripping) and `_is_active` (anything but `I` after stripping and
upper-casing, so a blank status counts as active).

Source columns not kept: `OZ/SQYD`, `Wide width conversion`, `Wide width`,
`PROGRAM`, `LAM`, `COMMENTS`, `PA WIP ITEM`, `PA ALT WIP ITEM`,
`Yield %`, `EOP`, `VOLUME (WEEKLY)`.

**`SHADE_RATINGS`.** Maps the `shade` column's rating to a `Shade`:
0 → `LIGHT0`, 1 → `LIGHT1`, 2 → `MEDIUM`, 3 → `BLACK`, 4 → `SD_BLACK`.

**Greige styles** (`GREIGE_STYLES_SHEET`, `GREIGE_STYLES`,
`GREIGE_STYLE_LOADER`). The `Greige Styles` tab of the same workbook has
one row per greige style with its `GreigeAlt` (the name as it appears in
the `GREIGE ITEM` column of the `Xref` tab), its `GreigeAlt2` (the master
style name, which the knitters use), and its `Target` (the target weight
of one roll). Those three columns are read, as `alias` (the index),
`master`, and `std_wt`; the tab's other columns (`WeeklyLbs`,
`SafetyDays`, `SafetyTgt`, `Pattern Family`, daily rates, and a grid of
machine flags) belong to inventory and demand planning and will be picked
up when those are designed.

| Column   | Source column | dtype     | Description |
|----------|---------------|-----------|-------------|
| `alias`  | `GreigeAlt`   | `string`  | Index. The greige name used in the `Xref` tab |
| `master` | `GreigeAlt2`  | `string`  | The master style name it stands for |
| `std_wt` | `Target`      | `float64` | Target roll weight, pounds; becomes `Greige.std_wt` |

The table serves two lookups. As an alias map it is read by `alias` to
get `master`. For the standard roll weight it is read by the master's own
name, which is always present as an `alias` of itself; the row is the
master's, not that of another alias pointing at it (`ANMUT-C` points at
`AU7805` but has its own target of 740 against `AU7805`'s 340). Targets
in the 2026-11-06 workbook are 740 for most styles, with 800, 340, and
310 on a few.

As of the 2026-11-06 workbook the only alias that differs from its master
is `ANMUT-C` → `AU7805`; every master style is listed, and two listed
names (`AU7368H`, `AU7798B`) are not master styles because they are
produced at other plants.

**`XrefFabricLoader`.** `XrefFabricLoader(ExcelTableLoader)` – the loader
for `FABRICS`. It adds one field, `aliases`, the loader for the greige
styles table, and overrides `load`:

1. Load the fabrics frame as `ExcelTableLoader.load` does.
2. Load the greige styles frame with `aliases.load`, passing the same
   `cfg`, `dt`, and `override_name` (both sheets are in the same workbook).
3. Replace each `greige` value that is an `alias` with its `master`.
   A value that is not an alias is left as it is (stripped), so nothing
   is lost and the product builder can name it when it warns.

The frame `FABRIC_LOADER.load(cfg)` returns therefore already carries the
`GreigeAlt2` name in `greige`, and nothing downstream needs the table for
aliasing.

**Notes for the product builder** (observed in the 2026-11-04 workbook):

- About 340 of the sheet's 760 rows are blank, and come through with an
  empty `part_no` index value; they must be dropped. A handful of rows
  have a `part_no` but no other data.
- `item` is not unique even among active rows: 19 item codes appear on two
  or three rows with different part numbers, sometimes differing in
  `greige` or the jet flags. Rows sharing an item code become one
  `Fabric`. Where they disagree on jets, the larger set is the correct
  one. Which part number of such a pair is the one in use (and so whose
  `greige` defines the fabric) is settled by the demand view
  (`catalog.demand`), not by this sheet.
- The `active` flag is not fully reliable: some rows marked `A` are on
  greige styles no longer in production (e.g. the `AU6946U - CAT` rows
  whose non-cationic replacement is also listed), and part `229081`
  (`FF HANA--59`) is marked `I` but has demand; that one is believed to be
  an error in the workbook.
- A dye formula number does not always carry one name or one shade: many
  formula numbers appear with two or more spellings of the name, and four
  (39066, 40629, 40733, 40760) with two different shade ratings. The
  conflicting shade ratings are to be verified with the development team;
  the name to use when spellings differ is still to be decided.
- Active rows with missing data: 2 lack a shade rating, 1 lacks a formula
  number, 5 lack a yield, and 14 have no jets flagged.
- After the loader's conversion, active `greige` values that are still
  not master style names, as of 2026-11-06: `AU7368H` and `AU7798B`
  (produced at other plants, so correctly absent), and `AU1148KWT`,
  `AU6946U  -  CAT`, `AU7614-BKAN`, `AU7614-CGAN`, `AU7614CLG-186`,
  `AUSR7992`, `NEOLUXE D2`, `NEOLUXE-W D2`, `NJ-85`, and the placeholder
  `NOT FINDING THIS`, none of which is in the alias sheet; 26 of 344
  active rows. Their fabrics are skipped with a warning.

### `catalog.variants`

**Source.** The style master in the SQL database, through the query in
`catalog/sql/si_variants.sql`: every style with a positive knitting width
and rack weight and a gauge, with its four bars joined out to the yarn
item (merge, vendor, denier, luster, description), stitch, and threading
tables. `SI_VARIANTS_QUERY` is the `SQLQuery` (no date parameters);
`VARIANTS` the `Table`; `VARIANT_LOADER` the `SQLTableLoader`.

The same table is also available as a TSV extract, `variants.tsv`, in the
plan inputs folder (config key `inputs`): `VARIANTS_TSV` is the `CSVFile`
and `VARIANT_TSV_LOADER` the `CSVTableLoader`. The extract writes nulls as
the literal `None`, which `pd.read_csv` reads as null by default, so both
loaders produce the same frame.

**Columns** (`VARIANTS`). The query already aliases its output to the
names below, so no `src_name` is needed.

| Column    | dtype     | Description |
|-----------|-----------|-------------|
| `variant` | `string`  | Style name as recorded in the database |
| `width`   | `int64`   | Knitting width, inches (`Greige.width`) |
| `rack_wt` | `float64` | Pounds per 100 racks (`Greige.rack_wt`) |
| `gauge`   | `int64`   | Needles per inch (`Greige.gauge`) |
| `beams`   | `int64`   | Number of beams |

and for each bar `i` in 1–4:

| Column          | dtype     | Null read as | Description |
|-----------------|-----------|--------------|-------------|
| `bar{i}_ends`   | `int64`   | `0`          | Ends on this bar; `0` means the bar is unused |
| `bar{i}_merge`  | `string`  |              | Yarn item (merge) code |
| `bar{i}_vendor` | `string`  |              | Yarn producer name |
| `bar{i}_denier` | `int64`   | `0`          | Yarn denier; the source column may be text, so values pass through `int` |
| `bar{i}_luster` | `string`  |              | Yarn luster code (`SD`, `SDBK`, `RGB`, …) |
| `bar{i}_desc`   | `string`  |              | Yarn type description (`POLY`, `TEXT POLY`, …) |
| `bar{i}_pct`    | `float64` | `0.0`        | Percent of the style's weight from this bar |
| `bar{i}_rl`     | `float64` | `0.0`        | Runner length |
| `bar{i}_stitch` | `string`  |              | Stitch notation |
| `bar{i}_thread` | `string`  |              | Threading pattern name |

**Notes for the product builder** (observed in the 2026-10-29 extract):

- `variant` is not unique: seven names appear twice as exactly duplicated
  rows. The table therefore has no index; the builder should drop
  duplicate rows before treating `variant` as a key.
- A few bars have ends but no yarn item (7 on bar 1, 6 on bar 2); these
  come through with `0` denier and null merge.
- All 34 representative variants in the master style map are present.

### `catalog.masterstyles`

**Source.** `greige-master-styles.json` in the plan inputs folder (config
key `inputs`): a list of objects, one per master style, with keys `master`
and `variant`. `MASTER_STYLES_FILE` is the `JSONFile`; `MASTER_STYLES` the
`Table`; `MASTER_STYLE_LOADER` the `JSONTableLoader`.

**Columns** (`MASTER_STYLES`).

| Column    | dtype    | Description |
|-----------|----------|-------------|
| `master`  | `string` | Master style name (`Greige.id`); the index |
| `variant` | `string` | The representative variant for this master |

A `safety_tgt` key, if present in the file, is not listed and so is
dropped; it belongs to demand and inventory planning and will get its own
table when that is designed.

### `catalog.demand`

**Source.** The `Fab shortage` tab of `pa_dmnd_<YYYYMMDD>.xlsx`, a dated
view of finished fabric demand for the next eight weeks, saved to the
`Shawmut Projects/Scheduling` folder (config key `scheduling`). The file is
dated in its name, so `PA_DEMAND_LOADER.load(cfg)` reads today's file and
`load(cfg, dt)` a specific day's. `PA_DEMAND_FILE` is the `ExcelFile`;
`PA_DEMAND` the `Table`; `PA_DEMAND_LOADER` the `ExcelTableLoader`.

Besides being the demand input for planning, this view settles which ply 1
part number is in use when the Xref sheet carries more than one part for an
item code: a part that appears here is the live one.

**Columns** (`PA_DEMAND`). Indexed by `part_no`, which is unique in the
file.

| Column     | Source column        | dtype     | Description |
|------------|----------------------|-----------|-------------|
| `part_no`  | `Ply1 Item`          | `string`  | Index. Ply 1 part number; joins to `FABRICS` |
| `item`     | `PA Item`            | `string`  | Finished fabric item code; agrees with `FABRICS.item` on every shared part |
| `bill_to`  | `Bill To`            | `int64`   | Customer bill-to number |
| `plant`    | `Plant`              | `string`  | Lamination plant code; may list two, as in `12/50` |
| `ship_day` | `Ship Day`           | `int64`   | Ship day of the week |
| `past_due` | `FAB req'd past due` | `float64` | Fabric required that is already past due |
| `wk0` … `wk8` | `FAB req'd WK0` … `FAB req'd WK8` | `float64` | Fabric required in each of the next nine weeks, week 0 being the current one |

The quantity columns read blanks as `0.0` and are in yards, the unit for
finished fabric (greige fabric is measured in pounds).

**Notes for the product builder** (observed in the 2026-11-06 file):

- 105 parts, 100 of them in the Xref sheet. The other five, `FO000001`
  to `FO000005` at plant `1350`, are placeholder part numbers for
  "fabric-only" demand: sales orders that reach the finishing plant from
  customers outside the lamination plants. They carry a real item code
  and are treated like any other row.
- 16 parts are listed with zero demand across every week.
- Of the 19 item codes duplicated in Xref, 12 have exactly one part here
  and 7 have none.

### `catalog.machines`

**Source.** `knit-machine-master.json` in the plan inputs folder (config
key `inputs`): a JSON object keyed by knitting machine id, each value an
object with the machine's `gauge`, `width`, `is_new`, `rpm`, and `attrs`.
It describes every knitting machine and is used to decide which greige
styles can run on which machines, by rules to be detailed in the
product-building design. `KNIT_MACHINES_FILE` is the `JSONFile` (read
with `orient='index'`); `KNIT_MACHINES` the `Table`; `KNIT_MACHINE_LOADER`
the `JSONTableLoader`.

**Columns** (`KNIT_MACHINES`). Indexed by `machine`.

| Column    | Source key | dtype    | Description |
|-----------|------------|----------|-------------|
| `machine` | (object key) | `string` | Index. Machine id, e.g. `B4`, `K10`, `N1` |
| `gauge`   | `gauge`    | `int64`  | Needles per inch: 28, 32, or 36 |
| `width`   | `width`    | `int64`  | Knitting width, inches: 168, 186, or 210 |
| `is_new`  | `is_new`   | `bool`   | Whether the machine is one of the new (faster) machines |
| `rpm`     | `rpm`      | `int64`  | Rated speed, revolutions per minute: 900, 1800, or 2200 |
| `attrs`   | `attrs`    | `object` | Tuple of attribute flags; only `"tall"` occurs so far |

**`NEW_MACHINES_ONLY`.** The master style names that may run only on
machines with `is_new` set; currently just `AU7992T2A`. It lives here, next
to the machine table, so the restriction is visible as data rather than
hidden in builder code. See "Which machines a style can run on" under
"Building products" for how it is applied.

**Notes** (observed in the 2026-11-06 file): 49 machines. All new
machines are 28 gauge at 186 or 210 inches; the 32 and 36 gauge machines
are all old 168-inch machines.

## `products`

### Entry points

`load_products(cfg, conn=None, dt=None)` is the one-call entry point. It
opens nothing itself beyond what the catalog loaders need: `cfg` is the
config dict, `conn` an open database connection for the variants query,
and `dt` the date of the demand view (today when `None`). When `conn` is
`None` the variants come from the TSV extract (`VARIANT_TSV_LOADER`)
instead of the database. It loads, in order, the variants, master styles,
greige styles, machines, cross-reference fabrics, and demand view, then
calls the four builders in dependency order and returns a `Products`.

The builders are the separate entry points. Each is a pure function of
its frame and dict arguments, so a caller that already has the frames (or
wants only one kind of product) can call it directly, and the tests can
drive it from small hand-made frames. The dependency order is: merges →
greiges (needs merges) → dye formulas → fabrics (needs greiges and
formulas).

### Warnings

Every rule below that says a row or item is *skipped* means: it does not
appear in the result, and a warning naming the item and the reason is
emitted on the `swmtplanner.io.products` logger. Builders never raise on
bad data; they raise only on structural problems such as a missing column,
which the loaders already turn into `KeyError`.

### Yarns and merges (`build_merges`)

A merge is a vendor's yarn item. The variants table carries, for each bar
with ends, the item's merge code, vendor, denier, luster, and description.
`build_merges` collects the distinct merge codes across every bar of every
variant row (a merge code appears with the same yarn columns on every row,
since they are joined from the yarn item table, so the first occurrence is
used), parses each into a `Yarn`, and returns `Merge(id=merge code,
yarn=..., vendor=...)` keyed by merge code. A merge whose yarn cannot be
parsed is skipped.

A `Yarn` is parsed from the `denier`, `luster`, and `desc` columns as
follows.

- **Denier.** Deniers of 70 and 75 are both treated as 75; all other deniers
  are kept as-is.
- **Color** is determined only by the `luster` column. The description
  column sometimes contains what looks like a color and must be ignored. For
  white yarn the luster is some version of dull, dim, semidull, or semidim
  (also abbreviated `D`, `SD`, etc.). For non-white yarn the luster also
  contains a color abbreviation. Anything without a color abbreviation is
  `"white"`. Recognized abbreviations (case-insensitive substrings, checked
  in the order listed, so e.g. `GYBK` is black):

  | Color            | Abbreviations              | Example lusters                        |
  |------------------|----------------------------|----------------------------------------|
  | `"greenerblack"` | `RGB` (the whole luster)   | `RGB`                                  |
  | `"black"`        | `BK`, `BLK`                | `SDBK`, `BLK`, `DBK`, `BKSD`, `OBBK`   |
  | `"grey"`         | `GY`, `GRY`, `GRAY`        | `SDGY`, `GRY`, `GRAY`, `DGY`, `BRGY`   |

- **Luster** is also determined by the `luster` column, from whatever
  remains once the color abbreviation is accounted for. Semi-dull is checked
  before dull, since every semi-dull marker contains a dull marker.
  (Case-insensitive; the exact markers below are a first proposal and should
  be checked against the data when the parser is implemented.)

  | Luster       | Markers                                | Example lusters                 |
  |--------------|----------------------------------------|---------------------------------|
  | `"semidull"` | `SD`, `SDIM`, `SEMIDULL`, `SEMI DULL`, `RGB` | `SD`, `SDIM`, `SDBK`, `SDGY`, `RGB` |
  | `"dull"`     | `DULL`, `D`, `DIM`, `OD`, `OBD`        | `DULL`, `DBK`, `DGY`, `OD`, `OBD` |
  | `"bright"`   | `BRT`, `BR`, `B`                       | `BRT`, `BRGY`, `BR`, `B`        |
  | `"clear"`    | `CLR`, `CL`                            | `CLR`, `CL`, `CLBK`, `CLBT`     |

  `RGB` ("Recycled Greener-Black") is a special case: it is a semi-dull,
  greener-black yarn, but the database luster column says only `RGB`, so
  the parser maps it to color `"greenerblack"` and luster `"semidull"`
  explicitly.

  A luster that matches none of these (e.g. `SB`, `MD`, `OBRO`) or that
  is a mixed form (e.g. `SD/D`, `D/B`, `B/SD`) has no recognized luster. As
  with materials, the parser must not guess: the merge is skipped.

  Mixed lusters always appear on bars whose merge is also two codes joined
  by `/` (e.g. the `4031` and `SR5572` families). Styles with this sort of
  configuration have not been run in a long time, and as of the 2026-10-29
  extract none of the 33 such variants is, or shares a base name with, a
  master style, so they are deliberately ignored.

- **Material** is determined by the `desc` column, by the first matching
  marker below. Markers are matched case-insensitively against the
  whitespace-separated tokens of the description, so that `POLY` does not
  match `POLYPRO` and a trailing `P` token is recognized as polyester.

  | Material      | Markers (tokens)             | Example descriptions                       |
  |---------------|------------------------------|--------------------------------------------|
  | `"nylon"`     | starts with `NYL`            | `NYLON`, `TYPE 6 NYL`, `NYL TRI 6.6`, `NYLON/POLY` |
  | `"lycra"`     | `LYCRA`                      | `LYCRA`, `LYCRA T162B`                     |
  | `"spandex"`   | `SPANDEX`                    | `SPANDEX`                                  |
  | `"acetate"`   | `ACETATE`                    | `ACETATE`                                  |
  | `"eptfe"`     | `EPTFE`                      | `EPTFE`, `TWIST EPTFE`                     |
  | `"polyester"` | `POLY`, `POLYESTER`, `P`     | `POLY`, `POLYESTER`, `TEXT POLY`, `RECYCLE TX P`, `LOW MELT P` |

  A description matching none of these (e.g. `POLYPRO`, `PTFE`,
  `FIBERGLASS`, `ELASTANE`, `DO NOT USE`, `POLY/NYL`) has no recognized
  material. The parser must not guess: the merge is skipped.

- **Attributes** are parsed from the `desc` column's whitespace-separated
  tokens (case-insensitive):

  | Attribute  | Markers                                 | Example descriptions                  |
  |------------|-----------------------------------------|---------------------------------------|
  | `textured` | `TEXT`, `TEX`, `TX`                     | `TEXT POLY`, `STR TEX POLY`, `RECYCLE TX P` |
  | `cationic` | `CAT`                                   | `CAT POLY`, `CAT TX POLY`             |
  | `recycled` | `REPREVE`, `REPR`, `RECYCLE`, `RECYCLED` | `REPREVE POLY`, `RECYCLED P`, `FR REPR TX P` |

  `BIO-MEG` and `SORBTEK` descriptions are left unmarked for now.

### Greige styles (`build_greiges`)

One `Greige` is built per row of the master style map, from that
master's representative variant. The variants frame is first stripped of
exactly duplicated rows (see `catalog.variants`) and indexed by variant.
A master whose representative variant is not in the frame is skipped.

For the representative row, the bars with `ends > 0` are the style's
bars. Each must have a merge code that is a key of `merges` (so its yarn
parsed) and a recognized threading; otherwise the style is skipped.

**Threading.** Grouping uses the `thread` column. The builder recognizes
exactly two forms, after upper-casing and trimming the value:

| Form                                    | Meaning                                              |
|-----------------------------------------|------------------------------------------------------|
| `SOLID`                                 | The bar feeds every needle in its row; it is its own group |
| `N IN, M OUT` or `N OUT, M IN`          | Partial (split-lease) threading; the bar is grouped with the other partial bars that share its yarn and end count |

The partial form is matched as two integer-plus-keyword segments in either
order, with the comma optional and whitespace flexible, so `1 IN, 1 OUT`,
`1 in,1 out`, and `1 OUT 1 IN` all match. Nothing else is accommodated:
multi-segment patterns (`1 OUT, 1 IN, 1 OUT`), doubled threadings
(`1 IN (DOUBLED), 1 OUT`), two-yarn patterns (`4 BRIGHT, 4 DULL`),
positional instructions (`495 THREAD TO THE CENTER OF BEAM`), free text
(`SEE BELOW`), and typos (`yOLID`) are all unrecognized. Typos are to be
fixed in the source system rather than tolerated here.

**Bar groups.** The reasoning behind the grouping is in "How bars are
grouped into `BeamConfig`s" in `core/products/DESIGN.md`. The builder
applies it as: every `SOLID` bar is a group by itself; the partial bars
are grouped by (yarn id, end count). A partial bar that ends up alone in
its group is kept as a one-bar group, with a warning, since it still
consumes a beam set. Groups are ordered by their lowest bar number.

For each group, the per-bar `BeamSetDesc(yarn, beam_count=beams,
end_count=ends)` descriptions are merged with `BeamSetDesc.merge` into the
group's combined description, and each bar becomes
`BarConfig(num, runlen=rl, pct, stitch)`. The group is a
`BeamConfig(beamset=combined, bars=...)`.

The `Greige` is then `Greige(id=master, gauge, width, rack_wt, std_wt,
beam_cfgs, rates)` with `rates` built as described next. `std_wt` is the
`std_wt` of the `greige_styles` row whose `alias` is the master's own
name; a master with no such row is skipped.

### Which machines a style can run on

A `Greige` can run on a machine if and only if it has a rate for it, so
the builder decides eligibility while assembling the `rates` map passed to
`Greige`. A machine from `KNIT_MACHINES` is eligible for a master style
when every one of these holds:

1. **Gauge matches.** The machine's `gauge` equals the style's `gauge`.
2. **Machine is wide enough.** The machine's `width` is at least the
   style's `width`.
3. **Solid bar on top needs a tall machine.** For a three-bar style whose
   bars are two split-lease bars (partial threading, grouped into one
   `BeamConfig`) and one `SOLID` bar, if the solid bar is the top bar
   (bars are numbered from the bottom up, so the top bar is the highest
   numbered one with ends), the machine must have `"tall"` in `attrs`.
   A solid bar at the bottom carries no restriction.
4. **New-machine-only styles.** If the style's name is in
   `NEW_MACHINES_ONLY`, the machine must have `is_new` set.

A style that no machine can run on is still built; it simply has an empty
`rates` map.

On the 2026-10-29 representatives, 28 of the 34 master styles are
solid-bottom three-bar styles (`SOLID`, partial, partial), one
(`AU1148G36`) is a two-bar all-solid style, and five are solid-top and
so tall-only: `AU5429D`, `AU5429H`, `AU7529`, `AU7805`, `AU8111A`.

### Rate of a style on a machine

The rate stored for each eligible machine is pounds per hour at 100%
efficiency. A machine runs at its `rpm` revolutions per minute, one rack
is 480 revolutions, and a style's `rack_wt` is pounds per 100 racks, so

```
racks per hour = rpm * 60 / 480
rate (lb/hr)   = racks per hour * rack_wt / 100
               = rpm * rack_wt / 800
```

For example, a style with a rack weight of 30.19 lb per 100 racks runs at
33.96 lb/hr on a 900 rpm machine and 83.02 lb/hr on a 2200 rpm machine.
The `rates` map passed to `Greige` is therefore
`{machine: rpm * rack_wt / 800}` over the eligible machines.

### Dye formulas (`build_dye_formulas`)

From the active rows of the cross-reference (`active` true, non-empty
`item`), one `DyeFormula` is built per distinct `formula` number:
`DyeFormula(id=formula, name=color, shade=SHADE_RATINGS[shade])`, taking
`color` and `shade` from the first row (in sheet order) carrying that
number with a non-null shade rating. Where later rows carry a different
name, the first is used silently, since the differences are spellings.
Where later rows carry a different shade rating a warning is emitted
naming the formula and the ratings, since that is a data conflict to
resolve in the workbook. A formula number with no rated row is skipped.

### Fabrics (`build_fabrics`)

From the same active, non-empty rows, one `Fabric` is built per distinct
`item` code. The rows sharing an item code are collapsed as follows:

1. **Live row.** If exactly one row carries the code, it is the live row.
   Otherwise, if exactly one of the rows' part numbers appears in the
   demand view, that row is live. Otherwise the last row in sheet order
   is live (parts are appended to the sheet as they are created, so the
   last is the newest).
2. **Jets.** The union of the jet flags across all rows with the code:
   `jets` is the tuple of `"1"` … `"10"` for every `jet<i>` true on any
   of them. This implements "the larger set is correct" and also covers
   the case where neither set contains the other.
3. **Greige style.** The live row's `greige`, which the loader has
   already converted to the master name, must be a key of `greiges`. If
   it is not (the name had no alias, the style is made at another plant,
   or the master was not built), the fabric is skipped.
4. **Formula.** The live row's `formula` must be a key of `formulas`;
   otherwise the fabric is skipped.
5. **Remaining fields.** `master_style` is the live row's `style`,
   `width` its `width`, and `yld` its `yld`. A missing yield skips the
   fabric.

The result is `Fabric(id=item, greige_style=greiges[master],
master_style=style, color=formulas[formula], width, yld, jets)`.

Jet ids are the bare numbers from the column headings (`"1"` to `"10"`),
to be reconciled with the dye-house machine ids when those are designed.
