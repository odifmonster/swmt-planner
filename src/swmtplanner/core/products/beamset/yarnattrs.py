#!/usr/bin/env python

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class YarnAttrs:
    textured: bool
    cationic: bool
    recycled: bool

    @classmethod
    def from_int(cls, code: int) -> 'YarnAttrs':
        nbits = len(fields(cls))
        if not 0 <= code < (1 << nbits):
            raise ValueError(f'attribute code {code} out of range for {nbits} attributes')
        bits = [bool((code >> (nbits - 1 - i)) & 1) for i in range(nbits)]
        return cls(*bits)

    def __int__(self) -> int:
        code = 0
        for f in fields(self):
            code = (code << 1) | int(getattr(self, f.name))
        return code
