from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class File:
    """
    An immutable description of a file-based source. It does not hold a
    path: it holds the name of the config parameter whose value is the
    folder the file lives in, and enough to build the file's name, which
    for many files includes a date.
    """

    cfg_name: str
    """The name of the config parameter that holds the path to the
    directory holding this file."""
    stem: str
    """The file's name without its extension. For a dated file it is a
    format string such that ``stem.format(dt.strftime(date_fmt))`` gives
    the name for date ``dt``."""
    ext: str
    """The file's extension, including the leading dot."""
    date_fmt: str | None = None
    """The ``strftime`` format for the date embedded in the file name.
    ``None`` means the file is not dated and ``stem`` is used as-is."""

    def get_fpath(self, cfg: dict, override_name: str | None = None,
                  date: date | None = None) -> str:
        """
        Return the full path of the file, in the folder ``cfg[cfg_name]``.

        If ``override_name`` is given it is the complete file name,
        extension included, and is used as-is. Otherwise the name is
        ``stem + ext`` for an undated file, or
        ``stem.format(date.strftime(date_fmt)) + ext`` for a dated one,
        where ``date`` defaults to today when not given.

        :raises KeyError: if ``cfg`` has no ``cfg_name`` key.
        """
        ...

@dataclass(frozen=True)
class CSVFile(File):
    """A delimited text file (CSV or TSV); the extension is whatever the
    file has."""

    sep: str = ','
    """The field separator passed to ``pd.read_csv``; ``"\\t"`` for a
    TSV."""

@dataclass(frozen=True)
class ExcelFile(File):
    """One sheet of an Excel workbook. ``ext`` is always ``.xlsx``; the
    remaining fields are passed straight through to ``pd.read_excel``."""

    ext: str = '.xlsx'
    sheet_name: str | int = 0
    """The sheet to read, by name or position."""
    header: int | None = 0
    """The row holding the column names, or ``None`` if there is none."""
    skiprows: int | None = None
    """Rows to skip at the top of the sheet."""
    nrows: int | None = None
    """Number of rows to read."""
    skipfooter: int = 0
    """Rows to skip at the bottom of the sheet."""

@dataclass(frozen=True)
class JSONFile(File):
    """A JSON file holding tabular data, such as a list of flat objects
    with one key per column. ``ext`` is always ``.json``."""

    ext: str = '.json'
    orient: str = 'records'
    """The JSON layout, passed to ``pd.read_json``. ``"records"`` is a
    list of objects, one per row; ``"index"`` is an object keyed by
    row."""
