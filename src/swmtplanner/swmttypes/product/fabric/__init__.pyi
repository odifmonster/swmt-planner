from . import color
from .color import Color

import datetime as dt
from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.product import Greige

__all__ = ['ITEMS', 'load_items', 'Color', 'Fabric', 'color']

ITEMS: dict[str, Fabric] = ...

def load_items(fpath: str) -> None: ...

class Fabric(SwmtBase, HasID[str],
             read_only=('id','master','color','width','greige','yld',
                        'cycle_time'),
             priv=('jets',)):
    def __init__(self, master: str, clr: Color, wd: float, grg: Greige,
                 yld: float, jets: list[str]) -> None: ...
    @property
    def master(self) -> str: ...
    @property
    def color(self) -> Color: ...
    @property
    def width(self) -> float: ...
    @property
    def greige(self) -> Greige: ...
    @property
    def yld(self) -> float: ...
    @property
    def cycle_time(self) -> dt.timedelta: ...