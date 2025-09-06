from . import interpreter, cli

from typing import TypedDict, Literal, Required
import pandas as pd

__all__ = ['interpreter', 'df_cols_as_str', 'write_excel_info', 'cli', 'INFO_MAP']

INFO_MAP: dict[_InfoName, tuple[str, _PandasArgs]] = ...

def df_cols_as_str(df: pd.DataFrame, *args: *tuple[str, ...]) -> pd.DataFrame:
    """Convert types of the listed DataFrame columns to 'string'."""
    ...

def write_excel_info(infosrc: str) -> None:
    """Write the excel info stored in 'infosrc' to the info.py file."""
    ...

type _InfoName = Literal[
    'dye_formulae', 'pa_fin_items', 'greige_styles', 'greige_translation',
    'jet_info', 'pa_inventory', 'adaptive_orders', 'si_release', 'wf_release',
    'pa_reqs']

class _PandasArgs(TypedDict, total=False):
    sheet_name: Required[str]
    header: int | None
    skiprows: int
    nrows: int
    usecols: str | list[str]
    names: list[str]