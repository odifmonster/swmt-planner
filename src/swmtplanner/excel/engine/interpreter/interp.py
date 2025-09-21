#!/usr/bin/env python

import pandas as pd

from ..parser import AtomType, StmtType, Atom, Exp, \
    AssignStmt, UseStmt, BlockStmt
from ._helpers import ValDType, RawVal

def _bad_stmt_in_ctxt(stmt, line, ctxt):
    msg = f'Line {line}: Unexpected \'{stmt.kind.name}\' statement in {ctxt} context'
    return SyntaxError(msg)

def _not_coercible(pos, srctype, tgttype):
    msg = f'Line {pos.line} at column {pos.column}: '
    msg += f'Value of type \'{srctype}\' not coercible to \'{tgttype}\''
    return SyntaxError(msg)

def _unknown_varname(pos, name):
    msg = f'Line {pos.line} at column {pos.column}: '
    msg += f'Variable \'{name}\' does not exist'
    return SyntaxError(msg)

def extract_srs(name: str, ctxt: dict[str]):
    if 'source' not in ctxt or not isinstance(ctxt['source'], pd.DataFrame) or \
        name not in ctxt['source'].columns:
        return None
    return ctxt['source'][name]

def eval_ref(ref: Atom, glbl_ctxt: dict[str], cur_ctxt: dict[str],
             dtype = ValDType.RAW):
    varname = ref.token.value[1:]
    if varname not in glbl_ctxt:
        raise _unknown_varname(ref.token.start, varname)
    
    val = glbl_ctxt[varname]
    if dtype == ValDType.RAW:
        return val
    
    if isinstance(val, RawVal):
        return None
    
    if 'INT' in dtype.name:
        tgt_type = int
        convert_type_name = 'float'
        tgt_type_name = 'int'
    if 'FLOAT' in dtype.name:
        tgt_type = float
        convert_type_name = 'float'
        tgt_type_name = 'float'
    if 'STRING' in dtype.name:
        tgt_type = str
        convert_type_name = 'string'
        tgt_type_name = 'string'
    
    if 'SRS' in dtype.name:
        if not isinstance(val, pd.Series):
            if type(val) is tgt_type:
                return val
            if type(val) is not str:
                msg = f'Line {ref.token.start.line} at column {ref.token.start.column}: '
                msg += f'Expected column name, got \'{type(val).__name__}\''
                raise SyntaxError(msg)
            val = extract_srs(val, cur_ctxt)
            if val is None:
                msg = f'Line {ref.token.start.line} at column {ref.token.start.column}: '
                msg += f'No column named \'{val}\''
                raise SyntaxError(msg)
        
        try:
            srs = val.astype(convert_type_name)
        except:
            raise _not_coercible(ref.token.start, f'column of {val.dtype.name}',
                                    f'column of {tgt_type_name}')
        if dtype == ValDType.INT_SRS and not (srs % 1 == 0).all():
            raise _not_coercible(ref.token.start, 'column of float', 'column of int')
        
        return val.astype(tgt_type_name)
    if 'LIST' in dtype.name:
        inner_type = dtype.name.split('_')[0]
        if type(val) is not list:
            raise _not_coercible(ref.token.start, type(val).__name__,
                                 f'list of {inner_type.lower()}')
    if not type(val) is tgt_type:
        raise _not_coercible(ref.token.start, type(val).__name__, tgt_type.__name__)
    return val

def eval_atom(at: Atom, glbl_ctxt: dict[str], cur_ctxt: dict[str],
              dtype = ValDType.RAW):
    if dtype == ValDType.RAW:
        return RawVal(at)
    
    at_pos = at.token.start
    if 'LIST' in dtype.name:
        inner_dtype = dtype.name.split('_')[0]
        raise _not_coercible(at_pos, at.kind.name.lower(),
                             f'list of {inner_dtype.lower()}')

    if dtype == ValDType.DATAFRAME:
        if at.kind != AtomType.REF:
            raise _not_coercible(at_pos, at.kind.name.lower(), 'dataframe')
        varname = at.token.value[1:]
        if varname not in glbl_ctxt:
            raise _unknown_varname(at.token.start, varname)
        
        if isinstance(glbl_ctxt[varname], RawVal):
            return pd.DataFrame(data={'foo': [0, 1], 'bar': [5, 10]})
        
        if not isinstance(glbl_ctxt[varname], pd.DataFrame):
            raise _not_coercible(at_pos, type(glbl_ctxt[varname]).__name__,
                                 'dataframe')
        
        return glbl_ctxt[varname]

def eval_excel_file(block: BlockStmt, glbl_ctxt: dict[str], cur_ctxt: dict[str]):
    mbrs = { 'folder', 'workbook', 'sheet', 'col_names', 'col_ranges', 'subst_names',
             'start_row', 'end_row' }
    for stmt in block.stmts:
        if stmt.kind == StmtType.Use:
            assert isinstance(stmt, UseStmt)
            raise _bad_stmt_in_ctxt(stmt, stmt.funcs[0].token.start.line,
                                    'ExcelFile')
        if stmt.kind == StmtType.Block:
            assert isinstance(stmt, BlockStmt)
            raise _bad_stmt_in_ctxt(stmt, stmt.name.token.start.line,
                                    'ExcelFile')
        assert isinstance(stmt, AssignStmt)

        key = stmt.dest.token.value
        if key not in mbrs:
            bad_mbr = stmt.dest.token
            msg = f'Line {bad_mbr.start.line} at column {bad_mbr.start.column}: '
            msg += f'\'{bad_mbr}\' is not a valid ExcelFile member'
            raise SyntaxError(msg)
        
        match key:
            case 'folder' | 'workbook' | 'sheet' | 'col_ranges':
                pass