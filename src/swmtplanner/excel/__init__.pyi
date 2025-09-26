from . import interpreter, cli

from typing import TypedDict, Literal, Required
import pandas as pd

__all__ = ['interpreter', 'df_cols_as_str', 'cli', 'INFO_MAP', 'info_to_pdargs',
           'load_info_map']

INFO_MAP: dict[_InfoName, tuple[str, _PandasArgs]] = ...

def load_info_map(srcpath: str) -> None: ...

def info_to_pdargs(info_name: _InfoName, info: dict[str]) -> tuple[str, _PandasArgs]:
    """Get excel info as a file path and valid pandas keyword arguments."""
    ...

def df_cols_as_str(df: pd.DataFrame, *args: *tuple[str, ...]) -> pd.DataFrame:
    """Convert types of the listed DataFrame columns to 'string'."""
    ...

type _InfoName = Literal[
    'dye_formulae', 'pa_fin_items', 'greige_styles', 'greige_translation',
    'jet_info', 'pa_inventory', 'adaptive_orders', 'si_release', 'wf_release',
    'pa_reqs', 'lam_ship_dates', 'pa_floor_mos', 'pa_714', 'dye_plan',
    'dye_plan_inv']

class _PandasArgs(TypedDict, total=False):
    sheet_name: Required[str]
    header: int | None
    skiprows: int
    nrows: int
    usecols: str | list[str]
    names: list[str]