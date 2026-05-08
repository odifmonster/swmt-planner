#!/usr/bin/env python

from datetime import datetime

from swmtplanner.demand import Order
from swmtplanner.demand.order.order import DemandQty
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

def make_order(item=None, due_date=None, priority=1, cur_lbs=100.0, prev_lbs=0.0,
               prev_due=None, safety=0.0, excess=0.0):
    if item is None:
        item = make_greige()
    if due_date is None:
        due_date = datetime(2025, 6, 15)
    if prev_due is None:
        prev_due = datetime(2025, 6, 1)
    return Order(item=item, due_date=due_date, priority=priority, cur_lbs=cur_lbs,
                 prev_lbs=prev_lbs, prev_due=prev_due, safety=safety, excess=excess)

# ---- identity properties --------------------------------------------------
def test_id_format():
    g = make_greige(id='G42')
    o = make_order(item=g, priority=3)
    assert o.id == 'P3@G42', f'id={o.id!r}, expected {"P3@G42"!r}'

def test_id_zero_priority():
    g = make_greige(id='G7')
    o = make_order(item=g, priority=0)
    assert o.id == 'P0@G7', f'id={o.id!r}, expected {"P0@G7"!r}'

def test_prefix():
    o = make_order()
    assert o.prefix == 'Order', f'prefix={o.prefix!r}, expected {"Order"!r}'

def test_item_returns_input():
    g = make_greige()
    o = make_order(item=g)
    assert o.item is g, 'item is not the Greige passed in'

def test_due_date_returns_input():
    d = datetime(2026, 1, 15, 9, 30)
    o = make_order(due_date=d)
    assert o.due_date == d, f'due_date={o.due_date!r}, expected {d!r}'
    assert o.due_date is d, 'due_date should be the same datetime object passed in'

# ---- remaining() at initialization ----------------------------------------
# Each case is (label, cur_lbs, prev_lbs, safety, excess, expected_DemandQty).
# remaining() with no args should reflect the constructor inputs verbatim:
#   cumulative = cur_lbs + prev_lbs
#   regular    = cur_lbs
#   safety     = safety
#   excess     = excess
REMAINING_CASES = [
    ('zero everywhere',
     0.0, 0.0, 0.0, 0.0,
     DemandQty(cumulative=0.0, regular=0.0, safety=0.0, excess=0.0)),

    ('only current demand',
     100.0, 0.0, 0.0, 0.0,
     DemandQty(cumulative=100.0, regular=100.0, safety=0.0, excess=0.0)),

    ('only previous demand',
     0.0, 50.0, 0.0, 0.0,
     DemandQty(cumulative=50.0, regular=0.0, safety=0.0, excess=0.0)),

    ('current and previous combined',
     100.0, 50.0, 0.0, 0.0,
     DemandQty(cumulative=150.0, regular=100.0, safety=0.0, excess=0.0)),

    ('safety carried through',
     100.0, 0.0, 25.0, 0.0,
     DemandQty(cumulative=100.0, regular=100.0, safety=25.0, excess=0.0)),

    ('excess carried through',
     100.0, 0.0, 0.0, 10.0,
     DemandQty(cumulative=100.0, regular=100.0, safety=0.0, excess=10.0)),

    ('all four populated',
     80.0, 20.0, 15.0, 5.0,
     DemandQty(cumulative=100.0, regular=80.0, safety=15.0, excess=5.0)),

    ('fractional values',
     12.5, 7.25, 3.5, 1.75,
     DemandQty(cumulative=19.75, regular=12.5, safety=3.5, excess=1.75)),
]

def test_remaining_no_args():
    for label, cur, prev, sfty, exc, expected in REMAINING_CASES:
        o = make_order(cur_lbs=cur, prev_lbs=prev, safety=sfty, excess=exc)
        actual = o.remaining()
        assert actual == expected, \
            f'[{label}] remaining()={actual!r}, expected {expected!r}'

def test_remaining_returns_demandqty():
    o = make_order(cur_lbs=10.0, prev_lbs=2.0, safety=1.0, excess=0.5)
    r = o.remaining()
    assert isinstance(r, DemandQty), \
        f'remaining() returned {type(r).__name__}, expected DemandQty'

# ---- item independence ----------------------------------------------------
# The Greige's own .safety should not influence Order.remaining() — Order
# tracks an explicit safety argument independent of the item's target.
def test_item_safety_does_not_leak_into_remaining():
    expected = DemandQty(cumulative=100.0, regular=100.0, safety=0.0, excess=0.0)
    for item_safety in (0.0, 50.0, 500.0):
        g = make_greige(safety=item_safety)
        o = make_order(item=g, cur_lbs=100.0, prev_lbs=0.0, safety=0.0, excess=0.0)
        actual = o.remaining()
        assert actual == expected, \
            f'[item.safety={item_safety}] remaining()={actual!r}, expected {expected!r}'

def main():
    test_id_format()
    test_id_zero_priority()
    test_prefix()
    test_item_returns_input()
    test_due_date_returns_input()
    print('All identity property cases passed.')
    test_remaining_no_args()
    print(f'All {len(REMAINING_CASES)} remaining() cases passed.')
    test_remaining_returns_demandqty()
    print('remaining() return type case passed.')
    test_item_safety_does_not_leak_into_remaining()
    print('Item safety independence case passed.')

if __name__ == '__main__':
    main()
