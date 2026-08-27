#!/usr/bin/env python

from swmtplanner.support import HasID


LUSTER_CODES = {
    'Semi-Dull': 'SDL',
    'Solution Dyed Black': 'DBK',
    'Solution Dyed Grey': 'DGY',
}

MATERIAL_CODES = {
    'Polyester': 'POL',
}

ATTR_CODES = {
    'Cationic': 'CAT',
    'Repreve': 'REP',
    'Textured': 'TX',
}


class Yarn(HasID[str]):

    def __init__(self, denier: int, fill_ct: int, luster: str, material: str,
                 attributes: list[str]):
        if luster not in LUSTER_CODES:
            raise ValueError(f'unknown luster {luster!r}')
        if material not in MATERIAL_CODES:
            raise ValueError(f'unknown material {material!r}')
        unknown = [a for a in attributes if a not in ATTR_CODES]
        if unknown:
            raise ValueError(f'unknown yarn attributes {unknown!r}')

        self._denier = denier
        self._fill_ct = fill_ct
        self._luster = luster
        self._material = material
        self._attributes = tuple(sorted(attributes))

        parts = [f'{denier}D{fill_ct}F', LUSTER_CODES[luster],
                 MATERIAL_CODES[material]]
        parts += [ATTR_CODES[a] for a in self._attributes]
        self._id = '-'.join(parts)

    @property
    def id(self) -> str:
        return self._id

    @property
    def denier(self) -> int:
        return self._denier

    @property
    def fill_ct(self) -> int:
        return self._fill_ct

    @property
    def luster(self) -> str:
        return self._luster

    @property
    def material(self) -> str:
        return self._material

    @property
    def attributes(self) -> tuple[str, ...]:
        return self._attributes
