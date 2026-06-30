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
3. **`can_run_on_jet`** — returns `True` for jet IDs provided to the constructor
   and `False` for jet IDs not provided.

### 2.2 Translations

1. **`load_ply1_translation`, 1-to-1** — confirm it works correctly on a
   one-to-one table (each `Fabric` contributes a single ply1 part).
2. **`load_ply1_translation`, many-to-1** — confirm it works correctly on a
   many-to-one table (a `Fabric` with multiple ply1 parts).
3. **`ply1_to_fabric` returns the `Fabric`** — confirm it returns the expected
   `Fabric` object.
4. **`ply1_to_fabric` unknown ply1** — confirm it returns `None` on a ply1 part
   not in the table.
