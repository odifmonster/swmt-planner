#!/usr/bin/env python

import functools

from ..tokenized import *
from .trees import *

def _match_tok(tstream: Tokenized, tgt: TokType | frozenset[TokType],
               converter = None):
    if type(tgt) is frozenset:
        is_tgt = lambda t: t.kind in tgt
    else:
        is_tgt = lambda t: t.kind == tgt

    if converter is None:
        converter = lambda _: Empty()

    if tstream.ended:
        return None, 0
    
    tok = tstream.advance()
    if is_tgt(tok):
        return converter(tok), 1
    tstream.backup(1)
    return None, 0

@functools.cache
def _get_tok_matcher(tgt: TokType | frozenset[TokType],
                     converter = None):
    def wrapper(tstream: Tokenized):
        return _match_tok(tstream, tgt, converter=converter)
    return wrapper

def _match_all(tstream: Tokenized, funcs, alt_vals = None):
    if alt_vals is None:
        alt_vals = [None for _ in range(len(funcs))]

    total = 0
    items = []
    for func, alt_val in zip(funcs, alt_vals):
        res, consumed = func(tstream)
        total += consumed
        if res is None and alt_val is None:
            tstream.backup(total)
            return None, 0
        if res is None:
            items.append(alt_val)
        else:
            items.append(res)
    
    return items, total

def _match_one(tstream: Tokenized, funcs):
    for func in funcs:
        res, consumed = func(tstream)
        if res is not None:
            return res, consumed
    return None, 0

def _get_atom(tok: Token):
    match tok.kind:
        case TokType.INT:
            val = int(tok.value)
        case TokType.FLOAT:
            val = float(tok.value)
        case TokType.STRING:
            val = tok.value[1:-1]
        case TokType.NAME:
            val = tok.value
        case _:
            raise RuntimeError('FATAL: something unexpected occurred')
    return Atom(AtomType[tok.kind.name], val, tok)

def _match_atom(tstream: Tokenized, kind = None):
    if kind is None:
        tgt = frozenset([TokType.INT, TokType.FLOAT, TokType.STRING,
                         TokType.NAME])
    else:
        tgt = kind
    return _match_tok(tstream, tgt, converter=_get_atom)

def _match_group(tstream: Tokenized):
    return _match_all(tstream,
                      [_get_tok_matcher(TokType.LPAREN),
                       _match_exp,
                       _get_tok_matcher(TokType.RPAREN)])

def _match_access(tstream: Tokenized):
    owner, total = _match_atom(tstream, kind=TokType.NAME)
    if owner is None:
        return None, 0

    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(TokType.DOT),
                      lambda s: _match_atom(s, kind=TokType.NAME)])
        
        if items is None:
            break

        total += consumed
        owner = AccessExp(owner, items[1])
    
    return owner, total

def _match_exps(tstream: Tokenized):
    exp, total = _match_exp(tstream)
    if exp is None:
        return None, 0
    
    exps = [exp]
    while True:
        items, consumed = _match_all(tstream, [_get_tok_matcher(TokType.COMMA),
                                               _match_exp])
        
        if items is None:
            break

        total += consumed
        exps.append(items[1])
    
    return exps, total

def _match_call(tstream: Tokenized):
    res, total = _match_all(
        tstream, [lambda s: _match_atom(s, kind=TokType.NAME),
                  _get_tok_matcher(TokType.LPAREN),
                  _match_exps,
                  _get_tok_matcher(TokType.RPAREN)],
                 [None, None, [], None])
    if res is None:
        return None, 0
    
    func = CallExp(res[0], res[2])
    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(TokType.LPAREN),
                      _match_exps,
                      _get_tok_matcher(TokType.RPAREN)],
            alt_vals=[None, [], None])
        
        if items is None:
            break

        total += consumed
        func = CallExp(func, items[1])
    
    return func, total

def _match_unpack(tstream: Tokenized):
    star, total = _match_tok(tstream, TokType.STAR)
    if star is not None:
        child, consumed = _match_unpack(tstream)
        if child is None:
            tstream.backup(total)
            return None, 0
        total += consumed
        return UnpackExp(child), total
    res, total = _match_one(tstream, [_match_call, _match_access, _match_group,
                                      _match_atom, _match_list])
    return res, total

def _match_prod(tstream: Tokenized):
    left, total = _match_unpack(tstream)
    if left is None:
        return None, 0
    
    op_map = {
        TokType.STAR: Binop.MULT, TokType.SLASH: Binop.DIV,
        TokType.PCT: Binop.MOD
    }

    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(TokType.STAR,
                                       converter=lambda t: op_map[t.kind]),
                      _match_unpack])
        
        if items is None:
            break

        total += consumed
        left = BinopExp(items[0], left, items[1])
    
    return left, total

def _match_sum(tstream: Tokenized):
    left, total = _match_prod(tstream)
    if left is None:
        return None, 0
    
    op_map = {
        TokType.PLUS: Binop.ADD, TokType.MINUS: Binop.SUB
    }

    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(TokType.STAR,
                                       converter=lambda t: op_map[t.kind]),
                      _match_prod])
        
        if items is None:
            break

        total += consumed
        left = BinopExp(items[0], left, items[1])
    
    return left, total

def _match_pattern(tstream: Tokenized):
    items, total = _match_all(
        tstream, [lambda s: _match_atom(s, kind=TokType.NAME),
                  _get_tok_matcher(TokType.ARROW),
                  _match_sum])
    if items is not None:
        return PatternExp(items[0], items[2]), total
    return None, 0

def _match_rng(tstream: Tokenized):
    items, total = _match_all(
        tstream, [_match_sum, _get_tok_matcher(TokType.TO),
                  _match_sum])
    if items is not None:
        return RngExp(items[0], items[2]), total
    return None, 0

def _match_list(tstream: Tokenized):
    items, total = _match_all(
        tstream, [_get_tok_matcher(TokType.LBRACK),
                  _match_exps,
                  _get_tok_matcher(TokType.RBRACK)],
                 [None, [], None])
    if items is not None:
        return ListExp(items[1]), total
    return None, 0

def _match_exp(tstream: Tokenized):
    return _match_one(tstream, [_match_rng, _match_pattern, _match_sum])

def _match_names(tstream: Tokenized):
    name, total = _match_atom(tstream, kind=TokType.NAME)
    if name is None:
        return None, 0
    
    names = [name]
    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(TokType.COMMA),
                      lambda s: _match_atom(s, kind=TokType.NAME)])
        
        if items is None:
            break

        total += consumed
        names.append(items[1])
    
    return names, total

def _match_use(tstream: Tokenized):
    items, total = _match_all(
        tstream, [_get_tok_matcher(TokType.USE),
                  _match_names,
                  _get_tok_matcher(TokType.FROM),
                  lambda s: _match_atom(s, kind=TokType.NAME)])
    if items is not None:
        return UseStmt(items[1], items[3]), total
    return None, 0

def _match_assign(tstream: Tokenized):
    items, total = _match_all(
        tstream, [lambda s: _match_atom(s, kind=TokType.NAME),
                  _get_tok_matcher(TokType.EQ), _match_exp])
    if items is not None:
        return AssignStmt(items[0], items[2]), total
    return None, 0

def _match_simple_stmt(tstream: Tokenized):
    stmt, total = _match_one(tstream, [_match_use, _match_assign])
    if stmt is None:
        return None, 0
    
    end, consumed = _match_tok(tstream, TokType.NEWLINE)
    if end is None:
        tstream.backup(total)
        return None, 0
    
    total += consumed
    return stmt, total

def _match_stmts(tstream: Tokenized):
    stmts = []
    total = 0

    while True:
        stmt, consumed = _match_stmt(tstream)
        if stmt is None:
            break
        total += consumed
        stmts.append(stmt)
    
    return stmts, total

def _match_block(tstream: Tokenized):
    items, total = _match_all(
        tstream, [_get_tok_matcher(TokType.LBRACK),
                  lambda s: _match_atom(s, kind=TokType.NAME),
                  _get_tok_matcher(TokType.RBRACK),
                  lambda s: _match_atom(s, kind=TokType.NAME),
                  _get_tok_matcher(TokType.COLON),
                  _get_tok_matcher(TokType.NEWLINE),
                  _get_tok_matcher(TokType.INDENT),
                  _match_stmts,
                  _get_tok_matcher(TokType.DEDENT)])
    if items is not None:
        if len(items[7]) == 0:
            tstream.backup(total)
            return None, 0
        return BlockStmt(items[1], items[3], items[7]), total
    return None, 0

def _match_stmt(tstream: Tokenized):
    return _match_one(tstream, [_match_simple_stmt, _match_block])

def parse(tstream: Tokenized):
    stmts, _ = _match_stmts(tstream)
    end, _ = _match_tok(tstream, TokType.END)
    if end is None:
        bad_tok = tstream.last_tok
        msg = f'Line {bad_tok.start.line} at column {bad_tok.start.column}:'
        msg += ' Failed to parse'
        raise SyntaxError(msg)
    return stmts