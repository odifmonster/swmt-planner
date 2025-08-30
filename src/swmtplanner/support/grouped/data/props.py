#!/usr/bin/env python

def match_props(data, prop_names, prop_vals):
    return all(map(lambda x: getattr(data, x[0]) == x[1], zip(prop_names, prop_vals)))

def repr_props(prop_names, prop_vals, indent = '  '):
    lines = list(map(lambda x: indent + f'{x[0]}={repr(x[1])}',
                     zip(prop_names, prop_vals)))
    return '\n'.join(lines)