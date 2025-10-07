from . import engine

from typing import Unpack
import datetime as dt, pandas as pd

__all__ = ['engine', 'init_info', 'load_data']

def init_info(fpath: str, **kwargs: Unpack[dict[str, dt.datetime]]) -> None: ...

def load_data(name: str) -> pd.DataFrame | dict[str, pd.DataFrame]: ...