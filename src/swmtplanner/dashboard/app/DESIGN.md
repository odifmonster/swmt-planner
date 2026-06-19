# Dashboard GUI (PyQt6) — Design

The PyQt6 front-end for the dashboard, under `swmtplanner/dashboard/app/`. It is
the **view layer** on top of the `sqlload` data layer (`Table` / `Row` / `Query`)
— it issues no SQL of its own, only drives a `Table`. It owns all GUI: the
generic raw grids and (later) the planner-specific "pretty" view. A per-planner
entry point (`knit-debug`) supplies the planner's manifest and a reader
connection.

Built in fine-grained phases (these refine the coarse phasing in
`../DESIGN.md`). This document specifies **Phase 1** and sketches the rest.

## Phase 1 — a paged raw grid (committed_sched, run 1, no filters)

**Goal:** a runnable app that connects as the reader, builds a `Table` over
`committed_sched` for `run_id = 1`, and displays one page of 20 rows with
forward / back paging. No run selection (run 1 is hard-coded), no filtering, no
FK navigation. It proves the whole read stack end-to-end against the real
database (`swmtinfinite`, where run 1 exists).

### Prerequisite — a `TableSpec` for the view ✅ done

`committed_sched` is a **DB view** (the committed-move slice of
`sched_cost_detail`), not a writable manifest table, so `Table`/`Query` (which are
spec-driven) need a `TableSpec`. The planner's manifest now exposes both views in
a **`VIEWS`** tuple — resolvable via `spec_for_name`, but kept out of the
writable `TABLES`/`ALL_TABLES` so the writer never touches them:

- `committed_sched` — columns `activity_id`, `machine`, `start`, `end`, `desc`
  (a **subset** of `sched_cost_detail` — `move_id`/`weight`/`cost` are dropped by
  the view), **key-less** (`pk=()`), `order_by=('machine', 'start', 'activity_id')`
  (mirrors the view's `ORDER BY machine, start` with the unique `activity_id`
  appended for a stable total order).
- `committed_prod` — `knit_id`, `roll_id`, `job_id`, `item`, `start`, `end`,
  `lbs`; key-less; `order_by=('item', 'knit_id')`.

Phase 1 uses only `committed_sched`. Neither view carries FK columns (the
`move_id` join column is dropped), so no drill-down from them for now.

### Components

**`PageModel(QAbstractTableModel)`** — a thin adapter exposing the current page's
rows to a `QTableView`.

- Constructed with the **column names** (the `Table`'s display columns, i.e.
  `schema.column_names` minus `run_id`) and the current `list[Row]`.
- `rowCount` → number of current rows; `columnCount` → number of columns.
- `data(index, DisplayRole)` → the cell value as text (`row.data[col]`, with
  `None` shown as an empty string).
- `headerData(section, Horizontal, DisplayRole)` → the column name (the
  **top row** of names); vertical header → the absolute row number (optional,
  from `displayed_range`).
- `set_rows(rows)` → replace the held rows inside `beginResetModel()` /
  `endResetModel()`.

**`RawGridWindow(QWidget)`** — the main window. **Stores the `Table` and the
current page's rows**, and turns button presses into paging.

- Layout, top to bottom (`QVBoxLayout`):
  1. **Top bar** (`QHBoxLayout`): a stretch, then a **Back** and a **Forward**
     button — so they sit in the **top-right**. `QToolButton`s captioned with
     arrows (`◀` / `▶`).
  2. **`QTableView`** bound to the `PageModel`. Its horizontal header is the
     column-name row; read-only (no edit triggers), whole-row selection off for
     now.
- Construction: `Table.set_page_size(20)`, then load page 1 via
  `table.next_page()` into the model.
- **Back** → `table.prev_page()`; **Forward** → `table.next_page()`. Each stores
  the returned rows, calls `model.set_rows(...)`, and refreshes button state.
- **Fixed geometry:** 20 rows per page; the **window height is fixed** (sized for
  20 data rows + the header + the top bar). Width may stay resizable.
- **Button state (polish):** disable Back on the first page and Forward on the
  last, derived from `table.displayed_range` vs `table.nrows`. (Paging already
  clamps, so this is cosmetic.)

**Entry point — `main()` / `knit-debug`.**

1. Create the `QApplication`.
2. Resolve the reader connection: `config.read_reader_config()` →
   `ConnConfig`; open a PyMySQL connection (reader) and a cursor.
3. `table = Table(spec_for_name('committed_sched'), cursor, run_id=1)` (the
   knit planner's manifest supplies the view spec).
4. `window = RawGridWindow(table); window.show(); app.exec()`.
5. Close the connection on exit.

Wired as the `knit-debug` console script (a knit-specific launcher in the
dashboard, since it names the knit planner's manifest + view).

### Rendering details (filled in; flexible)

- `QTableView` with `setEditTriggers(NoEditTriggers)`; header from the model.
- Column sizing: stretch the last section / resize-to-contents — cosmetic.
- Arrows: Unicode `◀`/`▶` on `QToolButton` (or `QStyle` standard arrows).
- An optional `rows X–Y of N` label in the top bar (from `displayed_range` /
  `nrows`) — nice for orientation, not required.

### Out of scope for Phase 1

Run selection / Home (run 1 is hard-coded); filtering; FK/PK navigation; the
committed-only toggle (we're already on `committed_sched`); changing the page
size; the pretty view.

### Notes / caveats

- `Table.__init__` builds the `Query`, which runs a `COUNT(*)` plus per-column
  distinct queries at construction. For run 1's `committed_sched` that's cheap;
  it's a one-time cost even though Phase 1 doesn't use `unique()` yet.
- The reader connection lives for the app's lifetime (one cursor, used
  sequentially by the `Table`); closed on exit.

### Testing

Per project convention the Qt layer is **verified by running the app** (against
real `swmtinfinite`, run 1), not by unit tests — the `Table`/`Query`/`Row` stack
underneath is already covered (`DASHBOARD_TEST_SPEC.md`).

### Dependencies

`PyQt6` (already in `requirements.txt`; mirror into `pyproject.toml`, ideally an
optional extra so headless installs skip it). `pymysql` is already present.

## Phase 2 — app shell, sidebar nav, run selection

**Goal:** a real application shell. A left **sidebar** navigates between
**Run selection**, **Raw view** (with a sub-item per viewable table), and
**Pretty view** (placeholder). Run selection drives a chosen `run_id`; the raw
view then lets you pick any table and page through it (run-scoped). Still **no
links or filters**. A lighter, more colorful theme replaces the bare default.

### Module layout

The Phase-1 standalone `RawGridWindow` is refactored into an embeddable widget;
the launcher now opens the shell rather than a single grid.

The Phase-1 standalone `RawGridWindow` is refactored into an embeddable widget;
the launcher now opens the shell rather than a single grid. Table rendering and
the (Phase-3) filter UI each live in their own sub-package:

- **`grid/`** — table rendering: `grid/model.py` (`PageModel`) and `grid/grid.py`
  (**`PagedGrid(QWidget)`** — the reusable `QTableView` + paging buttons + a
  `show_table(table)` method that (re)binds a `Table` and resets to page 1). The
  package re-exports both (`ROWS_PER_PAGE` too). (Replaces `RawGridWindow`.)
- **`filters/`** — the per-column filter UI (Phase 3): `filters/header.py`
  (`FilterHeader`), `filters/popup.py` (`FilterPopup`), `filters/bodies.py` (the
  per-kind body widgets). Re-exports `FilterHeader` / `FilterPopup`.
- **`formatting.py`** — `format_cell` (shared by `grid` and `filters`; a leaf, so
  `grid` can depend on `filters` without a cycle).
- **`run_select.py`** — `RunSelectionPage(QWidget)` + `RunButton(QToolButton)` +
  a `list_runs(cursor, runs_spec)` helper.
- **`pages.py`** — `RawViewPage(QWidget)` (header + `PagedGrid`) and
  `PrettyViewPage(QWidget)` (placeholder).
- **`window.py`** — `DashboardWindow(QWidget)`: the shell (sidebar + header +
  stacked content), owns `selected_run_id` and the reader cursor.
- **`theme.py`** — `apply_theme(app)`: the app-wide palette / stylesheet.
- **`knit_debug.py`** — `main()` now builds and shows `DashboardWindow` with the
  knit planner's specs.

### The shell — `DashboardWindow`

Constructed with the reader **`cursor`**, the ordered **viewable specs**
(`table_specs` — for the knit planner, `manifest.TABLES + manifest.VIEWS`; the
`runs` registry is excluded since it isn't run-scoped), and the **`runs_spec`**
(the registry, for the run page). Layout:

- **Left — sidebar** (`QTreeWidget`, no header): three top-level rows —
  **Run selection** (leaf), **Raw view** (expandable; one child per spec in
  `table_specs`, by `name`), **Pretty view** (leaf).
- **Right — content**: a `QVBoxLayout` of a **header label** (large, bold) over a
  `QStackedWidget` holding the three pages plus a shared **"no run" placeholder**
  reading *"Please select a run to investigate."*

State: `selected_run_id` starts `None`.

Navigation (on sidebar selection):
- **Run selection** → show `RunSelectionPage`; header `"Run selection"`.
- **Raw view ▸ \<table\>** → if no run selected, show the placeholder; else
  `RawViewPage.show_table(spec, run_id)` and header = the table name. (Clicking
  the **Raw view** parent just expands/collapses it.)
- **Pretty view** → if no run selected, the placeholder; else `PrettyViewPage`
  (its own *"Pretty view — not yet implemented"* message). Header `"Pretty view"`.

When the user picks a run on the run page, `selected_run_id` is set (and the
button highlighted); subsequent navigation to raw/pretty uses it. Run selection
is always available regardless of `selected_run_id`.

### Run selection page — `RunSelectionPage`

Lists every run from the registry, most recent first:
`list_runs(cursor, runs_spec)` runs a direct `SELECT run_id, created_at,
start_date, total_score FROM runs ORDER BY run_id DESC` (the registry is **not**
run-scoped, so it bypasses `Table`/`Query`). Each run renders as a **large
rounded-rectangle button** (`RunButton`) in a vertical, scrollable list. Button
text: **`Run N`** in bold, then the **date run** (`created_at`), the **start
date** (`start_date`), and the **total score** — laid out on following lines.
Datetimes use the Phase-1 `m/d/yy h:mm` formatting.

- Clicking a run sets `DashboardWindow.selected_run_id` and **highlights** that
  button — a **more saturated background color + a bold outline** — while the
  others return to the resting card style (single-selection within the list).
- The currently selected run stays highlighted when you revisit the page.

### Raw view page — `RawViewPage`

A header is owned by the shell (shows the table name, set **before** the grid
loads so it appears immediately). The page caches one `PagedGrid` per table for
the current run, in an internal `QStackedWidget` alongside a **"Loading…"**
placeholder:

- `show_table(spec, run_id)`: if the run changed since last time, the cache is
  cleared (the cached `Table`s are run-scoped). If the table is **already
  cached**, switch to it instantly — its paging (and, later, filter / selection)
  **state is preserved**. Otherwise show the **"Loading…"** placeholder and force
  a **synchronous repaint of the window** (so the new header + placeholder paint
  before the blocking build), then build `Table(spec, cursor, run_id)` + a
  `PagedGrid`, cache it, and switch to it. (With `unique` now lazy, the build
  itself is cheap — one `COUNT(*)` plus the first page — so "Loading…" mostly
  matters for very large runs.)

So switching tables never leaves the *previous* table on screen — you see the new
name and a brief "Loading…" instead — and navigating away and back restores a
table where you left it. This caching is the groundwork for FK navigation + a
back button (Phase 3), which will extend the keying beyond the table name to the
navigation context. (Building a `Table` is synchronous on the GUI thread; if the
one-time per-table load ever feels too slow, a worker thread is the next step.)
Still read-only, no filters, no FK navigation.

### Pretty view page — `PrettyViewPage`

A placeholder widget reading *"Pretty view — not yet implemented."* (Designed in
a later phase.)

### Theme — `theme.py`

A **light, colorful, friendly** palette applied app-wide (a Qt stylesheet on the
`QApplication`), for contrast and approachability. Starting palette (tunable):

- Window background `#f4f7fb`; content/cards `#ffffff`; text `#1f2933`.
- Accent `#2f6df0` (friendly blue); accent-dark `#1b4fd0` for outlines/selection.
- **Sidebar**: background `#eef2f8`; hover/selection span the **whole row**
  (`show-decoration-selected: 1`, flat — no per-item radius), the selected row in
  accent background with white text. (Avoids the branch-column-vs-item highlight
  gap.)
- **Run buttons**: resting = soft tint `#eaf0fe` with a `#c9d9fb` 1px border,
  ~10px corner radius; hover slightly darker; **selected** = accent `#2f6df0`
  background, white text, **2px accent-dark outline** (the saturated + bold-outline
  highlight).
- **Grid**: header row `#dfe8f5` (bold); alternating rows `#ffffff` / `#eef3fb`
  (replaces Phase 1's theme-default alternation, for stronger contrast).
- Headers/labels use a slightly larger, bold font.

Backgrounds are **soft off-white / grey** rather than pure white, with rounded
cards (run buttons, the filter popup) and a **blue `#5192a5` hover** on menu items
(combo-dropdown entries, the filter checkbox list). Exact values are easy to
adjust; this section pins a concrete starting point.

### `knit_debug.main()` (updated)

Resolve the reader connection (as Phase 1), then
`DashboardWindow(cursor, table_specs=manifest.TABLES + manifest.VIEWS,
runs_spec=manifest.RUNS)`; `apply_theme(app)`; show. No hard-coded run or table
anymore — selection is interactive.

### Out of scope for Phase 2

Per-column filters (Phase 3); FK/PK navigation + back button (Phase 4); the
pretty view (Phase 5); annotating/deleting runs (writes); changing the page size.

### Testing

Verified by running the app (per convention). The underlying `Table`/`Query`/`Row`
and `list_runs`' SQL are simple; the new code is GUI wiring.

## Phase 3 — per-column filters

**Goal:** each grid column gets a **filter button** in its header; clicking opens
a **popup** to build one `Filter`; applying it calls `Table.apply_filter_to`,
reloads the grid (back to page 1), and the button turns into an **✕** that clears
the filter. Still **no FK links** (Phase 4).

### Data-layer touch

The popup needs a column's distinct values, so add a passthrough
**`Table.unique(colname)`** → the current `Query.unique(colname)` (lazy + cached
as today; reflects the table's current constraints). Generic, in
`sqlload/table.py`; unit-tested alongside the other `Table` MySQL-gated tests.

### `FilterHeader(QHeaderView)`

A custom horizontal header for the grid's `QTableView`. Each section paints the
column name plus a small **filter button** — a rounded-rect with a **▾** when the
column has no active filter, an **✕ in accent orange (`#ff791f`)** when it does.
Mouse clicks in the button's rect emit `filter_requested(col)` (▾) or
`filter_cleared(col)` (✕); a click elsewhere behaves like a normal header click.
The header tracks which columns are filtered (to choose the glyph) — set by the
grid when a filter is applied/cleared. `sectionSizeFromContents` reserves the
button's width so it never overlaps the name.

### `FilterPopup(QWidget, Qt.WindowType.Popup)`

The "menu box", opened beneath the clicked section for one column (given its name,
`ColumnType`, an `unique()` getter, and an apply callback). It's a **rounded
off-white card** — a translucent `Qt.Popup` wrapping a `QFrame#filterCard` so the
corners round cleanly. Layout, top to bottom:

- **Kind selector** — a combo box of the kinds available for the column's type.
  It **starts empty** (a blank first item); until a kind is chosen the body reads
  *"Please select a filter method."* and Apply is disabled.
  - **text**: *Selection, Exclusion, Range, Starts with, Ends with, Contains*.
  - **int / float / datetime**: *Selection, Exclusion, Range* (the three pattern
    options are omitted — pattern matching is text-only).
- **Body** — a `QStackedWidget` whose page follows the selected kind (so the
  popup's appearance changes with the kind):
  - **Membership body** (Selection / Exclusion — same UI, different kind):
    calls `unique(col)` when shown. If it returns `None`, the body is a single
    label *"(Selection/exclusion) unavailable: too many values"* and **Apply is
    disabled**. Otherwise: a **search box pinned at the top** (filters the list as
    you type) over a **scrollable list of the distinct values, each with a
    checkbox**. **Apply enabled iff ≥1 value is checked.** Rule = the set of
    checked values; kind = `selection` / `exclusion`.
  - **Range body**: a **lower** and an **upper** row. Each row is a dropdown
    *(No bound / Bound)* plus a value editor that is **disabled when "No bound"**.
    The editor matches the column type — a plain text field (`str`), a
    number-only field (`int` / `float`), or a datetime editor (`datetime`).
    **Apply enabled iff ≥1 bound is set** (both "No bound" → disabled). Rule =
    `(low, high)` with `None` for an unset bound; kind = `range`.
  - **Pattern body** (Starts with / Ends with / Contains — same UI, the chosen
    item fixes the affix): a single text field. **Apply enabled iff non-empty.**
    Rule = a MySQL `LIKE` string built from the entry `v` — `f'{v}%'` (starts),
    `f'%{v}'` (ends), `f'%{v}%'` (contains), with `%`/`_`/`\` in `v` **escaped**
    so the user's text matches literally; kind = `pattern`.
- **"Apply filter" button** — always present at the bottom; enabled per the
  active body's rule above. On click it builds `(kind, rule)`, invokes the apply
  callback, and closes the popup.

The kinds map onto the existing `Filter(kind, rule)` (`helpers.py`): the UI only
ever produces valid rules (Apply is disabled otherwise), so `to_sql_str` never
sees an empty set or doubly-unbounded range.

### `PagedGrid` wiring

`PagedGrid` installs a `FilterHeader` on its view. On `filter_requested(col)` it
opens a `FilterPopup` for that column (passing `table.unique` and the column's
`ColumnType` from the schema) positioned under the section. On **Apply** it calls
`table.apply_filter_to(col, kind, rule)`, reloads page 1 (`Table` already resets
paging + clears selection on rebuild), and tells the header the column is now
filtered (glyph → ✕). On `filter_cleared(col)` it calls `table.remove_filter(col)`,
reloads, and resets the glyph to the ▾. On `show_table` it `resizeColumnsToContents`,
so every column starts wide enough for its full name (the header reserves the
button width). The per-table grid caching from Phase 2 means a table keeps its
applied filters when you navigate away and back (until the run changes).

### Out of scope for Phase 3

FK/PK navigation + the back button (Phase 4); the committed-only toggle; the
pretty view (Phase 5); editing the page size. One filter per column at a time
(re-opening replaces it), matching `Table`'s one-`Filter`-per-column model.

### Testing

Verified by running the app. The new `Table.unique` passthrough is unit-tested;
`Filter` rule construction is already covered (`helpers`). The LIKE-escaping
helper for pattern entries is pure and can be unit-tested.

## Phase 4 — FK / PK navigation + back button

**Goal:** the raw view becomes navigable along the FK graph, in both directions,
with a back button to retrace the route. Two complementary moves:

1. **Forward (FK → PK).** In a table with a foreign-key column, the FK cells are
   rendered as **links** (highlighted, clickable). Clicking one navigates to the
   **referenced table** and applies a **selection `Filter` with that single
   value** on the referenced PK column.
2. **Backward (PK → FK).** In a table with a primary key, you may **select rows**
   (a checkbox column). With ≥1 row selected a **"Go to…"** button appears; it
   opens a menu of the **tables that reference this PK**, and choosing one
   navigates to that table with an **`apply_fk_lookup`** of the selected keys.

A **navigation stack** records the route so a top-left **"‹ Back"** button returns
to the previous view. No new `sqlload` query primitive is needed — forward nav is
an ordinary selection `Filter` (`apply_filter_to`) and backward nav is the
existing `apply_fk_lookup`; the only new *data* artifact is a pure, generic
**reverse-FK map** derived from the manifest. (The earlier handoff floated a
`PKLookup`; it's dropped — a PK lookup is just a selection filter on the PK.)

### Data layer — the reverse-FK map (the only new non-GUI code)

The forward direction reads off each spec's own `fks`. The backward direction
needs the inverse: *given a table, which tables' FK columns point at its PK?* Add
a generic, planner-agnostic helper to **`dashboard/manifest.py`** (it's pure and
derived only from the handed specs):

- `referencing_fks(specs)` → a `dict[str, tuple[tuple[str, str], ...]]` mapping a
  **referenced table name** → the `(source_table, fk_column)` pairs that point at
  it. Built by scanning every spec's `fks` and bucketing by `fk.ref_table`.
  (Views carry no FKs, so they never appear as a source; nothing references a
  view, so they never appear as a key.)

This is pure and unit-testable — covered in `DASHBOARD_TEST_SPEC.md` (a new small
section) and `tests/dashboard_tests.py`. The `manifest.pyi` stub gains the
signature. No change to `helpers.py` / `query.py` / `table.py`.

> **Why these reuse cleanly.** A drill's destination constraint is
> `apply_filter_to(ref_col, 'selection', {value})` — so the destination shows the
> drill as an ordinary active filter on its PK column, clearable with the header
> **✕** like any other (clearing reveals the whole table *in the same frame*).
> A "Go to" applies `apply_fk_lookup(fk_col, keys)`, which `Table` stores in the
> same `_conds` slot — so it is likewise clearable via the FK column's ✕.

### Navigation model — a view stack (replaces the Phase-2 name cache)

Phase 2 cached one `PagedGrid` per **table name**; Phase 2's design noted this was
"groundwork… which will extend the keying beyond the table name to the navigation
context." Phase 4 makes that turn: the raw view is driven by a **stack of
frames**, each a live `(spec, PagedGrid)` bound to its own constrained `Table`.
The top frame is the visible one.

- **Sidebar selection of a table** = a fresh **root**: it resets the stack to a
  single, unconstrained frame for that table. (Trade-off: re-selecting a table
  from the sidebar no longer restores filters from a previous visit — the
  back button, not the sidebar, is now how you retrace. Recommended for
  predictability; the alternative — sidebar selections also push onto a single
  browser-like history — is noted under *Open decisions*.)
- **Forward drill** (FK click) and **backward "Go to"** each **push** a new frame
  (build `Table(dest_spec, …)`, apply the nav constraint, mark that column
  filtered on the new grid's header, set the header label).
- **"‹ Back"** **pops** the top frame and shows the one beneath, restoring it
  exactly (the frame holds the live grid+table, so its page, filters, and row
  selection are intact). Hidden/disabled when the stack has a single frame.
- **Run change** clears the whole stack (frames are run-scoped, as the cache was).

Frames are held (not rebuilt) on the stack, so a deep route stays cheap to
retrace; only a *new* push builds a `Table`.

### Mechanism 1 — FK cells as links (forward drill)

**Rendering.** The grid marks the columns that are FKs (from `spec.fks`). The
`PageModel` renders FK cells as links — **accent-blue, underlined** text
(`ForegroundRole` + `FontRole`) — and the view shows a pointing-hand cursor over
them. **NULL** FK cells are *not* styled or clickable (a null FK references
nothing).

**Click.** `QTableView.clicked(index)` → if the cell's column is an FK and its
**raw** value (the `Row`'s value, not the formatted text) is non-null, the grid
emits `fk_activated(fk_column, value)`. The navigation controller resolves the
target from the spec's `ForeignKey` (`ref_table`, `ref_column`), builds a frame
for `ref_table`, calls `apply_filter_to(ref_column, 'selection', {value})`, marks
`ref_column` filtered, and pushes.

### Mechanism 2 — row selection + "Go to…" (backward lookup)

**Selection UI — a leading checkbox column.** A keyed table's grid gains a
**checkbox column at view-position 0**; the data columns shift right by one.
Checking a box calls `Row.select()` / `Row.deselect()` (the existing
`Table.selected_keys` machinery); the checkbox state of a rendered row reads back
from `Row.selected`, so selection **persists across paging** (plain paging doesn't
rebuild the query) and is **cleared on any filter/lookup rebuild** (existing
`Table` behavior). Key-less tables and the views get **no** checkbox column.

> *Why a checkbox column rather than "click the PK cell to select":*
> `production.knit_id` is **both** the PK **and** an FK, so a click on that cell
> would be ambiguous between "select this row" and "drill to
> `sched_cost_detail`". A separate checkbox column keeps selection and FK-drill on
> distinct affordances. Its cost is a **view-column ↔ data-column offset of 1**
> that the grid, the `FilterHeader` (section 0 has no filter button), and the
> click handler must account for.

**"Go to…" button + menu.** The navigation controller shows a **"Go to…"** button
whenever the current frame's table has a non-empty `selected_keys`. Clicking it
opens a `QMenu` built from the reverse-FK map for the current table: one entry per
`(source_table, fk_column)` that references this PK (labelled by source table
name; the column is appended only if a source references this table via more than
one column — none do today, but the rule is unambiguous). Choosing an entry builds
a frame for `source_table`, calls `apply_fk_lookup(fk_column, selected_keys)`,
marks `fk_column` filtered, and pushes.

### Chrome — where Back and "Go to…" live; header updates

Both navigation controls and the frame stack live in the **`RawViewPage`**, which
becomes the small navigation controller (it already owns the per-table stacked
widget). Its top bar gains, left-to-right: **"‹ Back"** (far left, the requested
top-left position; shown when depth > 1) … a stretch … **"Go to…"** (shown when
the current frame has a selection). The per-frame paging buttons stay in each
`PagedGrid`'s own top-right, as today.

The shell's header label (owned by `DashboardWindow`) must track the current
frame's table across drills and backs: `RawViewPage` emits
`current_table_changed(name)` and the shell updates the header. (`window.py`'s
`_show_raw` still sets the initial header + run before the first frame builds.)

### Component changes (summary)

- **`dashboard/manifest.py`** (+ `.pyi`) — add `referencing_fks(specs)`.
- **`grid/model.py`** — optional leading checkbox column (checkable flags +
  `CheckStateRole` get/set wired to `Row.select`/`deselect`); FK-column link
  styling (`Foreground`/`Font` roles); a raw-value accessor for a cell; signal a
  selection change so the page can toggle "Go to…".
- **`grid/grid.py`** — know its FK columns and PK-ness; install the checkbox
  column for keyed tables (offset bookkeeping in the `FilterHeader`/click paths);
  emit `fk_activated(col, value)`; expose `set_filtered` use for nav-applied
  constraints; surface selection-changed.
- **`pages.py` — `RawViewPage`** becomes the nav controller: holds the frame
  stack + reverse-FK map, the **Back**/**Go to…** chrome, builds frames
  (`apply_filter_to` / `apply_fk_lookup`), and emits `current_table_changed`.
- **`window.py`** — pass the reverse-FK map (or the specs to build it) to
  `RawViewPage`; connect `current_table_changed` to the header.
- **`filters/header.py`** — account for the checkbox column at section 0 (no
  filter button there).

### Open decisions (for review)

1. **Sidebar vs. history.** Recommended: a sidebar table pick is a fresh root
   (clears the drill stack); Back only retraces drills/"Go to"s. Alternative: a
   single browser-style history where sidebar picks also push (Back walks across
   sidebar visits too). The first keeps the sidebar highlight honest and the Back
   semantics simple; I lean toward it.
2. **Selection affordance.** Recommended: a dedicated checkbox column (resolves
   the `knit_id` PK==FK collision cleanly). Alternative: native full-row
   selection synced to `selected_keys` (no extra column, but collides with
   FK-cell clicks). I lean toward the checkbox column.
3. **Back button placement.** In the `RawViewPage` top bar (far left) vs. in the
   shell header row. The former keeps navigation chrome encapsulated with the
   stack it controls; "top-left of the content" reads as top-left to the user.

### Out of scope for Phase 4

The **committed-only toggle** (deferred — it was bundled here in an earlier
handoff but is independent of FK nav); the pretty view (Phase 5); editing the page
size; multi-column selection filters.

### Testing

Per convention the Qt layer is **run-verified** (`knit-debug`): drill an FK cell,
check rows and use "Go to…", retrace with Back, clear a nav filter via the header
✕. The one new pure unit is **`referencing_fks`** (manifest helper) — covered in
`DASHBOARD_TEST_SPEC.md` + `tests/dashboard_tests.py`. `apply_filter_to` /
`apply_fk_lookup` / `Filter` / `FKLookup` are already covered.

## Later phases (sketch — refines `../DESIGN.md`)

5. **The planner-specific pretty view** — the elaborate, non-technical view built
   from custom `QtWidget` subclasses; its layout will be specified here when that
   phase starts.
