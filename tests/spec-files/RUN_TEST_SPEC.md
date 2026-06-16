# Specification of coverage of `run.py` CLI-helper tests

Covers the CLI helpers added for verbose-mode MySQL persistence: the
`database`-block override resolution and the interactive `vi` notes flow. The
full `run()` invocation (which needs a complete input bundle) is exercised by
manual CLI runs; `_persist_debuglog` is covered by `dashboard_tests.py`'s
MySQL-gated wiring tests.

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
