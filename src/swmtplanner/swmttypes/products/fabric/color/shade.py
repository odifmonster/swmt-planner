#!/usr/bin/env python

from enum import Enum, auto

class Shade(Enum):
    EMPTY = auto()
    HEAVYSTRIP = auto()
    STRIP = auto()
    SOLUTION = auto()
    LIGHT1 = auto()
    LIGHT2 = auto()
    MEDIUM = auto()
    BLACK = auto()

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
            case 'LIGHT1': return cls.LIGHT1
            case 'LIGHT2': return cls.LIGHT2
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
            case 0: return cls.LIGHT1
            case 1: return cls.LIGHT2
            case 2: return cls.MEDIUM
            case 3: return cls.BLACK
            case 4: return cls.SOLUTION
            case 5: return cls.EMPTY
            case 6: return cls.HEAVYSTRIP
            case 7: return cls.STRIP
            case _:
                raise ValueError(f'Unknown shade value {val}')