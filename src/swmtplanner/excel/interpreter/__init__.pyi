from . import file, lexer, parser
from .lexer import Lexer
from .parser import parse

from typing import TypedDict, Literal, Required

__all__ = ['file', 'lexer', 'Lexer', 'parser', 'parse', 'load_info_file']

type _InfoName = Literal['dye_formulae', 'fabric_items', 'greige_sizes',
                         'greige_translation', 'jet_info', 'pa_inventory',
                         'adaptive_orders', 'si_release', 'wf_release',
                         'pa_reqs']

class _ExcelInfo(TypedDict, total=False):
    folder: Required[str]
    workbook: Required[str]
    sheet: Required[str]
    col_names: list[str]
    col_ranges: str
    subst_names: list[str]
    start_row: int
    end_row: int

def load_info_file(fpath: str) -> dict[_InfoName, _ExcelInfo]: ...