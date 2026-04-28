#!/usr/bin/env python

import sys

from swmtplanner.excel import *

def print_token(t: tstream.tokens.Token):
    print(f'Token({t.kind}[{repr(t.raw)}], line={t.start.line}, col={t.start.col})')

def main(path: str):
    f = File(path)
    toks = tstream.TStream(f)
    while not toks.has_ended:
        print(toks.advance())

if __name__ == '__main__':
    main(sys.argv[1])