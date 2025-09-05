#!/usr/bin/env python

from .parser import Variable, parse

def get_excel_info(buffer):
    ast = parse(buffer)
    varnames = {}

    for stmt in ast:
        if isinstance(stmt, Variable):
            varnames[stmt.name] = stmt.value