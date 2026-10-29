#!/usr/bin/env python

from dataclasses import dataclass, replace

from ....support import HasID
from .yarn import Yarn


@dataclass(frozen=True, eq=False)
class BeamSetDesc(HasID[str]):
    yarn: Yarn
    beam_count: int
    end_count: int

    @property
    def id(self) -> str:
        return f'{self.yarn.id}-{self.end_count}-{self.beam_count}'

    def split(self, n: int) -> list['BeamSetDesc']:
        if n < 1:
            raise ValueError(f'cannot split a beam set into {n} parts')
        if self.end_count % n != 0:
            raise ValueError(f'{self.end_count} ends do not divide evenly into {n} parts')
        part = replace(self, end_count=self.end_count // n)
        return [part for _ in range(n)]

    @classmethod
    def merge(cls, *bsets: 'BeamSetDesc') -> 'BeamSetDesc':
        if not bsets:
            raise ValueError('cannot merge zero beam sets')
        first = bsets[0]
        if any(b != first for b in bsets[1:]):
            raise ValueError('cannot merge beam sets that are not identical')
        return replace(first, end_count=first.end_count * len(bsets))
