# product — Test Coverage

Test coverage for the `core/product/` submodules (`unittest`).

## Section 1 — `greige`

### 1.1 `BeamConfig` and `Greige`

The `Greige` tests are very simple — just a couple of construction checks.

1. **`BeamConfig` construction** — build a `BeamConfig` and verify its fields are
   stored correctly.
2. **`Greige` construction** — build a `Greige` and verify all attributes are
   exposed correctly as read-only properties (including that `alt_names`, passed
   in as a list, is stored as a tuple).

### 1.2 Translations

1. **`load_variant_translation` loads contents** — confirm it correctly loads the
   contents of the passed string into the table.
2. **`load_variant_translation` replaces on reload** — confirm that calling it
   again on a different string replaces the contents of the table.
3. **`variant_to_master` fetches the master** — confirm it fetches the correct
   master according to the table.
4. **`variant_to_master` missing variant** — confirm it returns `None` on a
   variant not in the table.
5. **`load_alt_translation`, 1-to-1** — confirm it works correctly on a
   one-to-one table (each `Greige` contributes a single alternate name).
6. **`load_alt_translation`, many-to-1** — confirm it works correctly on a
   many-to-one table (a `Greige` with multiple alternate names).
7. **`alt_greige_to_greige` returns the `Greige`** — confirm it returns the
   expected `Greige` object.
8. **`alt_greige_to_greige` unknown id** — confirm it returns `None` on an
   unknown alternate greige id.

## Section 2 — `fabric`

### 2.1 Construction

1. **`Fabric` construction** — build a `Fabric` and confirm the whole object is
   constructed properly: every read-only property is exposed correctly, including
   the `color` built from the passed `name` / `number` / `shade_rating`.
2. **`yds_per_lb` calculation** — a couple of cases with different `oz_sq_yd`,
   `width`, and `yld_pct` confirming `yds_per_lb` calculates as expected
   (`36 * 16 / (oz_sq_yd * width) * yld_pct`).
3. **`can_run_on_jet`** — returns `True` for jet IDs in the `jets` dict passed to
   the constructor and `False` for jet IDs not in it.
4. **`load_range_on_jet`** — returns the `(min, max)` per-port load mapped to a
   runnable jet, and raises `ValueError` for a jet not in the `jets` dict.

### 2.2 Translations

1. **`load_ply1_translation`, 1-to-1** — confirm it works correctly on a
   one-to-one table (each `Fabric` contributes a single ply1 part).
2. **`load_ply1_translation`, many-to-1** — confirm it works correctly on a
   many-to-one table (a `Fabric` with multiple ply1 parts).
3. **`ply1_to_fabric` returns the `Fabric`** — confirm it returns the expected
   `Fabric` object.
4. **`ply1_to_fabric` unknown ply1** — confirm it returns `None` on a ply1 part
   not in the table.

### 2.3 `Color.get_needed_strip`

Because the real `JetState` is not defined until `core/schedule`, these tests use
a small **fake jet state** — a stand-in object exposing just the two attributes
the method reads (`cycles_since_strip: int` and `max_prev_shade: int | None`).

1. **No preparation needed** — each of these returns `[]`:
   - running the same color again before the 9-cycle limit (`max_prev_shade`
     equals the color's shade, `cycles_since_strip < 9`);
   - running a different color of the same shade;
   - running a different shade in the same tier (light tier: `LIGHT` after
     `EXTRA_LIGHT` and `EXTRA_LIGHT` after `LIGHT`; black tier: `BLACK` after
     `SD_BLACK` and `SD_BLACK` after `BLACK`);
   - running any non-`EXTRA_LIGHT` color immediately after a strip
     (`max_prev_shade is None`);
   - running a darker shade after a lighter shade (e.g. `MEDIUM` after `LIGHT`,
     `BLACK` after `MEDIUM`).
2. **Single strip** — each of these returns `[STRIP]`:
   - a `LIGHT` after a `MEDIUM`;
   - a `LIGHT` after a `SD_BLACK`;
   - a `MEDIUM` after a `SD_BLACK`;
   - a `MEDIUM` at the 9-cycle limit where the max shade is not black;
   - a `BLACK` at the 9-cycle limit where the max shade is `BLACK`, and where it
     is `MEDIUM`;
   - a `SD_BLACK` at the 9-cycle limit where the max shade is `BLACK`, and where
     it is `MEDIUM`;
   - a `LIGHT` or `MEDIUM` after a `BLACK` when one strip has already run
     (`max_prev_shade == BLACK`, `cycles_since_strip == 0`).
3. **Double strip** — each of these returns `[STRIP, STRIP]`:
   - a `LIGHT` or `MEDIUM` after a `BLACK` before the 9-cycle limit
     (`max_prev_shade == BLACK`, `0 < cycles_since_strip < 9`);
   - a `LIGHT` or `MEDIUM` after a `BLACK` at the 9-cycle limit
     (`max_prev_shade == BLACK`, `cycles_since_strip == 9`).
4. **Extra light** — the `EXTRA_LIGHT` priming rule:
   - immediately after a strip (`max_prev_shade is None`) → `[EMPTY]`;
   - after a `BLACK` with no strip yet (`cycles_since_strip > 0`) →
     `[STRIP, STRIP, EMPTY]`;
   - after a `BLACK` with one strip already run (`cycles_since_strip == 0`) →
     `[STRIP, EMPTY]`;
   - after a `MEDIUM` or a `SD_BLACK` → `[STRIP, EMPTY]`.
