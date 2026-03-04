#!/usr/bin/env python

from ..parser.trees import *

def _sp_concat(*args):
    return ''.join([str(x) for x in args])

def _sp_map(vals, func):
    if not type(vals) is list:
        raise RuntimeError('First argument to Map must be a list.')
    if not callable(func):
        raise RuntimeError('Second argument to Map must be a function or pattern.')
    return [func(x) for x in vals]

def get_name(name: str, state: dict, at: Atom):
    if name not in state:
        if '#parent' not in state:
            at_pos = at.token.start
            raise NameError(f'Line {at_pos.line} at column {at_pos.column}: Unknown variable \'{name}\'.')
        return get_name(name, state['#parent'])
    return state[name]

def interp_atom(at: Atom, state: dict):
    match at.kind:
        case AtomType.INT:
            return int(at.value)
        case AtomType.FLOAT:
            return float(at.value)
        case AtomType.STRING:
            return at.value
        case AtomType.NAME:
            return get_name(at.value, state, at)

def build_list(exps: list[Exp], state: dict):
    res = []
    for exp in exps:
        if isinstance(exp.kind, AtomType):
            res.append(interp_atom(exp, state))
        elif exp.kind == ExpType.Unpack:
            val = interp_exp(exp, state)
            if not type(val) is list:
                raise TypeError('Cannot unpack non-list value.')
            res += val
        else:
            res.append(interp_exp(exp, state))
    return res

def build_pattern(tree: PatternExp, state: dict):
    sub_state = {'#parent': state}
    def func(x):
        sub_state[tree.var.value] = x
        return interp_exp(tree.exp, sub_state)
    return func

def interp_exp(tree: Exp, state: dict):
    if isinstance(tree.kind, AtomType):
        return interp_atom(tree, state)

    match tree.kind:
        case ExpType.Access:
            raise RuntimeError('Attribute access not yet supported.')
        case ExpType.Unpack:
            raise RuntimeError('Cannot unpack an expression outside of list context.')
        case ExpType.Rng:
            start = interp_exp(tree.start, state)
            if type(start) not in (int, float) or int(start) != start:
                raise TypeError('Range start value must be an integer.')
            start = int(start)
            stop = interp_exp(tree.stop, state)
            if type(stop) not in (int, float) or int(stop) != stop:
                raise TypeError('Range start value must be an integer.')
            stop = int(stop)
            if stop < start:
                raise ValueError(f'Invalid range values of {start} to {stop}')
            return list(range(start, stop+1))
        case ExpType.Binop:
            left = interp_exp(tree.left, state)
            right = interp_exp(tree.right, state)
            if type(left) not in (int, float) or type(right) not in (int, float):
                raise TypeError('Binary operations not supported between non-number values')
            
            match tree.op.kind:
                case BinopType.ADD:
                    return left + right
                case BinopType.SUB:
                    return left - right
                case BinopType.MOD:
                    return left % right
                case BinopType.MULT:
                    return left * right
                case BinopType.DIV:
                    return left / right
        case ExpType.List:
            return build_list(tree.exps, state)
        case ExpType.Pattern:
            return build_pattern(tree, state)
        case ExpType.Call:
            func = get_name(tree.func.value, state, tree.func)
            if not callable(func):
                raise TypeError('Cannot call a non-function value.')
            arg_list = build_list(tree.args, state)
            return func(*arg_list)

def interp_stmt(tree: Stmt, state: dict) -> None:
    if tree.kind == StmtType.Assign:
        val = interp_exp(tree.value, state)
        state[tree.name.value] = val
    else:
        new_state = {}

        if tree.dtype.value not in ('Excel', 'CSV', 'DatFile', 'Buildable'):
            raise NameError(f'\'{tree.dtype.value}\' is not a valid file type.')
        
        new_state['#parent'] = state
        new_state['#type'] = tree.dtype.value
        state[tree.name.value] = new_state

        for child in tree.stmts:
            interp_stmt(child, new_state)

def interpret(stmts: list[Stmt]) -> dict:
    glbl_state = {
        'Concat': _sp_concat, 'Map': _sp_map
    }
    for stmt in stmts:
        interp_stmt(stmt, glbl_state)
    return glbl_state