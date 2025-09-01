from swmtplanner.support import SwmtBase, HasID

__all__ = ['Snapshot']

class Snapshot(SwmtBase, HasID[int], read_only=('id',)):
    """
    A class for uniquely identifying snapshots of inventory
    positions. Allows you to compare many different versions of
    the inventory without copying it over each time.
    """
    def __init__(self) -> None: ...