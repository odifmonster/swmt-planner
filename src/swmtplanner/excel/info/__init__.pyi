from typing import TypedDict
from swmtplanner.excel.parser.tree import Info

class PandasKWArgs(TypedDict, total=False):
    sheet_name: str
    header: int | None
    skiprows: int
    nrows: int
    names: list[str]
    usecols: str | list[str]

type PandasInfo = tuple[str | None, str, PandasKWArgs]

def parse_pd_args(info: Info) -> PandasInfo: ...