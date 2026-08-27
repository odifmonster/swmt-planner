#!/usr/bin/env python

from swmtplanner.support import HasID

from .yarn import Yarn


class BeamSetItem(HasID[str]):

    def __init__(self, beams: int, ends: int, yarn: Yarn, is_split: bool):
        self._beams = beams
        self._ends = ends
        self._yarn = yarn
        self._is_split = is_split
        self._id = f'{yarn.id} {ends}X{beams}' + (' S/L' if is_split else '')

    @property
    def id(self) -> str:
        return self._id

    @property
    def beams(self) -> int:
        return self._beams

    @property
    def ends(self) -> int:
        return self._ends

    @property
    def yarn(self) -> Yarn:
        return self._yarn

    @property
    def is_split(self) -> bool:
        return self._is_split
