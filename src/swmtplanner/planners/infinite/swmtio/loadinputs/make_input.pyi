import os
from datetime import date
from enum import Enum

TSV_EXT: str
TSV_SEP: str
DATE_FMT: str


class InputName(str, Enum):
    MACHINES = 'machines'
    BEAM_SETS = 'beam-sets'
    ASSIGNED_SETS = 'assigned-sets'
    DOFFED_ROLLS = 'doffed-rolls'
    RUNOUT = 'runout'


def make_input_file(
    name: InputName,
    fpath: str | os.PathLike[str],
    *,
    since: date,
    files_dir: str | os.PathLike[str],
    dt: date | None = None,
    cfgpath: str | os.PathLike[str] | None = None,
) -> None: ...
