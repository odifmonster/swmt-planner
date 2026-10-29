#!/usr/bin/env python

from dataclasses import dataclass

from ....support import HasID
from .yarnattrs import YarnAttrs

MATERIAL_CODES = {
    'polyester': 'P',
    'nylon': 'N',
    'lycra': 'L',
    'spandex': 'S',
    'acetate': 'A',
    'eptfe': 'E',
}

COLOR_CODES = {
    'white': 'WT',
    'grey': 'GY',
    'black': 'BK',
    'greenerblack': 'GB',
}

LUSTER_CODES = {
    'dull': 'D',
    'semidull': 'S',
    'bright': 'B',
    'clear': 'C',
}


@dataclass(frozen=True, eq=False)
class Yarn(HasID[str]):
    denier: int
    material: str
    color: str
    luster: str
    attrs: YarnAttrs

    @property
    def id(self) -> str:
        return (f'{self.denier}{MATERIAL_CODES[self.material]}'
                f'{COLOR_CODES[self.color]}{LUSTER_CODES[self.luster]}'
                f'{int(self.attrs):02d}')


@dataclass(frozen=True, eq=False)
class Merge(HasID[str]):
    id: str
    yarn: Yarn
    vendor: str
