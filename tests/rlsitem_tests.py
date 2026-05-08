#!/usr/bin/env python

from datetime import date, datetime

from swmtplanner.demand import RlsItem
from swmtplanner.demand.order.order import DemandQty
from swmtplanner.products import Greige

# A known Monday so start_day-derived due dates are predictable.
START_DAY = date(2025, 6, 2).toordinal()  # Monday, 2025-06-02

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

def expected_due(week_offset):
    return datetime.fromordinal(START_DAY + week_offset * 7)

# ---- identity properties --------------------------------------------------
def test_id_matches_item_id():
    g = make_greige(id='G42')
    r = RlsItem(g, on_hand=0, weekly_use=[10], start_day=START_DAY)
    assert r.id == 'G42', f'id={r.id!r}, expected {"G42"!r}'

def test_prefix():
    r = RlsItem(make_greige(), on_hand=0, weekly_use=[10], start_day=START_DAY)
    assert r.prefix == 'RlsItem', f'prefix={r.prefix!r}, expected {"RlsItem"!r}'

def test_orders_returns_tuple():
    r = RlsItem(make_greige(), on_hand=0, weekly_use=[10, 20], start_day=START_DAY)
    assert isinstance(r.orders, tuple), \
        f'orders is {type(r.orders).__name__}, expected tuple'

# ---- order generation: shape & metadata -----------------------------------
# Each entry: (label, on_hand, weekly_use, item_safety,
#              [DemandQty for each order], rls_safety)
# DemandQty values describe what `Order.remaining()` should return at init —
# i.e. the demand left after netting on_hand against (in order):
#   1. week 0 demand
#   2. safety stock
#   3. weeks 1..N-1 demand
SCENARIOS = [
    ('no on-hand, no safety',
     0, [10, 20, 30], 0.0,
     [DemandQty(cumulative=10, regular=10, safety=0, excess=0),
      DemandQty(cumulative=30, regular=20, safety=0, excess=0),
      DemandQty(cumulative=60, regular=30, safety=0, excess=0)],
     0),

    ('on_hand partially covers wk0',
     5, [10, 20, 30], 0.0,
     [DemandQty(cumulative=5, regular=5, safety=0, excess=0),
      DemandQty(cumulative=25, regular=20, safety=0, excess=0),
      DemandQty(cumulative=55, regular=30, safety=0, excess=0)],
     0),

    ('on_hand exactly covers wk0',
     10, [10, 20, 30], 0.0,
     [DemandQty(cumulative=0, regular=0, safety=0, excess=0),
      DemandQty(cumulative=20, regular=20, safety=0, excess=0),
      DemandQty(cumulative=50, regular=30, safety=0, excess=0)],
     0),

    # No safety target, so excess after wk0 spills directly into wk1 demand.
    ('on_hand exceeds wk0, no safety target',
     15, [10, 20, 30], 0.0,
     [DemandQty(cumulative=0, regular=0, safety=0, excess=5),
      DemandQty(cumulative=15, regular=15, safety=0, excess=0),
      DemandQty(cumulative=45, regular=30, safety=0, excess=0)],
     0),

    # On-hand exactly covers wk0 + full safety, with nothing left for wk1+.
    ('on_hand covers wk0 + full safety',
     25, [10, 20, 30], 15.0,
     [DemandQty(cumulative=0, regular=0, safety=0, excess=0),
      DemandQty(cumulative=20, regular=20, safety=0, excess=0),
      DemandQty(cumulative=50, regular=30, safety=0, excess=0)],
     0),

    # On-hand covers wk0 + partial safety; safety target persists across orders.
    ('on_hand covers wk0 + partial safety',
     15, [10, 20, 30], 15.0,
     [DemandQty(cumulative=0, regular=0, safety=10, excess=0),
      DemandQty(cumulative=20, regular=20, safety=10, excess=0),
      DemandQty(cumulative=50, regular=30, safety=10, excess=0)],
     10),

    # On-hand covers wk0 (10) + safety (10) + wk1 (20) + 10 of wk2; remainder
    # of wk2 (20) is the only demand that survives.
    ('on_hand spills into wk1+wk2 after wk0+safety',
     50, [10, 20, 30], 10.0,
     [DemandQty(cumulative=0, regular=0, safety=0, excess=30),
      DemandQty(cumulative=0, regular=0, safety=0, excess=10),
      DemandQty(cumulative=20, regular=20, safety=0, excess=0)],
     0),

    # On-hand exceeds total demand: every order shows zero remaining demand
    # and a positive excess that decreases as later weeks consume on-hand.
    ('on_hand exceeds total demand',
     100, [10, 20, 30], 0.0,
     [DemandQty(cumulative=0, regular=0, safety=0, excess=90),
      DemandQty(cumulative=0, regular=0, safety=0, excess=70),
      DemandQty(cumulative=0, regular=0, safety=0, excess=40)],
     0),

    # Single-week horizon, no on-hand: one order carrying the full demand
    # plus the full item safety target.
    ('single week, no on_hand, with safety',
     0, [10], 5.0,
     [DemandQty(cumulative=10, regular=10, safety=5, excess=0)],
     5),

    # Zero-demand wk0 with on-hand: nothing to net against in wk0, so on-hand
    # flows directly to safety / future weeks.
    ('zero-demand wk0, on_hand flows to wk1',
     5, [0, 10, 20], 0.0,
     [DemandQty(cumulative=0, regular=0, safety=0, excess=5),
      DemandQty(cumulative=5, regular=5, safety=0, excess=0),
      DemandQty(cumulative=25, regular=20, safety=0, excess=0)],
     0),
]

def test_order_count_matches_weekly_use():
    for label, on_hand, wu, item_sfty, expected_qtys, _ in SCENARIOS:
        g = make_greige(safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=wu, start_day=START_DAY)
        assert len(r.orders) == len(wu), \
            f'[{label}] {len(r.orders)} orders, expected {len(wu)}'
        assert len(r.orders) == len(expected_qtys), \
            f'[{label}] test fixture mismatch: {len(r.orders)} orders vs ' \
            f'{len(expected_qtys)} expected DemandQtys'

def test_order_ids_and_priorities():
    for label, on_hand, wu, item_sfty, _, _ in SCENARIOS:
        g = make_greige(id='G7', safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=wu, start_day=START_DAY)
        for i, o in enumerate(r.orders):
            expected_id = f'P{i}@G7'
            assert o.id == expected_id, \
                f'[{label}] orders[{i}].id={o.id!r}, expected {expected_id!r}'

def test_order_due_dates():
    for label, on_hand, wu, item_sfty, _, _ in SCENARIOS:
        g = make_greige(safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=wu, start_day=START_DAY)
        for i, o in enumerate(r.orders):
            expected = expected_due(i)
            assert o.due_date == expected, \
                f'[{label}] orders[{i}].due_date={o.due_date!r}, expected {expected!r}'

def test_order_items_share_input_greige():
    for label, on_hand, wu, item_sfty, _, _ in SCENARIOS:
        g = make_greige(safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=wu, start_day=START_DAY)
        for i, o in enumerate(r.orders):
            assert o.item is g, \
                f'[{label}] orders[{i}].item is not the Greige passed in'

# ---- order generation: on_hand netting (the core behavior) ----------------
def test_remaining_per_order_reflects_on_hand_netting():
    for label, on_hand, wu, item_sfty, expected_qtys, _ in SCENARIOS:
        g = make_greige(safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=wu, start_day=START_DAY)
        for i, (o, expected) in enumerate(zip(r.orders, expected_qtys)):
            actual = o.remaining()
            assert actual == expected, \
                f'[{label}] orders[{i}].remaining()={actual!r}, expected {expected!r}'

# ---- safety property (non-empty weekly_use) -------------------------------
def test_safety_property_nonempty_weekly_use():
    for label, on_hand, wu, item_sfty, _, expected_safety in SCENARIOS:
        g = make_greige(safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=wu, start_day=START_DAY)
        actual = r.safety
        assert actual == expected_safety, \
            f'[{label}] rls.safety={actual!r}, expected {expected_safety!r}'

# ---- empty weekly_use -----------------------------------------------------
# (label, on_hand, item_safety, expected_safety)
EMPTY_CASES = [
    ('empty wu, no on_hand, no safety target', 0, 0.0, 0),
    ('empty wu, on_hand below safety target', 4, 10.0, 6),
    ('empty wu, on_hand exactly meets safety target', 10, 10.0, 0),
    ('empty wu, on_hand exceeds safety target', 20, 10.0, 0),
]

def test_empty_weekly_use_produces_no_orders():
    for label, on_hand, item_sfty, _ in EMPTY_CASES:
        g = make_greige(safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=[], start_day=START_DAY)
        assert r.orders == (), \
            f'[{label}] orders={r.orders!r}, expected empty tuple'

def test_empty_weekly_use_safety():
    for label, on_hand, item_sfty, expected in EMPTY_CASES:
        g = make_greige(safety=item_sfty)
        r = RlsItem(g, on_hand=on_hand, weekly_use=[], start_day=START_DAY)
        actual = r.safety
        assert actual == expected, \
            f'[{label}] rls.safety={actual!r}, expected {expected!r}'

def main():
    test_id_matches_item_id()
    test_prefix()
    test_orders_returns_tuple()
    print('All identity property cases passed.')

    test_order_count_matches_weekly_use()
    test_order_ids_and_priorities()
    test_order_due_dates()
    test_order_items_share_input_greige()
    print(f'All {len(SCENARIOS)} order-shape scenarios passed.')

    test_remaining_per_order_reflects_on_hand_netting()
    print(f'All {len(SCENARIOS)} on_hand-netting scenarios passed.')

    test_safety_property_nonempty_weekly_use()
    print(f'All {len(SCENARIOS)} non-empty rls.safety cases passed.')

    test_empty_weekly_use_produces_no_orders()
    test_empty_weekly_use_safety()
    print(f'All {len(EMPTY_CASES)} empty weekly_use cases passed.')

if __name__ == '__main__':
    main()
