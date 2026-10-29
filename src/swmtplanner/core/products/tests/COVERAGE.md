# `swmtplanner.core.products` test coverage

Test cases for the `products` submodules. These are mostly checks that the
classes initialize correctly and that their ids and computed values come
out as the design specifies. Each table row is one test case; the test
function name is given so the tests and this document can be kept in step.

Tests live in this `tests/` package, one module per `products` submodule:

| Test module        | Covers                                        |
|--------------------|-----------------------------------------------|
| `test_beamset.py`  | `YarnAttrs`, `Yarn`, `Merge`, `BeamSetDesc`   |
| `test_greige.py`   | `BarConfig`, `BeamConfig`, `Greige`           |
| `test_fabric.py`   | `Shade`, `DyeFormula`, `Fabric`               |

## `beamset`

### `YarnAttrs`

Shared fixture values: `ATTRS_NONE = YarnAttrs(False, False, False)`,
`ATTRS_TX = YarnAttrs(True, False, False)`.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_attrs_init`             | `YarnAttrs(True, False, True)`               | `textured is True`, `cationic is False`, `recycled is True` |
| `test_attrs_int_none`         | `int(YarnAttrs(False, False, False))`        | `0` |
| `test_attrs_int_recycled`     | `int(YarnAttrs(False, False, True))`         | `1` |
| `test_attrs_int_cationic`     | `int(YarnAttrs(False, True, False))`         | `2` |
| `test_attrs_int_textured`     | `int(YarnAttrs(True, False, False))`         | `4` |
| `test_attrs_int_tx_recycled`  | `int(YarnAttrs(True, False, True))`          | `5` |
| `test_attrs_int_all`          | `int(YarnAttrs(True, True, True))`           | `7` |
| `test_attrs_from_int_zero`    | `YarnAttrs.from_int(0)`                      | `YarnAttrs(False, False, False)` |
| `test_attrs_from_int_four`    | `YarnAttrs.from_int(4)`                      | `YarnAttrs(True, False, False)` |
| `test_attrs_from_int_five`    | `YarnAttrs.from_int(5)`                      | `YarnAttrs(True, False, True)` |
| `test_attrs_from_int_seven`   | `YarnAttrs.from_int(7)`                      | `YarnAttrs(True, True, True)` |
| `test_attrs_round_trip`       | for each `c` in `0..7`: `int(YarnAttrs.from_int(c))` | `c` |
| `test_attrs_from_int_negative` | `YarnAttrs.from_int(-1)`                    | raises `ValueError` |
| `test_attrs_from_int_too_large` | `YarnAttrs.from_int(8)`                    | raises `ValueError` |
| `test_attrs_equality`         | `YarnAttrs(True, False, False) == YarnAttrs.from_int(4)`; `YarnAttrs(True, False, False) == YarnAttrs(False, False, False)` | `True`; `False` |
| `test_attrs_frozen`           | assign `attrs.textured = False` on an instance | raises `FrozenInstanceError` |

### `Yarn`

Shared fixture values: `ATTRS_NONE`, `ATTRS_TX` as above, and
`YARN_75SD = Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)`.

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_yarn_init`              | `YARN_75SD`                                  | `denier == 75`, `material == 'polyester'`, `color == 'white'`, `luster == 'semidull'`, `attrs == ATTRS_TX` |
| `test_yarn_id_semidull`       | `YARN_75SD.id`                               | `'75PWTS04'` |
| `test_yarn_id_dull`           | `Yarn(75, 'polyester', 'white', 'dull', ATTRS_TX).id` | `'75PWTD04'` |
| `test_yarn_id_nylon_black_bright` | `Yarn(40, 'nylon', 'black', 'bright', ATTRS_NONE).id` | `'40NBKB00'` |
| `test_yarn_id_greener_black`  | `Yarn(75, 'polyester', 'greenerblack', 'semidull', YarnAttrs(True, False, True)).id` | `'75PGBS05'` |
| `test_yarn_id_grey_recycled`  | `Yarn(20, 'polyester', 'grey', 'semidull', YarnAttrs(False, False, True)).id` | `'20PGYS01'` |
| `test_yarn_id_three_digit_denier` | `Yarn(150, 'lycra', 'white', 'clear', YarnAttrs(False, True, False)).id` | `'150LWTC02'` |
| `test_yarn_equal_by_id`       | `a = Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)`; `b = Yarn(75, 'polyester', 'white', 'semidull', YarnAttrs.from_int(4))` | `a == b`, `hash(a) == hash(b)`, `a is not b` |
| `test_yarn_unequal_luster`    | `YARN_75SD` vs `Yarn(75, 'polyester', 'white', 'dull', ATTRS_TX)` | not equal |
| `test_yarn_unequal_attrs`     | `YARN_75SD` vs `Yarn(75, 'polyester', 'white', 'semidull', ATTRS_NONE)` | not equal |
| `test_yarn_unequal_denier`    | `YARN_75SD` vs `Yarn(70, 'polyester', 'white', 'semidull', ATTRS_TX)` | not equal (no denier normalization in `products`) |
| `test_yarn_hashable`          | `{YARN_75SD, Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)}` | set of length 1 |
| `test_yarn_invalid_material`  | `Yarn(75, 'polypro', 'white', 'semidull', ATTRS_TX)` | raises `ValueError` on construction |
| `test_yarn_invalid_color`     | `Yarn(75, 'polyester', 'navy', 'semidull', ATTRS_TX)` | raises `ValueError` on construction |
| `test_yarn_invalid_luster`    | `Yarn(75, 'polyester', 'white', 'shiny', ATTRS_TX)` | raises `ValueError` on construction |
| `test_yarn_frozen`            | assign `YARN_75SD.denier = 70`               | raises `FrozenInstanceError` |

### `Merge`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_merge_init`             | `m = Merge('R204B', YARN_75SD, 'Unifi')`     | `m.id == 'R204B'`, `m.yarn is YARN_75SD`, `m.vendor == 'Unifi'`; `m == Merge('R204B', YARN_75SD, 'Other')`; `m != YARN_75SD` |

### `BeamSetDesc`

Shared fixture values: `YARN_75SD` as above, `YARN_75D = Yarn(75,
'polyester', 'white', 'dull', ATTRS_TX)`, `YARN_40N = Yarn(40, 'nylon',
'white', 'semidull', ATTRS_NONE)`, and `BS_1172 = BeamSetDesc(YARN_75SD, 4,
1172)`.

**Construction and id**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_bsd_init`               | `BS_1172`                                    | `yarn is YARN_75SD`, `beam_count == 4`, `end_count == 1172` |
| `test_bsd_id`                 | `BS_1172.id`                                 | `'75PWTS04-1172-4'` |
| `test_bsd_id_other_yarn`      | `BeamSetDesc(YARN_40N, 7, 370).id`           | `'40NWTS00-370-7'` |
| `test_bsd_id_single_beam`     | `BeamSetDesc(YARN_75D, 1, 586).id`           | `'75PWTD04-586-1'` |
| `test_bsd_equal_by_id`        | `BS_1172` vs `BeamSetDesc(Yarn(75, 'polyester', 'white', 'semidull', YarnAttrs.from_int(4)), 4, 1172)` | equal, hashes equal |
| `test_bsd_unequal_yarn`       | `BS_1172` vs `BeamSetDesc(YARN_75D, 4, 1172)` | not equal |
| `test_bsd_unequal_ends`       | `BS_1172` vs `BeamSetDesc(YARN_75SD, 4, 1173)` | not equal |
| `test_bsd_unequal_beams`      | `BS_1172` vs `BeamSetDesc(YARN_75SD, 3, 1172)` | not equal |
| `test_bsd_frozen`             | assign `BS_1172.end_count = 1`               | raises `FrozenInstanceError` |

**`split`**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_split_zero`             | `BS_1172.split(0)`                           | raises `ValueError` |
| `test_split_negative`         | `BS_1172.split(-2)`                          | raises `ValueError` |
| `test_split_uneven`           | `BS_1172.split(3)` (1172 % 3 != 0)           | raises `ValueError` |
| `test_split_larger_than_ends` | `BeamSetDesc(YARN_75SD, 4, 2).split(4)`      | raises `ValueError` |
| `test_split_one`              | `BS_1172.split(1)`                           | `[BS_1172]` (single-element list, equal to the original) |
| `test_split_two`              | `BS_1172.split(2)`                           | list of 2, each `== BeamSetDesc(YARN_75SD, 4, 586)` with `id == '75PWTS04-586-4'` |
| `test_split_four`             | `BS_1172.split(4)`                           | list of 4, each `== BeamSetDesc(YARN_75SD, 4, 293)` |
| `test_split_preserves_rest`   | `BeamSetDesc(YARN_40N, 7, 370).split(2)`     | each part has `yarn is YARN_40N`, `beam_count == 7`, `end_count == 185` |
| `test_split_leaves_original`  | `BS_1172.split(2)`; then `BS_1172.end_count` | `1172` (original unchanged) |

**`merge`**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_merge_none`             | `BeamSetDesc.merge()`                        | raises `ValueError` |
| `test_merge_mismatch_yarn`    | `BeamSetDesc.merge(BeamSetDesc(YARN_75SD, 4, 586), BeamSetDesc(YARN_75D, 4, 586))` | raises `ValueError` |
| `test_merge_mismatch_ends`    | `BeamSetDesc.merge(BeamSetDesc(YARN_75SD, 4, 586), BeamSetDesc(YARN_75SD, 4, 587))` | raises `ValueError` |
| `test_merge_mismatch_beams`   | `BeamSetDesc.merge(BeamSetDesc(YARN_75SD, 4, 586), BeamSetDesc(YARN_75SD, 3, 586))` | raises `ValueError` |
| `test_merge_mismatch_third`   | `BeamSetDesc.merge(h, h, BeamSetDesc(YARN_75SD, 4, 587))` with `h = BeamSetDesc(YARN_75SD, 4, 586)` | raises `ValueError` (mismatch is not only checked against the first two) |
| `test_merge_one`              | `BeamSetDesc.merge(BS_1172)`                 | `== BS_1172` |
| `test_merge_two`              | `BeamSetDesc.merge(h, h)` with `h = BeamSetDesc(YARN_75SD, 4, 586)` | `== BS_1172`, `id == '75PWTS04-1172-4'` |
| `test_merge_four`             | `BeamSetDesc.merge(*[BeamSetDesc(YARN_75SD, 4, 293)] * 4)` | `== BS_1172` |
| `test_merge_separate_instances` | `BeamSetDesc.merge(BeamSetDesc(YARN_40N, 7, 185), BeamSetDesc(YARN_40N, 7, 185))` (two distinct but equal objects) | `== BeamSetDesc(YARN_40N, 7, 370)` |
| `test_merge_preserves_rest`   | result of `test_merge_separate_instances`    | `yarn == YARN_40N`, `beam_count == 7` |
| `test_merge_split_round_trip` | for `n` in `(1, 2, 4)`: `BeamSetDesc.merge(*BS_1172.split(n))` | `== BS_1172` |

## `greige`

Shared fixture values, modeled on the `AU5429DASHSDU/1` construction (28
gauge, 168 inch, 4 beams; bars 1 and 2 partial at 586 ends each, bar 3
solid at 1,172 ends) plus a hypothetical three-bar group:

```python
YARN_75SD = Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)
YARN_75D  = Yarn(75, 'polyester', 'white', 'dull', ATTRS_TX)
YARN_40N  = Yarn(40, 'nylon', 'white', 'semidull', ATTRS_NONE)

BS_1172 = BeamSetDesc(YARN_75SD, 4, 1172)
BS_586  = BeamSetDesc(YARN_75SD, 4, 586)
BS_1170 = BeamSetDesc(YARN_40N, 4, 1170)
BS_390  = BeamSetDesc(YARN_40N, 4, 390)

BAR1 = BarConfig(1, 61.5, 14.71, '1/0,1/2,2/3,2/1')
BAR2 = BarConfig(2, 61.5, 14.73, '2/3,2/1,1/0,1/2')
BAR3 = BarConfig(3, 81.5, 70.56, '1/0,2/3')
BAR4 = BarConfig(4, 50.0, 33.3, '1/0,1/2')
BAR5 = BarConfig(5, 50.0, 33.3, '1/2,1/0')
BAR6 = BarConfig(6, 50.0, 33.4, '1/0,2/3')

CFG_1BAR = BeamConfig(BS_1172, (BAR3,))           # solid bar, one-bar group
CFG_2BAR = BeamConfig(BS_1172, (BAR1, BAR2))      # two partial bars
CFG_3BAR = BeamConfig(BS_1170, (BAR4, BAR5, BAR6))  # three-bar group

G_5429D = Greige('AU5429D', 28, 168, 24.36, 300.0, (CFG_2BAR, CFG_1BAR),
                 rates={'K1': 12.5, 'K2': 11.0})
```

### `BarConfig`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_bar_init`               | `BAR1`                                       | `num == 1`, `runlen == 61.5`, `pct == 14.71`, `stitch == '1/0,1/2,2/3,2/1'` |
| `test_bar_equality`           | `BAR1 == BarConfig(1, 61.5, 14.71, '1/0,1/2,2/3,2/1')`; `BAR1 == BAR2`; `BAR1 == BarConfig(1, 61.0, 14.71, '1/0,1/2,2/3,2/1')` | `True`; `False`; `False` (field-wise) |
| `test_bar_hashable`           | `{BAR1, BarConfig(1, 61.5, 14.71, '1/0,1/2,2/3,2/1'), BAR2}` | set of length 2 |
| `test_bar_frozen`             | assign `BAR1.runlen = 1.0`                   | raises `FrozenInstanceError` |

### `BeamConfig`

**Construction**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_cfg_init`               | `CFG_2BAR`                                   | `beamset is BS_1172`, `bars == (BAR1, BAR2)` |
| `test_cfg_equality`           | `CFG_2BAR == BeamConfig(BS_1172, (BAR1, BAR2))`; `CFG_2BAR == BeamConfig(BS_1172, (BAR2, BAR1))`; `CFG_2BAR == CFG_1BAR` | `True`; `False` (bar order matters); `False` |
| `test_cfg_frozen`             | assign `CFG_2BAR.bars = ()`                  | raises `FrozenInstanceError` |

**`can_use`, single beam set**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_use_one_bar_match`      | `CFG_1BAR.can_use([BS_1172])`                | `True` |
| `test_use_one_bar_match_separate_instance` | `CFG_1BAR.can_use([BeamSetDesc(YARN_75SD, 4, 1172)])` | `True` (equal by id, not identity) |
| `test_use_one_bar_wrong_ends` | `CFG_1BAR.can_use([BS_586])`                 | `False` |
| `test_use_one_bar_wrong_yarn` | `CFG_1BAR.can_use([BeamSetDesc(YARN_75D, 4, 1172)])` | `False` |
| `test_use_one_bar_wrong_beams` | `CFG_1BAR.can_use([BeamSetDesc(YARN_75SD, 3, 1172)])` | `False` |
| `test_use_two_bar_match`      | `CFG_2BAR.can_use([BS_1172])`                | `True` (one combined set split across both bars) |
| `test_use_two_bar_half`       | `CFG_2BAR.can_use([BS_586])`                 | `False` (one set, but only one bar's worth) |
| `test_use_two_bar_wrong_yarn` | `CFG_2BAR.can_use([BeamSetDesc(YARN_75D, 4, 1172)])` | `False` |
| `test_use_three_bar_match`    | `CFG_3BAR.can_use([BS_1170])`                | `True` |
| `test_use_three_bar_wrong_ends` | `CFG_3BAR.can_use([BS_390])`               | `False` |
| `test_use_empty_one_bar`      | `CFG_1BAR.can_use([])`                       | `False` |
| `test_use_empty_two_bar`      | `CFG_2BAR.can_use([])`                       | `False` |

**`can_use`, multiple beam sets, false cases**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_use_count_one_bar_two_sets` | `CFG_1BAR.can_use([BS_586, BS_586])`     | `False` (merges to `BS_1172`, but two sets cannot feed one solid bar) |
| `test_use_count_two_bar_three_sets` | `CFG_2BAR.can_use([BS_586, BS_586, BS_586])` | `False` |
| `test_use_count_three_bar_two_sets` | `CFG_3BAR.can_use([BeamSetDesc(YARN_40N, 4, 585)] * 2)` | `False` (merges to `BS_1170`, but count ≠ bars) |
| `test_use_merged_wrong_ends`  | `CFG_2BAR.can_use([BeamSetDesc(YARN_75SD, 4, 585)] * 2)` | `False` (merges to 1,170 ≠ 1,172) |
| `test_use_merged_wrong_yarn`  | `CFG_2BAR.can_use([BeamSetDesc(YARN_75D, 4, 586)] * 2)` | `False` |
| `test_use_merged_wrong_beams` | `CFG_2BAR.can_use([BeamSetDesc(YARN_75SD, 3, 586)] * 2)` | `False` |
| `test_use_unmergeable_ends`   | `CFG_2BAR.can_use([BS_586, BeamSetDesc(YARN_75SD, 4, 587)])` | `False` (no exception escapes) |
| `test_use_unmergeable_yarn`   | `CFG_2BAR.can_use([BS_586, BeamSetDesc(YARN_75D, 4, 586)])` | `False` |
| `test_use_unmergeable_three_bar` | `CFG_3BAR.can_use([BS_390, BS_390, BeamSetDesc(YARN_40N, 4, 391)])` | `False` |

**`can_use`, multiple beam sets, true cases**

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_use_two_bar_two_sets`   | `CFG_2BAR.can_use([BS_586, BS_586])`         | `True` |
| `test_use_two_bar_two_sets_separate_instances` | `CFG_2BAR.can_use([BeamSetDesc(YARN_75SD, 4, 586), BeamSetDesc(YARN_75SD, 4, 586)])` | `True` |
| `test_use_three_bar_three_sets` | `CFG_3BAR.can_use([BS_390, BS_390, BS_390])` | `True` |
| `test_use_split_round_trip`   | `CFG_2BAR.can_use(BS_1172.split(2))`; `CFG_3BAR.can_use(BS_1170.split(3))` | `True`; `True` |

### `Greige`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_greige_init`            | `G_5429D`                                    | `id == 'AU5429D'`, `gauge == 28`, `width == 168`, `rack_wt == 24.36`, `std_wt == 300.0`, `beam_cfgs == (CFG_2BAR, CFG_1BAR)` |
| `test_greige_pattern`         | `G_5429D.pattern`                            | `[('1/0,1/2,2/3,2/1', '2/3,2/1,1/0,1/2'), ('1/0,2/3',)]` |
| `test_greige_beamsets`        | `G_5429D.beamsets`                           | `[('75PWTS04-1172-4', (1, 2)), ('75PWTS04-1172-4', (3,))]` |
| `test_greige_pattern_reversed` | `g = Greige('AU5429H', 28, 168, 24.36, 300.0, (CFG_1BAR, CFG_2BAR), rates={})`; `g.pattern` | `== list(reversed(G_5429D.pattern))`; stitch order *within* each group unchanged |
| `test_greige_pattern_empty`   | `Greige('X', 28, 168, 1.0, 1.0, (), rates={}).pattern` | `[]` |
| `test_greige_can_run`         | `G_5429D.can_run_on_machine('K1')`; `('K2')`; `('K9')` | `True`; `True`; `False` |
| `test_greige_rate`            | `G_5429D.get_rate_on_machine('K1')`; `('K2')` | `12.5`; `11.0` |
| `test_greige_rate_unknown`    | `G_5429D.get_rate_on_machine('K9')`          | raises `KeyError` |
| `test_greige_rates_copied`    | `src = {'K1': 1.0}`; `g = Greige('X', 28, 168, 1.0, 1.0, (), rates=src)`; `src['K2'] = 2.0`; `g.can_run_on_machine('K2')` | `False` (private copy, caller's dict not shared) |
| `test_greige_rates_private`   | `G_5429D`                                    | `not hasattr(G_5429D, 'rates')`; `'K1' not in repr(G_5429D)` |
| `test_greige_equal_by_id`     | `G_5429D == Greige('AU5429D', 32, 1, 0.0, 0.0, (), rates={})` | `True`, hashes equal |
| `test_greige_unequal_id`      | `G_5429D == Greige('AU5429H', 28, 168, 24.36, 300.0, (CFG_2BAR, CFG_1BAR), rates={'K1': 12.5, 'K2': 11.0})` | `False` |
| `test_greige_hashable`        | `{G_5429D, Greige('AU5429D', 28, 168, 24.36, 300.0, (), rates={})}` | set of length 1 |
| `test_greige_frozen`          | assign `G_5429D.gauge = 32`                  | raises `FrozenInstanceError` |

## `fabric`

Shared fixture values:

```python
DF_1234 = DyeFormula(1234, 'Ebony', Shade.BLACK)
DF_2001 = DyeFormula(2001, 'Fog', Shade.LIGHT1)
G_5429D = Greige('AU5429D', 28, 168, 24.36, 300.0, (), rates={})
FAB = Fabric('FF AU5429D-1234-60', G_5429D, 'AU5429D', DF_1234, 60.0, 1.85,
             jets=('J1', 'J3'))
```

### `Shade`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_shade_members`          | `[m.name for m in Shade]`                    | `['LIGHT0', 'LIGHT1', 'MEDIUM', 'SD_BLACK', 'BLACK']` (exactly five, in this order) |
| `test_shade_values`           | `Shade.BLACK.value`; `Shade('LIGHT0')`        | `'BLACK'`; `Shade.LIGHT0` (values are the member names, so they round-trip through strings) |
| `test_shade_identity`         | `Shade.LIGHT0 is Shade.LIGHT1`; `Shade.SD_BLACK is Shade.BLACK` | `False`; `False` (the paired shades are distinct members) |

### `DyeFormula`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_formula_init`           | `DF_1234`                                    | `id == 1234`, `name == 'Ebony'`, `shade is Shade.BLACK` |
| `test_formula_equal_by_id`    | `DF_1234 == DyeFormula(1234, 'other', Shade.MEDIUM)` | `True`, hashes equal, `hash(DF_1234) == hash(1234)` |
| `test_formula_unequal_id`     | `DF_1234 == DyeFormula(1235, 'Ebony', Shade.BLACK)` | `False` |
| `test_formula_hashable`       | `{DF_1234, DyeFormula(1234, 'x', Shade.LIGHT0), DF_2001}` | set of length 2 |
| `test_formula_frozen`         | assign `DF_1234.shade = Shade.MEDIUM`        | raises `FrozenInstanceError` |

### `Fabric`

| Test                          | Input                                        | Expected |
|-------------------------------|----------------------------------------------|----------|
| `test_fabric_init`            | `FAB`                                        | `id == 'FF AU5429D-1234-60'`, `greige_style is G_5429D`, `master_style == 'AU5429D'`, `color is DF_1234`, `width == 60.0`, `yld == 1.85`, `jets == ('J1', 'J3')` |
| `test_fabric_jet_present`     | `FAB.can_run_on_jet('J1')`; `('J3')`         | `True`; `True` |
| `test_fabric_jet_absent`      | `FAB.can_run_on_jet('J2')`                   | `False` |
| `test_fabric_jet_case`        | `FAB.can_run_on_jet('j1')`                   | `False` (exact match; no normalization) |
| `test_fabric_no_jets`         | `Fabric('FF X-1-1', G_5429D, 'X', DF_1234, 1.0, 1.0, jets=()).can_run_on_jet('J1')` | `False` |
| `test_fabric_equal_by_id`     | `FAB == Fabric('FF AU5429D-1234-60', G_5429D, 'other', DF_2001, 0.0, 0.0, jets=())` | `True`, hashes equal |
| `test_fabric_unequal_id`      | `FAB == Fabric('FF AU5429D-2001-60', G_5429D, 'AU5429D', DF_2001, 60.0, 1.85, jets=('J1', 'J3'))` | `False` (different formula number in the item code) |
| `test_fabric_unequal_other_class` | `FAB == DF_1234`; `FAB == G_5429D`       | `False`; `False` |
| `test_fabric_hashable`        | `{FAB, Fabric('FF AU5429D-1234-60', G_5429D, 'AU5429D', DF_1234, 60.0, 1.85, jets=())}` | set of length 1 |
| `test_fabric_frozen`          | assign `FAB.width = 54.0`                    | raises `FrozenInstanceError` |
