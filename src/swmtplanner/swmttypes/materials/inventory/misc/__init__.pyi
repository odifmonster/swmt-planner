from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.product import *

__all__ = ['Snapshot', 'Alloc']

class Snapshot(SwmtBase, HasID[int], read_only=('id',)):
    def __init__(self) -> None: ...

class Alloc(SwmtBase, HasID[int],
            read_only=('id','prod','mat_id','qty')):
    def __init__(self, prod: Fabric | Greige | BeamSet, mat_id: str, qty: float) -> None: ...