#!/usr/bin/env python

from typing import NamedTuple

from swmtplanner.products import *

class _BSProps(NamedTuple):
    denier: int
    ends: int
    spools: int
    split_lease: bool
    yarn_desc: str

ANSWERS = {
    "70D WHT TX 1172X4": _BSProps(70, 1172, 4, False, "WHT TX"),
    "40D WHT 1172X4 S/L": _BSProps(40, 1172, 4, True, "WHT"),
    "40D W CAT 1172X5 S/L": _BSProps(40, 1172, 5, True, "W CAT"),
    "70D WHT TX 1340X4": _BSProps(70, 1340, 4, False, "WHT TX")
}

def main():
    for id, expected in ANSWERS.items():
        bs = BeamSet(id)
        assert bs.id == id, f'{id!r}: id={bs.id!r}, expected {id!r}'
        assert bs.denier == expected.denier, \
            f'{id!r}: denier={bs.denier!r}, expected {expected.denier!r}'
        assert bs.ends == expected.ends, \
            f'{id!r}: ends={bs.ends!r}, expected {expected.ends!r}'
        assert bs.spools == expected.spools, \
            f'{id!r}: spools={bs.spools!r}, expected {expected.spools!r}'
        assert bs.split_lease == expected.split_lease, \
            f'{id!r}: split_lease={bs.split_lease!r}, expected {expected.split_lease!r}'
        assert bs.yarn_desc == expected.yarn_desc, \
            f'{id!r}: yarn_desc={bs.yarn_desc!r}, expected {expected.yarn_desc!r}'
    print(f'All {len(ANSWERS)} BeamSet cases passed.')

if __name__ == '__main__':
    main()