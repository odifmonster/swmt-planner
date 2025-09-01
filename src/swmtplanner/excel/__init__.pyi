from . import parser, info

from typing import Literal, Annotated
import pandas as pd

__all__ = ['parser', 'info']

type _InfoName = Literal['dye_formulae', 'fabric_items', 'greige_sizes',
                         'greige_translation', 'jet_info', 'pa_inventory',
                         'adaptive_orders', 'pa_demand_plan']

def init() -> None: ...
def get_read_args(name: _InfoName) -> info.PandasInfo: ...
def load_df(info: _InfoName, default_dir: str) -> pd.DataFrame: ...
def to_tsv_file(name: str, default_dir: str, outpath: str) -> None: ...