#!/usr/bin/env python

import warnings

from .parser import AtomType, VarType, Block, parse

_INFO_ATTRS = {
    'workbook', 'folder', 'sheet', 'col_names', 'col_ranges', 'subst_names',
    'start_row', 'end_row'
}

def _get_var(var_map: dict[str], name: str):
    if name not in var_map:
        raise NameError(f'No such variable \'{name}\'')
    return var_map[name]

def _get_atom_value(var_map: dict[str], at):
    match at.kind:
        case AtomType.VARNAME:
            return _get_var(var_map, at.data)
        case AtomType.NAME | AtomType.FILE | AtomType.STRING:
            return at.data
        case AtomType.NUMBER:
            return int(at.data)
        
def _get_attr_value(var_map: dict[str], attr):
    if attr.name not in _INFO_ATTRS:
        raise KeyError(f'Unknown keyword \'{attr.name}\'')
    
    if attr.name not in ('col_names', 'subst_names') and len(attr.value) > 1:
        raise TypeError(f'\'{attr.name}\' cannot be a list')
    
    match attr.name:
        case 'folder' | 'workbook' | 'sheet' | 'col_ranges':
            val = attr.value[0]
            if val.kind == AtomType.VARNAME:
                varval = _get_var(var_map, val.data)
                if type(varval) is not str:
                    msg = f'Keyword \'{attr.name}\' cannot be of type ' + \
                        f'\'{type(varval).__name__}\''
                    raise TypeError(msg)
                return varval
            return val.data
        case 'start_row' | 'end_row':
            val = attr.value[0]
            if val.kind != AtomType.NUMBER:
                raise TypeError(f'Keyword \'{attr.name}\' must be a number')
            return int(val.data)
        case _:
            vals = []
            for at in attr.value:
                if at.kind == AtomType.VARNAME:
                    varval = _get_var(var_map, at.data)
                    if type(varval) is list:
                        vals += varval
                    else:
                        vals.append(varval)
                else:
                    vals.append(at.data)
            
            for v in vals:
                if type(v) is not str:
                    msg = f'Keyword \'{attr.name}\' cannot contain values of ' + \
                        f'type \'{type(v).__name__}\''
                    raise TypeError(msg)
            return vals

def load_info_file(fpath: str):
    buffer = open(fpath)
    ast = parse(buffer)
    buffer.close()

    var_map = {}
    info_map = {}

    for stmt in ast:
        if isinstance(stmt, Block):
            if stmt.name in info_map:
                msg = f'Redefinition of info for \'{stmt.name}\' will override '
                msg += 'previous value'
                warnings.warn(msg, category=RuntimeWarning)

            info_map[stmt.name] = {}
            for attr in stmt.attrs:
                info_map[stmt.name][attr.name] = _get_attr_value(var_map, attr)
        else:
            if stmt.kind == VarType.NORMAL:
                var_map[stmt.name] = _get_atom_value(var_map, stmt.value)
            else:
                vals = []
                for at in stmt.value:
                    vals.append(_get_atom_value(var_map, at))
                var_map[stmt.name] = vals
    
    return info_map