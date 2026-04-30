#!/usr/bin/env python

from collections import namedtuple

FixedDate = namedtuple('FixedDate', ['month', 'day'])
FlexDate = namedtuple('FlexDate', ['month', 'weekday', 'n'])

HOLIDAYS = {
    'new-years': FixedDate(month=1, day=1),
    'mlk': FlexDate(month=1, weekday=0, n=3),
    'washington': FlexDate(month=2, weekday=0, n=3),
    'memorial': FlexDate(month=5, weekday=0, n=-1),
    'juneteenth': FixedDate(month=6, day=19),
    'independence': FixedDate(month=7, day=4),
    'labor': FlexDate(month=9, weekday=0, n=1),
    'columbus': FlexDate(month=10, weekday=0, n=2),
    'veterans': FixedDate(month=11, day=11),
    'thanksgiving': FlexDate(month=11, weekday=3, n=4),
    'christmas': FixedDate(month=12, day=25)
}