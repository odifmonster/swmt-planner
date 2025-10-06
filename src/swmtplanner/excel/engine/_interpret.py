#!/usr/bin/env python

from collections import namedtuple
from enum import Enum, auto
import datetime as dt

from .parser import trees

class ValType(Enum):
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    FUNC = auto()

Value = namedtuple('Value', ['dtype', 'data'])

type _Context = dict[str, Value | _Context]

def _coerce_value(msg: str, val: Value | list | dict, coerce_type: ValType) -> Value:
    cannot_coerce = 'Cannot coerce {} to {}'

    if type(val) in (list, dict):
        msg += cannot_coerce.format(type(val).__name__.upper(), coerce_type.name)
        raise TypeError(msg)

    if val.dtype == coerce_type:
        return val
    
    if val.dtype in (ValType.STRING, ValType.FUNC):
        msg += cannot_coerce.format(val.dtype.name, coerce_type.name)
        raise TypeError(msg)
    if coerce_type == ValType.FUNC:
        msg += cannot_coerce.format(val.dtype.name, 'FUNC')
        raise TypeError(msg)
    
    match coerce_type:
        case ValType.INT:
            if val.data != int(val.data):
                msg += cannot_coerce.format('INT', val.dtype.name)
                raise TypeError(msg)
            return Value(ValType.INT, int(val.data))
        case ValType.FLOAT:
            return Value(ValType.FLOAT, float(val.data))
        case ValType.STRING:
            return Value(ValType.STRING, str(val.data))

def _interp_atom(x: trees.Atom, glbl: _Context, cur: _Context):
    msg = f'Line {x.token.start.line} at column {x.token.start.column}: '
    if x.kind == trees.AtomType.NAME:
        if x.value == 'this':
            return cur
        
        if x.value not in glbl:
            msg += f'Unknown variable \'{x.value}\''
            raise NameError(msg)
        
        return glbl[x.value]
    return Value(ValType[x.kind.name], x.value)

def _interp_access(x: trees.AccessExp, glbl: _Context, cur: _Context):
    owner: _Context = _interp_exp(x.owner, glbl, cur)
    if type(owner) is not dict:
        pos = x.r_dot.token.start
        msg = f'Line {pos.line} at column {pos.column}: '
        dtype = 'LIST' if type(owner) is list else owner.dtype.name
        msg += f'{dtype} has no members to access'
        raise TypeError(msg)
    return _interp_atom(x.member, owner, owner)

def _interp_binop(x: trees.BinopExp, glbl: _Context, cur: _Context):
    left: Value = _interp_exp(x.left, glbl, cur, coerce_type=ValType.FLOAT)
    rtype = ValType.INT if x.op.kind == trees.BinopType.MOD else ValType.FLOAT
    right: Value = _interp_exp(x.right, glbl, cur, coerce_type=rtype)

    if x.op.kind.name in ('MOD', 'DIV') and right.data == 0:
        pos = x.op.token.start
        msg = f'Line {pos.line} at column {pos.column}: '
        msg += f'{x.op.kind.name} operation invalid on {repr(left.data)} and {repr(right.data)}'
        raise ValueError(msg)
    
    match x.op.kind:
        case trees.BinopType.MULT:
            res = left.data * right.data
        case trees.BinopType.DIV:
            res = left.data / right.data
        case trees.BinopType.MOD:
            res = left.data % right.data
        case trees.BinopType.ADD:
            res = left.data + right.data
        case trees.BinopType.SUB:
            res = left.data - right.data
    
    pos = x.op.token.start
    msg = f'Line {pos.line}'

    return Value(ValType.FLOAT, res)

def _build_list(x: list[trees.Exp], glbl: _Context, cur: _Context):
    res = []
    for exp in x:
        if exp.kind == trees.ExpType.Unpack:
            add_items = _interp_exp(exp.child, glbl, cur)
            if type(add_items) is not list:
                pos = exp.r_star.token.start
                msg = f'Line {pos.line} at column {pos.column}: '
                msg += f'Expression not unpackable'
                raise TypeError(msg)
            res += add_items
        else:
            res.append(_interp_exp(exp, glbl, cur))
    return res

def _interp_call(x: trees.CallExp, glbl: _Context, cur: _Context):
    func: Value = _interp_exp(x.func, glbl, cur, coerce_type=ValType.FUNC)
    args = _build_list(x.args, glbl, cur)
    return func.data(*args)

def _interp_pattern(x: trees.PatternExp, glbl: _Context, cur: _Context):
    def wrapper(arg: Value):
        new_glbl = glbl.copy()
        new_glbl[x.var.value] = arg
        res = _interp_exp(x.exp, new_glbl, cur)
        return res
    return Value(ValType.FUNC, wrapper)

def _interp_rng(x: trees.RngExp, glbl: _Context, cur: _Context):
    pos = x.r_to.token.start
    msg = f'Line {pos.line}: '

    start = _interp_exp(x.start, glbl, cur)
    start = _coerce_value(msg, start, ValType.INT)

    stop = _interp_exp(x.stop, glbl, cur)
    stop = _coerce_value(msg, stop, ValType.INT)

    res = []
    for i in range(start.data, stop.data+1):
        res.append(Value(ValType.INT, i))
    
    return res

def _interp_exp(x: trees.Exp, glbl: _Context, cur: _Context, coerce_type = None):
    if isinstance(x, trees.Atom):
        pos = x.token.start
        msg = f'Line {pos.line} at column {pos.column}: '
        res = _interp_atom(x, glbl, cur)
    else:
        match x.kind:
            case trees.ExpType.Binop:
                pos = x.op.token.start
                msg = f'Line {pos.line}: '
                res = _interp_binop(x, glbl, cur)
            case trees.ExpType.Access:
                pos = x.r_dot.token.start
                msg = f'Line {pos.line}: '
                res = _interp_access(x, glbl, cur)
            case trees.ExpType.Call:
                msg = ''
                res = _interp_call(x, glbl, cur)
            case trees.ExpType.List:
                msg = ''
                res = _build_list(x.exps, glbl, cur)
            case trees.ExpType.Pattern:
                pos = x.r_arrow.token.start
                msg = f'Line {pos.line}: '
                res = _interp_pattern(x, glbl, cur)
            case trees.ExpType.Rng:
                pos = x.r_to.token.start
                msg = f'Line {pos.line}: '
                res = _interp_rng(x, glbl, cur)
            case _:
                # print(x)
                raise RuntimeError('FATAL: something unexpected occurred')
    
    if coerce_type is not None:
        res = _coerce_value(msg, res, coerce_type)
    return res

def _interp_assign(x: trees.AssignStmt, glbl: _Context, cur: _Context):
    res = _interp_exp(x.value, glbl, cur)
    cur[x.name.value] = res

def _interp_block(x: trees.BlockStmt, glbl: _Context, cur: _Context):
    cur[x.name.value] = { '@dtype': x.dtype.value }
    new_block = cur[x.name.value]

    for stmt in x.stmts:
        _interp_stmt(stmt, glbl, new_block)

def _interp_args(x: trees.BlockStmt, glbl: _Context, **kwargs):
    glbl[x.name.value] = { '@dtype': 'Args' }
    args_block = glbl[x.name.value]
    
    for stmt in x.stmts:
        if stmt.kind != trees.StmtType.Assign:
            pos = stmt.dtype.token.start
            msg = f'Line {pos.line}: \'Args\' block must only contain assignments'
            raise RuntimeError(msg)
        
        pos = stmt.r_eq.token.start
        msg = f'Line {pos.line}: '

        if stmt.name.value not in kwargs:
            msg += f'No value provided for argument {repr(stmt.name.value)}'
            raise RuntimeError(msg)
        if not isinstance(stmt.value, trees.Atom) or stmt.value.kind != trees.AtomType.NAME:
            msg += 'Invalid argument value'
            raise RuntimeError(msg)
        
        arg_val = kwargs[stmt.name.value]
        if stmt.value.value in ('Date1', 'Date2'):
            if not isinstance(arg_val, dt.datetime):
                raise RuntimeError(f'{repr(stmt.name.value)} must be a date')
            if stmt.value.value == 'Date1':
                args_block[stmt.name.value] = Value(ValType.STRING, arg_val.strftime('%Y%m%d'))
            else:
                m = arg_val.month
                d = arg_val.day
                args_block[stmt.name.value] = Value(ValType.STRING, f'{m}-{d}')
        else:
            msg += f'Unknown argument type {repr(stmt.value.value)}'
            raise NameError(msg)

def _interp_stmt(x: trees.Stmt, glbl: _Context, cur: _Context):
    match x.kind:
        case trees.StmtType.Assign:
            _interp_assign(x, glbl, cur)
        case trees.StmtType.Block:
            _interp_block(x, glbl, cur)

def _builtin_concat(*args: *tuple[Value, ...]):
    res = ''
    for a in args:
        a_str = _coerce_value('', a, ValType.STRING)
        res += a_str.data
    return Value(ValType.STRING, res)

def _builtin_map(*args):
    if len(args) != 2:
        raise RuntimeError('\'Map\' expects 2 arguments')
    
    arr, func = args
    if type(arr) is not list:
        raise RuntimeError('First argument of \'Map\' must be a list')
    func = _coerce_value('', func, ValType.FUNC)

    return list(map(func.data, arr))

def interpret(file: list[trees.Stmt], **kwargs):
    glbl = {
        'Map': Value(ValType.FUNC, _builtin_map),
        'Concat': Value(ValType.FUNC, _builtin_concat)
    }

    for stmt in file:
        if stmt.kind == trees.StmtType.Block and stmt.dtype.value == 'Args':
            _interp_args(stmt, glbl, **kwargs)
        else:
            _interp_stmt(stmt, glbl, glbl)
    return glbl