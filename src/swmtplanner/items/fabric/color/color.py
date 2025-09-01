#!/usr/bin/env python

from typing import NewType

from swmtplanner.support import SwmtBase, HasID

Shade = NewType('Shade', str)
EMPTY = Shade('0_EMPTY')
HEAVYSTRIP = Shade('1_HEAVYSTRIP')
STRIP = Shade('2_STRIP')
SOLUTION = Shade('3_SOLUTION')
LIGHT = Shade('4_LIGHT')
MEDIUM = Shade('5_MEDIUM')
BLACK = Shade('6_BLACK')

def _get_shade(rawval):
    if type(rawval) is int:
        match rawval:
            case 1: return LIGHT
            case 2: return MEDIUM
            case 3: return BLACK
            case 4: return SOLUTION
            case 5: return EMPTY
            case 6: return HEAVYSTRIP
            case 7: return STRIP
            case _:
                raise ValueError(f'Unknown shade value: {rawval}')
    if type(rawval) is str:
        match rawval:
            case 'EMPTY': return EMPTY
            case 'HEAVYSTRIP': return HEAVYSTRIP
            case 'STRIP': return STRIP
            case 'SOLUTION': return SOLUTION
            case 'LIGHT': return LIGHT
            case 'MEDIUM': return MEDIUM
            case 'BLACK': return BLACK
            case _:
                raise ValueError(f'Unknown shade value: {repr(rawval)}')
    raise TypeError(f'Invalid type for shade: \'{type(rawval).__name__}\'')

class Color(SwmtBase, HasID[str], read_only=('id','name','shade','soil')):

    def __init__(self, number, name, shadeval):
        shade = _get_shade(shadeval)
        if shade == EMPTY:
            soil = 0
        elif shade == HEAVYSTRIP:
            soil = -63
        elif shade == STRIP:
            soil = -21
        elif shade == SOLUTION:
            soil = 1
        elif shade == LIGHT:
            soil = 2
        elif shade == MEDIUM:
            soil = 3
        else:
            soil = 7
        SwmtBase.__init__(self, _id=f'{number:05}', _name=name, _shade=shade,
                          _soil=soil)
        
    @property
    def prefix(self):
        return 'Color'
    
    def get_strip(self, soil):
        if self.shade == LIGHT and soil >= 20:
            if soil - 21 >= 10:
                return HEAVYSTRIP
            return STRIP
        if self.shade == MEDIUM and soil >= 38:
            return STRIP
        return None