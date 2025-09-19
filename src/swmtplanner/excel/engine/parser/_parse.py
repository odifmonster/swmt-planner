#!/usr/bin/env python

import functools

from .. import lexer
from .trees import Empty, AtomType, Atom, RngExp, AccessExp, CallExp, \
    ListExp, UnpackExp, Binop, BinopExp, PatternExp, UseStmt, AssignStmt, \
    BlockStmt

_mk_empty = lambda _: Empty()

def _match_tok(lex: lexer.Lexer, tgt: lexer.TokType | list[lexer.TokType],
               converter = None):
    if type(tgt) is list:
        is_tgt = lambda t: t.kind in tgt
    else:
        is_tgt = lambda t: t.kind == tgt

    if converter is None:
        converter = _mk_empty

    if lex.ended:
        return None, 0
    
    tok = lex.advance()
    if is_tgt(tok):
        return converter(tok), 1
    lex.backup(1)
    return None, 0

def _get_match_tok(tgt: lexer.TokType | list[lexer.TokType],
                   converter = None):
    def wrapper(lex: lexer.Lexer):
        return _match_tok(lex, tgt, converter=converter)
    return wrapper

def _match_all(lex: lexer.Lexer, funcs, alt_vals = None):
    if alt_vals is None:
        alt_vals = [None for _ in range(len(funcs))]

    total = 0
    items = []
    for func, alt_val in zip(funcs, alt_vals):
        res, consumed = func(lex)
        total += consumed
        if res is None and alt_val is None:
            lex.backup(total)
            return None, 0
        if res is None:
            items.append(alt_val)
        else:
            items.append(res)
    
    return items, total

def _match_one(lex: lexer.Lexer, funcs):
    for func in funcs:
        res, consumed = func(lex)
        if res is not None:
            return res, consumed
    return None, 0

def _match_atom(lex: lexer.Lexer):
    at_map = {
        lexer.TokType.INT: AtomType.INT,
        lexer.TokType.FLOAT: AtomType.FLOAT,
        lexer.TokType.STRING: AtomType.STRING,
        lexer.TokType.NAME: AtomType.NAME
    }
    return _match_tok(lex, list(at_map.keys()),
                      converter=lambda t: Atom(at_map[t.kind], t))

def _match_group_exp(lex: lexer.Lexer):
    items, consumed = _match_all(
        lex, [_get_match_tok(lexer.TokType.LPAREN),
              _match_exp,
              _get_match_tok(lexer.TokType.RPAREN)])
    if items is None:
        return None, consumed
    return items[1], consumed

def _match_rng_exp(lex: lexer.Lexer):
    int_matcher = _get_match_tok(lexer.TokType.INT,
                                 converter=lambda t: Atom(AtomType.INT, t))
    items, consumed = _match_all(
        lex, [int_matcher,
              _get_match_tok(lexer.TokType.TO),
              int_matcher])
    if items is None:
        return None, consumed
    return RngExp(start=items[0], stop=items[2]), consumed

def _match_access_exp(lex: lexer.Lexer):
    owner, total = _match_tok(lex, lexer.TokType.REF,
                              converter=lambda t: Atom(AtomType.REF, t))
    if owner is None:
        return None, total
    
    while True:
        items, consumed = _match_all(
            lex, [_get_match_tok(lexer.TokType.DOT),
                  _get_match_tok(lexer.TokType.NAME,
                                 converter=lambda t: Atom(AtomType.NAME, t))])
        if items is None:
            break
        total += consumed
        member = items[1]
        owner = AccessExp(owner=owner, member=member)

    return owner, total

def _match_call_exp(lex: lexer.Lexer):
    func, total = _match_tok(lex, lexer.TokType.NAME,
                             converter=lambda t: Atom(AtomType.NAME, t))
    if func is None:
        return None, total
    
    while True:
        items, consumed = _match_all(
            lex, [_get_match_tok(lexer.TokType.LPAREN),
                  _match_exps,
                  _get_match_tok(lexer.TokType.RPAREN)],
            alt_vals=[None, [], None])
        total += consumed
        if items is None:
            break
        func = CallExp(func=func, args=items[1])
    
    return func, total

def _match_list_exp(lex: lexer.Lexer):
    items, total = _match_all(
        lex, [_get_match_tok(lexer.TokType.LBRACK),
              _match_exps,
              _get_match_tok(lexer.TokType.RBRACK)],
        alt_vals=[None, [], None])
    if items is None:
        return None, total
    return ListExp(exps=items[1]), total

def _match_unit_exp(lex: lexer.Lexer):
    return _match_one(lex, [_match_group_exp, _match_list_exp, _match_call_exp,
                            _match_access_exp, _match_rng_exp, _match_atom])

def _match_unpack_exp(lex: lexer.Lexer):
    star, total = _match_tok(lex, lexer.TokType.STAR)
    if star is None:
        return _match_unit_exp(lex)
    child, consumed = _match_unpack_exp(lex)
    total += consumed
    if child is None:
        lex.backup(total)
        return None, 0
    return UnpackExp(child=child), total

def _match_prod_exp(lex: lexer.Lexer):
    left, total = _match_unpack_exp(lex)
    if left is None:
        return None, 0
    
    op_map = {
        lexer.TokType.STAR: Binop.MULT,
        lexer.TokType.SLASH: Binop.DIV,
        lexer.TokType.MOD: Binop.MOD
    }
    while True:
        items, consumed = _match_all(
            lex, [_get_match_tok(list(op_map.keys()),
                                 converter=lambda t: op_map[t.kind]),
                  _match_unpack_exp])
        total += consumed
        if items is None:
            break
        left = BinopExp(op=items[0], left=left, right=items[1])
    
    return left, total

def _match_sum_exp(lex: lexer.Lexer):
    left, total = _match_prod_exp(lex)
    if left is None:
        return None, 0
    
    op_map = {
        lexer.TokType.PLUS: Binop.ADD,
        lexer.TokType.MINUS: Binop.SUB
    }
    while True:
        items, consumed = _match_all(
            lex, [_get_match_tok(list(op_map.keys()),
                                 converter=lambda t: op_map[t.kind]),
                  _match_prod_exp])
        total += consumed
        if items is None:
            break
        left = BinopExp(op=items[0], left=left, right=items[1])
    
    return left, total

def _match_pattern_exp(lex: lexer.Lexer):
    items, total = _match_all(
        lex, [_get_match_tok(lexer.TokType.NAME,
                             converter=lambda t: Atom(AtomType.NAME, t)),
              _get_match_tok(lexer.TokType.ARROW),
              _match_exp])
    if items is None:
        return None, 0
    return PatternExp(var=items[0], pattern=items[2]), total

def _match_exp(lex: lexer.Lexer):
    return _match_one(lex,
                      [_match_pattern_exp, _match_sum_exp])

def _match_exps(lex: lexer.Lexer):
    res, total = _match_exp(lex)

    exps = [res]
    while True:
        items, consumed = _match_all(
            lex, [_get_match_tok(lexer.TokType.COMMA),
                  _match_exp])
        total += consumed
        if items is None:
            break
        exps.append(items[1])

    return exps, total

def _match_names(lex: lexer.Lexer):
    name_matcher = _get_match_tok(lexer.TokType.NAME,
                                  converter=lambda t: Atom(AtomType.NAME, t))
    res, total = name_matcher(lex)
    if res is None:
        return None, 0
    
    names = [res]
    while True:
        items, consumed = _match_all(
            lex, [_get_match_tok(lexer.TokType.COMMA), name_matcher])
        total += consumed
        if items is None:
            break
        names.append(items[1])
    
    return names, total

def _match_use_stmt(lex: lexer.Lexer):
    items, total = _match_all(
        lex, [_get_match_tok(lexer.TokType.USE),
              _match_names,
              _get_match_tok(lexer.TokType.FROM),
              _get_match_tok(lexer.TokType.NAME,
                             converter=lambda t: Atom(AtomType.NAME, t)),
              _get_match_tok(lexer.TokType.NEWLINE)])
    if items is None:
        return None, 0
    return UseStmt(funcs=items[1], source=items[3]), total

def _match_assign_stmt(lex: lexer.Lexer):
    items, total = _match_all(
        lex, [_get_match_tok(lexer.TokType.NAME,
                             converter=lambda t: Atom(AtomType.NAME, t)),
              _get_match_tok(lexer.TokType.EQ),
              _match_exp,
              _get_match_tok(lexer.TokType.NEWLINE)])
    if items is None:
        return None, 0
    return AssignStmt(dest=items[0], source=items[2]), total

def _match_block_stmt(lex: lexer.Lexer):
    total = 0
    name_matcher = _get_match_tok(lexer.TokType.NAME,
                                  converter=lambda t: Atom(AtomType.NAME, t))

    items, consumed = _match_all(
        lex, [_get_match_tok(lexer.TokType.LBRACK),
              name_matcher,
              _get_match_tok(lexer.TokType.RBRACK)])
    total += consumed
    if items is not None:
        dtype = items[1]
    else:
        dtype = Empty()

    items, consumed = _match_all(
        lex, [name_matcher,
              _get_match_tok(lexer.TokType.COLON),
              _get_match_tok(lexer.TokType.NEWLINE),
              _get_match_tok(lexer.TokType.INDENT),
              _match_stmts,
              _get_match_tok(lexer.TokType.DEDENT)])
    total += consumed
    if items is None:
        lex.backup(total)
        return None, 0
    return BlockStmt(dtype=dtype, name=items[0], stmts=items[4]), total

def _match_stmts(lex: lexer.Lexer):
    total = 0
    stmts = []

    while True:
        stmt, consumed = _match_one(lex, [_match_use_stmt, _match_assign_stmt,
                                          _match_block_stmt])
        
        if stmt is None:
            break

        total += consumed
        stmts.append(stmt)

    return stmts, total

def parse(lex: lexer.Lexer):
    stmts, _ = _match_stmts(lex)
    if stmts is None:
        last = lex.last_tok
        msg = f'Line {last.start.line} at column {last.start.column}: '
        msg += 'Unable to parse'
        raise SyntaxError(msg)
    end, _ = _match_tok(lex, lexer.TokType.END)
    if end is None:
        last = lex.last_tok
        msg = f'Line {last.start.line} at column {last.start.column}: '
        msg += f'Unexpected {last.kind.name.lower()} token ({repr(last.value)})'
        raise SyntaxError(msg)
    return stmts