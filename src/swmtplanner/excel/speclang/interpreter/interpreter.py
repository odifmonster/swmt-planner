#!/usr/bin/env python

from typing import TYPE_CHECKING, Any
from swmtplanner.excel.speclang.parser import trees

State = dict[str, Any]

def interp_atom(state: State, atom: trees.Atom):
    if atom.kind == trees.AtomType.NAME:
        varname = atom.value
        if varname not in state:
            raise NameError(f'unknown identifier \'{varname}\'')
        return state[varname]
    return atom.value

def interp_binop(state: State, binop: trees.BinopExp):
    left = interp_exp(state, binop.left)
    if type(left) not in (int, float):
        raise TypeError(f'arithmetic operator invalid for type \'{type(left).__name__}\'')
    right = interp_exp(state, binop.right)
    if type(right) not in (int, float):
        raise TypeError(f'arithmetic operator invalid for type \'{type(left).__name__}\'')
    
    match binop.op.kind:
        case trees.BinopType.MULT:
            return left * right
        case trees.BinopType.DIV:
            if right == 0:
                raise ValueError('division by 0')
            return left / right
        case trees.BinopType.MOD:
            return left % right
        case trees.BinopType.ADD:
            return left + right
        case trees.BinopType.SUB:
            return left - right

def interp_exp(state: State, exp: trees.Exp):
    if isinstance(exp, trees.Atom):
        return interp_atom(state, exp)
    return 0