#!/usr/bin/env python

import sys

from swmtplanner.excel.engine import *

type Tree = parser.trees.Stmt | parser.trees.Exp | parser.trees.Binop | parser.trees.Atom

def repr_atom(a: parser.trees.Atom) -> str:
    val_rep = repr(a.value)
    if a.kind == parser.trees.AtomType.NAME:
        val_rep = a.value
    return f'({a.kind.name} {val_rep})'

def repr_binop(b: parser.trees.Binop) -> str:
    return f'Binop.{b.kind.name}'

def repr_list(l: list[Tree], indent: str = '') -> str:
    lines = []
    for t in l:
        lines.append(repr_tree(t, indent=indent+'  '))
    joiner = ',\n' + indent + '  '
    prefix = '[\n' + indent + '  '
    suffix = '\n' + indent + ']'
    return prefix + joiner.join(lines) + suffix

def repr_tree(t: Tree, indent: str = '') -> str:
    if isinstance(t, parser.trees.Atom):
        return repr_atom(t)
    if isinstance(t, parser.trees.Binop):
        return repr_binop(t)
    if type(t) is list or isinstance(t, parser.trees.ListExp):
        lval = t
        if isinstance(t, parser.trees.ListExp):
            lval = t.exps
        return repr_list(lval, indent=indent)
    
    kind = ''
    if isinstance(t.kind, parser.trees.StmtType):
        kind = 'Stmt'
    else:
        kind = 'Exp'
    
    prefix = f'{kind}.{t.kind.name}(\n' + indent + '  '
    suffix = '\n' + indent + ')'
    lines = []
    
    for field in t._fields:
        if field == 'kind': continue
        fval = getattr(t, field)
        if isinstance(fval, parser.trees.Empty): continue
        lines.append(field + '=' + repr_tree(fval, indent=indent+'  '))
    
    joiner = ',\n' + indent + '  '
    return prefix + joiner.join(lines) + suffix

def main(fname: str):
    buffer = open(fname)
    f = file.File(buffer)
    tstream = tokenized.Tokenized(f)
    stmts = parser.parse(tstream)
    f.close()
    
    for stmt in stmts:
        print(repr_tree(stmt))

if __name__ == '__main__':
    main(sys.argv[1])