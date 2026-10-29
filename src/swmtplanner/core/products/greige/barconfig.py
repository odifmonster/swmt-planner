#!/usr/bin/env python

from dataclasses import dataclass


@dataclass(frozen=True)
class BarConfig:
    num: int
    runlen: float
    pct: float
    stitch: str
