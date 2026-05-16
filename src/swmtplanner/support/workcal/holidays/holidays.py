#!/usr/bin/env python

from collections import namedtuple
import json

FlexDate = namedtuple('FlexDate', ['name', 'month', 'weekday', 'n'])
FixedDate = namedtuple('FixedDate', ['name', 'month', 'day'])

def load_holidays(path):
    ret = []

    with open(path) as f:
        holidays = json.load(f)
        if not type(holidays) is list:
            raise TypeError('holidays file must contain a list of holiday objects')
        
        for h in holidays:
            if not type(h) is dict:
                raise TypeError('elements of holidays list must be objects')
            
            if h['kind'] == 'fixed':
                ret.append(FixedDate(name=h['name'],
                                     month=int(h['month']),
                                     day=int(h['day'])))
            else:
                ret.append(FlexDate(name=h['name'],
                                    month=int(h['month']),
                                    weekday=int(h['weekday']),
                                    n=int(h['n'])))
    
    return ret