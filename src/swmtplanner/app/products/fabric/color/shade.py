#!/usr/bin/env python

from enum import Enum
from functools import total_ordering

@total_ordering
class Shade(Enum):
    EMPTY = 0
    HEAVYSTRIP = 1
    STRIP = 2
    SOLUTION = 3
    LIGHT = 4
    MEDIUM = 5
    BLACK = 6

    @classmethod
    def from_str(cls, val):
        if type(val) is not str:
            msg = f'Cannot call Shade.from_str on type \'{type(val).__name__}\''
            raise TypeError(msg)
        match val:
            case 'EMPTY': return cls.EMPTY
            case 'HEAVYSTRIP': return cls.HEAVYSTRIP
            case 'STRIP': return cls.STRIP
            case 'SOLUTION': return cls.SOLUTION
            case 'LIGHT': return cls.LIGHT
            case 'MEDIUM': return cls.MEDIUM
            case 'BLACK': return cls.BLACK
            case _:
                raise ValueError(f'Unknown shade value \'{val}\'')
    
    @classmethod
    def from_int(cls, val):
        if type(val) is not int:
            msg = f'Cannot call Shade.from_int on type \'{type(val).__name__}\''
            raise TypeError(msg)
        match val:
            case 1: return cls.LIGHT
            case 2: return cls.MEDIUM
            case 3: return cls.BLACK
            case 4: return cls.SOLUTION
            case 5: return cls.EMPTY
            case 6: return cls.HEAVYSTRIP
            case 7: return cls.STRIP
            case _:
                raise ValueError(f'Unknown shade value {val}')

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented