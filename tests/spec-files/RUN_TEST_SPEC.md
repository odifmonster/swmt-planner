# Specification of coverage of `run.py` CLI-helper tests

Covers the CLI helpers added for verbose-mode SQL Server persistence: the
`database`-block override resolution and the interactive `vi` notes flow. The
full `run()` invocation (which needs a complete input bundle) is exercised by
manual CLI runs; `_persist_debuglog` is covered by `dashboard_tests.py`'s
SQL Server-gated wiring tests.

## 1. `_resolve_db_block`

1. **Inline override** — a `--db-conn` value starting with `{`/`[` is parsed as
   inline JSON.
2. **Path override** — otherwise it is read as a path to a JSON file and parsed.
3. **Fallback** — with no override, returns the config's `database` value (a
   dict, or `None` when absent).

## 2. `_next_temp_path`

Returns `temp.txt`, or the first `tempN.txt` (N = 1, 2, …) that does not already
exist in the current directory (verified by creating each candidate and
re-asking).

## 3. `_gather_notes` (vi mocked)

`subprocess.Popen` is patched with a stand-in that writes known content to the
target file (simulating the user editing + saving), so the editor is never
actually launched.

1. **Returns contents, cleans up** — non-whitespace content is returned
   verbatim (incl. multi-line); the temp file is deleted afterward.
2. **Empty/whitespace-only aborts** — content that strips to empty raises
   `typer.Exit`; the temp file is still deleted.
3. **`vi` not found aborts** — a `FileNotFoundError` from `Popen` raises
   `typer.Exit`; the temp file is still deleted.

(The `--label`-required-in-verbose guard in `run()` is a one-line precondition
verified by inspection; testing it would require a full `run()` invocation.)


## 4. `_parse_duration` / `_parse_state_block`

The config's `state` block spells durations as hours or unit strings (see
"Run-config JSON" in the planner design).

1. **Numbers are hours** — `24` and `1.5` give 24 h and 1 h 30 min.
2. **Unit strings** — `"48h"`, `"3d"`, `"2w"`, `"90m"` give 48 h, 3 days,
   14 days, 1 h 30 min; whitespace and case are ignored (`" 2 D "`).
3. **Clock form** — `"36:30"` gives 36 h 30 min.
4. **Negative** — `"-2w"` and `-14` give negative durations.
5. **Already a timedelta** passes through unchanged.
6. **Rejects** — `"soon"`, `""`, `True` raise `typer.BadParameter` naming
   the field.
7. **`_parse_state_block`** converts exactly the three duration fields
   (`window_advance_amount`, `carrying_avoidance_margin`,
   `planning_horizon_buffer`), leaves integer fields untouched, and does
   not mutate its input.

## 5. `blacklisted_on_machines`

1. **Lines** — one line per blacklisted set found at a machine, in machine
   order: a set mounted on a bar (`mounted set … is blacklisted: the first
   plan tapes it out`) or queued at one (`queued set … passed over at the
   hang`), naming the machine, bar, set number and merge.
2. **Nothing** — machines with no blacklisted set give an empty list.
