from . import interpreter, cli

from typing import TypedDict, Literal, Required

__all__ = ['interpreter', 'write_excel_info', 'cli', 'INFO_MAP']

INFO_MAP: dict[_InfoName, tuple[str, _PandasArgs]] = ...

def write_excel_info(infosrc: str) -> None: ...

type _InfoName = Literal[
    'dye_formulae', 'fabric_items', 'greige_sizes', 'greige_translation',
    'jet_info', 'pa_inventory', 'adaptive_orders', 'si_release', 'wf_release',
    'pa_reqs']

class _PandasArgs(TypedDict, total=False):
    sheet_name: Required[str]
    header: int | None
    skiprows: int
    nrows: int
    usecols: str | list[str]
    names: list[str]