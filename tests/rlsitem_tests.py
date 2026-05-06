#!/usr/bin/env python

from swmtplanner.demand import RlsItem
from swmtplanner.products import Greige

def make_greige(id='G1', safety=0.0):
    return Greige(
        id=id,
        family='FAM',
        tgt_wt=100.0,
        top_beam='TB',
        top_pct=0.5,
        btm_beam='BB',
        btm_pct=0.5,
        safety=safety,
        machines={},
    )

# ---- identity properties --------------------------------------------------
def test_id_matches_item_id():
    g = make_greige(id='G42')
    r = RlsItem(g, on_hand=0, weekly_use=[])
    assert r.id == 'G42', f'id={r.id!r}, expected {"G42"!r}'

def test_prefix():
    r = RlsItem(make_greige(), on_hand=0, weekly_use=[])
    assert r.prefix == 'RlsItem', f'prefix={r.prefix!r}, expected {"RlsItem"!r}'

def test_item_returns_input():
    g = make_greige()
    r = RlsItem(g, on_hand=0, weekly_use=[])
    assert r.item is g, f'item is not the Greige passed in'

# ---- safety fixtures ------------------------------------------------------
# (label, item_safety, on_hand, expected_remaining_safety)
SAFETY_CASES = [
    ('on_hand below safety target', 100.0, 30.0, 70.0),
    ('on_hand exactly meets safety target', 100.0, 100.0, 0.0),
    ('on_hand exceeds safety target', 100.0, 200.0, 0.0),
    ('zero safety target, zero on hand', 0.0, 0.0, 0.0),
    ('zero safety target, positive on hand', 0.0, 50.0, 0.0),
    ('fractional values', 12.5, 4.25, 8.25),
]

def test_safety():
    for label, item_safety, on_hand, expected in SAFETY_CASES:
        g = make_greige(safety=item_safety)
        r = RlsItem(g, on_hand=on_hand, weekly_use=[])
        assert r.safety == expected, \
            f'[{label}] safety={r.safety!r}, expected {expected!r}'

# ---- demand fixtures ------------------------------------------------------
# (label, on_hand, weekly_use, expected_demand_list)
DEMAND_CASES = [
    # No on-hand inventory: each week's demand equals its raw usage.
    ('no on-hand, sequential demand',
     0, [10, 20, 30], [10, 20, 30]),

    # On-hand partially covers the first week; the leftover usage still bills
    # against on-hand carryover (cum_added stays at 0 until demand kicks in).
    ('on-hand covers part of first week',
     5, [10, 20, 30], [5, 20, 30]),

    # On-hand exactly equals first week's usage: week 0 zero, week 1 onward
    # bills the full incremental amount.
    ('on-hand exactly covers first week',
     10, [10, 5], [0, 5]),

    # On-hand spans into week 1: week 0 fully absorbed, week 1 partially.
    ('on-hand spans into second week',
     15, [10, 20, 30], [0, 15, 30]),

    # On-hand exceeds total demand across the horizon: nothing is needed.
    ('on-hand exceeds total demand',
     100, [10, 20, 30], [0, 0, 0]),

    # Empty horizon: no weeks recorded.
    ('empty weekly_use',
     0, [], []),

    # Zero-demand weeks at the end leave demand at 0 once cumulative is met.
    ('zero-demand weeks at end',
     0, [10, 0, 0], [10, 0, 0]),

    # Zero-demand week wedged between non-zero weeks while on-hand is still
    # being consumed.
    ('zero-demand week mid-stream while on-hand absorbing',
     10, [10, 0, 5], [0, 0, 5]),

    # Fractional usages exercise the float arithmetic path.
    ('fractional weekly use, no on-hand',
     0.0, [1.5, 2.5, 4.0], [1.5, 2.5, 4.0]),

    # Fractional on-hand mid-coverage.
    ('fractional on-hand mid-coverage',
     2.5, [1.0, 2.0, 3.0], [0, 0.5, 3.0]),
]

def test_demand():
    for label, on_hand, weekly_use, expected in DEMAND_CASES:
        g = make_greige()
        r = RlsItem(g, on_hand=on_hand, weekly_use=weekly_use)
        actual = [r.demand(i) for i in range(len(expected))]
        assert actual == expected, \
            f'[{label}] demand={actual!r}, expected {expected!r}'

# ---- safety and demand are independent of each other ----------------------
def test_safety_does_not_affect_demand():
    # demand() should depend only on on_hand and weekly_use, not on the item's
    # safety stock target.
    weekly_use = [10, 20, 30]
    on_hand = 15
    expected = [0, 15, 30]
    for safety in (0.0, 50.0, 500.0):
        g = make_greige(safety=safety)
        r = RlsItem(g, on_hand=on_hand, weekly_use=weekly_use)
        actual = [r.demand(i) for i in range(len(expected))]
        assert actual == expected, \
            f'[safety={safety}] demand={actual!r}, expected {expected!r}'

def main():
    test_id_matches_item_id()
    test_prefix()
    test_item_returns_input()
    print('All identity property cases passed.')
    test_safety()
    print(f'All {len(SAFETY_CASES)} safety cases passed.')
    test_demand()
    print(f'All {len(DEMAND_CASES)} demand cases passed.')
    test_safety_does_not_affect_demand()
    print('Safety/demand independence case passed.')

if __name__ == '__main__':
    main()
