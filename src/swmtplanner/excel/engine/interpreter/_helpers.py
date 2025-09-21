#!/usr/bin/env python

from collections import namedtuple
from enum import Enum, auto

class ValDType(Enum):
    RAW = auto()
    INT = auto()
    FLOAT = auto()
    STR = auto()
    INT_LIST = auto()
    FLOAT_LIST = auto()
    STR_LIST = auto()
    INT_SRS = auto()
    FLOAT_SRS = auto()
    STR_SRS = auto()
    DATAFRAME = auto()

RawVal = namedtuple('RawVal', ['ast'])